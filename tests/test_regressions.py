import copy
import concurrent.futures
import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import qa_preview_audit as preview_qa


def director_fields(payload):
    return {
        field["key"]: field
        for group in payload["groups"]
        for field in group["fields"]
    }


class StudioGenerationLimitTests(unittest.TestCase):
    def test_run_config_accepts_counts_above_the_previous_limits(self):
        database, _ = app.load_database()
        config = app.parse_run_config(
            {"mode": "photoshoot", "count": 201, "photoshoots": 51}, database
        )
        self.assertEqual(config.count, 201)
        self.assertEqual(config.photoshoots, 51)

    def test_run_config_still_rejects_non_positive_counts(self):
        database, _ = app.load_database()
        with self.assertRaisesRegex(app.AppError, "Images must be at least 1"):
            app.parse_run_config({"count": 0}, database)

    def test_studio_number_inputs_have_no_maximum(self):
        html = (Path(app.__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('name="photoshoots" min="1" max=', html)
        self.assertNotIn('name="count" min="1" max=', html)


class CatalogQualityTests(unittest.TestCase):
    def test_custom_mast_actions_are_wired_as_hands_only_actions(self):
        database, _ = app.load_database()
        actions = {item["id"]: item for item in database["actions"]}
        expected_hands = {
            "action_inserting_vagina": 1,
            "action_inserting_anus": 1,
            "action_inserting_both": 2,
        }
        for action_id, hands in expected_hands.items():
            item = actions[action_id]
            self.assertTrue(item["prompt"].strip())
            self.assertTrue(item["menu_label"].strip())
            self.assertTrue(
                {"explicit_action", "masturbation_action", "explicit"}.issubset(
                    app.tags(item)
                )
            )
            self.assertEqual(set(item["requires_tags"]), {"genitals", "open_legs"})
            self.assertEqual(item["hands_required"], hands)
            self.assertEqual(item["allowed_levels"], ["explicit"])

    def test_database_rejects_duplicate_json_keys(self):
        with self.assertRaisesRegex(app.AppError, "Duplicate JSON key: catalog_category"):
            app.json.loads(
                '{"catalog_category":"normal","catalog_category":"luxury"}',
                object_pairs_hook=app.unique_json_object,
            )

    def test_database_source_contains_no_duplicate_json_keys(self):
        source = Path(app.__file__).with_name("database.json").read_text(encoding="utf-8")
        app.json.loads(source, object_pairs_hook=app.unique_json_object)

    def test_intimate_arousal_modifiers_are_visibility_gated_and_seeded(self):
        database, _ = app.load_database()
        composer = app.Composer(database, app.random.Random(20260721))
        context = composer.fixed_context()
        explicit = next(
            stage
            for stage in app.effective_photoshoot_stages(context["outfit"]["template"])
            if stage["level"] == "explicit"
        )
        intimate = composer.resolve_scene(
            context, explicit, {"explicit_recipe": "recipe_intimate_macro"}
        )
        masturbation = composer.resolve_scene(
            context, explicit, {"explicit_recipe": "recipe_hands_only"}
        )
        rear = composer.resolve_scene(
            context, explicit, {"explicit_recipe": "recipe_rear_standing"}
        )
        breast = composer.resolve_scene(
            context, explicit, {"explicit_recipe": "recipe_breast_focus"}
        )
        modifier = intimate["intimate_arousal_modifier"]
        self.assertIn(
            modifier["id"],
            {item["id"] for item in database["intimate_arousal_modifiers"]},
        )
        self.assertIn(modifier["prompt"], app.compile_scene(database, intimate)[0])
        self.assertIsNotNone(masturbation["intimate_arousal_modifier"])
        self.assertIsNone(rear["intimate_arousal_modifier"])
        self.assertIsNone(breast["intimate_arousal_modifier"])

    def test_wardrobe_environment_and_surface_catalogs_use_one_explicit_category(self):
        database, _ = app.load_database()
        items = list(database["outfit_templates"])
        items.extend(database["interiors"])
        items.extend(database["furniture"])
        items.extend(
            item for values in database["garments"].values() for item in values
        )
        self.assertGreater(len(items), 500)
        self.assertTrue(all(item.get("catalog_category") in {"normal", "luxury"} for item in items))
        self.assertFalse(any("wardrobe_category" in item for item in items))

    def test_scene_default_categories_reliably_isolate_normal_and_luxury(self):
        database, _ = app.load_database()
        for category in ("normal", "luxury"):
            configured = copy.deepcopy(database)
            defaults = configured["settings"]["scene_defaults"]
            defaults["wardrobe_categories"] = [category]
            defaults["environment_categories"] = [category]
            app.validate_database(configured)
            selected_garment_categories = set()
            selected_surface_categories = set()
            for seed in range(60):
                context = app.Composer(configured, app.random.Random(seed)).fixed_context()
                self.assertEqual(app.catalog_category(context["outfit"]["template"]), category)
                self.assertEqual(app.catalog_category(context["interior"]), category)
                self.assertTrue(app.category_allows(context["interior"], context["furniture"]))
                selected_surface_categories.add(app.catalog_category(context["furniture"]))
                for garment in context["outfit"]["garments"].values():
                    self.assertTrue(app.category_allows(context["outfit"]["template"], garment))
                    selected_garment_categories.add(app.catalog_category(garment))
            if category == "normal":
                self.assertEqual(selected_garment_categories, {"normal"})
                self.assertEqual(selected_surface_categories, {"normal"})
            else:
                self.assertIn("luxury", selected_garment_categories)
                self.assertIn("luxury", selected_surface_categories)

    def test_enabling_both_categories_cycles_through_both_in_a_batch(self):
        database, _ = app.load_database()
        defaults = database["settings"]["scene_defaults"]
        self.assertEqual(set(defaults["wardrobe_categories"]), {"normal", "luxury"})
        self.assertEqual(set(defaults["environment_categories"]), {"normal", "luxury"})
        composer = app.Composer(database, app.random.Random(20260721))
        contexts = [composer.fixed_context() for _ in range(10)]
        self.assertEqual(
            [app.catalog_category(item["outfit"]["template"]) for item in contexts].count("luxury"),
            5,
        )
        self.assertEqual(
            [app.catalog_category(item["interior"]) for item in contexts].count("luxury"),
            5,
        )

    def test_age_catalog_contains_only_three_explicit_adult_presets(self):
        database, _ = app.load_database()
        ages = database["human_model_parts"]["age"]
        self.assertEqual(
            [(item["id"], item["prompt"]) for item in ages],
            [
                ("girl_21", "21-year-old girl"),
                ("girl_22", "22-year-old girl"),
                ("girl_23", "23-year-old girl"),
            ],
        )
        self.assertTrue(all("adult" in app.tags(item) for item in ages))

    def test_catalog_has_large_unique_curated_collections(self):
        database, _ = app.load_database()
        self.assertGreaterEqual(sum(1 for _ in app.iter_content_items(database)), 1100)
        self.assertGreaterEqual(len(database["interiors"]), 60)
        self.assertGreaterEqual(len(database["poses"]), 100)
        self.assertGreaterEqual(len(database["actions"]), 79)
        self.assertGreaterEqual(
            sum(len(items) for items in database["garments"].values()), 430
        )
        ids = {item["id"] for item in app.iter_content_items(database)}
        self.assertIn("interior_apartment_compact_bedroom", ids)
        self.assertIn("interior_apartment_studio_flat", ids)
        self.assertIn("shoes_simple_01", ids)
        self.assertIn("action_curated_20", ids)

    def test_catalog_has_no_mechanical_variants_and_modifier_refs_are_valid(self):
        database, _ = app.load_database()
        items = list(app.iter_content_items(database))
        self.assertFalse(any(item.get("expansion_source") for item in items))
        self.assertFalse(any(item.get("expansion_variant") for item in items))
        garment_ids = {
            item["id"] for values in database["garments"].values() for item in values
        }
        for modifier in database["patterns"] + database["fabric_textures"]:
            allowed = set(modifier["allowed_garment_ids"])
            self.assertTrue(allowed)
            self.assertTrue(allowed.issubset(garment_ids))
        pattern_garments = set().union(*(
            set(item["allowed_garment_ids"]) for item in database["patterns"]
        ))
        texture_garments = set().union(*(
            set(item["allowed_garment_ids"])
            for item in database["fabric_textures"]
        ))
        self.assertGreaterEqual(len(pattern_garments), 200)
        self.assertGreaterEqual(len(texture_garments), 220)
        self.assertGreaterEqual(
            sum(item_id.startswith("panties_") for item_id in pattern_garments), 20
        )
        self.assertGreaterEqual(
            sum("surface_texture_target" in item for item in database["furniture"]),
            20,
        )

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

    def test_base_negative_prompt_contains_only_minimal_anatomy_terms(self):
        database, _ = app.load_database()
        negative = database["prompt_defaults"]["negative_prompt"]
        self.assertEqual(
            negative,
            "extra limbs, missing limbs, fused limbs, malformed hands, extra fingers, "
            "fused fingers, malformed feet, extra toes, malformed anatomy, distorted face",
        )
        for removed in (
            "man", "male", "dildo", "vibrator", "sex toy", "multiple people",
            "low quality", "blurry", "watermark", "text",
        ):
            self.assertNotIn(removed, negative.split(", "))


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

    def test_pregnancy_is_a_persistent_body_modifier_without_waist_conflict(self):
        state, storyboard_id = self.make_storyboard()
        fields = director_fields(state.director_payload(storyboard_id, 1))
        modifier = fields["human.body_state"]
        self.assertEqual(modifier["label"], "Body modifier")
        self.assertEqual(
            {option["label"] for option in modifier["options"]},
            {"No modifier", "Pregnant"},
        )

        state.update_director(
            storyboard_id,
            {
                "shot": 1,
                "field": "human.body_state",
                "value": "body_state_pregnant",
            },
        )
        record = state.get_storyboard(storyboard_id)
        rendered = state.storyboard_payload(record)["shots"]
        for shot, payload in zip(record["shots"], rendered):
            self.assertEqual(
                shot["context"]["human"]["body_state"]["id"],
                "body_state_pregnant",
            )
            self.assertIn("pregnant", payload["positive_prompt"].casefold())
            self.assertNotIn(
                shot["context"]["human"]["waist"]["prompt"],
                payload["positive_prompt"],
            )
            positive = payload["positive_prompt"].casefold()
            stage_marker = {
                "covered": "opaque upper-body clothing",
                "lingerie": "opaque bra",
                "topless": "topless",
                "nude": "fully nude body",
                "explicit": "explicit adult pose",
            }[shot["stage"]["level"]]
            self.assertLess(positive.index("pregnant"), positive.index(stage_marker))
            self.assertLess(
                positive.index("pregnant"),
                positive.index(shot["context"]["human"]["ethnic_appearance"]["prompt"].casefold()),
            )

    def test_default_photoshoot_stays_in_casual_amateur_treatment_pools(self):
        database, _ = app.load_database()
        pools = database["settings"]["scene_defaults"]["pools"]
        self.assertEqual(pools["interiors"], [])
        self.assertEqual(pools["furniture"], [])
        allowed = {
            "mood": set(pools["moods"]),
            "photography_style": (
                set(pools["photography_styles"])
                | set(pools["explicit_photography_styles"])
            ),
        }
        for seed in range(20):
            state, storyboard_id = self.make_storyboard(count=12, prompt_seed=seed)
            for shot in state.get_storyboard(storyboard_id)["shots"]:
                scene = shot["scene"]
                for field in ("mood", "photography_style"):
                    self.assertIn(scene[field]["id"], allowed[field], (seed, field))

    def test_compiled_prompt_contains_only_current_frame_visual_instructions(self):
        state, storyboard_id = self.make_storyboard(count=12)
        prompts = [
            shot["positive_prompt"]
            for shot in state.storyboard_payload(
                state.get_storyboard(storyboard_id)
            )["shots"]
        ]
        temporal_placeholders = (
            "clothing continuity",
            "clothing state remains consistent",
            "wearing the listed",
            "listed retained",
        )
        self.assertFalse(
            any(term in prompt for prompt in prompts for term in temporal_placeholders)
        )
        self.assertFalse(any("complete intact body" in prompt for prompt in prompts))
        self.assertFalse(
            any("two legs" in prompt or "two feet" in prompt for prompt in prompts)
        )
        explicit_negatives = [
            shot["negative_prompt"].split(", ")
            for shot in state.storyboard_payload(
                state.get_storyboard(storyboard_id)
            )["shots"]
            if shot["stage"]["level"] == "explicit"
        ]
        self.assertTrue(explicit_negatives)
        self.assertTrue(
            all("clothes" not in terms and "underwear" not in terms for terms in explicit_negatives)
        )

    def test_director_camera_options_are_unique_real_presets(self):
        state, storyboard_id = self.make_storyboard()
        fields = director_fields(state.director_payload(storyboard_id, 1))
        options = fields["shot.camera_angle"]["options"]
        self.assertEqual(len(options), len({item["id"] for item in options}))
        self.assertEqual(len(options), len({item["prompt"] for item in options}))

    def test_surface_color_and_texture_are_composed_and_director_editable(self):
        state, storyboard_id = self.make_storyboard(count=12, prompt_seed=0)
        record = state.get_storyboard(storyboard_id)
        position = next(
            index for index, shot in enumerate(record["shots"], 1)
            if shot["scene"]["furniture"].get("surface_texture_target")
        )
        payload = state.director_payload(storyboard_id, position)
        fields = director_fields(payload)
        self.assertIn("shot.surface_color", fields)
        self.assertIn("shot.surface_texture", fields)
        color = next(
            option for option in fields["shot.surface_color"]["options"]
            if option["id"] and option["id"] != fields["shot.surface_color"]["value"]
        )
        texture = next(
            option for option in fields["shot.surface_texture"]["options"]
            if option["id"] and option["id"] != fields["shot.surface_texture"]["value"]
        )
        state.update_director(
            storyboard_id,
            {"shot": position, "field": "shot.surface_color", "value": color["id"]},
        )
        state.update_director(
            storyboard_id,
            {"shot": position, "field": "shot.surface_texture", "value": texture["id"]},
        )
        rendered = state.storyboard_payload(state.get_storyboard(storyboard_id))["shots"][position - 1]
        self.assertIn(color["prompt"], rendered["positive_prompt"])
        self.assertIn(texture["prompt"], rendered["positive_prompt"])
        imported = state.import_storyboard(state.export_storyboard(storyboard_id))
        imported_shot = state.get_storyboard(imported["id"])["shots"][position - 1]["scene"]
        self.assertEqual(imported_shot["surface_color"]["id"], color["id"])
        self.assertEqual(imported_shot["surface_texture"]["id"], texture["id"])

    def test_amateur_style_does_not_reduce_explicit_direction(self):
        poses, actions, recipes, plateau_kinds = set(), set(), set(), set()
        for seed in range(20):
            state, storyboard_id = self.make_storyboard(
                count=12, prompt_seed=seed, xxx_only=True
            )
            for shot in state.get_storyboard(storyboard_id)["shots"]:
                scene = shot["scene"]
                self.assertEqual(scene["stage"]["level"], "explicit")
                self.assertIn("explicit_pose", app.tags(scene["pose"]))
                self.assertIn("explicit_action", app.tags(scene["action"]))
                poses.add(scene["pose"]["id"])
                actions.add(scene["action"]["id"])
                plateau_kinds.add(scene["stage"].get("plateau_kind"))
                if scene.get("explicit_recipe"):
                    recipes.add(scene["explicit_recipe"]["id"])
        self.assertGreaterEqual(len(poses), 35)
        self.assertGreaterEqual(len(actions), 30)
        self.assertGreaterEqual(len(recipes), 8)
        self.assertTrue({
            "pose_explicit_side_scissor", "pose_explicit_half_roll_open",
            "pose_explicit_overhead_asymmetric", "pose_explicit_edge_side_open",
        }.issubset(poses))
        self.assertEqual(
            plateau_kinds,
            {"provocative_rear", "intimate_closeup", "panties_aside", "masturbation"},
        )

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
        self.assertNotIn("attempt", job)
        self.assertNotIn("retrying", job)
        self.assertNotIn("last_error", job)

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

    def test_random_director_value_uses_a_compatible_nonempty_option(self):
        state, storyboard_id = self.make_storyboard()
        before = director_fields(state.director_payload(storyboard_id, 1))
        field = before["shot.pose"]
        compatible = {option["id"] for option in field["options"] if option["id"]}
        updated = state.update_director(
            storyboard_id,
            {"shot": 1, "field": "shot.pose", "value": "__director_random__"},
        )
        selected = director_fields(updated)["shot.pose"]["value"]
        self.assertIn(selected, compatible)
        if len(compatible) > 1:
            self.assertNotEqual(selected, field["value"])

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

    def test_photoshoot_stages_never_move_back_toward_more_clothing(self):
        levels = {"covered": 0, "lingerie": 1, "topless": 2, "nude": 3, "explicit": 4}
        for seed in range(40):
            state, storyboard_id = self.make_storyboard(
                count=12, prompt_seed=seed, xxx_only=bool(seed % 2)
            )
            shots = state.get_storyboard(storyboard_id)["shots"]
            progression = [levels[shot["scene"]["stage"]["level"]] for shot in shots]
            self.assertEqual(progression, sorted(progression), (seed, progression))

    def test_zero_nsfw_and_plateau_never_resolve_nude_stages(self):
        for seed in range(20):
            state, storyboard_id = self.make_storyboard(
                count=20,
                prompt_seed=seed,
                nsfw_percent=0,
                plateau_percent=0,
            )
            levels = {
                shot["scene"]["stage"]["level"]
                for shot in state.get_storyboard(storyboard_id)["shots"]
            }
            self.assertTrue(levels.issubset({"covered", "lingerie"}), (seed, levels))

    def test_compiler_preserves_stage_and_visible_garments(self):
        anchors = {
            "covered": "opaque upper-body clothing fully covering both breasts",
            "lingerie": "opaque bra, lingerie top, or upper garment fully covering both breasts",
            "topless": "topless, bare breasts and visible nipples",
            "nude": "fully nude body",
            "explicit": "explicit adult pose",
        }
        state, storyboard_id = self.make_storyboard(count=12, prompt_seed=8800)
        record = state.get_storyboard(storyboard_id)
        payload = state.storyboard_payload(record)
        for shot, rendered in zip(record["shots"], payload["shots"]):
            scene = shot["scene"]
            positive = rendered["positive_prompt"].casefold()
            expected_anchor = (
                "anatomically coherent rear-facing nude pose"
                if scene["stage"].get("plateau_kind") == "provocative_rear"
                else "one coherent sheer bra or lingerie top"
                if scene["stage"]["level"] == "lingerie" and any(
                    "sheer" in app.tags(scene["outfit"]["garments"][slot])
                    for slot in scene["stage"].get("visible_slots", [])
                    if slot in scene["outfit"]["garments"]
                )
                else "one opaque bra fully covering both breasts beneath the sheer outer garment"
                if scene["stage"]["level"] == "covered" and any(
                    "sheer" in app.tags(scene["outfit"]["garments"][slot])
                    for slot in scene["stage"].get("visible_slots", [])
                    if slot in scene["outfit"]["garments"]
                )
                else anchors[scene["stage"]["level"]]
            )
            self.assertIn(expected_anchor, positive)
            self.assertEqual(
                len(rendered["selected_ids"]), len(set(rendered["selected_ids"]))
            )
            for slot in scene["stage"].get("visible_slots", []):
                garment = scene["outfit"]["garments"].get(slot)
                if garment:
                    self.assertIn(garment["prompt"].casefold(), positive)

    def test_rear_recipe_enforces_orientation_without_competing_hand_action(self):
        state, storyboard_id = self.make_storyboard(count=4, prompt_seed=97531)
        record = state.get_storyboard(storyboard_id)
        shot = record["shots"][-1]
        db = record["db"]
        recipe = next(
            item for item in db["explicit_recipes"] if item["id"] == "recipe_bent_over"
        )
        shot["stage"]["level"] = "explicit"
        shot["stage"].pop("plateau_kind", None)
        shot["stage"]["visible_slots"] = []
        shot["stage"]["body_visibility"] = ["breasts", "nipples", "pubic_area", "genitals"]
        shot["scene"]["stage"] = shot["stage"]
        shot["scene"]["explicit_recipe"] = recipe
        shot["scene"]["garment_transition"] = {
            "id": "transition_test",
            "prompt": "deliberately removing bra and panties with both hands",
            "slots": ["bra", "panties"],
        }

        positive, negative, _ = app.compile_scene(db, shot["scene"])
        folded = positive.casefold()
        self.assertIn("anatomically coherent rear-facing nude pose", folded)
        self.assertNotIn("bare breasts, visible nipples", folded)
        self.assertNotIn("deliberately removing", folded)
        self.assertNotIn("orgasmic facial expression", folded)
        self.assertIn("face turned mostly away from the camera", folded)
        self.assertIn("front-facing torso", negative.casefold())
        self.assertLess(
            folded.index("rear-facing nude pose"),
            folded.index(shot["scene"]["human"]["ethnic_appearance"]["prompt"].casefold()),
        )

    def test_explicit_recipe_focus_constrains_pose_action_and_director_options(self):
        checked = 0
        for seed in range(20):
            state, storyboard_id = self.make_storyboard(
                count=8, prompt_seed=seed, xxx_only=True
            )
            record = state.get_storyboard(storyboard_id)
            for position, shot in enumerate(record["shots"], 1):
                scene = shot["scene"]
                recipe = scene.get("explicit_recipe")
                if recipe is None:
                    continue
                checked += 1
                self.assertTrue(app.recipe_focus_compatible(scene["pose"], recipe, "pose"))
                self.assertTrue(app.recipe_focus_compatible(scene["action"], recipe, "action"))
                fields = director_fields(state.director_payload(storyboard_id, position))
                for option in fields["shot.pose"]["options"]:
                    item = next(item for item in record["db"]["poses"] if item["id"] == option["id"])
                    self.assertTrue(app.recipe_focus_compatible(item, recipe, "pose"))
                for option in fields["shot.action"]["options"]:
                    item = next(item for item in record["db"]["actions"] if item["id"] == option["id"])
                    self.assertTrue(app.recipe_focus_compatible(item, recipe, "action"))
        self.assertGreater(checked, 40)

    def test_automatic_garment_transition_describes_state_not_second_action(self):
        state, storyboard_id = self.make_storyboard(count=12, prompt_seed=24680)
        transitions = [
            shot["scene"]["garment_transition"]["prompt"]
            for shot in state.get_storyboard(storyboard_id)["shots"]
            if shot["scene"].get("garment_transition")
        ]
        self.assertTrue(transitions)
        for prompt in transitions:
            self.assertTrue(prompt.startswith("fully removed and no longer wearing "))
            self.assertNotIn("deliberately removing", prompt)

    def test_compiler_prioritizes_persistent_visual_identity(self):
        state, storyboard_id = self.make_storyboard(count=8, prompt_seed=4141)
        record = state.get_storyboard(storyboard_id)
        shot = record["shots"][0]
        scene = shot["scene"]
        positive = state.storyboard_payload(record)["shots"][0]["positive_prompt"].casefold()
        first_visible_garment = next(
            scene["outfit"]["garments"][slot]
            for slot in scene["outfit"]["template"]["slots"]
            if slot in set(scene["stage"].get("visible_slots", []))
            and slot in scene["outfit"]["garments"]
        )
        positions = [
            positive.index("single subject"),
            positive.index(scene["human"]["ethnic_appearance"]["prompt"].casefold()),
            positive.index(first_visible_garment["prompt"].casefold()),
            positive.index(scene["interior"]["prompt"].casefold()),
            positive.index(scene["pose"]["prompt"].casefold()),
            positive.index(scene["shot_size"]["prompt"].casefold()),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_covered_chest_blocks_nipple_clipping_without_losing_bust_shape(self):
        state, storyboard_id = self.make_storyboard(count=12, prompt_seed=24680)
        record = state.get_storyboard(storyboard_id)
        payload = state.storyboard_payload(record)
        covered = [
            (raw["scene"], rendered)
            for raw, rendered in zip(record["shots"], payload["shots"])
            if raw["scene"]["stage"]["level"] in {"covered", "lingerie"}
        ]
        self.assertTrue(covered)
        for scene, rendered in covered:
            positive = rendered["positive_prompt"].casefold()
            negative = rendered["negative_prompt"].casefold()
            if "unbroken opaque fabric over the entire bust" not in positive:
                self.assertTrue(
                    "one coherent sheer bra" in positive
                    or "one opaque bra fully covering both breasts beneath" in positive
                )
                continue
            self.assertIn("unbroken opaque fabric over the entire bust", positive)
            self.assertIn("natural clothed bust silhouette", positive)
            self.assertIn("continuous garment color and fabric texture", positive)
            self.assertIn("smooth continuous same-color fabric", positive)
            self.assertNotIn("nipple", positive)
            self.assertNotIn("areola", positive)
            self.assertIn("bust", positive)
            self.assertIn("nipples clipping through clothing", negative)
            self.assertIn("skin-colored nipples through clothing", negative)
            self.assertIn("areola color visible through fabric", negative)
            self.assertIn("colored nipple shapes on fabric", negative)
            self.assertNotIn("nipple outline through clothes", negative)
            self.assertNotIn("nipples protruding through fabric", negative)

    def test_lingerie_bra_is_compiled_as_one_coherent_layer(self):
        lingerie = None
        for seed in range(20):
            state, storyboard_id = self.make_storyboard(count=12, prompt_seed=seed)
            rendered = state.storyboard_payload(state.get_storyboard(storyboard_id))["shots"]
            lingerie = next((
                shot for shot in rendered
                if shot["stage"]["level"] == "lingerie"
                and "multiple bras" in shot["negative_prompt"].casefold()
            ), None)
            if lingerie:
                break
        self.assertIsNotNone(lingerie)
        positive = lingerie["positive_prompt"].casefold()
        negative = lingerie["negative_prompt"].casefold()
        self.assertIn("one single-layer", positive)
        self.assertIn("straps and underband matching the same base color and material", positive)
        self.assertIn("multiple bras", negative)
        self.assertIn("extra bra straps", negative)

    def test_rear_focus_requires_pose_or_action_rear_orientation(self):
        database, _ = app.load_database()
        focus = next(item for item in database["focus_targets"] if item["id"] == "focus_rear")
        self.assertEqual(focus["requires_any_tags"], ["provocative_rear"])

    def test_extremely_large_breasts_keep_their_scale_under_clothing(self):
        state, storyboard_id = self.make_storyboard(count=12, prompt_seed=24680)
        state.update_director(
            storyboard_id,
            {
                "shot": 1,
                "field": "human.breast_size",
                "value": "breasts_extremely_large",
            },
        )
        shots = state.storyboard_payload(state.get_storyboard(storyboard_id))["shots"]
        covered = next(
            shot for shot in shots if shot["stage"]["level"] in {"covered", "lingerie"}
        )
        nude = next(
            shot for shot in shots if shot["stage"]["level"] in {"nude", "explicit"}
        )
        self.assertIn(
            "extremely large heavy natural breasts under opaque clothing:1.55",
            covered["positive_prompt"],
        )
        self.assertIn("enormous wide deep projecting clothed bust:1.5", covered["positive_prompt"])
        self.assertIn("breasts completely covered", covered["positive_prompt"])
        self.assertIn("extremely large heavy natural breasts", nude["positive_prompt"])
        self.assertNotIn("under opaque clothing", nude["positive_prompt"])

    def test_dress_templates_only_offer_physically_compatible_bra_layers(self):
        state, storyboard_id = self.make_storyboard(count=8, prompt_seed=7788)
        state.update_director(
            storyboard_id,
            {
                "shot": 1,
                "field": "outfit.template",
                "value": "template_sexy_casual_dress",
            },
        )
        fields = director_fields(state.director_payload(storyboard_id, 1))
        bra_ids = {option["id"] for option in fields["outfit.garments.bra"]["options"]}
        dress_ids = {
            option["id"] for option in fields["outfit.garments.full_body"]["options"]
        }
        self.assertIn("bra_tshirt", bra_ids)
        self.assertNotIn("bra_sports", bra_ids)
        self.assertNotIn("bra_longline", bra_ids)
        self.assertIn("dress_tshirt_bodycon", dress_ids)
        self.assertNotIn("dress_offshoulder_knit_mini", dress_ids)
        with self.assertRaises(app.AppError):
            state.update_director(
                storyboard_id,
                {
                    "shot": 1,
                    "field": "outfit.garments.bra",
                    "value": "bra_sports",
                },
            )

    def test_resolved_outfits_always_pass_layer_validation(self):
        database, _ = app.load_database()
        composer = app.Composer(database, app.random.Random(9911))
        protected = {
            template_id
            for rule in database["settings"]["garment_layer_rules"]
            for template_id in rule["template_ids"]
        }
        for template in database["outfit_templates"]:
            if template["id"] not in protected:
                continue
            for _ in range(50):
                app.validate_outfit_layers(
                    database,
                    composer.choose_outfit(template),
                )

    def test_prop_is_directly_editable_with_only_compatible_options(self):
        state, storyboard_id = self.make_storyboard(count=12, prompt_seed=13579)
        payload = state.director_payload(storyboard_id, 1)
        field = director_fields(payload)["shot.prop"]
        compatible = [option for option in field["options"] if option["id"]]
        self.assertTrue(compatible)
        selected = compatible[0]
        updated = state.update_director(
            storyboard_id,
            {"shot": 1, "field": "shot.prop", "value": selected["id"]},
        )
        self.assertEqual(director_fields(updated)["shot.prop"]["value"], selected["id"])
        rendered = state.storyboard_payload(state.get_storyboard(storyboard_id))["shots"][0]
        self.assertIn(selected["prompt"], rendered["positive_prompt"])

    def test_garment_transition_can_be_changed_disabled_and_customized(self):
        state, storyboard_id = self.make_storyboard(count=12, prompt_seed=24680)
        record = state.get_storyboard(storyboard_id)
        position = next(
            index for index, shot in enumerate(record["shots"], 1)
            if shot["scene"].get("garment_transition")
        )
        field = director_fields(state.director_payload(storyboard_id, position))[
            "shot.garment_transition"
        ]
        alternative = next(
            option for option in field["options"]
            if option["id"] and option["id"] != field["value"]
        )
        state.update_director(
            storyboard_id,
            {
                "shot": position,
                "field": "shot.garment_transition",
                "value": alternative["id"],
            },
        )
        rendered = state.storyboard_payload(state.get_storyboard(storyboard_id))["shots"][position - 1]
        self.assertIn(alternative["prompt"], rendered["positive_prompt"])
        disabled = state.update_director(
            storyboard_id,
            {"shot": position, "field": "shot.garment_transition", "value": ""},
        )
        self.assertIn("shot.garment_transition", director_fields(disabled))
        self.assertNotIn(alternative["prompt"], state.storyboard_payload(
            state.get_storyboard(storyboard_id)
        )["shots"][position - 1]["positive_prompt"])
        state.update_director(
            storyboard_id,
            {
                "shot": position,
                "field": "shot.garment_transition",
                "custom_value": "carefully sliding the dress down",
            },
        )
        self.assertIn("carefully sliding the dress down", state.storyboard_payload(
            state.get_storyboard(storyboard_id)
        )["shots"][position - 1]["positive_prompt"])

    def test_legacy_prompt_profile_is_ignored_without_truncation(self):
        state = app.WebState()
        common = {
            "mode": "photoshoot", "count": 4, "photoshoots": 1,
            "prompt_seed": 31415, "inference_seed": 92653,
        }
        normal = state.create_storyboard(common)
        legacy = state.create_storyboard({**common, "prompt_profile": "compact"})
        normal_prompts = [shot["positive_prompt"] for shot in normal["shots"]]
        legacy_prompts = [shot["positive_prompt"] for shot in legacy["shots"]]
        self.assertEqual(normal_prompts, legacy_prompts)


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


class OutputDeletionRegressionTests(unittest.TestCase):
    def test_output_payload_provides_versioned_thumbnail_url(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.png"
            target.write_bytes(b"image")
            payload = app.output_payload(target)
        self.assertEqual(payload["url"], "/api/outputs/result.png")
        self.assertRegex(payload["thumbnail_url"], r"^/api/thumbnails/result\.png\?v=\d+$")

    def test_generated_thumbnail_is_reused_from_memory_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.png"
            target.write_bytes(b"image")
            app._thumbnail_cache_remove()
            with (
                patch.object(app, "output_directory", return_value=Path(directory)),
                patch.object(app, "Image", None),
            ):
                key = (target.name, target.stat().st_mtime_ns, target.stat().st_size)
                with app.THUMBNAIL_CACHE_LOCK:
                    app.THUMBNAIL_CACHE[key] = b"thumbnail"
                    app.THUMBNAIL_CACHE_BYTES = len(b"thumbnail")
                self.assertEqual(app.output_thumbnail(target.name), b"thumbnail")
            app._thumbnail_cache_remove()

    def test_concurrent_thumbnail_misses_share_one_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.png"
            target.write_bytes(b"image")
            app._thumbnail_cache_remove()
            workers = 8
            ready = threading.Barrier(workers)
            calls = 0
            calls_lock = threading.Lock()

            def generate(_target):
                nonlocal calls
                with calls_lock:
                    calls += 1
                time.sleep(0.05)
                return b"thumbnail"

            def request_thumbnail():
                ready.wait()
                return app.output_thumbnail(target.name)

            with (
                patch.object(app, "output_directory", return_value=Path(directory)),
                patch.object(app, "_generate_thumbnail", side_effect=generate),
                concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor,
            ):
                results = list(executor.map(lambda _: request_thumbnail(), range(workers)))
            self.assertEqual(results, [b"thumbnail"] * workers)
            self.assertEqual(calls, 1)
            app._thumbnail_cache_remove()

    def test_thumbnail_generation_failure_is_shared_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.png"
            target.write_bytes(b"image")
            app._thumbnail_cache_remove()
            workers = 4
            ready = threading.Barrier(workers)

            def fail(_target):
                time.sleep(0.05)
                raise app.AppError("thumbnail failed")

            def request_thumbnail():
                ready.wait()
                return app.output_thumbnail(target.name)

            with (
                patch.object(app, "output_directory", return_value=Path(directory)),
                patch.object(app, "_generate_thumbnail", side_effect=fail) as generate,
                concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor,
            ):
                futures = [executor.submit(request_thumbnail) for _ in range(workers)]
                for future in futures:
                    with self.assertRaisesRegex(app.AppError, "thumbnail failed"):
                        future.result()
                self.assertEqual(generate.call_count, 1)

            with (
                patch.object(app, "output_directory", return_value=Path(directory)),
                patch.object(app, "_generate_thumbnail", return_value=b"retry") as generate,
            ):
                self.assertEqual(app.output_thumbnail(target.name), b"retry")
                generate.assert_called_once_with(target)
            app._thumbnail_cache_remove()

    def test_thumbnail_cache_evicts_least_recently_used_entries_by_byte_size(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            first = output_dir / "first.png"
            second = output_dir / "second.png"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            generated = []

            def generate(target):
                generated.append(target.name)
                return target.stem.encode()[:6]

            app._thumbnail_cache_remove()
            with (
                patch.object(app, "output_directory", return_value=output_dir),
                patch.object(app, "_generate_thumbnail", side_effect=generate),
                patch.object(app, "THUMBNAIL_CACHE_MAX_BYTES", 10),
            ):
                self.assertEqual(app.output_thumbnail(first.name), b"first")
                self.assertEqual(app.output_thumbnail(second.name), b"second")
                self.assertEqual(app.output_thumbnail(second.name), b"second")
                self.assertEqual(app.output_thumbnail(first.name), b"first")
                self.assertEqual(generated, ["first.png", "second.png", "first.png"])
                self.assertLessEqual(app.THUMBNAIL_CACHE_BYTES, 10)
            app._thumbnail_cache_remove()

    def test_deleting_output_invalidates_all_cached_versions_of_its_thumbnail(self):
        state = app.WebState()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            target = output_dir / "result.png"
            target.write_bytes(b"image")
            removed_keys = [
                (target.name, 1, 5),
                (target.name, 2, 5),
            ]
            retained_key = ("other.png", 1, 5)
            app._thumbnail_cache_remove()
            with app.THUMBNAIL_CACHE_LOCK:
                app.THUMBNAIL_CACHE[removed_keys[0]] = b"old"
                app.THUMBNAIL_CACHE[retained_key] = b"other"
                app.THUMBNAIL_CACHE[removed_keys[1]] = b"new"
                app.THUMBNAIL_CACHE_BYTES = 11

            with (
                patch.object(app, "WEB_STATE", state),
                patch.object(app, "output_directory", return_value=output_dir),
            ):
                app.delete_output_image(target.name)

            with app.THUMBNAIL_CACHE_LOCK:
                self.assertEqual(list(app.THUMBNAIL_CACHE), [retained_key])
                self.assertEqual(app.THUMBNAIL_CACHE_BYTES, len(b"other"))
            app._thumbnail_cache_remove()

    def test_completed_frame_can_be_deleted_while_batch_is_rendering(self):
        state = app.WebState()
        name = "run_photoshoot_001_shot_001_1_image_01.png"
        state.jobs["job"] = {
            "status": "running",
            "_run_id": "run",
            "outputs": [{"name": name, "url": f"/api/outputs/{name}"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / name
            target.write_bytes(b"complete image")
            with (
                patch.object(app, "WEB_STATE", state),
                patch.object(app, "output_directory", return_value=Path(directory)),
            ):
                result = app.delete_output_image(name)
        self.assertEqual(result["deleted"], name)
        self.assertFalse(target.exists())
        self.assertEqual(state.jobs["job"]["outputs"], [])

    def test_frame_still_being_written_remains_protected(self):
        state = app.WebState()
        name = "run_photoshoot_001_shot_002_2_image_01.png"
        state.jobs["job"] = {
            "status": "running", "_run_id": "run", "outputs": []
        }
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / name
            target.write_bytes(b"partial image")
            with (
                patch.object(app, "WEB_STATE", state),
                patch.object(app, "output_directory", return_value=Path(directory)),
            ):
                with self.assertRaisesRegex(app.AppError, "still being written"):
                    app.delete_output_image(name)
                self.assertTrue(target.exists())


class FrontendContractTests(unittest.TestCase):
    def test_lightbox_close_aligns_grid_to_last_viewed_output(self):
        js = (Path(app.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function syncOutputGridToPreview()", js)
        self.assertIn("focusOutputCard(state.previewIndex, { alignTop: true })", js)
        self.assertIn("window.scrollTo({ top: cardTop, behavior: 'auto' })", js)
        self.assertIn("syncOutputGridToPreview();", js)

    def test_lightbox_has_fullscreen_and_non_interrupting_slideshow_controls(self):
        root = Path(app.__file__).parent
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        js = (root / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="image-true-fullscreen"', html)
        self.assertIn('id="image-viewer-shell"', html)
        self.assertIn('id="image-slideshow-toggle"', html)
        self.assertNotIn("<span>Pause</span>", html)
        self.assertIn('class="viewer-delay-menu"', html)
        slideshow = html.split('id="image-slideshow-delay"', 1)[1].split("</select>", 1)[0]
        self.assertEqual(slideshow.count('<option value="'), 10)
        self.assertIn("function scheduleSlideshow()", js)
        self.assertIn("if (state.slideshowActive) scheduleSlideshow();", js)
        self.assertIn("document.fullscreenElement === target", js)
        self.assertIn("target.requestFullscreen()", js)
        self.assertIn("const target = $('#image-viewer-shell')", js)
        self.assertIn("function hideFullscreenControls()", js)
        self.assertIn("setTimeout(hideFullscreenControls, 2200)", js)
        self.assertIn("event.clientY > 90", js)

    def test_output_cards_use_lazy_async_thumbnails(self):
        js = (Path(app.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("item.thumbnail_url || item.url", js)
        self.assertIn('loading="lazy" decoding="async"', js)

    def test_output_gallery_virtualizes_rows_with_bounded_overscan(self):
        js = (Path(app.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("const OUTPUT_OVERSCAN_ROWS = 3", js)
        self.assertIn(".slice(start, end)", js)
        self.assertIn("renderVirtualOutputs", js)
        self.assertNotIn("state.outputs.map((item, index)", js)

    def test_virtual_output_navigation_uses_stable_absolute_indexes(self):
        js = (Path(app.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-output-index="${index}"', js)
        self.assertIn("focusOutputCard(state.previewIndex, { alignTop: true })", js)
        self.assertIn("ArrowUp: -columns, ArrowDown: columns", js)

    def test_typography_presets_use_relative_scale_with_normal_default(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        js = (root / "web" / "app.js").read_text(encoding="utf-8")
        css = (root / "web" / "styles.css").read_text(encoding="utf-8")

        for size in ("small", "normal", "large"):
            self.assertIn(f'data-type-size="{size}"', html)
            self.assertIn(f':root[data-type-size="{size}"]', css)
        self.assertIn(": 'normal'", js)
        self.assertIn("valhalla-type-size", js)
        self.assertIn("font-size: 0.75rem", css)

    def test_entity_values_are_capitalized_without_bold_emphasis(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "web" / "app.js").read_text(encoding="utf-8")
        css = (root / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function displayValue(value)", js)
        self.assertIn("escapeHtml(displayValue(shot.pose.prompt))", js)
        self.assertIn("const display = displayValue(value)", js)
        self.assertIn('strong title="${escapeHtml(display)}"', js)
        self.assertIn(".shot-detail strong { overflow: hidden; color: var(--text); font-weight: 450;", css)
        self.assertIn(".director-summary strong { margin-top: 3px; font-size: 0.75rem; font-weight: 450;", css)

    def test_clearing_director_search_collapses_all_groups(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("filterDirector(query, { collapseEmpty = false } = {})", js)
        self.assertIn("if (!normalized && collapseEmpty)", js)
        self.assertIn("state.directorOpenGroup = null", js)
        self.assertIn("filterDirector(event.target.value, { collapseEmpty: true })", js)

    def test_director_marks_defaults_only_inside_dropdown(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("option.default ? ' (default)' : ''", js)
        self.assertNotIn("Database default", js)
        self.assertNotIn("escapeHtml(current?.prompt || current?.label || '')", js)

    def test_dropdowns_and_render_split_share_unified_control_geometry(self):
        root = Path(__file__).resolve().parents[1]
        css = (root / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".field input, .field select, .director-field select", css)
        self.assertIn(".render-choice { display: inline-grid;", css)
        self.assertIn("overflow: hidden; border: 1px solid", css)
        self.assertIn(".render-choice:focus-within", css)
        self.assertIn(".render-choice:hover .button.render", css)

    def test_studio_and_director_use_the_same_control_column_width(self):
        root = Path(__file__).resolve().parents[1]
        css = (root / "web" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("--workspace-control-column: 328px", css)
        self.assertIn(
            ".studio-grid { display: grid; grid-template-columns: var(--workspace-control-column)",
            css,
        )
        self.assertIn(
            ".director-workspace { min-height: calc(100vh - 122px); display: grid; grid-template-columns: var(--workspace-control-column)",
            css,
        )
        self.assertIn(".director-rail { position: static; width: 100%; min-width: 0;", css)
        self.assertNotIn(".director-rail { position: sticky", css)

    def test_storyboard_render_mode_uses_synchronized_split_buttons(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "web" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('name="fast"', html)
        self.assertEqual(html.count("data-render-mode"), 2)
        self.assertIn("Preview storyboard", html)
        self.assertIn("Render storyboard", html)
        self.assertIn("state.renderMode === 'preview'", javascript)
        self.assertNotIn("retry_count", html)
        self.assertNotIn("retry_count", javascript)

    def test_global_settings_have_pending_update_and_slider_guardrails(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "web" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'id="config-notice"', 'id="active-config"',
            'id="nsfw-help"', 'id="plateau-help"',
            'id="update-storyboard-dialog"',
        ):
            self.assertIn(marker, html)
        self.assertIn("state.pendingStructural", javascript)
        self.assertIn("Update & Render", javascript)
        self.assertIn("form.elements.plateau_percent.max = String(nsfw)", javascript)
        self.assertIn("form.elements.plateau_percent.disabled", javascript)
        self.assertIn("if (state.pendingStructural)", javascript)


class StoryboardEditStateTests(unittest.TestCase):
    def test_director_edit_flag_survives_export_import(self):
        state = app.WebState()
        board = state.create_storyboard({
            "mode": "photoshoot", "count": 4, "photoshoots": 1,
            "prompt_seed": 123, "inference_seed": 456,
        })
        self.assertFalse(board["director_edited"])
        updated = state.update_director(
            board["id"],
            {"shot": 1, "field": "shot.intensity", "value": "sensual"},
        )
        self.assertTrue(updated["summary"] is not None)
        self.assertTrue(state.storyboard_payload(state.get_storyboard(board["id"]))["director_edited"])
        imported = state.import_storyboard(state.export_storyboard(board["id"]))
        self.assertTrue(imported["director_edited"])


class RenderLifecycleRegressionTests(unittest.TestCase):
    def test_cancel_requested_is_exposed_to_the_ui(self):
        state = app.WebState()
        job = {
            "id": "job",
            "status": "running",
            "cancel_requested": True,
        }
        self.assertTrue(state.job_payload(job)["cancel_requested"])


class PreviewVisualAuditTests(unittest.TestCase):
    def test_balanced_profile_is_reproducible_and_uses_non_default_subjects(self):
        replay_seed = 20260721
        first = preview_qa.build_record(3, 8, replay_seed)
        second = preview_qa.build_record(3, 8, replay_seed)
        self.assertEqual(
            [shot["inference_seed"] for shot in first["shots"]],
            [shot["inference_seed"] for shot in second["shots"]],
        )
        for photoshoot in range(3):
            shots = first["shots"][photoshoot * 8:(photoshoot + 1) * 8]
            safe = sum(
                shot["stage"]["level"] not in app.NSFW_LEVELS for shot in shots
            )
            self.assertEqual((safe, len(shots) - safe), (4, 4))
            self.assertTrue(
                preview_qa._uses_non_default_subject(first, photoshoot * 8 + 1)
            )

    def test_review_jpeg_limit_is_100_kilobytes(self):
        self.assertEqual(preview_qa.MAX_REVIEW_BYTES, 100_000)

    def test_random_audit_seed_survives_incompatible_scene_remix(self):
        record = preview_qa.build_record(10, 8, 8788274676380310665)
        self.assertEqual(len(record["shots"]), 80)


class VisualCompatibilityRegressionTests(unittest.TestCase):
    def test_random_scenes_obey_physical_and_wardrobe_contracts(self):
        database, _ = app.load_database()
        composer = app.Composer(database, app.random.Random(20260721))
        checked = 0
        for _ in range(80):
            fixed = composer.fixed_context()
            for stage in app.effective_photoshoot_stages(fixed["outfit"]["template"]):
                scene = composer.resolve_scene(fixed, stage)
                checked += 1
                furniture_tags = app.tags(scene["furniture"])
                if scene["pose"]["id"].startswith("pose_bed_"):
                    self.assertIn("bed", furniture_tags)
                if scene["pose"]["id"] == "pose_sofa_sprawl":
                    self.assertIn("sofa", furniture_tags)
                if scene["pose"]["id"] == "pose_chair_reverse":
                    self.assertIn("chair", furniture_tags)
                self.assertLessEqual(
                    sum(app.hands_required(scene.get(key)) for key in ("pose", "action", "prop")),
                    2,
                )
                self.assertFalse(
                    "rear_focus" in app.tags(scene["shot_size"])
                    and scene["focus_target"]["id"] == "focus_face"
                )
        self.assertGreater(checked, 200)

    def test_sheer_covered_stage_uses_same_opaque_bra_in_prompt(self):
        database, _ = app.load_database()
        composer = app.Composer(database, app.random.Random(991177))
        found = False
        for _ in range(300):
            fixed = composer.fixed_context()
            for stage in fixed["outfit"]["template"]["stages"]:
                visible = [
                    fixed["outfit"]["garments"][slot]
                    for slot in stage.get("visible_slots", [])
                    if slot in fixed["outfit"]["garments"]
                ]
                if stage["level"] != "covered" or not any(
                    "sheer" in app.tags(item) for item in visible
                ):
                    continue
                found = True
                bra = fixed["outfit"]["garments"]["bra"]
                self.assertFalse(app.tags(bra) & {"sheer", "explicit"})
                scene = composer.resolve_scene(fixed, stage)
                positive, _, selected = app.compile_scene(database, scene)
                self.assertIn(bra["prompt"], positive)
                self.assertIn(bra["id"], selected)
                self.assertIn("same underlying", positive)
                break
            if found:
                break
        self.assertTrue(found)

    def test_lingerie_stage_never_hides_breasts_with_an_exposing_bra(self):
        database, _ = app.load_database()
        composer = app.Composer(database, app.random.Random(778899))
        sheer_checked = False
        for _ in range(250):
            fixed = composer.fixed_context()
            for stage in fixed["outfit"]["template"]["stages"]:
                if stage["level"] != "lingerie" or "bra" not in stage.get("visible_slots", []):
                    continue
                bra = fixed["outfit"]["garments"]["bra"]
                self.assertNotIn("explicit", app.tags(bra))
                if "sheer" not in app.tags(bra):
                    continue
                scene = composer.resolve_scene(fixed, stage)
                positive, negative, _ = app.compile_scene(database, scene)
                self.assertIn("one coherent sheer bra", positive)
                self.assertNotIn("opaque bra, lingerie top", positive)
                self.assertNotIn("transparent chest fabric", negative)
                sheer_checked = True
                break
            if sheer_checked:
                break
        self.assertTrue(sheer_checked)

    def test_covered_prompt_avoids_nipple_like_raised_disc_instruction(self):
        database, _ = app.load_database()
        composer = app.Composer(database, app.random.Random(4545))
        while True:
            fixed = composer.fixed_context()
            stage = next((
                item for item in fixed["outfit"]["template"]["stages"]
                if item["level"] == "covered"
            ), None)
            if stage:
                break
        positive, _, _ = app.compile_scene(database, composer.resolve_scene(fixed, stage))
        self.assertNotIn("raised cloth contour at each bust apex", positive)
        self.assertIn("no colored anatomical detail visible", positive)

    def test_panties_are_compiled_beneath_pantyhose_and_tights(self):
        database, _ = app.load_database()
        composer = app.Composer(database, app.random.Random(314159))
        checked = 0
        for _ in range(500):
            fixed = composer.fixed_context()
            legwear = fixed["outfit"]["garments"].get("legwear")
            if not legwear:
                continue
            legwear_prompt = legwear["prompt"].casefold()
            if not (
                "pantyhose" in app.tags(legwear)
                or "pantyhose" in legwear_prompt
                or "tights" in legwear_prompt
            ):
                continue
            for stage in app.effective_photoshoot_stages(fixed["outfit"]["template"]):
                visible = set(stage.get("visible_slots", []))
                if not {"panties", "legwear"}.issubset(visible):
                    continue
                positive, negative, _ = app.compile_scene(
                    database, composer.resolve_scene(fixed, stage)
                )
                self.assertIn("panties are worn underneath", positive)
                self.assertIn("continuous outer layer over the panties", positive)
                self.assertIn("panties outside pantyhose", negative)
                checked += 1
                break
            if checked >= 10:
                break
        self.assertGreaterEqual(checked, 10)


if __name__ == "__main__":
    unittest.main()
