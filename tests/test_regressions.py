import time
import unittest
from unittest.mock import patch

import app


def director_fields(payload):
    return {
        field["key"]: field
        for group in payload["groups"]
        for field in group["fields"]
    }


class DirectorRegressionTests(unittest.TestCase):
    def make_storyboard(self, **overrides):
        state = app.WebState()
        config = {
            "mode": "photoshoot",
            "count": 4,
            "photoshoots": 1,
            "prompt_seed": 1234,
            "inference_seed": 5678,
        }
        config.update(overrides)
        board = state.create_storyboard(config)
        return state, board["id"]

    def test_all_stage_levels_are_available_even_for_xxx_only(self):
        state, storyboard_id = self.make_storyboard(xxx_only=True)
        fields = director_fields(state.director_payload(storyboard_id, 1))
        levels = {option["prompt"] for option in fields["shot.stage"]["options"]}
        self.assertTrue(
            {"covered", "lingerie", "topless", "nude", "explicit"}.issubset(levels)
        )

    def test_stage_change_is_manual_and_rebuilds_compatible_direction(self):
        state, storyboard_id = self.make_storyboard()
        fields = director_fields(state.director_payload(storyboard_id, 1))
        covered = next(
            option for option in fields["shot.stage"]["options"]
            if option["prompt"] == "covered"
        )
        updated = state.update_director(
            storyboard_id,
            {"shot": 1, "field": "shot.stage", "value": covered["id"]},
        )
        updated_fields = director_fields(updated)
        self.assertTrue(updated["summary"]["stage"]["manual"])
        self.assertGreater(updated_fields["shot.stage"]["compatibility"]["poses"], 0)
        self.assertGreater(updated_fields["shot.stage"]["compatibility"]["actions"], 0)

    def test_custom_to_preset_is_one_atomic_director_update(self):
        state, storyboard_id = self.make_storyboard()
        state.update_director(
            storyboard_id,
            {"shot": 1, "field": "human.hair_color", "custom_value": "custom hair"},
        )
        fields = director_fields(state.director_payload(storyboard_id, 1))
        preset = fields["human.hair_color"]["options"][0]["id"]
        updated = state.update_director(
            storyboard_id,
            {
                "shot": 1,
                "field": "human.hair_color",
                "value": preset,
                "clear_custom": True,
            },
        )
        self.assertEqual(director_fields(updated)["human.hair_color"]["custom"], "")

    def test_custom_values_survive_export_import_and_reroll(self):
        state, storyboard_id = self.make_storyboard()
        state.update_director(
            storyboard_id,
            {"shot": 1, "field": "human.hair_color", "custom_value": "exported hair"},
        )
        state.update_director(
            storyboard_id,
            {"shot": 1, "field": "shot.pose", "custom_value": "exported pose"},
        )
        imported = state.import_storyboard(state.export_storyboard(storyboard_id))
        imported_id = imported["id"]
        state.reroll_shot(imported_id, 1)
        shot = state.storyboard_payload(state.get_storyboard(imported_id))["shots"][0]
        self.assertIn("exported hair", shot["positive_prompt"])
        self.assertIn("exported pose", shot["positive_prompt"])


class PreviewRegressionTests(unittest.TestCase):
    def test_preview_lifecycle_keeps_image_in_memory(self):
        state = app.WebState()
        board = state.create_storyboard(
            {"count": 1, "prompt_seed": 11, "inference_seed": 22}
        )
        with (
            patch.object(app, "load_workflow_runtime", return_value=({}, {})),
            patch.object(
                app,
                "generate_preview_image",
                return_value=("preview-prompt", b"preview-bytes", "image/png"),
            ),
        ):
            preview = state.create_preview(board["id"], 1, True)
            for _ in range(100):
                preview = state.get_preview(preview["id"])
                if preview["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.01)
        self.assertEqual(preview["status"], "completed")
        self.assertEqual(
            state.preview_image(preview["id"]),
            (b"preview-bytes", "image/png"),
        )
        self.assertEqual(state.delete_preview(preview["id"]), {"deleted": True})
        self.assertNotIn(preview["id"], state.previews)

    def test_preview_requires_fast_mode(self):
        state = app.WebState()
        board = state.create_storyboard(
            {"count": 1, "prompt_seed": 33, "inference_seed": 44}
        )
        with self.assertRaisesRegex(app.AppError, "Fast test mode"):
            state.create_preview(board["id"], 1, False)

    def test_save_image_nodes_become_temporary_preview_nodes(self):
        class Response:
            headers = {"Content-Type": "image/png"}
            content = b"image"

            def raise_for_status(self):
                return None

            def json(self):
                return {"prompt_id": "prompt-id"}

        class Session:
            def __init__(self):
                self.queued_workflow = None

            def post(self, url, json, timeout):
                self.queued_workflow = json["prompt"]
                return Response()

            def get(self, url, params, timeout):
                return Response()

        session = Session()
        workflow = {
            "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "sampler": {"class_type": "KSampler", "inputs": {"seed": 1}},
            "save": {
                "class_type": "SaveImage",
                "inputs": {"images": ["sampler", 0], "filename_prefix": "Valhalla"},
            },
        }
        mapping = {
            "positive_prompt": {"node": "positive", "input": "text"},
            "negative_prompt": {"node": "negative", "input": "text"},
            "inference_seed": [{"node": "sampler", "input": "seed"}],
        }
        outputs = {"save": {"images": [{"filename": "preview.png"}]}}
        with (
            patch.object(app, "prepare_fast_workflow", side_effect=lambda graph, _: graph),
            patch.object(app, "comfy_session", return_value=(session, "http://comfy", 1)),
            patch.object(app, "wait_for_outputs", return_value=outputs),
        ):
            _, image, mime_type = app.generate_preview_image(
                {"settings": {}}, "positive", "negative", 9, workflow, mapping
            )
        self.assertEqual(image, b"image")
        self.assertEqual(mime_type, "image/png")
        self.assertEqual(session.queued_workflow["save"]["class_type"], "PreviewImage")
        self.assertNotIn("filename_prefix", session.queued_workflow["save"]["inputs"])


class RenderLifecycleRegressionTests(unittest.TestCase):
    def test_cancel_requested_is_exposed_to_the_ui(self):
        state = app.WebState()
        job = {
            "id": "job",
            "status": "running",
            "cancel_requested": True,
        }
        self.assertTrue(state.job_payload(job)["cancel_requested"])


if __name__ == "__main__":
    unittest.main()
