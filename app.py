#!/usr/bin/env python3
"""Small, single-file rule-based prompt composer for a local ComfyUI server."""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import secrets
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

    color_ids = {item["id"] for item in db["colors"]}
    garment_catalogs = set(db["garments"])
    for item in index.values():
        for key in ("requires", "excludes"):
            for reference in item.get(key, []):
                if reference not in ids:
                    raise AppError(f"{item['id']}.{key} references unknown id '{reference}'")
        unknown_colors = set(item.get("allowed_colors", [])) - color_ids
        if unknown_colors:
            raise AppError(f"{item['id']} references unknown colors: {sorted(unknown_colors)}")

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
        self.colors = {item["id"]: item for item in db["colors"]}
        self.item_index = {item["id"]: item for item in iter_content_items(db)}

    def choose_human(self) -> dict[str, Any]:
        human: dict[str, Any] = {}
        parts = self.db["human_model_parts"]
        order = list(parts)
        for category in order:
            if category == "facial_accents":
                count = self.rng.choices([0, 1, 2], weights=[3, 5, 2], k=1)[0]
                human[category] = self.rng.sample(parts[category], k=min(count, len(parts[category])))
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
            allowed = item.get("allowed_colors") or list(self.colors)
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

    def variable_context(self, stage: dict[str, Any], fixed: dict[str, Any]) -> dict[str, Any]:
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
                and "adult_toy" not in tags(item)
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
        return {
            "pose": pose,
            "action": action,
            "prop": prop,
            "expression": weighted_choice(self.rng, expression_candidates),
        }

    def resolve_scene(self, fixed: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
        attempts = int(self.db["settings"].get("max_scene_attempts", 100))
        last_error = "no candidates"
        for _ in range(attempts):
            try:
                scene = dict(fixed)
                scene.update(self.variable_context(stage, fixed))
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

IDENTITY_HUMAN_PARTS = (
    "ethnic_appearance", "skin_tone", "face_shape", "eye_shape", "eye_color",
    "eyebrows", "nose", "lips", "cheekbones", "jawline", "hair_texture",
    "hair_length", "hair_style", "hair_color", "height", "body_frame", "waist", "hips",
)


def human_fragments(
    human: dict[str, Any], visibility: set[str], include_identity: bool = True
) -> list[str]:
    keys = ALWAYS_HUMAN_PARTS if include_identity else tuple(
        key for key in ALWAYS_HUMAN_PARTS if key not in IDENTITY_HUMAN_PARTS
    )
    items: list[dict[str, Any]] = [human[key] for key in keys]
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


def identity_consistency_fragment(defaults: dict[str, Any], human: dict[str, Any]) -> str:
    traits = [human[key]["prompt"] for key in IDENTITY_HUMAN_PARTS if human[key].get("prompt")]
    prefix = defaults.get(
        "identity_consistency_prompt",
        "single subject, solo, exactly one adult woman, consistent facial identity and hairstyle",
    )
    strength = float(defaults.get("identity_consistency_strength", 1.25))
    return f"({prefix}, {', '.join(traits)}:{strength:g})"


def compile_scene(
    db: dict[str, Any], scene: dict[str, Any], identity_consistency: bool = False
) -> tuple[str, str, list[str]]:
    defaults = db["prompt_defaults"]
    stage = scene["stage"]
    visibility = set(stage.get("body_visibility", []))
    plateau_kind = stage.get("plateau_kind")
    xxx_prompt = defaults.get("xxx_plateau_prompts", {}).get(plateau_kind, "")
    fragments = [xxx_prompt, defaults.get("positive_prefix", "")]
    if identity_consistency:
        fragments.append(identity_consistency_fragment(defaults, scene["human"]))
    fragments.extend(
        human_fragments(scene["human"], visibility, include_identity=not identity_consistency)
    )
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
    if identity_consistency and defaults.get("identity_consistency_negative"):
        negative = f"{negative}, {defaults['identity_consistency_negative']}"
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


def run_batch(args: argparse.Namespace, render: bool) -> None:
    db, db_path = load_database()
    prompt_seed = args.prompt_seed if args.prompt_seed is not None else secrets.randbits(63)
    rng = random.Random(prompt_seed)
    composer = Composer(db, rng)
    configured_percent = float(db["settings"].get("photoshoot_progression", {}).get("nsfw_final_percent", 50))
    nsfw_percent = configured_percent if args.nsfw_percent is None else args.nsfw_percent
    configured_plateau = float(db["settings"].get("photoshoot_progression", {}).get("explicit_plateau_percent", 30))
    plateau_percent = configured_plateau if args.plateau_percent is None else args.plateau_percent
    if args.mode == "random" and (args.nsfw_percent is not None or args.plateau_percent is not None):
        raise AppError("--nsfw-percent and --plateau-percent are only valid with --mode photoshoot")
    if args.xxx_only and (args.nsfw_percent is not None or args.plateau_percent is not None):
        raise AppError("--xxx-only cannot be combined with --nsfw-percent or --plateau-percent")
    if args.mode == "random" and args.photoshoots != 1:
        raise AppError("--photoshoots is only valid with --mode photoshoot")
    if plateau_percent > nsfw_percent:
        raise AppError("The explicit plateau percentage cannot exceed the NSFW final percentage")
    fixed_inference_seed = args.inference_seed
    photoshoot_count = args.photoshoots if args.mode == "photoshoot" else 1
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    print(
        f"mode={args.mode} count={args.count} photoshoots={photoshoot_count} "
        f"total_images={args.count * photoshoot_count} prompt_seed={prompt_seed} "
        f"content_mode={'xxx-only' if args.xxx_only else 'progressive'}"
    )
    if args.mode == "photoshoot" and not args.xxx_only:
        print(f"nsfw_final_percent={nsfw_percent:g}")
        print(f"explicit_plateau_percent={plateau_percent:g}")
    if fixed_inference_seed is not None:
        print(f"fixed_inference_seed={fixed_inference_seed}")
    seen_photoshoots: set[tuple[Any, ...]] = set()
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
                    f"Could not assemble {photoshoot_count} distinct photoshoots after "
                    f"{attempts} attempts for photoshoot {photoshoot_index + 1}"
                )
        if args.mode == "photoshoot":
            assert fixed is not None
            print(
                f"\n=== Photoshoot {photoshoot_index + 1}/{photoshoot_count}: "
                f"template={fixed['outfit']['template']['id']} "
                f"model_signature={model_signature(fixed['human'])} ==="
            )
        for shot_index in range(args.count):
            context = fixed if fixed is not None else composer.fixed_context()
            assert context is not None
            template = context["outfit"]["template"]
            if args.xxx_only:
                stage = xxx_only_stage(template, shot_index, args.count, args.mode, rng)
            else:
                stage = stage_for_index(
                    template, shot_index, args.count, args.mode, rng, nsfw_percent, plateau_percent
                )
            scene = composer.resolve_scene(context, stage)
            positive, negative, selected_ids = compile_scene(
                db, scene, identity_consistency=args.mode == "photoshoot"
            )
            inference_seed = fixed_inference_seed if fixed_inference_seed is not None else secrets.randbelow(2**63)
            if args.mode == "photoshoot":
                progress = (
                    f"photoshoot {photoshoot_index + 1}/{photoshoot_count} "
                    f"shot {shot_index + 1}/{args.count}"
                )
            else:
                progress = f"{shot_index + 1}/{args.count}"
            print(f"\n[{progress}] stage={stage['id']} inference_seed={inference_seed}")
            print(f"model_signature={model_signature(scene['human'])}")
            print(f"selected_ids={','.join(selected_ids)}")
            print(f"positive={positive}")
            print(f"negative={negative}")
            if render:
                prompt_id, paths = generate_one(
                    db,
                    db_path,
                    positive,
                    negative,
                    inference_seed,
                    args.mode,
                    shot_index,
                    photoshoot_index,
                    run_id,
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
