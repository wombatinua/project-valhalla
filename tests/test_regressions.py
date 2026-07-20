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


class DatabaseExpansionTests(unittest.TestCase):
    def test_catalog_is_tripled_and_curated_everyday_sets_are_present(self):
        database, _ = app.load_database()
        self.assertGreaterEqual(sum(1 for _ in app.iter_content_items(database)), 2703)
        self.assertGreaterEqual(len(database["interiors"]), 123)
        self.assertGreaterEqual(len(database["poses"]), 240)
        self.assertGreaterEqual(len(database["actions"]), 177)
        self.assertGreaterEqual(
            sum(len(items) for items in database["garments"].values()), 1026
        )
        ids = {item["id"] for item in app.iter_content_items(database)}
        self.assertIn("interior_apartment_compact_bedroom", ids)
        self.assertIn("interior_apartment_studio_flat", ids)
        self.assertIn("shoes_simple_01", ids)
        self.assertIn("action_curated_20", ids)

    def test_expansion_preserves_modifier_relationships(self):
        database, _ = app.load_database()
        for modifier in database["patterns"] + database["fabric_textures"]:
            allowed = set(modifier["allowed_garment_ids"])
            for original in list(allowed):
                if original.endswith(("_studio", "_editorial")):
                    continue
                self.assertIn(f"{original}_studio", allowed)
                self.assertIn(f"{original}_editorial", allowed)

    def test_catalog_prompts_are_unique_and_model_friendly(self):
        database, _ = app.load_database()
        prompts = [
            item["prompt"].strip().casefold()
            for item in app.iter_content_items(database)
            if item.get("prompt")
        ]
        self.assertEqual(len(prompts), len(set(prompts)))
        self.assertLessEqual(max(len(prompt.split()) for prompt in prompts), 48)
        self.assertFalse(any("production variation" in prompt for prompt in prompts))


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

    def test_camera_grammar_is_visible_and_editable_in_director(self):
        state, storyboard_id = self.make_storyboard()
        payload = state.director_payload(storyboard_id, 1)
        fields = director_fields(payload)
        for key in (
            "shot.furniture", "shot.editorial_role", "shot.shot_size",
            "shot.camera_angle", "shot.framing", "shot.focus_target",
        ):
            self.assertIn(key, fields)
            self.assertTrue(fields[key]["options"])

    def test_sequence_seeds_are_stable_and_unique(self):
        first_state, first_id = self.make_storyboard(inference_strategy="sequence")
        second_state, second_id = self.make_storyboard(inference_strategy="sequence")
        first = [shot["inference_seed"] for shot in first_state.storyboard_payload(first_state.get_storyboard(first_id))["shots"]]
        second = [shot["inference_seed"] for shot in second_state.storyboard_payload(second_state.get_storyboard(second_id))["shots"]]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))

    def test_single_frame_job_targets_only_requested_shot(self):
        state, storyboard_id = self.make_storyboard()
        with patch.object(app.threading, "Thread"):
            job = state.create_job(storyboard_id, False, [3])
        self.assertEqual(job["kind"], "shot")
        self.assertEqual(job["shot_numbers"], [3])
        self.assertEqual(job["total"], 1)
        self.assertEqual(job["logs"][0]["type"], "queued")
        self.assertEqual(job["logs"][0]["total"], 1)

    def test_new_variation_changes_only_the_shot_inference_seed(self):
        state, storyboard_id = self.make_storyboard()
        before = state.storyboard_payload(state.get_storyboard(storyboard_id))["shots"][1]
        after = state.randomize_shot_seed(storyboard_id, 2)
        self.assertNotEqual(before["inference_seed"], after["inference_seed"])
        self.assertTrue(after["seed_manual"])
        self.assertEqual(before["positive_prompt"], after["positive_prompt"])
        self.assertEqual(before["selected_ids"], after["selected_ids"])

    def test_changing_variation_settings_preserves_director_custom_values(self):
        state, storyboard_id = self.make_storyboard()
        state.update_director(
            storyboard_id,
            {"shot": 1, "field": "shot.pose", "custom_value": "custom held pose"},
        )
        before = state.get_storyboard(storyboard_id)["shots"][0]
        scene_id = id(before["scene"])
        updated = state.update_storyboard_seeds(
            storyboard_id,
            {"inference_seed": 987654, "inference_strategy": "sequence"},
        )
        after = state.get_storyboard(storyboard_id)["shots"][0]
        self.assertEqual(id(after["scene"]), scene_id)
        self.assertEqual(after["custom_values"]["shot.pose"], "custom held pose")
        self.assertIn("custom held pose", updated["shots"][0]["positive_prompt"])

    def test_custom_subject_value_updates_director_summary(self):
        state, storyboard_id = self.make_storyboard()
        updated = state.update_director(
            storyboard_id,
            {
                "shot": 1,
                "field": "human.hair_color",
                "custom_value": "vivid copper hair",
            },
        )
        self.assertIn("vivid copper hair", updated["summary"]["subject"])

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

    def test_preview_always_uses_preview_workflow_without_toggle(self):
        state = app.WebState()
        board = state.create_storyboard(
            {"count": 1, "prompt_seed": 33, "inference_seed": 44}
        )
        with patch.object(app.threading, "Thread"):
            preview = state.create_preview(board["id"], 1, False)
        self.assertEqual(preview["type"], "preview")
        self.assertTrue(preview["positive"])
        self.assertTrue(preview["negative"])
        self.assertEqual(preview["seed"], board["shots"][0]["inference_seed"])

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

    def test_clear_logger_hides_preview_but_keeps_displayed_image_available(self):
        state = app.WebState()
        board = state.create_storyboard(
            {"count": 1, "prompt_seed": 55, "inference_seed": 66}
        )
        with patch.object(app.threading, "Thread"):
            preview = state.create_preview(board["id"], 1, False)
        stored = state.previews[preview["id"]]
        stored.update(
            status="completed", image_bytes=b"still-visible", mime_type="image/png"
        )
        result = state.clear_logger()
        self.assertEqual(result["previews"], 1)
        self.assertIsNone(state.jobs_payload()["latest_preview"])
        self.assertEqual(
            state.preview_image(preview["id"]), (b"still-visible", "image/png")
        )


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
