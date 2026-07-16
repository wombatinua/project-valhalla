#!/usr/bin/env python3
"""Small, single-file rule-based prompt composer for a local ComfyUI server."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
except ImportError:  # dry-run deliberately works without the HTTP dependency
    requests = None  # type: ignore[assignment]


class AppError(RuntimeError):
    """An expected, user-facing application error."""


def weighted_choice(rng: random.Random, items: list[dict[str, Any]]) -> dict[str, Any]:
    items = [item for item in items if not item.get("disabled", False)]
    if not items:
        raise AppError("No compatible choices remain for a required selection")
    weights = [float(item.get("weight", 1)) for item in items]
    if any(weight <= 0 for weight in weights):
        raise AppError("Every selectable item weight must be greater than zero")
    return rng.choices(items, weights=weights, k=1)[0]


def database_path() -> Path:
    return Path(__file__).resolve().with_name("database.json")


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_database() -> tuple[dict[str, Any], Path]:
    path = database_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"Database not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AppError(f"Invalid JSON in {path}: {exc}") from exc
    validate_database(data, require_mapping=False)
    return data, path


def iter_content_items(db: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for values in db.get("human_model_parts", {}).values():
        if isinstance(values, list):
            yield from values
    yield from db.get("colors", [])
    for values in db.get("garments", {}).values():
        yield from values
    for section in (
        "outfit_templates", "interiors", "furniture", "poses", "actions",
        "props", "expressions", "moods", "photography_styles",
    ):
        yield from db.get(section, [])


def validate_item(item: Any, context: str) -> None:
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        raise AppError(f"{context}: every item needs a string id")
    if context != "outfit_templates" and not isinstance(item.get("prompt"), str):
        raise AppError(f"{context}.{item['id']}: missing string prompt")
    weight = item.get("weight", 1)
    if not isinstance(weight, (int, float)) or weight <= 0:
        raise AppError(f"{context}.{item['id']}: weight must be greater than zero")
    if "disabled" in item and not isinstance(item["disabled"], bool):
        raise AppError(f"{context}.{item['id']}: disabled must be true or false")


def validate_database(db: dict[str, Any], require_mapping: bool) -> None:
    required_sections = (
        "settings", "prompt_defaults", "colors", "human_model_parts", "garments",
        "outfit_templates", "interiors", "furniture", "poses", "actions", "props",
        "expressions", "moods", "photography_styles",
    )
    for section in required_sections:
        if section not in db:
            raise AppError(f"database.json is missing the '{section}' section")
    settings = db["settings"]
    for key in ("comfy_url", "workflow_file", "output_dir"):
        if not isinstance(settings.get(key), str) or not settings[key]:
            raise AppError(f"settings.{key} must be a non-empty string")
    progression = settings.get("photoshoot_progression", {})
    nsfw_percent = progression.get("nsfw_final_percent", 50)
    if not isinstance(nsfw_percent, (int, float)) or not 0 <= nsfw_percent <= 100:
        raise AppError("settings.photoshoot_progression.nsfw_final_percent must be between 0 and 100")
    plateau_percent = progression.get("explicit_plateau_percent", 30)
    if not isinstance(plateau_percent, (int, float)) or not 0 <= plateau_percent <= nsfw_percent:
        raise AppError(
            "settings.photoshoot_progression.explicit_plateau_percent must be between 0 "
            "and nsfw_final_percent"
        )

    ids: set[str] = set()
    index: dict[str, dict[str, Any]] = {}
    for section, values in db["human_model_parts"].items():
        if not isinstance(values, list) or not values:
            raise AppError(f"human_model_parts.{section} must be a non-empty list")
        for item in values:
            validate_item(item, f"human_model_parts.{section}")
            if item["id"] in ids:
                raise AppError(f"Duplicate id: {item['id']}")
            ids.add(item["id"]); index[item["id"]] = item
    for section, values in db["garments"].items():
        if not isinstance(values, list) or not values:
            raise AppError(f"garments.{section} must be a non-empty list")
        for item in values:
            validate_item(item, f"garments.{section}")
            if item["id"] in ids:
                raise AppError(f"Duplicate id: {item['id']}")
            ids.add(item["id"]); index[item["id"]] = item
    for section in (
        "colors", "outfit_templates", "interiors", "furniture", "poses", "actions",
        "props", "expressions", "moods", "photography_styles",
    ):
        values = db[section]
        if not isinstance(values, list) or not values:
            raise AppError(f"{section} must be a non-empty list")
        for item in values:
            validate_item(item, section)
            if item["id"] in ids:
                raise AppError(f"Duplicate id: {item['id']}")
            ids.add(item["id"]); index[item["id"]] = item

    enabled_ids = {item_id for item_id, item in index.items() if not item.get("disabled", False)}
    color_ids = {item["id"] for item in db["colors"]}
    enabled_color_ids = {
        item["id"] for item in db["colors"] if not item.get("disabled", False)
    }
    if not enabled_color_ids:
        raise AppError("colors must contain at least one enabled item")
    for section, values in db["human_model_parts"].items():
        if not any(not item.get("disabled", False) for item in values):
            raise AppError(f"human_model_parts.{section} must contain at least one enabled item")
    for section, values in db["garments"].items():
        if not any(not item.get("disabled", False) for item in values):
            raise AppError(f"garments.{section} must contain at least one enabled item")
    for section in (
        "outfit_templates", "interiors", "furniture", "poses", "actions",
        "expressions", "moods", "photography_styles",
    ):
        if not any(not item.get("disabled", False) for item in db[section]):
            raise AppError(f"{section} must contain at least one enabled item")
    garment_catalogs = set(db["garments"])
    for item in index.values():
        for key in ("requires", "excludes"):
            for reference in item.get(key, []):
                if reference not in ids:
                    raise AppError(f"{item['id']}.{key} references unknown id '{reference}'")
        unknown_colors = set(item.get("allowed_colors", [])) - color_ids
        if unknown_colors:
            raise AppError(f"{item['id']} references unknown colors: {sorted(unknown_colors)}")
        if not item.get("disabled", False):
            disabled_requirements = set(item.get("requires", [])) - enabled_ids
            if disabled_requirements:
                raise AppError(
                    f"Enabled item {item['id']} requires disabled IDs: "
                    f"{sorted(disabled_requirements)}"
                )
            configured_colors = set(item.get("allowed_colors", []))
            if configured_colors and not configured_colors & enabled_color_ids:
                raise AppError(f"Enabled item {item['id']} has no enabled allowed colors")

    for template in db["outfit_templates"]:
        slots = template.get("slots")
        stages = template.get("stages")
        if not isinstance(slots, dict) or not slots:
            raise AppError(f"Template {template['id']} needs a non-empty slots object")
        if not isinstance(stages, list) or not stages:
            raise AppError(f"Template {template['id']} needs at least one stage")
        for slot, rule in slots.items():
            if rule.get("catalog") not in garment_catalogs:
                raise AppError(f"Template {template['id']} slot {slot} has unknown catalog")
            chance = rule.get("chance", 1)
            if not isinstance(chance, (int, float)) or not 0 <= chance <= 1:
                raise AppError(f"Template {template['id']} slot {slot} chance must be 0..1")
        for stage in stages:
            if not isinstance(stage.get("id"), str) or not isinstance(stage.get("level"), str):
                raise AppError(f"Template {template['id']} has an invalid stage")
            unknown_slots = set(stage.get("visible_slots", [])) - set(slots)
            if unknown_slots:
                raise AppError(f"Template {template['id']} stage has unknown slots: {sorted(unknown_slots)}")

    if require_mapping:
        mapping = db.get("node_mapping", {})
        for key in ("positive_prompt", "negative_prompt", "inference_seed"):
            if not mapping.get(key):
                raise AppError(f"node_mapping.{key} is missing; run 'python app.py capture' first")


def tags(item: dict[str, Any]) -> set[str]:
    return set(item.get("tags", []))


def compatible_with_requirements(item: dict[str, Any], available_tags: set[str]) -> bool:
    required_any = set(item.get("requires_any_tags", []))
    return (
        set(item.get("requires_tags", [])).issubset(available_tags)
        and (not required_any or bool(required_any & available_tags))
        and not (set(item.get("excludes_tags", [])) & available_tags)
    )


NSFW_LEVELS = ("topless", "nude", "explicit")


def effective_photoshoot_stages(template: dict[str, Any]) -> list[dict[str, Any]]:
    """Return configured stages plus generic terminal NSFW stages when absent."""
    stages = copy.deepcopy(template["stages"])
    levels = {stage["level"] for stage in stages}
    terminal_specs = {
        "topless": {
            "visible_slots": ["panties", "legwear", "footwear", "accessories"],
            "body_visibility": ["breasts", "nipples"],
        },
        "nude": {
            "visible_slots": ["legwear", "footwear", "accessories"],
            "body_visibility": ["breasts", "nipples", "pubic_area", "genitals"],
        },
        "explicit": {
            "visible_slots": ["legwear", "footwear", "accessories"],
            "body_visibility": ["breasts", "nipples", "pubic_area", "genitals"],
        },
    }
    template_slots = set(template["slots"])
    for level in NSFW_LEVELS:
        if level in levels:
            continue
        spec = terminal_specs[level]
        stages.append({
            "id": f"{template['id']}_{level}",
            "level": level,
            "visible_slots": [slot for slot in spec["visible_slots"] if slot in template_slots],
            "body_visibility": spec["body_visibility"],
        })
    safe = [stage for stage in stages if stage["level"] not in NSFW_LEVELS]
    nsfw = sorted(
        (stage for stage in stages if stage["level"] in NSFW_LEVELS),
        key=lambda stage: NSFW_LEVELS.index(stage["level"]),
    )
    return safe + nsfw


def progressive_stage(stages: list[dict[str, Any]], index: int, count: int) -> dict[str, Any]:
    if count <= len(stages):
        return stages[len(stages) - count + index]
    return stages[min(len(stages) - 1, index * len(stages) // count)]


class Composer:
    def __init__(self, db: dict[str, Any], rng: random.Random):
        self.db = db
        self.rng = rng
        self.colors = {
            item["id"]: item for item in db["colors"] if not item.get("disabled", False)
        }
        self.item_index = {
            item["id"]: item
            for item in iter_content_items(db)
            if not item.get("disabled", False)
        }

    def choose_human(self) -> dict[str, Any]:
        human: dict[str, Any] = {}
        parts = self.db["human_model_parts"]
        order = list(parts)
        for category in order:
            if category == "facial_accents":
                count = self.rng.choices([0, 1, 2], weights=[3, 5, 2], k=1)[0]
                candidates = [item for item in parts[category] if not item.get("disabled", False)]
                human[category] = self.rng.sample(candidates, k=min(count, len(candidates)))
                continue
            candidates = list(parts[category])
            if category == "hair_style":
                selected_tags = tags(human["hair_length"]) | tags(human["hair_texture"])
                candidates = [item for item in candidates if compatible_with_requirements(item, selected_tags)]
            elif category == "areola_color":
                selected_tags = tags(human["skin_tone"])
                candidates = [item for item in candidates if compatible_with_requirements(item, selected_tags)]
            human[category] = weighted_choice(self.rng, candidates)
        return human

    def choose_template(self) -> dict[str, Any]:
        return weighted_choice(self.rng, self.db["outfit_templates"])

    def _choose_outfit_once(self, template: dict[str, Any]) -> dict[str, Any]:
        selected: dict[str, dict[str, Any]] = {}
        group_tags: dict[str, set[str]] = {}
        for slot, rule in template["slots"].items():
            required = bool(rule.get("required", False))
            if not required and self.rng.random() > float(rule.get("chance", 1)):
                continue
            candidates = list(self.db["garments"][rule["catalog"]])
            required_tags = set(rule.get("required_tags", []))
            if required_tags:
                candidates = [item for item in candidates if required_tags.issubset(tags(item))]
            match_group = rule.get("match_group")
            if match_group and match_group in group_tags:
                candidates = [
                    item for item in candidates
                    if set(item.get("mix_tags", item.get("tags", []))) & group_tags[match_group]
                ]
            choice = weighted_choice(self.rng, candidates)
            selected[slot] = choice
            if match_group:
                mix = set(choice.get("mix_tags", choice.get("tags", [])))
                group_tags[match_group] = group_tags.get(match_group, mix) & mix

        occupied: dict[str, str] = {}
        for slot, item in selected.items():
            for occupied_slot in item.get("occupies_slots", [slot]):
                if occupied_slot in occupied and occupied[occupied_slot] != item["id"]:
                    raise AppError(f"Outfit slot conflict: {occupied[occupied_slot]} and {item['id']}")
                occupied[occupied_slot] = item["id"]

        assigned_colors: dict[str, dict[str, Any]] = {}
        grouped_slots: dict[str, list[str]] = {}
        for slot in selected:
            group = template["slots"][slot].get("color_group")
            if group:
                grouped_slots.setdefault(group, []).append(slot)
        color_groups: dict[str, str] = {}
        for group, slots in grouped_slots.items():
            shared = set(self.colors)
            for slot in slots:
                shared &= set(selected[slot].get("allowed_colors") or self.colors)
            if not shared:
                raise AppError(f"Outfit color group '{group}' has no color shared by slots {slots}")
            color_groups[group] = self.rng.choice(sorted(shared))
        for slot, item in selected.items():
            allowed = [
                color_id
                for color_id in (item.get("allowed_colors") or list(self.colors))
                if color_id in self.colors
            ]
            rule = template["slots"][slot]
            group = rule.get("color_group")
            if group:
                color_id = color_groups[group]
            else:
                color_id = self.rng.choice(allowed)
            assigned_colors[slot] = self.colors[color_id]
        return {"template": template, "garments": selected, "colors": assigned_colors}

    def choose_outfit(self, template: dict[str, Any]) -> dict[str, Any]:
        attempts = int(self.db["settings"].get("max_scene_attempts", 100))
        last_error = "no compatible outfit"
        for _ in range(attempts):
            try:
                return self._choose_outfit_once(template)
            except AppError as exc:
                last_error = str(exc)
        raise AppError(
            f"Could not resolve outfit template {template['id']} after {attempts} attempts: {last_error}"
        )

    def fixed_context(self) -> dict[str, Any]:
        attempts = int(self.db["settings"].get("max_scene_attempts", 100))
        last_error = "no compatible fixed context"
        for _ in range(attempts):
            try:
                template = self.choose_template()
                interior = weighted_choice(self.rng, self.db["interiors"])
                furniture_candidates = [
                    item for item in self.db["furniture"]
                    if compatible_with_requirements(item, tags(interior))
                ]
                return {
                    "human": self.choose_human(),
                    "outfit": self.choose_outfit(template),
                    "interior": interior,
                    "furniture": weighted_choice(self.rng, furniture_candidates),
                    "mood": weighted_choice(self.rng, self.db["moods"]),
                    "photography_style": weighted_choice(self.rng, self.db["photography_styles"]),
                }
            except AppError as exc:
                last_error = str(exc)
        raise AppError(f"Could not resolve a compatible fixed context after {attempts} attempts: {last_error}")

    def variable_context(
        self,
        stage: dict[str, Any],
        fixed: dict[str, Any],
        overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        overrides = overrides or {}
        available_tags = set(stage.get("body_visibility", [])) | {stage["level"]}
        available_tags |= set(stage.get("visible_slots", []))
        available_tags |= tags(fixed["furniture"]) | tags(fixed["interior"])
        poses = [
            item for item in self.db["poses"]
            if stage["level"] in item.get("allowed_levels", [stage["level"]])
            and compatible_with_requirements(item, available_tags)
        ]
        if stage["level"] == "explicit":
            poses = [item for item in poses if "explicit_pose" in tags(item)]
        elif stage["level"] in {"topless", "nude"}:
            nsfw_pose_tags = {"erotic_pose", "topless_pose", "nude_pose", "open_legs"}
            poses = [item for item in poses if tags(item) & nsfw_pose_tags]
        plateau_kind = stage.get("plateau_kind")
        if plateau_kind == "provocative_rear":
            poses = [item for item in poses if "provocative_rear" in tags(item)]
        elif plateau_kind == "intimate_closeup":
            poses = [item for item in poses if "intimate_closeup" in tags(item)]
        elif plateau_kind == "masturbation":
            poses = [item for item in poses if "masturbation_pose" in tags(item)]
        if overrides.get("pose"):
            poses = [item for item in poses if item["id"] == overrides["pose"]]
        pose = weighted_choice(self.rng, poses)
        action_tags = available_tags | tags(pose)
        actions = [
            item for item in self.db["actions"]
            if stage["level"] in item.get("allowed_levels", [stage["level"]])
            and compatible_with_requirements(item, action_tags)
        ]
        if stage["level"] == "explicit":
            actions = [item for item in actions if "explicit_action" in tags(item)]
        elif stage["level"] in {"topless", "nude"}:
            actions = [
                item for item in actions
                if tags(item) & {"erotic_action", "undressing_action"}
            ]
        if plateau_kind == "provocative_rear":
            actions = [item for item in actions if "provocative_action" in tags(item)]
        elif plateau_kind == "intimate_closeup":
            actions = [item for item in actions if "closeup_action" in tags(item)]
        elif plateau_kind == "masturbation":
            actions = [item for item in actions if "masturbation_action" in tags(item)]
        if overrides.get("action"):
            actions = [item for item in actions if item["id"] == overrides["action"]]
        action = weighted_choice(self.rng, actions)
        prop = None
        required_prop_tags = set(action.get("requires_prop_tags", []))
        if required_prop_tags:
            candidates = [item for item in self.db["props"] if required_prop_tags.issubset(tags(item))]
            prop = weighted_choice(self.rng, candidates)
        elif self.rng.random() < 0.18:
            candidates = [
                item for item in self.db["props"]
                if compatible_with_requirements(item, available_tags | tags(action))
            ]
            if candidates:
                prop = weighted_choice(self.rng, candidates)
        expression_candidates = list(self.db["expressions"])
        required_expression_tags = set(action.get("requires_expression_tags", []))
        if required_expression_tags:
            expression_candidates = [
                item for item in expression_candidates
                if required_expression_tags.issubset(tags(item))
            ]
        if overrides.get("expression"):
            expression_candidates = [
                item for item in expression_candidates
                if item["id"] == overrides["expression"]
            ]
        return {
            "pose": pose,
            "action": action,
            "prop": prop,
            "expression": weighted_choice(self.rng, expression_candidates),
        }

    def resolve_scene(
        self,
        fixed: dict[str, Any],
        stage: dict[str, Any],
        overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        attempts = int(self.db["settings"].get("max_scene_attempts", 100))
        last_error = "no candidates"
        for _ in range(attempts):
            try:
                scene = dict(fixed)
                scene.update(self.variable_context(stage, fixed, overrides))
                scene["stage"] = stage
                scene["dependencies"] = self.resolve_dependencies(scene)
                self.validate_scene_rules(scene)
                return scene
            except AppError as exc:
                last_error = str(exc)
        raise AppError(f"Could not resolve a valid scene after {attempts} attempts: {last_error}")

    def scene_items(self, scene: dict[str, Any]) -> list[dict[str, Any]]:
        selected = list(scene["human"].values())
        flattened: list[dict[str, Any]] = []
        for value in selected:
            flattened.extend(value if isinstance(value, list) else [value])
        visible_slots = set(scene["stage"].get("visible_slots", []))
        flattened.extend(
            item for slot, item in scene["outfit"]["garments"].items() if slot in visible_slots
        )
        flattened.extend([scene[key] for key in ("interior", "furniture", "pose", "action", "expression", "mood", "photography_style")])
        if scene.get("prop"):
            flattened.append(scene["prop"])
        flattened.extend(scene.get("dependencies", []))
        return flattened

    def resolve_dependencies(self, scene: dict[str, Any]) -> list[dict[str, Any]]:
        selected = self.scene_items(scene)
        selected_ids = {item["id"] for item in selected}
        dependencies: list[dict[str, Any]] = []
        cursor = 0
        while cursor < len(selected):
            item = selected[cursor]
            cursor += 1
            for required_id in item.get("requires", []):
                if required_id in selected_ids:
                    continue
                dependency = self.item_index.get(required_id)
                if dependency is None or not dependency.get("prompt"):
                    raise AppError(f"Cannot add dependency '{required_id}' required by {item['id']}")
                dependencies.append(dependency)
                selected.append(dependency)
                selected_ids.add(required_id)
        return dependencies

    def validate_scene_rules(self, scene: dict[str, Any]) -> None:
        flattened = self.scene_items(scene)
        ids = {item["id"] for item in flattened}
        all_tags = set().union(*(tags(item) for item in flattened))
        all_tags |= set(scene["stage"].get("body_visibility", [])) | set(scene["stage"].get("visible_slots", [])) | {scene["stage"]["level"]}
        for item in flattened:
            missing = set(item.get("requires", [])) - ids
            excluded = set(item.get("excludes", [])) & ids
            missing_tags = set(item.get("requires_tags", [])) - all_tags
            missing_any_tags = set(item.get("requires_any_tags", []))
            if missing_any_tags & all_tags:
                missing_any_tags.clear()
            excluded_tags = set(item.get("excludes_tags", [])) & all_tags
            if missing or excluded or missing_tags or missing_any_tags or excluded_tags:
                raise AppError(
                    f"Rule conflict for {item['id']}: missing={sorted(missing)}, "
                    f"excluded={sorted(excluded)}, missing_tags={sorted(missing_tags)}, "
                    f"missing_any_tags={sorted(missing_any_tags)}, "
                    f"excluded_tags={sorted(excluded_tags)}"
                )
        required_expression_tags = set(scene["action"].get("requires_expression_tags", []))
        if not required_expression_tags.issubset(tags(scene["expression"])):
            raise AppError(
                f"Expression {scene['expression']['id']} is incompatible with action "
                f"{scene['action']['id']}; required tags: {sorted(required_expression_tags)}"
            )


ALWAYS_HUMAN_PARTS = (
    "age", "ethnic_appearance", "skin_tone", "face_shape", "eye_shape", "eye_color",
    "eyebrows", "nose", "lips", "cheekbones", "jawline", "hair_texture", "hair_length",
    "hair_style", "hair_color", "height", "body_frame", "waist", "hips", "makeup",
    "manicure",
)

def human_fragments(human: dict[str, Any], visibility: set[str]) -> list[str]:
    items: list[dict[str, Any]] = [human[key] for key in ALWAYS_HUMAN_PARTS]
    items.extend(human.get("facial_accents", []))
    if "breasts" in visibility or "nipples" in visibility:
        items.extend([human["breast_size"], human["breast_shape"]])
    if "nipples" in visibility:
        items.extend([human["areola_size"], human["areola_color"], human["nipple_size"], human["nipple_shape"]])
    if "pubic_area" in visibility:
        items.append(human["pubic_hair"])
    if "genitals" in visibility:
        items.append(human["genital_appearance"])
    return [item["prompt"] for item in items if item.get("prompt")]


def compile_scene(db: dict[str, Any], scene: dict[str, Any]) -> tuple[str, str, list[str]]:
    defaults = db["prompt_defaults"]
    stage = scene["stage"]
    visibility = set(stage.get("body_visibility", []))
    plateau_kind = stage.get("plateau_kind")
    xxx_prompt = defaults.get("xxx_plateau_prompts", {}).get(plateau_kind, "")
    fragments = [xxx_prompt, defaults.get("positive_prefix", "")]
    fragments.extend(human_fragments(scene["human"], visibility))
    visible_slots = set(stage.get("visible_slots", []))
    outfit = scene["outfit"]
    for slot in outfit["template"]["slots"]:
        if slot in visible_slots and slot in outfit["garments"]:
            fragments.append(f"{outfit['colors'][slot]['prompt']} {outfit['garments'][slot]['prompt']}")
    for key in ("pose", "action", "prop", "expression", "interior", "furniture", "mood", "photography_style"):
        item = scene.get(key)
        if item:
            fragments.append(item["prompt"])
    fragments.extend(item["prompt"] for item in scene.get("dependencies", []))
    fragments.append(defaults.get("positive_suffix", ""))
    positive = ", ".join(fragment.strip(" ,") for fragment in fragments if fragment.strip(" ,"))
    negative = defaults.get("negative_prompt", "")
    if plateau_kind and defaults.get("xxx_negative_additions"):
        negative = f"{negative}, {defaults['xxx_negative_additions']}"
    ids = []
    for value in scene["human"].values():
        ids.extend(item["id"] for item in value) if isinstance(value, list) else ids.append(value["id"])
    ids.extend(item["id"] for slot, item in outfit["garments"].items() if slot in visible_slots)
    ids.extend(scene[key]["id"] for key in ("pose", "action", "expression", "interior", "furniture", "mood", "photography_style"))
    if scene.get("prop"):
        ids.append(scene["prop"]["id"])
    ids.extend(item["id"] for item in scene.get("dependencies", []))
    return positive, negative, ids


def model_signature(human: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in human.items():
        if isinstance(value, list):
            parts.extend(item["id"] for item in value)
        else:
            parts.append(value["id"])
    return "+".join(parts)


def photoshoot_signature(context: dict[str, Any]) -> tuple[Any, ...]:
    outfit = context["outfit"]
    garments = tuple(
        (slot, item["id"], outfit["colors"][slot]["id"])
        for slot, item in sorted(outfit["garments"].items())
    )
    return (
        model_signature(context["human"]),
        outfit["template"]["id"],
        garments,
        context["interior"]["id"],
        context["furniture"]["id"],
        context["mood"]["id"],
        context["photography_style"]["id"],
    )


def stage_for_index(
    template: dict[str, Any],
    index: int,
    count: int,
    mode: str,
    rng: random.Random,
    nsfw_percent: float,
    plateau_percent: float,
) -> dict[str, Any]:
    stages = template["stages"]
    if mode == "photoshoot":
        effective = effective_photoshoot_stages(template)
        safe = [stage for stage in effective if stage["level"] not in NSFW_LEVELS]
        nsfw = [stage for stage in effective if stage["level"] in NSFW_LEVELS]
        nsfw_count = min(count, math.ceil(count * nsfw_percent / 100)) if nsfw_percent > 0 else 0
        plateau_count = min(nsfw_count, math.ceil(count * plateau_percent / 100)) if plateau_percent > 0 else 0
        safe_count = count - nsfw_count
        if index < safe_count:
            return safe[min(len(safe) - 1, index * len(safe) // safe_count)]
        nsfw_index = index - safe_count
        transition_count = nsfw_count - plateau_count
        if nsfw_index < transition_count:
            transition_stages = nsfw if plateau_count == 0 else [
                stage for stage in nsfw if stage["level"] != "explicit"
            ]
            return progressive_stage(transition_stages, nsfw_index, transition_count)
        explicit_stage = next(stage for stage in nsfw if stage["level"] == "explicit")
        plateau_kinds = [
            {"plateau_kind": "provocative_rear"},
            {"plateau_kind": "intimate_closeup"},
            {"plateau_kind": "masturbation"},
        ]
        plateau_index = nsfw_index - transition_count
        kind = progressive_stage(plateau_kinds, plateau_index, plateau_count)["plateau_kind"]
        result = copy.deepcopy(explicit_stage)
        result["id"] = f"{explicit_stage['id']}_{kind}"
        result["plateau_kind"] = kind
        result["visible_slots"] = []
        result["body_visibility"] = ["breasts", "nipples", "pubic_area", "genitals"]
        return result
    return weighted_choice(rng, stages)


def xxx_only_stage(
    template: dict[str, Any], index: int, count: int, mode: str, rng: random.Random
) -> dict[str, Any]:
    """Build an immediately explicit stage for full-XXX photoshoot or random mode."""
    effective = effective_photoshoot_stages(template)
    explicit = next(stage for stage in effective if stage["level"] == "explicit")
    kinds = ("provocative_rear", "intimate_closeup", "masturbation")
    if mode == "photoshoot":
        kind = kinds[min(len(kinds) - 1, index * len(kinds) // count)]
    else:
        kind = rng.choice(kinds)
    result = copy.deepcopy(explicit)
    result["id"] = f"{explicit['id']}_xxx_only_{kind}"
    result["plateau_kind"] = kind
    result["visible_slots"] = []
    result["body_visibility"] = ["breasts", "nipples", "pubic_area", "genitals"]
    return result


def require_requests() -> Any:
    if requests is None:
        raise AppError("The 'requests' package is required for this command. Install it with: python3 -m pip install --user requests")
    return requests


def comfy_session(db: dict[str, Any]) -> tuple[Any, str, float]:
    module = require_requests()
    session = module.Session()
    url = db["settings"]["comfy_url"].rstrip("/")
    timeout = float(db["settings"].get("http_timeout_seconds", 15))
    return session, url, timeout


def capture(db: dict[str, Any], db_path: Path, force: bool) -> None:
    session, url, timeout = comfy_session(db)
    try:
        response = session.get(f"{url}/history", timeout=timeout)
        response.raise_for_status()
        history = response.json()
    except Exception as exc:
        raise AppError(f"Could not fetch ComfyUI history: {exc}") from exc
    completed = []
    for prompt_id, item in history.items():
        status = item.get("status", {})
        if status.get("completed") and status.get("status_str") == "success" and item.get("outputs"):
            timestamp = 0
            for message, payload in status.get("messages", []):
                if message == "execution_success":
                    timestamp = payload.get("timestamp", timestamp)
            completed.append((timestamp, prompt_id, item))
    if not completed:
        raise AppError("ComfyUI history contains no successful completed workflow with outputs")
    _, prompt_id, item = max(completed, key=lambda entry: entry[0])
    prompt_record = item.get("prompt", [])
    if len(prompt_record) < 3 or not isinstance(prompt_record[2], dict):
        raise AppError(f"History item {prompt_id} does not contain an API workflow in prompt[2]")
    workflow = prompt_record[2]
    text_candidates = []
    for node_id, node in workflow.items():
        if isinstance(node.get("inputs", {}).get("text"), str):
            text_candidates.append((node_id, node))
    positives = [entry for entry in text_candidates if "positive" in entry[0].lower()]
    negatives = [entry for entry in text_candidates if "negative" in entry[0].lower()]
    if len(positives) != 1 or len(negatives) != 1:
        candidates = ", ".join(f"{node_id}:{node.get('class_type')}" for node_id, node in text_candidates)
        raise AppError(f"Prompt node mapping is ambiguous. Text candidates: {candidates}")
    seed_targets = []
    for node_id, node in workflow.items():
        class_type = str(node.get("class_type", ""))
        if "sampler" not in class_type.lower() and "detailer" not in class_type.lower():
            continue
        for input_name in ("seed", "noise_seed"):
            value = node.get("inputs", {}).get(input_name)
            if isinstance(value, int):
                seed_targets.append({"node": node_id, "input": input_name})
    if not seed_targets:
        raise AppError("Could not find a scalar seed input in sampler/detailer nodes")
    workflow_path = resolve_path(db_path.parent, db["settings"]["workflow_file"])
    if workflow_path.exists() and not force:
        raise AppError(f"Workflow already exists: {workflow_path}. Use capture --force to replace it")
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    db["node_mapping"] = {
        "positive_prompt": {"node": positives[0][0], "input": "text"},
        "negative_prompt": {"node": negatives[0][0], "input": "text"},
        "inference_seed": seed_targets,
    }
    db_path.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Captured prompt_id: {prompt_id}")
    print(f"Workflow: {workflow_path}")
    print(f"Positive node: {positives[0][0]}")
    print(f"Negative node: {negatives[0][0]}")
    print(f"Seed targets: {len(seed_targets)}")


def patch_workflow(workflow: dict[str, Any], mapping: dict[str, Any], positive: str, negative: str, seed: int) -> None:
    for map_key, value in (("positive_prompt", positive), ("negative_prompt", negative)):
        target = mapping[map_key]
        try:
            workflow[target["node"]]["inputs"][target["input"]] = value
        except KeyError as exc:
            raise AppError(f"Workflow no longer matches node_mapping.{map_key}: missing {exc}") from exc
    for target in mapping["inference_seed"]:
        try:
            workflow[target["node"]]["inputs"][target["input"]] = seed
        except KeyError as exc:
            raise AppError(f"Workflow no longer matches inference seed mapping: missing {exc}") from exc


def wait_for_outputs(session: Any, url: str, prompt_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + float(settings.get("generation_timeout_seconds", 600))
    interval = float(settings.get("poll_interval_seconds", 1))
    timeout = float(settings.get("http_timeout_seconds", 15))
    while time.monotonic() < deadline:
        response = session.get(f"{url}/history/{prompt_id}", timeout=timeout)
        response.raise_for_status()
        item = response.json().get(prompt_id)
        if item:
            status = item.get("status", {})
            if status.get("completed") and status.get("status_str") == "success":
                return item.get("outputs", {})
            if status.get("status_str") == "error" or any(message[0] == "execution_error" for message in status.get("messages", [])):
                raise AppError(f"ComfyUI execution failed for prompt_id {prompt_id}")
        time.sleep(interval)
    raise AppError(f"Timed out waiting for prompt_id {prompt_id}")


def generate_one(
    db: dict[str, Any],
    db_path: Path,
    positive: str,
    negative: str,
    seed: int,
    mode: str,
    shot_index: int,
    photoshoot_index: int,
    run_id: str,
) -> tuple[str, list[Path]]:
    validate_database(db, require_mapping=True)
    workflow_path = resolve_path(db_path.parent, db["settings"]["workflow_file"])
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"Workflow not found: {workflow_path}. Run capture first") from exc
    patch_workflow(workflow, db["node_mapping"], positive, negative, seed)
    session, url, timeout = comfy_session(db)
    try:
        response = session.post(f"{url}/prompt", json={"prompt": workflow, "client_id": str(uuid.uuid4())}, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise AppError(f"Could not queue ComfyUI workflow: {exc}") from exc
    if payload.get("node_errors"):
        raise AppError(f"ComfyUI rejected workflow: {json.dumps(payload['node_errors'], ensure_ascii=False)}")
    prompt_id = payload.get("prompt_id")
    if not prompt_id:
        raise AppError(f"ComfyUI response has no prompt_id: {payload}")
    outputs = wait_for_outputs(session, url, prompt_id, db["settings"])
    output_dir = resolve_path(db_path.parent, db["settings"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    image_number = 0
    for node_output in outputs.values():
        for image in node_output.get("images", []):
            image_number += 1
            suffix = Path(image.get("filename", "image.png")).suffix or ".png"
            if mode == "photoshoot":
                label = f"photoshoot_{photoshoot_index + 1:03d}_shot_{shot_index + 1:03d}"
            else:
                label = f"random_shot_{shot_index + 1:03d}"
            destination = output_dir / f"{run_id}_{label}_{seed}_image_{image_number:02d}{suffix}"
            response = session.get(
                f"{url}/view",
                params={"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")},
                timeout=timeout,
            )
            response.raise_for_status()
            destination.write_bytes(response.content)
            saved.append(destination)
    if not saved:
        raise AppError(f"ComfyUI completed prompt_id {prompt_id} but returned no images")
    return prompt_id, saved


def build_storyboard(
    args: argparse.Namespace,
    db: dict[str, Any],
    composer: Composer,
    rng: random.Random,
    nsfw_percent: float,
    plateau_percent: float,
) -> list[dict[str, Any]]:
    photoshoot_count = args.photoshoots if args.mode == "photoshoot" else 1
    seen_photoshoots: set[tuple[Any, ...]] = set()
    storyboard: list[dict[str, Any]] = []
    for photoshoot_index in range(photoshoot_count):
        fixed = None
        if args.mode == "photoshoot":
            attempts = int(db["settings"].get("max_scene_attempts", 100))
            for _ in range(attempts):
                candidate = composer.fixed_context()
                signature = photoshoot_signature(candidate)
                if signature not in seen_photoshoots:
                    fixed = candidate
                    seen_photoshoots.add(signature)
                    break
            if fixed is None:
                raise AppError(
                    f"Could not assemble distinct photoshoot {photoshoot_index + 1} "
                    f"after {attempts} attempts"
                )
        for shot_index in range(args.count):
            context = fixed if fixed is not None else composer.fixed_context()
            assert context is not None
            template = context["outfit"]["template"]
            stage = (
                xxx_only_stage(template, shot_index, args.count, args.mode, rng)
                if args.xxx_only
                else stage_for_index(
                    template, shot_index, args.count, args.mode, rng,
                    nsfw_percent, plateau_percent,
                )
            )
            storyboard.append({
                "number": len(storyboard) + 1,
                "photoshoot_index": photoshoot_index,
                "shot_index": shot_index,
                "context": context,
                "stage": stage,
                "scene": composer.resolve_scene(context, stage),
                "inference_seed": (
                    args.inference_seed
                    if args.inference_seed is not None
                    else secrets.randbelow(2**63)
                ),
            })
    return storyboard


def director_clear() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def short_id(value: str, width: int) -> str:
    prefixes = ("pose_", "action_", "expression_", "template_")
    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return value if len(value) <= width else value[: width - 1] + "…"


def show_storyboard(storyboard: list[dict[str, Any]], title: str = "DIRECTOR'S DESK") -> None:
    director_clear()
    print(title)
    print("═" * 104)
    unique_contexts = {id(shot["context"]) for shot in storyboard}
    random_contexts = len(unique_contexts) > len({shot["photoshoot_index"] for shot in storyboard})
    if random_contexts:
        print("RANDOM SET: every shot has an independently assembled model, wardrobe, and location.")
        print("═" * 104)
    seen_sets: set[int] = set()
    for shot in storyboard:
        if random_contexts:
            break
        photo = shot["photoshoot_index"]
        if photo in seen_sets:
            continue
        seen_sets.add(photo)
        context = shot["context"]
        human = context["human"]
        identity = ", ".join((
            human["age"]["prompt"],
            human["ethnic_appearance"]["prompt"],
            human["hair_color"]["prompt"],
            human["hair_style"]["prompt"],
            human["body_frame"]["prompt"],
        ))
        print(
            f"SET {photo + 1}: {identity}\n"
            f"       wardrobe={context['outfit']['template']['id']} | "
            f"location={context['interior']['id']} | surface={context['furniture']['id']}"
        )
    print("═" * 104)
    print(f"{'#':>3} {'Set':>3} {'Stage':<18} {'Pose':<23} {'Action':<24} {'Expression':<18}")
    print("─" * 104)
    for shot in storyboard:
        scene = shot["scene"]
        print(
            f"{shot['number']:>3} {shot['photoshoot_index'] + 1:>3} "
            f"{short_id(shot['stage']['id'], 18):<18} "
            f"{short_id(scene['pose']['id'], 23):<23} "
            f"{short_id(scene['action']['id'], 24):<24} "
            f"{short_id(scene['expression']['id'], 18):<18}"
        )
    print("═" * 104)


def director_input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError as exc:
        raise AppError("Interactive storyboard input ended before confirmation") from exc


def choose_number(prompt: str, maximum: int, allow_zero: bool = True) -> int | None:
    value = director_input(prompt)
    if value == "" and allow_zero:
        return 0
    try:
        parsed = int(value)
    except ValueError:
        return None
    if (allow_zero and parsed == 0) or 1 <= parsed <= maximum:
        return parsed
    return None


def fzf_binary() -> str | None:
    configured_env = os.environ.get("FZF_BIN")
    if configured_env and Path(configured_env).is_file():
        return configured_env
    configured = shutil.which("fzf")
    if configured:
        return configured
    for path in (
        "/home/linuxbrew/.linuxbrew/bin/fzf",
        "/opt/homebrew/bin/fzf",
        "/usr/local/bin/fzf",
    ):
        if Path(path).is_file():
            return path
    return None


def director_uses_fzf() -> bool:
    return bool(fzf_binary() and sys.stdin.isatty() and sys.stdout.isatty())


def fzf_select(
    prompt: str,
    choices: list[tuple[str, Any]],
    default: Any | None = None,
    height: str = "72%",
) -> Any | None:
    executable = fzf_binary()
    if not executable or not sys.stdin.isatty() or not sys.stdout.isatty():
        return None
    rows = []
    for index, (label, value) in enumerate(choices, 1):
        display = label.replace(chr(9), " ")
        if value is FZF_GROUP:
            display = f"\033[2m{display}\033[0m"
        rows.append(f"{index}\t{display}")
    while True:
        try:
            result = subprocess.run(
                [
                    executable,
                    f"--height={height}",
                    "--layout=reverse",
                    "--border=rounded",
                    "--info=inline",
                    "--ansi",
                    "--delimiter=\t",
                    "--with-nth=2..",
                    f"--prompt={prompt} › ",
                    "--header=Type to search • Enter select • Esc keep Auto",
                ],
                input="\n".join(rows) + "\n",
                text=True,
                stdout=subprocess.PIPE,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return default
        try:
            selected = int(result.stdout.split("\t", 1)[0])
        except ValueError:
            return default
        value = choices[selected - 1][1]
        if value is not FZF_GROUP:
            return value


FZF_GROUP = object()


def fzf_group(title: str) -> tuple[str, Any]:
    return (f"── {title.upper()} " + "─" * max(1, 28 - len(title)), FZF_GROUP)


def director_menu_choice(
    prompt: str,
    choices: list[tuple[str, Any]],
    default: str,
) -> str:
    if director_uses_fzf():
        selected = fzf_select(
            prompt,
            choices,
            default,
            height="42%",
        )
        return str(selected)
    return director_input(f"\n{prompt} [{default}]: ") or default


def director_stage_options(shot: dict[str, Any], xxx_only: bool) -> list[dict[str, Any]]:
    template = shot["context"]["outfit"]["template"]
    explicit = [xxx_only_stage(template, i, 3, "photoshoot", random.Random(0)) for i in range(3)]
    if xxx_only:
        return explicit
    non_explicit = [
        stage for stage in effective_photoshoot_stages(template) if stage["level"] != "explicit"
    ]
    return non_explicit + explicit


def effective_progression(args: argparse.Namespace, db: dict[str, Any]) -> tuple[float, float]:
    progression = db["settings"].get("photoshoot_progression", {})
    nsfw = float(
        progression.get("nsfw_final_percent", 50)
        if args.nsfw_percent is None else args.nsfw_percent
    )
    plateau = float(
        progression.get("explicit_plateau_percent", 30)
        if args.plateau_percent is None else args.plateau_percent
    )
    return nsfw, plateau


def replace_set_context(
    args: argparse.Namespace,
    db: dict[str, Any],
    composer: Composer,
    storyboard: list[dict[str, Any]],
    indices: list[int],
    context: dict[str, Any],
    recalculate_stages: bool,
) -> None:
    nsfw, plateau = effective_progression(args, db)
    replacements: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index in indices:
        shot = storyboard[index]
        if recalculate_stages:
            template = context["outfit"]["template"]
            stage = (
                xxx_only_stage(template, shot["shot_index"], args.count, args.mode, composer.rng)
                if args.xxx_only
                else stage_for_index(
                    template, shot["shot_index"], args.count, args.mode,
                    composer.rng, nsfw, plateau,
                )
            )
        else:
            stage = shot["stage"]
        scene = composer.resolve_scene(context, stage)
        replacements.append((index, stage, scene))
    for index, stage, scene in replacements:
        storyboard[index]["context"] = context
        storyboard[index]["stage"] = stage
        storyboard[index]["scene"] = scene


def set_indices(storyboard: list[dict[str, Any]], index: int, mode: str) -> list[int]:
    if mode == "random":
        return [index]
    photo = storyboard[index]["photoshoot_index"]
    return [i for i, shot in enumerate(storyboard) if shot["photoshoot_index"] == photo]


def human_cast_label(human: dict[str, Any]) -> str:
    return ", ".join((
        human["age"]["prompt"], human["ethnic_appearance"]["prompt"],
        human["skin_tone"]["prompt"], human["face_shape"]["prompt"],
        human["eye_shape"]["prompt"], human["eye_color"]["prompt"],
        human["nose"]["prompt"], human["lips"]["prompt"],
        human["hair_color"]["prompt"], human["hair_style"]["prompt"],
        human["body_frame"]["prompt"], human["breast_size"]["prompt"],
    ))


HUMAN_FACE_PARTS = {
    "face_shape", "eye_shape", "eye_color", "eyebrows", "nose", "lips",
    "cheekbones", "jawline", "facial_accents",
}
HUMAN_HAIR_PARTS = {"hair_texture", "hair_length", "hair_style", "hair_color"}
HUMAN_BODY_PARTS = {
    "height", "body_frame", "waist", "hips", "breast_size", "breast_shape",
    "areola_size", "areola_color", "nipple_size", "nipple_shape", "pubic_hair",
    "genital_appearance",
}
HUMAN_STYLING_PARTS = {"makeup", "manicure"}


def remixed_human(
    composer: Composer,
    current: dict[str, Any],
    replace_parts: set[str] | None = None,
    keep_parts: set[str] | None = None,
) -> dict[str, Any]:
    fresh = composer.choose_human()
    if replace_parts is not None:
        return {
            key: fresh[key] if key in replace_parts else value
            for key, value in current.items()
        }
    keep_parts = keep_parts or set()
    return {
        key: value if key in keep_parts else fresh[key]
        for key, value in current.items()
    }


def choose_subject_remix(composer: Composer, current: dict[str, Any]) -> dict[str, Any] | None:
    mode = select_labeled(
        "SUBJECT REMIX — choose what stays locked",
        [
            ("New completely random subject", "all"),
            (f"Keep ethnic appearance: {current['ethnic_appearance']['prompt']}", "ethnic"),
            ("Remix face only", "face"),
            ("Remix hair only", "hair"),
            ("Remix body and anatomy only", "body"),
            ("Remix makeup and manicure only", "styling"),
        ],
    )
    if mode is None:
        return None
    candidates: list[dict[str, Any]] = []
    for _ in range(8):
        if mode == "all":
            candidate = composer.choose_human()
        elif mode == "ethnic":
            candidate = remixed_human(composer, current, keep_parts={"ethnic_appearance"})
        else:
            groups = {
                "face": HUMAN_FACE_PARTS,
                "hair": HUMAN_HAIR_PARTS,
                "body": HUMAN_BODY_PARTS,
                "styling": HUMAN_STYLING_PARTS,
            }
            candidate = remixed_human(composer, current, replace_parts=groups[mode])
            if mode == "body":
                compatible_colors = [
                    item for item in composer.db["human_model_parts"]["areola_color"]
                    if not item.get("disabled", False)
                    and compatible_with_requirements(item, tags(current["skin_tone"]))
                ]
                candidate["areola_color"] = weighted_choice(composer.rng, compatible_colors)
        candidates.append(candidate)
    return select_labeled(
        "CASTING CALL — choose the remixed subject",
        [(human_cast_label(candidate), candidate) for candidate in candidates],
    )


def outfit_label(outfit: dict[str, Any]) -> str:
    garments = ", ".join(
        f"{slot}={item['id']} ({outfit['colors'][slot]['id']})"
        for slot, item in outfit["garments"].items()
    )
    return f"{outfit['template']['id']} — {garments}"


def choose_wardrobe_remix(
    db: dict[str, Any], composer: Composer, current: dict[str, Any]
) -> dict[str, Any] | None:
    mode = select_labeled(
        "WARDROBE REMIX",
        [
            ("Choose another outfit category / template", "template"),
            (f"Remix pieces and colors inside {current['template']['id']}", "same_template"),
        ],
    )
    if mode is None:
        return None
    if mode == "same_template":
        candidates = [composer.choose_outfit(current["template"]) for _ in range(8)]
    else:
        candidates = []
        for template in db["outfit_templates"]:
            if template.get("disabled", False):
                continue
            try:
                candidates.append(composer.choose_outfit(template))
            except AppError:
                continue
    return select_labeled(
        "WARDROBE DEPARTMENT — choose a resolved outfit",
        [(outfit_label(outfit), outfit) for outfit in candidates],
    )


def location_family(interior: dict[str, Any]) -> set[str]:
    generic = {"indoor", "private", "luxury", "cozy", "intimate"}
    return tags(interior) - generic


def resolved_location_candidates(
    db: dict[str, Any], composer: Composer, interiors: list[dict[str, Any]]
) -> list[tuple[str, tuple[dict[str, Any], dict[str, Any]]]]:
    result = []
    for interior in interiors:
        surfaces = [
            item for item in db["furniture"]
            if not item.get("disabled", False)
            and compatible_with_requirements(item, tags(interior))
        ]
        if surfaces:
            surface = weighted_choice(composer.rng, surfaces)
            result.append((f"{interior['prompt']} — {surface['prompt']}", (interior, surface)))
    return result


def choose_location_remix(
    db: dict[str, Any], composer: Composer, current: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    family = location_family(current)
    mode = select_labeled(
        "LOCATION REMIX",
        [
            ("Choose any new interior", "all"),
            (f"Remix within the same location family: {', '.join(sorted(family)) or 'general'}", "family"),
            (f"Keep {current['id']} and remix its surface", "surface"),
        ],
    )
    if mode is None:
        return None
    if mode == "surface":
        interiors = [current]
        count = 8
    else:
        interiors = [item for item in db["interiors"] if not item.get("disabled", False)]
        if mode == "family" and family:
            interiors = [item for item in interiors if location_family(item) & family]
        count = 1
    candidates = []
    for _ in range(count):
        candidates.extend(resolved_location_candidates(db, composer, interiors))
    return select_labeled("LOCATION SCOUTING — choose a resolved set", candidates)


def choose_surface_remix(
    db: dict[str, Any], current_interior: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any] | None:
    surface_types = {
        "bed", "sofa", "chair", "bathtub", "floor", "wall", "windowsill",
        "table", "shower", "bench", "stool",
    }
    current_types = tags(current) & surface_types
    mode = select_labeled(
        "SURFACE REMIX",
        [
            ("Choose any compatible surface", "all"),
            (f"Remix the same surface type: {', '.join(sorted(current_types)) or current['id']}", "type"),
        ],
    )
    if mode is None:
        return None
    candidates = [
        item for item in db["furniture"]
        if not item.get("disabled", False)
        and compatible_with_requirements(item, tags(current_interior))
    ]
    if mode == "type" and current_types:
        candidates = [item for item in candidates if tags(item) & current_types]
    return select_labeled(
        "SURFACE & BLOCKING — choose a variant",
        [(item["prompt"], item) for item in candidates],
    )


def select_labeled(prompt: str, choices: list[tuple[str, Any]]) -> Any | None:
    if director_uses_fzf():
        return fzf_select(prompt, choices)
    director_clear()
    print(prompt + "\n")
    for number, (label, _) in enumerate(choices, 1):
        print(f"{number:>2}) {label}")
    print(" 0) Keep current / Auto")
    selected = choose_number("\nChoose: ", len(choices))
    return choices[selected - 1][1] if selected else None


def direct_set(
    args: argparse.Namespace,
    db: dict[str, Any],
    composer: Composer,
    storyboard: list[dict[str, Any]],
    index: int,
) -> None:
    indices = set_indices(storyboard, index, args.mode)
    while True:
        shot = storyboard[index]
        context = shot["context"]
        show_storyboard([storyboard[i] for i in indices], f"CASTING & SET DESIGN — SET {shot['photoshoot_index'] + 1}")
        if not director_uses_fzf():
            print("1) Cast / remix subject")
            print("2) Change wardrobe")
            print("3) Change location")
            print("4) Change surface / furniture")
            print("5) Change mood")
            print("6) Change photography style")
            print("7) Reroll the complete set")
            print("0) Back to storyboard")
        choice = director_menu_choice(
            "Set designer's choice",
            [
                fzf_group("Casting"),
                ("Cast / remix subject", "1"),
                fzf_group("Styling"),
                ("Change wardrobe", "2"),
                ("Change mood", "5"),
                ("Change photography style", "6"),
                fzf_group("Location"),
                ("Change location", "3"),
                ("Change surface / furniture", "4"),
                fzf_group("Complete SET"),
                ("Reroll the complete set", "7"),
                ("Back to storyboard", "0"),
            ],
            "0",
        )
        if choice == "0":
            return
        new_context = dict(context)
        recalculate_stages = False
        if choice == "1":
            human = choose_subject_remix(composer, context["human"])
            if human is None:
                continue
            new_context["human"] = human
        elif choice == "2":
            outfit = choose_wardrobe_remix(db, composer, context["outfit"])
            if outfit is None:
                continue
            new_context["outfit"] = outfit
            recalculate_stages = True
        elif choice == "3":
            selected = choose_location_remix(db, composer, context["interior"])
            if selected is None:
                continue
            new_context["interior"], new_context["furniture"] = selected
        elif choice == "4":
            surface = choose_surface_remix(db, context["interior"], context["furniture"])
            if surface is None:
                continue
            new_context["furniture"] = surface
        elif choice == "5":
            mood = select_labeled(
                "MOOD",
                [(item["prompt"], item) for item in db["moods"] if not item.get("disabled", False)],
            )
            if mood is None:
                continue
            new_context["mood"] = mood
        elif choice == "6":
            style = select_labeled(
                "PHOTOGRAPHY STYLE",
                [(item["prompt"], item) for item in db["photography_styles"] if not item.get("disabled", False)],
            )
            if style is None:
                continue
            new_context["photography_style"] = style
        elif choice == "7":
            new_context = composer.fixed_context()
            recalculate_stages = True
        else:
            continue
        try:
            replace_set_context(
                args, db, composer, storyboard, indices, new_context, recalculate_stages
            )
        except AppError as exc:
            director_input(f"Could not apply this direction: {exc}\nPress Enter...")


def stage_change_preserves_progression(
    storyboard: list[dict[str, Any]], index: int, stage: dict[str, Any], mode: str
) -> bool:
    if mode != "photoshoot":
        return True
    ranks = {"covered": 0, "lingerie": 1, "topless": 2, "nude": 3, "explicit": 4}
    photo = storyboard[index]["photoshoot_index"]
    previous = next(
        (storyboard[i] for i in range(index - 1, -1, -1)
         if storyboard[i]["photoshoot_index"] == photo), None
    )
    following = next(
        (storyboard[i] for i in range(index + 1, len(storyboard))
         if storyboard[i]["photoshoot_index"] == photo), None
    )
    rank = ranks[stage["level"]]
    return (
        (previous is None or ranks[previous["stage"]["level"]] <= rank)
        and (following is None or rank <= ranks[following["stage"]["level"]])
    )


def choose_compatible_override(
    db: dict[str, Any], composer: Composer, shot: dict[str, Any], key: str
) -> dict[str, Any] | None:
    section = {"pose": "poses", "action": "actions"}[key]
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in db[section]:
        if item.get("disabled", False):
            continue
        try:
            scene = composer.resolve_scene(
                shot["context"], shot["stage"], {key: item["id"]}
            )
        except AppError:
            continue
        candidates.append((item, scene))
    return select_labeled(
        f"Compatible {key}s for shot {shot['number']}",
        [(f"{item['id']} — {item['prompt']}", scene) for item, scene in candidates],
    )


def choose_expression(
    db: dict[str, Any], composer: Composer, shot: dict[str, Any]
) -> dict[str, Any] | None:
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in db["expressions"]:
        if item.get("disabled", False):
            continue
        scene = dict(shot["scene"])
        scene["expression"] = item
        try:
            composer.validate_scene_rules(scene)
        except AppError:
            continue
        candidates.append((item, scene))
    return select_labeled(
        f"Compatible expressions for shot {shot['number']}",
        [(f"{item['id']} — {item['prompt']}", scene) for item, scene in candidates],
    )


def direct_one_shot(
    args: argparse.Namespace,
    db: dict[str, Any],
    composer: Composer,
    storyboard: list[dict[str, Any]],
    index: int,
) -> None:
    shot = storyboard[index]
    while True:
        show_storyboard([shot], f"DIRECT SHOT {shot['number']}")
        if not director_uses_fzf():
            print("1) Stage / XXX category")
            print("2) Pose")
            print("3) Action")
            print("4) Expression")
            print("5) Reroll complete shot composition")
            print("6) View full prompt")
            print("0) Back to storyboard")
        choice = director_menu_choice(
            "Director's choice",
            [
                fzf_group("Composition"),
                ("Stage / XXX category", "1"),
                ("Pose", "2"),
                ("Action", "3"),
                ("Expression", "4"),
                ("Reroll complete shot composition", "5"),
                fzf_group("Review & navigation"),
                ("View full prompt", "6"),
                ("Back to storyboard", "0"),
            ],
            "0",
        )
        if choice == "0":
            return
        if choice == "1":
            options = director_stage_options(shot, args.xxx_only)
            stage = select_labeled(
                f"Stage for shot {shot['number']}",
                [(f"{stage['id']} ({stage['level']})", stage) for stage in options],
            )
            if stage:
                if not stage_change_preserves_progression(storyboard, index, stage, args.mode):
                    director_input("That would reverse the photoshoot progression. Press Enter...")
                    continue
                shot["stage"] = stage
                shot["scene"] = composer.resolve_scene(shot["context"], stage)
        elif choice in {"2", "3"}:
            scene = choose_compatible_override(
                db, composer, shot, "pose" if choice == "2" else "action"
            )
            if scene:
                shot["scene"] = scene
        elif choice == "4":
            scene = choose_expression(db, composer, shot)
            if scene:
                shot["scene"] = scene
        elif choice == "5":
            shot["scene"] = composer.resolve_scene(shot["context"], shot["stage"])
            if args.inference_seed is None:
                shot["inference_seed"] = secrets.randbelow(2**63)
        elif choice == "6":
            positive, negative, _ = compile_scene(db, shot["scene"])
            director_clear()
            print(f"POSITIVE\n{positive}\n\nNEGATIVE\n{negative}\n")
            director_input("Press Enter to return...")


def review_storyboard(
    args: argparse.Namespace,
    db: dict[str, Any],
    composer: Composer,
    storyboard: list[dict[str, Any]],
    render: bool,
) -> str:
    while True:
        show_storyboard(storyboard)
        if not director_uses_fzf():
            print(f"1) {'Lights, camera, generate!' if render else 'Accept and print dry-run'}")
            print("2) Reroll the entire storyboard")
            print("3) Cast & design a SET")
            print("4) Reroll one shot")
            print("5) Direct one shot")
            print("6) Inspect one full prompt")
            print("0) Cancel")
        choice = director_menu_choice(
            "Director's choice",
            [
                fzf_group("Run"),
                (("Lights, camera, generate!" if render else "Accept and print dry-run"), "1"),
                ("Reroll the entire storyboard", "2"),
                fzf_group("Direct"),
                ("Cast & design a SET", "3"),
                ("Reroll one shot", "4"),
                ("Direct one shot", "5"),
                ("Inspect one full prompt", "6"),
                fzf_group("Exit"),
                ("Cancel", "0"),
            ],
            "1",
        )
        if choice == "1":
            return "accept"
        if choice == "2":
            return "reroll"
        if choice == "0":
            return "cancel"
        if choice in {"3", "4", "5", "6"}:
            if choice == "3" and args.mode == "photoshoot":
                set_representatives = []
                seen_sets: set[int] = set()
                for offset, shot in enumerate(storyboard):
                    photo = shot["photoshoot_index"]
                    if photo not in seen_sets:
                        seen_sets.add(photo)
                        set_representatives.append((offset, shot))
                selection_choices = [
                    (
                        f"SET {shot['photoshoot_index'] + 1} · "
                        f"{human_cast_label(shot['context']['human'])} · "
                        f"{shot['context']['outfit']['template']['id']} · "
                        f"{shot['context']['interior']['id']}",
                        offset,
                    )
                    for offset, shot in set_representatives
                ]
                noun = "Choose a SET for casting and design"
            else:
                selection_choices = [
                    (
                        f"Shot {shot['number']} · SET {shot['photoshoot_index'] + 1} · "
                        f"{shot['stage']['id']} · {shot['scene']['pose']['id']}",
                        offset,
                    )
                    for offset, shot in enumerate(storyboard)
                ]
                noun = "Choose an independent shot as its SET" if choice == "3" else "Choose a shot"
            index = select_labeled(
                noun,
                selection_choices,
            )
            if index is None:
                continue
            number = index + 1
            if choice == "3":
                direct_set(args, db, composer, storyboard, index)
            elif choice == "4":
                shot = storyboard[index]
                shot["scene"] = composer.resolve_scene(shot["context"], shot["stage"])
                if args.inference_seed is None:
                    shot["inference_seed"] = secrets.randbelow(2**63)
            elif choice == "5":
                direct_one_shot(args, db, composer, storyboard, index)
            else:
                shot = storyboard[index]
                positive, negative, _ = compile_scene(db, shot["scene"])
                director_clear()
                print(f"SHOT {number}\n\nPOSITIVE\n{positive}\n\nNEGATIVE\n{negative}\n")
                director_input("Press Enter to return...")


def run_batch(args: argparse.Namespace, render: bool) -> None:
    db, db_path = load_database()
    prompt_seed = args.prompt_seed if args.prompt_seed is not None else secrets.randbits(63)
    rng = random.Random(prompt_seed)
    composer = Composer(db, rng)
    progression = db["settings"].get("photoshoot_progression", {})
    nsfw_percent = float(
        progression.get("nsfw_final_percent", 50)
        if args.nsfw_percent is None else args.nsfw_percent
    )
    plateau_percent = float(
        progression.get("explicit_plateau_percent", 30)
        if args.plateau_percent is None else args.plateau_percent
    )
    if args.mode == "random" and (args.nsfw_percent is not None or args.plateau_percent is not None):
        raise AppError("--nsfw-percent and --plateau-percent are only valid with --mode photoshoot")
    if args.xxx_only and (args.nsfw_percent is not None or args.plateau_percent is not None):
        raise AppError("--xxx-only cannot be combined with --nsfw-percent or --plateau-percent")
    if args.mode == "random" and args.photoshoots != 1:
        raise AppError("--photoshoots is only valid with --mode photoshoot")
    if plateau_percent > nsfw_percent:
        raise AppError("The explicit plateau percentage cannot exceed the NSFW final percentage")

    photoshoot_count = args.photoshoots if args.mode == "photoshoot" else 1
    storyboard = build_storyboard(args, db, composer, rng, nsfw_percent, plateau_percent)
    if args.review_storyboard:
        while True:
            decision = review_storyboard(args, db, composer, storyboard, render)
            if decision == "accept":
                break
            if decision == "cancel":
                print("Cancelled by director.")
                return
            storyboard = build_storyboard(args, db, composer, rng, nsfw_percent, plateau_percent)

    director_clear() if args.review_storyboard else None
    print(
        f"mode={args.mode} count={args.count} photoshoots={photoshoot_count} "
        f"total_images={len(storyboard)} prompt_seed={prompt_seed} "
        f"content_mode={'xxx-only' if args.xxx_only else 'progressive'}"
    )
    if args.mode == "photoshoot" and not args.xxx_only:
        print(f"nsfw_final_percent={nsfw_percent:g}")
        print(f"explicit_plateau_percent={plateau_percent:g}")
    if args.inference_seed is not None:
        print(f"fixed_inference_seed={args.inference_seed}")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    announced_photoshoot = -1
    for shot in storyboard:
        photo = shot["photoshoot_index"]
        scene = shot["scene"]
        if args.mode == "photoshoot" and photo != announced_photoshoot:
            context = shot["context"]
            print(
                f"\n=== Photoshoot {photo + 1}/{photoshoot_count}: "
                f"template={context['outfit']['template']['id']} "
                f"model_signature={model_signature(context['human'])} ==="
            )
            announced_photoshoot = photo
        positive, negative, selected_ids = compile_scene(db, scene)
        progress = (
            f"photoshoot {photo + 1}/{photoshoot_count} "
            f"shot {shot['shot_index'] + 1}/{args.count}"
            if args.mode == "photoshoot" else f"{shot['shot_index'] + 1}/{args.count}"
        )
        print(f"\n[{progress}] stage={shot['stage']['id']} inference_seed={shot['inference_seed']}")
        print(f"model_signature={model_signature(scene['human'])}")
        print(f"selected_ids={','.join(selected_ids)}")
        print(f"positive={positive}")
        print(f"negative={negative}")
        if render:
            prompt_id, paths = generate_one(
                db, db_path, positive, negative, shot["inference_seed"], args.mode,
                shot["shot_index"], photo, run_id,
            )
            print(f"prompt_id={prompt_id}")
            for path in paths:
                print(f"saved={path}")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def inference_seed_value(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed < 2**64:
        raise argparse.ArgumentTypeError("must be between 0 and 18446744073709551615")
    return parsed


def percent_value(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rule-based prompt composer for ComfyUI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture", help="Capture the latest successful ComfyUI workflow")
    capture_parser.add_argument("--force", action="store_true", help="Replace an existing workflow.json")
    for name, help_text in (("dry-run", "Resolve and print prompts without rendering"), ("generate", "Resolve prompts and render them")):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--mode", choices=("photoshoot", "random"), required=True)
        command.add_argument("--count", type=positive_int, required=True, help="Images per photoshoot (or total random images)")
        command.add_argument("--photoshoots", type=positive_int, default=1, help="Number of distinct photoshoots (photoshoot mode only)")
        command.add_argument("--prompt-seed", type=int)
        command.add_argument("--inference-seed", type=inference_seed_value)
        command.add_argument(
            "--xxx-only",
            action="store_true",
            help="Make every image immediately explicit XXX (works with photoshoot and random modes)",
        )
        command.add_argument(
            "--review-storyboard",
            action="store_true",
            help="Open the interactive Director's Desk before printing or generating the batch",
        )
        command.add_argument(
            "--nsfw-percent",
            type=percent_value,
            help="Override settings.photoshoot_progression.nsfw_final_percent (photoshoot only)",
        )
        command.add_argument(
            "--plateau-percent",
            type=percent_value,
            help="Override settings.photoshoot_progression.explicit_plateau_percent (photoshoot only)",
        )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "capture":
            db, db_path = load_database()
            capture(db, db_path, args.force)
        else:
            run_batch(args, render=args.command == "generate")
        return 0
    except AppError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
