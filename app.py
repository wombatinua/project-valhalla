#!/usr/bin/env python3
"""Small, single-file rule-based prompt composer for a local ComfyUI server."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import re
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
    validate_database(data)
    return data, path


def iter_content_items(db: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for values in db.get("human_model_parts", {}).values():
        if isinstance(values, list):
            yield from values
    yield from db.get("colors", [])
    yield from db.get("patterns", [])
    yield from db.get("fabric_textures", [])
    for values in db.get("garments", {}).values():
        yield from values
    for section in (
        "outfit_templates", "interiors", "furniture", "poses", "actions",
        "props", "expressions", "moods", "photography_styles", "shot_sizes",
        "camera_angles", "framings", "focus_targets", "editorial_roles",
        "explicit_recipes",
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
    if "menu_label" in item and (
        not isinstance(item["menu_label"], str) or not item["menu_label"].strip()
    ):
        raise AppError(f"{context}.{item['id']}: menu_label must be a non-empty string")
    if "menu_group" in item and (
        not isinstance(item["menu_group"], str) or not item["menu_group"].strip()
    ):
        raise AppError(f"{context}.{item['id']}: menu_group must be a non-empty string")
    if "covered_prompt" in item and (
        not isinstance(item["covered_prompt"], str)
        or not item["covered_prompt"].strip()
    ):
        raise AppError(
            f"{context}.{item['id']}: covered_prompt must be a non-empty string"
        )
    if "reveals_cameltoe" in item and not isinstance(item["reveals_cameltoe"], bool):
        raise AppError(f"{context}.{item['id']}: reveals_cameltoe must be true or false")
    for field in ("requires_environment_tags", "excludes_environment_tags"):
        if field in item and (
            not isinstance(item[field], list)
            or not all(isinstance(tag, str) and tag for tag in item[field])
        ):
            raise AppError(f"{context}.{item['id']}: {field} must be a list of tags")


def validate_database(db: dict[str, Any]) -> None:
    required_sections = (
        "settings", "prompt_defaults", "colors", "patterns", "fabric_textures",
        "human_model_parts", "garments",
        "outfit_templates", "interiors", "furniture", "poses", "actions", "props",
        "expressions", "moods", "photography_styles", "shot_sizes",
        "camera_angles", "framings", "focus_targets", "editorial_roles",
        "explicit_recipes",
    )
    for section in required_sections:
        if section not in db:
            raise AppError(f"database.json is missing the '{section}' section")
    settings = db["settings"]
    for key in ("comfy_url", "workflow_file", "output_dir"):
        if not isinstance(settings.get(key), str) or not settings[key]:
            raise AppError(f"settings.{key} must be a non-empty string")
    positive_prefix = db["prompt_defaults"].get("positive_prefix")
    if not isinstance(positive_prefix, str) or positive_prefix.count("{age}") != 1:
        raise AppError(
            "prompt_defaults.positive_prefix must contain exactly one {age} placeholder"
        )
    cameltoe_prompt = db["prompt_defaults"].get("cameltoe_prompt")
    if not isinstance(cameltoe_prompt, str) or not cameltoe_prompt.strip():
        raise AppError("prompt_defaults.cameltoe_prompt must be a non-empty string")
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
    garment_modifiers = settings.get("garment_modifiers", {})
    if not isinstance(garment_modifiers, dict):
        raise AppError("settings.garment_modifiers must be an object")
    for field in ("pattern_chance", "texture_chance"):
        value = garment_modifiers.get(field, 0)
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise AppError(f"settings.garment_modifiers.{field} must be between 0 and 1")

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
        "colors", "patterns", "fabric_textures", "outfit_templates", "interiors", "furniture", "poses", "actions",
        "props", "expressions", "moods", "photography_styles", "shot_sizes",
        "camera_angles", "framings", "focus_targets", "editorial_roles",
        "explicit_recipes",
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
    for recipe in db["explicit_recipes"]:
        for field, section in (
            ("shot_size", "shot_sizes"),
            ("camera_angle", "camera_angles"),
            ("focus_target", "focus_targets"),
        ):
            if recipe.get(field) not in {item["id"] for item in db[section]}:
                raise AppError(
                    f"explicit_recipes.{recipe['id']}.{field} references unknown id"
                )
    human_defaults = settings.get("human_defaults", {})
    if not isinstance(human_defaults, dict):
        raise AppError("settings.human_defaults must be an object")
    default_pools = human_defaults.get("pools", {})
    if not isinstance(default_pools, dict):
        raise AppError("settings.human_defaults.pools must be an object")
    for category, item_ids in default_pools.items():
        if category not in db["human_model_parts"]:
            raise AppError(f"settings.human_defaults.pools has unknown category: {category}")
        if not isinstance(item_ids, list) or not all(
            isinstance(item_id, str) and item_id for item_id in item_ids
        ):
            raise AppError(
                f"settings.human_defaults.pools.{category} must be a list of IDs"
            )
        if len(item_ids) != len(set(item_ids)):
            raise AppError(
                f"settings.human_defaults.pools.{category} contains duplicate IDs"
            )
        category_ids = {
            item["id"] for item in db["human_model_parts"][category]
            if not item.get("disabled", False)
        }
        unknown_ids = set(item_ids) - category_ids
        if unknown_ids:
            raise AppError(
                f"settings.human_defaults.pools.{category} references unavailable items: "
                f"{sorted(unknown_ids)}"
            )
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
    garment_ids = {
        item["id"] for values in db["garments"].values() for item in values
    }
    for section in ("patterns", "fabric_textures"):
        for item in db[section]:
            allowed = item.get("allowed_garment_ids")
            if (
                not isinstance(allowed, list) or not allowed
                or not all(isinstance(item_id, str) and item_id for item_id in allowed)
                or len(allowed) != len(set(allowed))
            ):
                raise AppError(
                    f"{section}.{item['id']}.allowed_garment_ids must be a non-empty unique list"
                )
            unknown = set(allowed) - garment_ids
            if unknown:
                raise AppError(
                    f"{section}.{item['id']} references unknown garments: {sorted(unknown)}"
                )
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

    prompt_owners: dict[str, str] = {}
    internal_prompt_phrases = {
        "production variation", "editorial variation", "understated variation",
        "realistic variation", "production detail", "construction detail",
    }
    for item in iter_content_items(db):
        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        normalized = re.sub(r"\s+", " ", prompt.strip().casefold())
        internal = next(
            (phrase for phrase in internal_prompt_phrases if phrase in normalized), None
        )
        if internal:
            raise AppError(
                f"{item['id']}.prompt contains internal non-visual wording: {internal}"
            )
        if len(prompt.split()) > 48:
            raise AppError(f"{item['id']}.prompt is too long for a catalog fragment")
        owner = prompt_owners.get(normalized)
        if owner is not None:
            raise AppError(
                f"{item['id']}.prompt duplicates the visual wording of {owner}"
            )
        prompt_owners[normalized] = item["id"]

    for template in db["outfit_templates"]:
        if template.get("wardrobe_category") not in {"normal", "glamour"}:
            raise AppError(
                f"Template {template['id']} wardrobe_category must be normal or glamour"
            )
        slots = template.get("slots")
        stages = template.get("stages")
        if not isinstance(slots, dict) or not slots:
            raise AppError(f"Template {template['id']} needs a non-empty slots object")
        if not isinstance(stages, list) or not stages:
            raise AppError(f"Template {template['id']} needs at least one stage")
        for slot, rule in slots.items():
            catalog = rule.get("catalog")
            if catalog not in garment_catalogs:
                raise AppError(f"Template {template['id']} slot {slot} has unknown catalog")
            chance = rule.get("chance", 1)
            if not isinstance(chance, (int, float)) or not 0 <= chance <= 1:
                raise AppError(f"Template {template['id']} slot {slot} chance must be 0..1")
            for field in ("required_tags", "required_any_tags", "excludes_tags"):
                values = rule.get(field, [])
                if (
                    not isinstance(values, list)
                    or not all(isinstance(value, str) and value for value in values)
                    or len(values) != len(set(values))
                ):
                    raise AppError(
                        f"Template {template['id']} slot {slot} {field} must be a unique list of tags"
                    )
            candidates = [
                item for item in db["garments"][catalog]
                if not item.get("disabled", False)
                and set(rule.get("required_tags", [])).issubset(tags(item))
                and (
                    not rule.get("required_any_tags")
                    or set(rule["required_any_tags"]) & tags(item)
                )
                and not set(rule.get("excludes_tags", [])) & tags(item)
            ]
            if not candidates:
                raise AppError(
                    f"Template {template['id']} slot {slot} filters out every enabled garment"
                )
        for stage in stages:
            if not isinstance(stage.get("id"), str) or not isinstance(stage.get("level"), str):
                raise AppError(f"Template {template['id']} has an invalid stage")
            unknown_slots = set(stage.get("visible_slots", [])) - set(slots)
            if unknown_slots:
                raise AppError(f"Template {template['id']} stage has unknown slots: {sorted(unknown_slots)}")

    scene_defaults = settings.get("scene_defaults")
    if not isinstance(scene_defaults, dict):
        raise AppError("settings.scene_defaults must be an object")
    category_specs = {
        "wardrobe_categories": (
            {"normal", "glamour"},
            {
                template["wardrobe_category"] for template in db["outfit_templates"]
                if not template.get("disabled", False)
            },
        ),
        "environment_categories": (
            {"normal", "luxury"},
            {
                "luxury" if "luxury" in tags(interior) else "normal"
                for interior in db["interiors"] if not interior.get("disabled", False)
            },
        ),
    }
    for field, (allowed, available) in category_specs.items():
        values = scene_defaults.get(field)
        if (
            not isinstance(values, list) or not values
            or not all(isinstance(value, str) for value in values)
            or len(values) != len(set(values))
            or not set(values).issubset(allowed)
        ):
            raise AppError(
                f"settings.scene_defaults.{field} must be a non-empty unique list "
                f"containing only {sorted(allowed)}"
            )
        if not set(values) & available:
            raise AppError(f"settings.scene_defaults.{field} has no enabled candidates")

    scene_pools = scene_defaults.get("pools", {})
    if not isinstance(scene_pools, dict):
        raise AppError("settings.scene_defaults.pools must be an object")
    scene_pool_sections = {
        "interiors": db["interiors"],
        "furniture": db["furniture"],
        "moods": db["moods"],
        "photography_styles": db["photography_styles"],
        "explicit_photography_styles": db["photography_styles"],
    }
    unknown_scene_pools = set(scene_pools) - set(scene_pool_sections)
    if unknown_scene_pools:
        raise AppError(
            f"settings.scene_defaults.pools has unknown sections: {sorted(unknown_scene_pools)}"
        )
    for section, item_ids in scene_pools.items():
        if not isinstance(item_ids, list) or not all(
            isinstance(item_id, str) and item_id for item_id in item_ids
        ):
            raise AppError(f"settings.scene_defaults.pools.{section} must be a list of IDs")
        if len(item_ids) != len(set(item_ids)):
            raise AppError(f"settings.scene_defaults.pools.{section} contains duplicate IDs")
        enabled_section_ids = {
            item["id"] for item in scene_pool_sections[section]
            if not item.get("disabled", False)
        }
        unavailable = set(item_ids) - enabled_section_ids
        if unavailable:
            raise AppError(
                f"settings.scene_defaults.pools.{section} references unavailable items: "
                f"{sorted(unavailable)}"
            )

def detect_fast_mode_mapping(workflow: dict[str, Any]) -> dict[str, Any]:
    base_candidates = []
    for sampler_id, sampler in workflow.items():
        class_name = str(sampler.get("class_type", "")).lower()
        if "sampler" not in class_name or "detailer" in class_name:
            continue
        latent_link = sampler.get("inputs", {}).get("latent_image")
        if not (isinstance(latent_link, list) and len(latent_link) == 2):
            continue
        latent_node = workflow.get(str(latent_link[0]), {})
        latent_class = str(latent_node.get("class_type", "")).lower()
        if "latent" not in latent_class or "empty" not in latent_class:
            continue
        decoders = [
            node_id for node_id, node in workflow.items()
            if str(node.get("class_type", "")).lower() == "vaedecode"
            and node.get("inputs", {}).get("samples") == [sampler_id, 0]
        ]
        if len(decoders) == 1:
            base_candidates.append((sampler_id, decoders[0]))
    if len(base_candidates) != 1:
        found = ", ".join(sampler for sampler, _ in base_candidates) or "none"
        raise AppError(
            "Fast-test mapping is ambiguous: expected one base sampler fed by an empty "
            f"latent with one VAE Decode, found {found}"
        )
    sampler_id, decode_id = base_candidates[0]
    output_targets = []
    for node_id, node in workflow.items():
        class_name = str(node.get("class_type", "")).lower()
        if "saveimage" not in class_name and "previewimage" not in class_name:
            continue
        if "images" in node.get("inputs", {}):
            output_targets.append({
                "node": node_id,
                "input": "images",
                "source": [decode_id, 0],
            })
    if not output_targets:
        raise AppError("Fast-test mapping could not find a SaveImage or PreviewImage output")
    return {"base_sampler": sampler_id, "output_targets": output_targets}


def detect_node_mapping(
    workflow: dict[str, Any], include_fast: bool = False
) -> dict[str, Any]:
    """Discover workflow-specific prompt and seed targets for this process only."""
    text_candidates = [
        (node_id, node) for node_id, node in workflow.items()
        if isinstance(node.get("inputs", {}).get("text"), str)
    ]
    positives = [entry for entry in text_candidates if "positive" in entry[0].lower()]
    negatives = [entry for entry in text_candidates if "negative" in entry[0].lower()]
    if len(positives) != 1 or len(negatives) != 1:
        candidates = ", ".join(
            f"{node_id}:{node.get('class_type')}" for node_id, node in text_candidates
        )
        raise AppError(f"Prompt node detection is ambiguous. Text candidates: {candidates}")
    seed_targets = []
    for node_id, node in workflow.items():
        class_type = str(node.get("class_type", "")).lower()
        if "sampler" not in class_type and "detailer" not in class_type:
            continue
        for input_name in ("seed", "noise_seed"):
            if isinstance(node.get("inputs", {}).get(input_name), int):
                seed_targets.append({"node": node_id, "input": input_name})
    if not seed_targets:
        raise AppError("Could not find a scalar seed input in sampler/detailer nodes")
    mapping = {
        "positive_prompt": {"node": positives[0][0], "input": "text"},
        "negative_prompt": {"node": negatives[0][0], "input": "text"},
        "inference_seed": seed_targets,
    }
    if include_fast:
        mapping["fast_mode"] = detect_fast_mode_mapping(workflow)
    return mapping


def tags(item: dict[str, Any]) -> set[str]:
    return set(item.get("tags", []))


def base_catalog_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep production variants in Director, not in casual automatic direction."""
    base = [
        item for item in items
        if not item["id"].endswith(("_studio", "_editorial"))
    ]
    return base or items


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


HUMAN_SELECTION_ORDER = (
    "age", "ethnic_appearance", "skin_tone", "face_shape", "eye_shape",
    "eye_color", "eyebrows", "nose", "lips", "cheekbones", "jawline",
    "hair_texture", "hair_length", "hair_style", "hair_color", "height",
    "body_frame", "waist", "hips", "breast_size", "breast_shape",
    "areola_size", "areola_color", "nipple_size", "nipple_shape",
    "pubic_hair", "genital_appearance", "facial_accents", "makeup",
    "manicure",
)


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

    def choose_garment_modifier(
        self, section: str, garment: dict[str, Any], chance: float
    ) -> dict[str, Any] | None:
        if self.rng.random() >= chance:
            return None
        candidates = [
            item for item in self.db[section]
            if not item.get("disabled", False)
            and garment["id"] in item["allowed_garment_ids"]
        ]
        candidates = base_catalog_items(candidates)
        return weighted_choice(self.rng, candidates) if candidates else None

    def choose_human(
        self,
        overrides: dict[str, dict[str, Any]] | None = None,
        use_default_ethnicity: bool = True,
        use_human_defaults: bool = True,
    ) -> dict[str, Any]:
        overrides = dict(overrides or {})
        human_defaults = self.db["settings"].get("human_defaults", {})
        default_pools = (
            dict(human_defaults.get("pools", {})) if use_human_defaults else {}
        )
        if not use_default_ethnicity:
            default_pools.pop("ethnic_appearance", None)
        human: dict[str, Any] = {}
        parts = self.db["human_model_parts"]
        order = [category for category in HUMAN_SELECTION_ORDER if category in parts]
        order.extend(
            category for category in parts if category not in HUMAN_SELECTION_ORDER
        )
        selected_tags: set[str] = set()
        for category in order:
            if category == "facial_accents":
                count = self.rng.choices([0, 1, 2], weights=[3, 5, 2], k=1)[0]
                candidates = [
                    item for item in parts[category]
                    if not item.get("disabled", False)
                    and compatible_with_requirements(item, selected_tags)
                ]
                if default_pools.get(category):
                    allowed_ids = set(default_pools[category])
                    candidates = [item for item in candidates if item["id"] in allowed_ids]
                    candidates = base_catalog_items(candidates)
                human[category] = self.rng.sample(candidates, k=min(count, len(candidates)))
                for item in human[category]:
                    selected_tags |= tags(item)
                continue
            candidates = [
                item for item in parts[category]
                if not item.get("disabled", False)
                and compatible_with_requirements(item, selected_tags)
            ]
            if category not in overrides and default_pools.get(category):
                allowed_ids = set(default_pools[category])
                candidates = [item for item in candidates if item["id"] in allowed_ids]
                candidates = base_catalog_items(candidates)
            if category in overrides:
                choice = overrides[category]
                if choice not in candidates:
                    raise AppError(
                        f"Human trait override {choice['id']} is incompatible in category {category}"
                    )
            else:
                if not candidates:
                    raise AppError(
                        f"No compatible enabled default candidates remain for human category {category}"
                    )
                choice = weighted_choice(self.rng, candidates)
            human[category] = choice
            selected_tags |= tags(choice)
        return human

    def choose_template(self) -> dict[str, Any]:
        allowed = set(
            self.db["settings"]["scene_defaults"]["wardrobe_categories"]
        )
        candidates = [
            template for template in self.db["outfit_templates"]
            if not template.get("disabled", False)
            and template["wardrobe_category"] in allowed
        ]
        return weighted_choice(self.rng, candidates)

    def _choose_outfit_once(self, template: dict[str, Any]) -> dict[str, Any]:
        selected: dict[str, dict[str, Any]] = {}
        group_tags: dict[str, set[str]] = {}
        for slot, rule in template["slots"].items():
            required = bool(rule.get("required", False))
            if not required and self.rng.random() > float(rule.get("chance", 1)):
                continue
            candidates = base_catalog_items(
                list(self.db["garments"][rule["catalog"]])
            )
            required_tags = set(rule.get("required_tags", []))
            if required_tags:
                candidates = [item for item in candidates if required_tags.issubset(tags(item))]
            required_any_tags = set(rule.get("required_any_tags", []))
            if required_any_tags:
                candidates = [item for item in candidates if required_any_tags & tags(item)]
            excluded_tags = set(rule.get("excludes_tags", []))
            if excluded_tags:
                candidates = [item for item in candidates if not excluded_tags & tags(item)]
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
        modifier_settings = self.db["settings"].get("garment_modifiers", {})
        assigned_patterns: dict[str, dict[str, Any]] = {}
        assigned_textures: dict[str, dict[str, Any]] = {}
        for slot, item in selected.items():
            pattern = self.choose_garment_modifier(
                "patterns", item, float(modifier_settings.get("pattern_chance", 0))
            )
            texture = self.choose_garment_modifier(
                "fabric_textures", item, float(modifier_settings.get("texture_chance", 0))
            )
            if pattern:
                assigned_patterns[slot] = pattern
            if texture:
                assigned_textures[slot] = texture
        return {
            "template": template,
            "garments": selected,
            "colors": assigned_colors,
            "patterns": assigned_patterns,
            "textures": assigned_textures,
        }

    def validate_outfit_environment(
        self,
        outfit: dict[str, Any],
        interior: dict[str, Any],
    ) -> None:
        environment_tags = tags(interior)
        for item in outfit["garments"].values():
            required = set(item.get("requires_environment_tags", []))
            excluded = set(item.get("excludes_environment_tags", []))
            if not required.issubset(environment_tags) or excluded & environment_tags:
                raise AppError(
                    f"Garment {item['id']} is incompatible with interior {interior['id']}: "
                    f"required_environment={sorted(required)}, "
                    f"excluded_environment={sorted(excluded)}"
                )

    def choose_outfit(
        self,
        template: dict[str, Any],
        interior: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts = int(self.db["settings"].get("max_scene_attempts", 100))
        last_error = "no compatible outfit"
        for _ in range(attempts):
            try:
                outfit = self._choose_outfit_once(template)
                if interior is not None:
                    self.validate_outfit_environment(outfit, interior)
                return outfit
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
                allowed_environments = set(
                    self.db["settings"]["scene_defaults"]["environment_categories"]
                )
                interiors = [
                    interior for interior in self.db["interiors"]
                    if not interior.get("disabled", False)
                    and ("luxury" if "luxury" in tags(interior) else "normal")
                    in allowed_environments
                ]
                scene_pools = self.db["settings"]["scene_defaults"].get("pools", {})
                if scene_pools.get("interiors"):
                    allowed_ids = set(scene_pools["interiors"])
                    interiors = [item for item in interiors if item["id"] in allowed_ids]
                interior = weighted_choice(self.rng, interiors)
                furniture_candidates = [
                    item for item in self.db["furniture"]
                    if compatible_with_requirements(item, tags(interior))
                ]
                if scene_pools.get("furniture"):
                    allowed_ids = set(scene_pools["furniture"])
                    furniture_candidates = [
                        item for item in furniture_candidates if item["id"] in allowed_ids
                    ]
                mood_candidates = self.db["moods"]
                if scene_pools.get("moods"):
                    allowed_ids = set(scene_pools["moods"])
                    mood_candidates = [
                        item for item in mood_candidates if item["id"] in allowed_ids
                    ]
                photography_candidates = self.db["photography_styles"]
                if scene_pools.get("photography_styles"):
                    allowed_ids = set(scene_pools["photography_styles"])
                    photography_candidates = [
                        item for item in photography_candidates if item["id"] in allowed_ids
                    ]
                outfit = self.choose_outfit(template, interior)
                return {
                    "human": self.choose_human(),
                    "outfit": outfit,
                    "interior": interior,
                    "furniture": weighted_choice(self.rng, furniture_candidates),
                    "mood": weighted_choice(self.rng, mood_candidates),
                    "photography_style": weighted_choice(self.rng, photography_candidates),
                }
            except AppError as exc:
                last_error = str(exc)
        raise AppError(f"Could not resolve a compatible fixed context after {attempts} attempts: {last_error}")

    def variable_context(
        self,
        stage: dict[str, Any],
        fixed: dict[str, Any],
        overrides: dict[str, str] | None = None,
        avoid: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        overrides = overrides or {}
        avoid = avoid or {}
        def choose(section: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
            fresh = [item for item in candidates if item["id"] not in avoid.get(section, set())]
            return weighted_choice(self.rng, fresh or candidates)

        furniture_candidates = [
            item for item in self.db["furniture"]
            if not item.get("disabled", False)
            and compatible_with_requirements(item, tags(fixed["interior"]))
        ]
        scene_pools = self.db["settings"]["scene_defaults"].get("pools", {})
        if not overrides.get("furniture") and scene_pools.get("furniture"):
            default_furniture = set(scene_pools["furniture"])
            furniture_candidates = [
                item for item in furniture_candidates
                if item["id"] in default_furniture
            ]
        if overrides.get("furniture"):
            furniture_candidates = [item for item in furniture_candidates if item["id"] == overrides["furniture"]]
        else:
            furniture_candidates = base_catalog_items(furniture_candidates)
        furniture = choose("furniture", furniture_candidates)
        available_tags = set(stage.get("body_visibility", [])) | {stage["level"]}
        available_tags |= set(stage.get("visible_slots", []))
        available_tags |= tags(furniture) | tags(fixed["interior"])
        recipe = None
        if stage["level"] == "explicit":
            recipes = [item for item in self.db["explicit_recipes"] if not item.get("disabled", False)]
            if stage.get("plateau_kind"):
                recipes = [item for item in recipes if item.get("plateau_kind") == stage["plateau_kind"]]
            if overrides.get("explicit_recipe"):
                recipes = [item for item in recipes if item["id"] == overrides["explicit_recipe"]]
            else:
                recipes = base_catalog_items(recipes)
            if recipes:
                recipe = choose("explicit_recipe", recipes)
                available_tags |= tags(recipe)
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
        elif plateau_kind == "panties_aside":
            poses = [
                item for item in poses
                if "open_legs" in tags(item) and "provocative_rear" not in tags(item)
            ]
        if recipe and recipe.get("pose_tags"):
            required = set(recipe["pose_tags"])
            poses = [item for item in poses if required & tags(item)]
        if overrides.get("pose"):
            poses = [item for item in poses if item["id"] == overrides["pose"]]
        else:
            poses = base_catalog_items(poses)
        pose = choose("pose", poses)
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
        elif plateau_kind == "panties_aside":
            actions = [item for item in actions if "panties_aside_action" in tags(item)]
        if recipe and recipe.get("action_tags"):
            required = set(recipe["action_tags"])
            actions = [item for item in actions if required & tags(item)]
        if overrides.get("action"):
            actions = [item for item in actions if item["id"] == overrides["action"]]
        else:
            actions = base_catalog_items(actions)
        action = choose("action", actions)
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
            if stage["level"] != "explicit":
                casual_props = [
                    item for item in candidates
                    if tags(item) & {"casual_prop", "home_prop"}
                ]
                candidates = casual_props or candidates
            if candidates:
                prop = weighted_choice(self.rng, candidates)
        expression_candidates = base_catalog_items(list(self.db["expressions"]))
        required_expression_tags = set(action.get("requires_expression_tags", []))
        if required_expression_tags:
            expression_candidates = [
                item for item in expression_candidates
                if required_expression_tags.issubset(tags(item))
            ]
            if stage["level"] == "lingerie":
                subtle = [
                    item for item in expression_candidates
                    if item["id"] == "expression_shy_sultry"
                ]
                expression_candidates = subtle or expression_candidates
        elif stage["level"] in {"covered", "lingerie"}:
            natural_expressions = {
                "expression_confident", "expression_soft_smile",
                "expression_dreamy", "expression_playful", "expression_serene",
                "expression_shy_sultry",
            }
            expression_candidates = [
                item for item in expression_candidates
                if item["id"] in natural_expressions
            ]
        elif stage["level"] in {"topless", "nude"}:
            expression_candidates = [
                item for item in expression_candidates
                if not tags(item) & {"pleasure_expression", "intense_pleasure_expression"}
            ]
        if overrides.get("expression"):
            expression_candidates = [
                item for item in expression_candidates
                if item["id"] == overrides["expression"]
            ]
        editorial_role = None
        if overrides.get("editorial_role"):
            editorial_role = self.item_index.get(overrides["editorial_role"])
        if editorial_role is None:
            role_hint = "role_" + {
                "covered": "establishing", "lingerie": "development",
                "topless": "reveal", "nude": "nude_study", "explicit": "plateau",
            }.get(stage["level"], "portrait")
            candidates = [item for item in self.db["editorial_roles"] if role_hint in tags(item) or item["id"] == role_hint]
            editorial_role = choose("editorial_role", candidates or self.db["editorial_roles"])
        camera_tags = available_tags | tags(pose) | tags(action) | tags(editorial_role)
        camera = {}
        recipe_refs = {
            "shot_size": recipe.get("shot_size") if recipe else None,
            "camera_angle": recipe.get("camera_angle") if recipe else None,
            "focus_target": recipe.get("focus_target") if recipe else None,
        }
        for key, section in (
            ("shot_size", "shot_sizes"), ("camera_angle", "camera_angles"),
            ("framing", "framings"), ("focus_target", "focus_targets"),
        ):
            candidates = [
                item for item in self.db[section]
                if not item.get("disabled", False)
                and stage["level"] in item.get("allowed_levels", [stage["level"]])
                and compatible_with_requirements(item, camera_tags)
            ]
            wanted = overrides.get(key) or recipe_refs.get(key)
            if wanted:
                candidates = [item for item in candidates if item["id"] == wanted]
            else:
                candidates = base_catalog_items(candidates)
                if key == "framing":
                    casual_framings = {
                        "framing_centered", "framing_tight_crop",
                        "framing_environmental",
                    }
                    casual = [
                        item for item in candidates
                        if item["id"] in casual_framings
                    ]
                    candidates = casual or candidates
            camera[key] = choose(key, candidates)
            camera_tags |= tags(camera[key])
        intensity = overrides.get("intensity") or (recipe.get("intensity", "explicit") if recipe else {
            "covered": "fashion", "lingerie": "sensual", "topless": "erotic", "nude": "nude"
        }.get(stage["level"], "fashion"))
        return {
            "furniture": furniture,
            "pose": pose,
            "action": action,
            "prop": prop,
            "expression": choose("expression", expression_candidates),
            "editorial_role": editorial_role,
            "explicit_recipe": recipe,
            "intensity": intensity,
            **camera,
        }

    def resolve_scene(
        self,
        fixed: dict[str, Any],
        stage: dict[str, Any],
        overrides: dict[str, str] | None = None,
        avoid: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        attempts = int(self.db["settings"].get("max_scene_attempts", 100))
        last_error = "no candidates"
        for _ in range(attempts):
            try:
                scene = dict(fixed)
                scene.update(self.variable_context(stage, fixed, overrides, avoid))
                scene_pools = self.db["settings"]["scene_defaults"].get("pools", {})
                base_photo_ids = set(scene_pools.get("photography_styles", []))
                explicit_photo_ids = scene_pools.get("explicit_photography_styles", [])
                if (
                    stage["level"] == "explicit"
                    and explicit_photo_ids
                    and fixed["photography_style"]["id"] in base_photo_ids
                ):
                    explicit_candidates = [
                        item for item in self.db["photography_styles"]
                        if item["id"] in set(explicit_photo_ids)
                    ]
                    scene["photography_style"] = weighted_choice(
                        self.rng, explicit_candidates
                    )
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
        for modifier_key in ("patterns", "textures"):
            flattened.extend(
                item for slot, item in scene["outfit"].get(modifier_key, {}).items()
                if slot in visible_slots
            )
        flattened.extend([scene[key] for key in ("interior", "furniture", "pose", "action", "expression", "mood", "photography_style", "editorial_role", "shot_size", "camera_angle", "framing", "focus_target")])
        if scene.get("explicit_recipe"):
            flattened.append(scene["explicit_recipe"])
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
        self.validate_outfit_environment(scene["outfit"], scene["interior"])
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
    "ethnic_appearance", "skin_tone", "face_shape", "eye_shape", "eye_color",
    "eyebrows", "nose", "lips", "cheekbones", "jawline", "hair_texture", "hair_length",
    "hair_style", "hair_color", "height", "body_frame", "waist", "hips", "makeup",
    "manicure",
)

def human_fragments(
    human: dict[str, Any],
    visibility: set[str],
    covered_chest: bool,
    custom: dict[str, str],
) -> list[str]:
    fragments = [
        custom.get(f"human.{key}") or human[key].get("prompt", "")
        for key in ALWAYS_HUMAN_PARTS
    ]
    facial_custom = custom.get("human.facial_accents")
    if facial_custom:
        fragments.append(facial_custom)
    else:
        fragments.extend(
            item["prompt"] for item in human.get("facial_accents", [])
            if item.get("prompt")
        )
    if "breasts" in visibility or "nipples" in visibility:
        fragments.extend([
            custom.get("human.breast_size") or human["breast_size"]["prompt"],
            custom.get("human.breast_shape") or human["breast_shape"]["prompt"],
        ])
    elif covered_chest:
        for key in ("breast_size", "breast_shape"):
            override = custom.get(f"human.{key}")
            if override:
                fragments.append(
                    f"{override}, expressed through clothing only, chest fully covered by clothing"
                )
            elif human[key].get("covered_prompt"):
                fragments.append(human[key]["covered_prompt"])
    if "nipples" in visibility:
        fragments.extend(
            custom.get(f"human.{key}") or human[key]["prompt"]
            for key in ("areola_size", "areola_color", "nipple_size", "nipple_shape")
        )
    if "pubic_area" in visibility:
        fragments.append(custom.get("human.pubic_hair") or human["pubic_hair"]["prompt"])
    if "genitals" in visibility:
        fragments.append(custom.get("human.genital_appearance") or human["genital_appearance"]["prompt"])
    return [fragment for fragment in fragments if fragment]


def compile_scene(db: dict[str, Any], scene: dict[str, Any]) -> tuple[str, str, list[str]]:
    defaults = db["prompt_defaults"]
    custom = scene.get("custom_values", {})
    stage = scene["stage"]
    stage_visibility = set(stage.get("body_visibility", []))
    covered_chest = not bool({"breasts", "nipples"} & stage_visibility)
    visibility = set(stage_visibility)
    plateau_kind = stage.get("plateau_kind")
    if plateau_kind == "provocative_rear":
        visibility -= {"breasts", "nipples"}
    xxx_prompt = defaults.get("xxx_plateau_prompts", {}).get(plateau_kind, "")
    age_prompt = custom.get("human.age") or scene["human"]["age"]["prompt"]
    positive_prefix = defaults.get("positive_prefix", "").replace("{age}", age_prompt)
    fragments = [positive_prefix]
    scene_pools = db["settings"]["scene_defaults"].get("pools", {})
    casual_photo_ids = set(scene_pools.get("photography_styles", [])) | set(
        scene_pools.get("explicit_photography_styles", [])
    )
    casual_role_prompts = {
        "role_establishing": "casual opening snapshot showing the subject in her room",
        "role_portrait": "relaxed personal portrait snapshot",
        "role_development": "natural mid-sequence home snapshot",
        "role_reveal": "candid reveal moment",
        "role_nude_study": "relaxed natural nude snapshot",
        "role_plateau": "close candid explicit home snapshot",
        "role_peak": "intense closing snapshot",
    }

    def shot_prompt(key: str, item: dict[str, Any]) -> str:
        override = custom.get(f"shot.{key}")
        if override:
            return override
        if (
            key == "editorial_role"
            and scene.get("photography_style", {}).get("id") in casual_photo_ids
        ):
            return casual_role_prompts.get(item["id"], item["prompt"])
        return item["prompt"]
    # A stage label alone is UI metadata. These anchors state the visual contract
    # explicitly in vocabulary image models reliably understand.
    stage_anchors = {
        "covered": (
            "wearing the listed outfit, clothing continuity, breasts and nipples "
            "fully covered by clothing"
        ),
        "lingerie": (
            "wearing the listed lingerie, lingerie continuity, breasts and nipples "
            "covered by the bra"
        ),
        "topless": "topless, bare breasts and visible nipples, lower garments retained",
        "nude": "fully nude body, no clothing except the listed retained accessories",
        "explicit": "explicit adult nudity, clothing state remains consistent",
    }
    stage_anchor = stage_anchors.get(stage.get("level"), "")
    if stage_anchor:
        fragments.append(stage_anchor)
    # Compiler v2 keeps the subject first, then establishes editorial intent and camera.
    for key in ("editorial_role", "shot_size", "camera_angle", "framing", "focus_target"):
        item = scene.get(key)
        if item:
            fragments.append(shot_prompt(key, item))
    stage_custom = custom.get("shot.stage")
    if stage_custom:
        fragments.append(stage_custom)
    elif xxx_prompt:
        fragments.append(xxx_prompt)
    if scene.get("explicit_recipe"):
        fragments.append(custom.get("shot.explicit_recipe") or scene["explicit_recipe"]["prompt"])
    if scene.get("intensity"):
        fragments.append(custom.get("shot.intensity") or f"{scene['intensity']} visual intensity")
    if scene.get("garment_transition"):
        fragments.append(custom.get("shot.garment_transition") or scene["garment_transition"]["prompt"])
    for key in ("pose", "action", "prop"):
        item = scene.get(key)
        if item:
            fragments.append(custom.get(f"shot.{key}") or item["prompt"])
    fragments.extend(
        human_fragments(scene["human"], visibility, covered_chest, custom)
    )
    if stage_custom:
        fragments.append(stage_custom)
    elif xxx_prompt:
        fragments.append(xxx_prompt)
    if scene.get("explicit_recipe"):
        fragments.append(custom.get("shot.explicit_recipe") or scene["explicit_recipe"]["prompt"])
    if scene.get("intensity"):
        fragments.append(custom.get("shot.intensity") or f"{scene['intensity']} visual intensity")
    if scene.get("garment_transition"):
        fragments.append(custom.get("shot.garment_transition") or scene["garment_transition"]["prompt"])
    visible_slots = set(stage.get("visible_slots", []))
    outfit = scene["outfit"]
    if custom.get("outfit.template"):
        fragments.append(custom["outfit.template"])
    reveals_cameltoe = False
    for slot in outfit["template"]["slots"]:
        if slot in visible_slots and slot in outfit["garments"]:
            garment = outfit["garments"][slot]
            garment_parts = [custom.get(f"outfit.colors.{slot}") or outfit["colors"][slot]["prompt"]]
            if custom.get(f"outfit.patterns.{slot}") or slot in outfit.get("patterns", {}):
                garment_parts.append(custom.get(f"outfit.patterns.{slot}") or outfit["patterns"][slot]["prompt"])
            if custom.get(f"outfit.textures.{slot}") or slot in outfit.get("textures", {}):
                garment_parts.append(custom.get(f"outfit.textures.{slot}") or outfit["textures"][slot]["prompt"])
            garment_parts.append(custom.get(f"outfit.garments.{slot}") or garment["prompt"])
            garment_fragment = " ".join(garment_parts)
            fragments.append(garment_fragment)
            reveals_cameltoe = reveals_cameltoe or garment.get("reveals_cameltoe", False)
    if reveals_cameltoe:
        fragments.append(defaults["cameltoe_prompt"])
    for key in ("pose", "action", "prop", "expression", "interior", "furniture", "mood", "photography_style"):
        item = scene.get(key)
        if item:
            director_key = f"shot.{key}" if key in {"pose", "action", "expression", "furniture"} else f"scene.{key}"
            if key == "editorial_role":
                fragments.append(shot_prompt(key, item))
            else:
                fragments.append(custom.get(director_key) or item["prompt"])
    fragments.extend(item["prompt"] for item in scene.get("dependencies", []))
    fragments.append(defaults.get("positive_suffix", ""))
    unique_fragments = []
    seen_fragments = set()
    for fragment in fragments:
        clean = fragment.strip(" ,")
        normalized = re.sub(r"\s+", " ", clean.casefold())
        if clean and normalized not in seen_fragments:
            unique_fragments.append(clean)
            seen_fragments.add(normalized)
    positive = ", ".join(unique_fragments)
    negative = defaults.get("negative_prompt", "")
    if covered_chest and defaults.get("covered_chest_negative"):
        negative = f"{negative}, {defaults['covered_chest_negative']}"
    if plateau_kind and defaults.get("xxx_negative_additions"):
        xxx_negative = defaults["xxx_negative_additions"]
        if plateau_kind == "panties_aside":
            xxx_negative = ", ".join(
                term.strip() for term in xxx_negative.split(",")
                if term.strip() not in {"clothes", "underwear"}
            )
        negative = f"{negative}, {xxx_negative}"
    kind_negative = defaults.get("xxx_plateau_negative_additions", {}).get(
        plateau_kind, ""
    )
    if kind_negative:
        negative = f"{negative}, {kind_negative}"
    ids = []
    for value in scene["human"].values():
        ids.extend(item["id"] for item in value) if isinstance(value, list) else ids.append(value["id"])
    ids.extend(item["id"] for slot, item in outfit["garments"].items() if slot in visible_slots)
    for modifier_key in ("patterns", "textures"):
        ids.extend(
            item["id"] for slot, item in outfit.get(modifier_key, {}).items()
            if slot in visible_slots
        )
    ids.extend(scene[key]["id"] for key in ("pose", "action", "expression", "interior", "furniture", "mood", "photography_style", "editorial_role", "shot_size", "camera_angle", "framing", "focus_target"))
    if scene.get("explicit_recipe"):
        ids.append(scene["explicit_recipe"]["id"])
    if scene.get("prop"):
        ids.append(scene["prop"]["id"])
    ids.extend(item["id"] for item in scene.get("dependencies", []))
    return positive, negative, ids


def prompt_lint(scene: dict[str, Any], positive: str) -> list[str]:
    warnings: list[str] = []
    folded = positive.casefold()
    if folded.count("single subject") > 1:
        warnings.append("Subject identity is repeated")
    if scene["stage"]["level"] == "covered" and any(term in folded for term in ("fully nude", "exposed genitals")):
        warnings.append("Covered stage contains exposed-content wording")
    coverage_anchors = {
        "covered": "breasts and nipples fully covered by clothing",
        "lingerie": "breasts and nipples covered by the bra",
    }
    expected_anchor = coverage_anchors.get(scene["stage"]["level"])
    if expected_anchor and expected_anchor not in folded:
        warnings.append("Clothing coverage contract is missing")
    for slot in scene["stage"].get("visible_slots", []):
        garment = scene["outfit"]["garments"].get(slot)
        garment_prompt = scene.get("custom_values", {}).get(
            f"outfit.garments.{slot}"
        ) or (garment or {}).get("prompt", "")
        if garment_prompt and garment_prompt.casefold() not in folded:
            warnings.append(f"Visible garment is missing from prompt: {slot}")
    if scene.get("focus_target", {}).get("id") == "environment" and scene.get("shot_size", {}).get("id") in {"intimate_macro", "breast_closeup"}:
        warnings.append("Environmental focus conflicts with close-up framing")
    word_count = len(positive.split())
    if word_count > 500:
        warnings.append(
            f"Long prompt ({word_count} words); review it without automatic truncation"
        )
    return warnings


def model_signature(human: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in human.items():
        if isinstance(value, list):
            parts.extend(item["id"] for item in value)
        else:
            parts.append(value["id"])
    return "+".join(parts)


def model_description(
    human: dict[str, Any], custom: dict[str, str] | None = None
) -> str:
    custom = custom or {}
    keys = (
        "age", "ethnic_appearance", "skin_tone", "hair_length", "hair_style",
        "hair_color", "height", "body_frame", "breast_size",
    )
    parts = [custom.get(f"human.{key}") or human[key]["prompt"] for key in keys]
    summarized = {f"human.{key}" for key in keys}
    parts.extend(
        value for key, value in custom.items()
        if key.startswith("human.") and key not in summarized and value
    )
    return " · ".join(parts)


def photoshoot_signature(context: dict[str, Any]) -> tuple[Any, ...]:
    outfit = context["outfit"]
    garments = tuple(
        (
            slot,
            item["id"],
            outfit["colors"][slot]["id"],
            outfit.get("patterns", {}).get(slot, {}).get("id"),
            outfit.get("textures", {}).get(slot, {}).get("id"),
        )
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
        if kind == "intimate_closeup" and "panties" in template.get("slots", {}) and rng.random() < 0.5:
            kind = "panties_aside"
        result = copy.deepcopy(explicit_stage)
        result["id"] = f"{explicit_stage['id']}_{kind}"
        result["plateau_kind"] = kind
        result["visible_slots"] = (
            [slot for slot in ("panties", "legwear", "footwear", "accessories") if slot in template.get("slots", {})]
            if kind == "panties_aside" else []
        )
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
    if kind == "intimate_closeup" and "panties" in template.get("slots", {}) and rng.random() < 0.5:
        kind = "panties_aside"
    result = copy.deepcopy(explicit)
    result["id"] = f"{explicit['id']}_xxx_only_{kind}"
    result["plateau_kind"] = kind
    result["visible_slots"] = (
        [slot for slot in ("panties", "legwear", "footwear", "accessories") if slot in template.get("slots", {})]
        if kind == "panties_aside" else []
    )
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
    mapping = detect_node_mapping(workflow, include_fast=True)
    fast_mode = mapping["fast_mode"]
    workflow_path = resolve_path(db_path.parent, db["settings"]["workflow_file"])
    if workflow_path.exists() and not force:
        raise AppError(f"Workflow already exists: {workflow_path}. Use capture --force to replace it")
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Captured prompt_id: {prompt_id}")
    print(f"Workflow: {workflow_path}")
    print(f"Positive node: {mapping['positive_prompt']['node']}")
    print(f"Negative node: {mapping['negative_prompt']['node']}")
    print(f"Seed targets: {len(mapping['inference_seed'])}")
    print(f"Fast base sampler: {fast_mode['base_sampler']}")
    print(f"Fast output targets: {len(fast_mode['output_targets'])}")


def patch_workflow(workflow: dict[str, Any], mapping: dict[str, Any], positive: str, negative: str, seed: int) -> None:
    for map_key, value in (("positive_prompt", positive), ("negative_prompt", negative)):
        target = mapping[map_key]
        try:
            workflow[target["node"]]["inputs"][target["input"]] = value
        except KeyError as exc:
            raise AppError(f"Detected workflow target {map_key} is missing: {exc}") from exc
    for target in mapping["inference_seed"]:
        try:
            workflow[target["node"]]["inputs"][target["input"]] = seed
        except KeyError as exc:
            raise AppError(f"Workflow no longer matches inference seed mapping: missing {exc}") from exc


def lora_bypass_link(node: dict[str, Any], output_index: int) -> list[Any] | None:
    preferred = ("model", "model1", "base_model") if output_index == 0 else ("clip", "clip1")
    for input_name in preferred:
        value = node.get("inputs", {}).get(input_name)
        if isinstance(value, list) and len(value) == 2:
            return value
    return None


def prepare_fast_workflow(
    workflow: dict[str, Any], mapping: dict[str, Any]
) -> dict[str, Any]:
    fast_mapping = mapping.get("fast_mode")
    if not isinstance(fast_mapping, dict) or not fast_mapping.get("output_targets"):
        raise AppError("Fast workflow mapping was not detected")
    output_nodes = []
    for target in fast_mapping["output_targets"]:
        try:
            source = target["source"]
            if (
                not isinstance(source, list) or len(source) != 2
                or source[0] not in workflow
            ):
                raise KeyError(f"invalid source {source}")
            workflow[target["node"]]["inputs"][target["input"]] = source
            output_nodes.append(target["node"])
        except (KeyError, TypeError) as exc:
            raise AppError(
                f"Detected fast workflow target is no longer valid: {exc}"
            ) from exc

    # Disconnect LoRA nodes from every live model/CLIP chain before pruning.
    while True:
        changed = False
        for node in workflow.values():
            for input_name, value in list(node.get("inputs", {}).items()):
                if not (isinstance(value, list) and len(value) == 2):
                    continue
                source_node = workflow.get(str(value[0]))
                if not source_node or "lora" not in str(source_node.get("class_type", "")).lower():
                    continue
                replacement = lora_bypass_link(source_node, int(value[1]))
                if replacement is None:
                    raise AppError(
                        f"Cannot bypass LoRA node {value[0]} output {value[1]}; "
                        "use production mode or recapture a supported workflow"
                    )
                node["inputs"][input_name] = replacement
                changed = True
        if not changed:
            break

    required: set[str] = set()
    pending = list(output_nodes)
    while pending:
        node_id = pending.pop()
        if node_id in required:
            continue
        node = workflow.get(node_id)
        if node is None:
            raise AppError(f"Fast workflow references missing node: {node_id}")
        required.add(node_id)
        for value in node.get("inputs", {}).values():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in workflow:
                pending.append(str(value[0]))
    return {node_id: node for node_id, node in workflow.items() if node_id in required}


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


def load_workflow_runtime(
    db: dict[str, Any], db_path: Path, fast: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow_path = resolve_path(db_path.parent, db["settings"]["workflow_file"])
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"Workflow not found: {workflow_path}. Run capture first") from exc
    except json.JSONDecodeError as exc:
        raise AppError(f"Invalid workflow JSON in {workflow_path}: {exc}") from exc
    if not isinstance(workflow, dict) or not workflow:
        raise AppError(f"Workflow must be a non-empty JSON object: {workflow_path}")
    return workflow, detect_node_mapping(workflow, include_fast=fast)


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
    fast: bool,
    workflow_template: dict[str, Any],
    mapping: dict[str, Any],
) -> tuple[str, list[Path]]:
    workflow = copy.deepcopy(workflow_template)
    patch_workflow(workflow, mapping, positive, negative, seed)
    if fast:
        workflow = prepare_fast_workflow(workflow, mapping)
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
            if fast:
                label = f"fast_{label}"
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


def generate_preview_image(
    db: dict[str, Any],
    positive: str,
    negative: str,
    seed: int,
    workflow_template: dict[str, Any],
    mapping: dict[str, Any],
) -> tuple[str, bytes, str]:
    """Render one fast preview and keep its bytes out of the output directory."""
    workflow = copy.deepcopy(workflow_template)
    patch_workflow(workflow, mapping, positive, negative, seed)
    workflow = prepare_fast_workflow(workflow, mapping)
    for node in workflow.values():
        if node.get("class_type") == "SaveImage":
            node["class_type"] = "PreviewImage"
            node.get("inputs", {}).pop("filename_prefix", None)
    session, url, timeout = comfy_session(db)
    try:
        response = session.post(
            f"{url}/prompt",
            json={"prompt": workflow, "client_id": str(uuid.uuid4())},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise AppError(f"Could not queue ComfyUI preview workflow: {exc}") from exc
    if payload.get("node_errors"):
        raise AppError(
            f"ComfyUI rejected preview workflow: "
            f"{json.dumps(payload['node_errors'], ensure_ascii=False)}"
        )
    prompt_id = payload.get("prompt_id")
    if not prompt_id:
        raise AppError(f"ComfyUI response has no prompt_id: {payload}")
    outputs = wait_for_outputs(session, url, prompt_id, db["settings"])
    for node_output in outputs.values():
        for image in node_output.get("images", []):
            response = session.get(
                f"{url}/view",
                params={
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                },
                timeout=timeout,
            )
            response.raise_for_status()
            mime_type = (
                response.headers.get("Content-Type", "").split(";", 1)[0]
                or mimetypes.guess_type(image.get("filename", "preview.png"))[0]
                or "image/png"
            )
            return prompt_id, response.content, mime_type
    raise AppError(f"ComfyUI completed preview {prompt_id} but returned no images")


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
        avoid: dict[str, set[str]] = {}
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
            role_id = "role_peak" if shot_index == args.count - 1 and stage["level"] == "explicit" else {
                "covered": "role_establishing" if shot_index == 0 else "role_portrait",
                "lingerie": "role_development", "topless": "role_reveal", "nude": "role_nude_study",
                "explicit": "role_plateau",
            }.get(stage["level"], "portrait")
            try:
                scene = composer.resolve_scene(
                    context, stage, {"editorial_role": role_id}, avoid
                )
            except AppError:
                # Diversity is a preference; compatibility always wins.
                scene = composer.resolve_scene(
                    context, stage, {"editorial_role": role_id}
                )
            previous = storyboard[-1] if storyboard and storyboard[-1]["photoshoot_index"] == photoshoot_index else None
            previous_slots = set(previous["stage"].get("visible_slots", [])) if previous else set(stage.get("visible_slots", []))
            removed = previous_slots - set(stage.get("visible_slots", []))
            if removed:
                names = [
                    context["outfit"]["garments"][slot]["prompt"]
                    for slot in context["outfit"]["template"]["slots"]
                    if slot in removed and slot in context["outfit"]["garments"]
                ]
                if names:
                    scene["garment_transition"] = {
                        "id": "transition_" + "_".join(sorted(removed)),
                        "prompt": "deliberately removing " + " and ".join(names),
                        "slots": sorted(removed),
                    }
            for key in ("furniture", "pose", "action", "expression", "editorial_role", "shot_size", "camera_angle", "framing", "focus_target", "explicit_recipe"):
                item = scene.get(key)
                if item:
                    avoid.setdefault(key, set()).add(item["id"])
            inference_seed = args.inference_seed
            if args.inference_strategy == "random":
                inference_seed = secrets.randbelow(2**63)
            elif args.inference_strategy == "sequence":
                material = f"{args.inference_seed}:{photoshoot_index}:{shot_index}".encode()
                inference_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & (2**63 - 1)
            storyboard.append({
                "number": len(storyboard) + 1,
                "photoshoot_index": photoshoot_index,
                "shot_index": shot_index,
                "context": context,
                "stage": stage,
                "scene": scene,
                "inference_seed": inference_seed,
            })
    return storyboard



# ---------------------------------------------------------------------------
# Web application
# ---------------------------------------------------------------------------

import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

WEB_ROOT = Path(__file__).resolve().with_name("web")
MAX_STORYBOARDS = 20
MAX_JOBS = 40
MAX_PREVIEWS = 8


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_int(value: Any, name: str, minimum: int = 1, maximum: int = 500) -> int:
    if isinstance(value, bool):
        raise AppError(f"{name} must be a whole number")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(f"{name} must be a whole number") from exc
    if not minimum <= parsed <= maximum:
        raise AppError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _optional_seed(value: Any, name: str, maximum: int) -> int | None:
    if value in (None, ""):
        return None
    return _safe_int(value, name, 0, maximum)


def _safe_percent(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AppError(f"{name} must be a number") from exc
    if not 0 <= parsed <= 100:
        raise AppError(f"{name} must be between 0 and 100")
    return parsed


def parse_run_config(payload: dict[str, Any], db: dict[str, Any]) -> SimpleNamespace:
    mode = payload.get("mode", "photoshoot")
    if mode not in {"photoshoot", "random"}:
        raise AppError("mode must be photoshoot or random")
    count = _safe_int(payload.get("count", 12), "Images", 1, 200)
    photoshoots = _safe_int(payload.get("photoshoots", 1), "Photoshoots", 1, 50)
    if mode == "random":
        photoshoots = 1
    prompt_seed = _optional_seed(payload.get("prompt_seed"), "Prompt seed", 2**63 - 1)
    inference_seed = _optional_seed(payload.get("inference_seed"), "Inference seed", 2**64 - 1)
    inference_strategy = str(payload.get("inference_strategy", "sequence"))
    if inference_strategy not in {"random", "fixed", "sequence"}:
        raise AppError("Inference seed strategy must be random, fixed, or sequence")
    if inference_strategy in {"fixed", "sequence"} and inference_seed is None:
        inference_seed = secrets.randbelow(2**63)
    retry_count = _safe_int(
        payload.get("retry_count", db["settings"].get("render_retry_count", 2)),
        "Render retries", 0, 5,
    )
    xxx_only = bool(payload.get("xxx_only", False))
    progression = db["settings"].get("photoshoot_progression", {})
    nsfw = _safe_percent(
        payload.get("nsfw_percent", progression.get("nsfw_final_percent", 50)),
        "NSFW ending",
    )
    plateau = _safe_percent(
        payload.get("plateau_percent", progression.get("explicit_plateau_percent", 30)),
        "Explicit plateau",
    )
    if plateau > nsfw:
        raise AppError("The explicit plateau percentage cannot exceed the NSFW ending")
    return SimpleNamespace(
        mode=mode,
        count=count,
        photoshoots=photoshoots,
        prompt_seed=prompt_seed,
        inference_seed=inference_seed,
        inference_strategy=inference_strategy,
        retry_count=retry_count,
        xxx_only=xxx_only,
        nsfw_percent=None if xxx_only or mode == "random" else nsfw,
        plateau_percent=None if xxx_only or mode == "random" else plateau,
        fast=bool(payload.get("fast", False)),
    )


def _args_dict(args: SimpleNamespace) -> dict[str, Any]:
    return {key: value for key, value in vars(args).items() if key != "review_storyboard"}


def _outfit_summary(outfit: dict[str, Any]) -> list[str]:
    result = []
    for slot, garment in outfit["garments"].items():
        color = outfit.get("colors", {}).get(slot, {}).get("prompt")
        result.append(f"{color} {garment['prompt']}" if color else garment["prompt"])
    return result


def serialize_shot(db: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    scene = shot["scene"]
    context = shot["context"]
    positive, negative, selected_ids = compile_scene(db, scene)
    template = context["outfit"]["template"]
    return {
        "number": shot["number"],
        "photoshoot_index": shot["photoshoot_index"],
        "shot_index": shot["shot_index"],
        "stage": {
            "id": shot["stage"]["id"],
            "level": shot["stage"]["level"],
            "plateau_kind": shot["stage"].get("plateau_kind"),
            "manual": bool(shot.get("stage_manual", False)),
        },
        "inference_seed": shot["inference_seed"],
        "seed_manual": bool(shot.get("seed_manual", False)),
        "subject": model_description(context["human"], scene.get("custom_values")),
        "wardrobe": template.get("menu_label", template["id"]),
        "outfit": _outfit_summary(context["outfit"]),
        "location": context["interior"]["prompt"],
        "surface": scene["furniture"]["prompt"],
        "mood": context["mood"]["prompt"],
        "photography": context["photography_style"]["prompt"],
        "pose": {"id": scene["pose"]["id"], "prompt": scene["pose"]["prompt"]},
        "action": {"id": scene["action"]["id"], "prompt": scene["action"]["prompt"]},
        "expression": {"id": scene["expression"]["id"], "prompt": scene["expression"]["prompt"]},
        "editorial_role": {"id": scene["editorial_role"]["id"], "prompt": scene["editorial_role"]["prompt"]},
        "camera": " · ".join(scene[key]["prompt"] for key in ("shot_size", "camera_angle", "framing", "focus_target")),
        "shot_size": {"id": scene["shot_size"]["id"], "prompt": scene["shot_size"]["prompt"]},
        "camera_angle": {"id": scene["camera_angle"]["id"], "prompt": scene["camera_angle"]["prompt"]},
        "framing": {"id": scene["framing"]["id"], "prompt": scene["framing"]["prompt"]},
        "focus_target": {"id": scene["focus_target"]["id"], "prompt": scene["focus_target"]["prompt"]},
        "explicit_recipe": ({"id": scene["explicit_recipe"]["id"], "prompt": scene["explicit_recipe"]["prompt"]} if scene.get("explicit_recipe") else None),
        "intensity": scene["intensity"],
        "garment_transition": scene.get("garment_transition", {}).get("prompt"),
        "positive_prompt": positive,
        "negative_prompt": negative,
        "prompt_warnings": prompt_lint(scene, positive),
        "selected_ids": selected_ids,
    }


STORYBOARD_FORMAT = "valhalla-storyboard"
STORYBOARD_FORMAT_VERSION = 1


def database_fingerprint(db: dict[str, Any]) -> str:
    canonical = json.dumps(
        db, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def encode_database_refs(value: Any, index: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, dict):
        item_id = value.get("id")
        if isinstance(item_id, str) and index.get(item_id) == value:
            return {"$": item_id}
        return {key: encode_database_refs(item, index) for key, item in value.items()}
    if isinstance(value, list):
        return [encode_database_refs(item, index) for item in value]
    return value


def decode_database_refs(value: Any, index: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$"}:
            item_id = value["$"]
            if not isinstance(item_id, str) or item_id not in index:
                raise AppError(f"Storyboard references unknown database item: {item_id}")
            return index[item_id]
        return {key: decode_database_refs(item, index) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_database_refs(item, index) for item in value]
    return value


DIRECTOR_HUMAN_GROUPS = (
    ("Identity", ("age", "ethnic_appearance", "skin_tone")),
    ("Face", ("face_shape", "eye_shape", "eye_color", "eyebrows", "nose", "lips", "cheekbones", "jawline", "facial_accents")),
    ("Hair", ("hair_texture", "hair_length", "hair_style", "hair_color")),
    ("Body", ("height", "body_frame", "waist", "hips", "breast_size", "breast_shape", "areola_size", "areola_color", "nipple_size", "nipple_shape", "pubic_hair", "genital_appearance")),
    ("Styling", ("makeup", "manicure")),
)

DIRECTOR_LABELS = {
    "age": "Age", "ethnic_appearance": "Nationality / appearance", "skin_tone": "Skin tone",
    "face_shape": "Face shape", "eye_shape": "Eye shape", "eye_color": "Eye color",
    "eyebrows": "Eyebrows", "nose": "Nose", "lips": "Lips", "cheekbones": "Cheekbones",
    "jawline": "Jawline", "facial_accents": "Facial detail", "hair_texture": "Hair texture",
    "hair_length": "Hair length", "hair_style": "Hair style", "hair_color": "Hair color",
    "height": "Height", "body_frame": "Body type", "waist": "Waist", "hips": "Hips",
    "breast_size": "Breast size", "breast_shape": "Breast shape",
    "areola_size": "Areola size", "areola_color": "Areola color",
    "nipple_size": "Nipple size", "nipple_shape": "Nipple shape",
    "pubic_hair": "Pubic hair", "genital_appearance": "Vulva appearance",
    "makeup": "Makeup", "manicure": "Manicure",
}


def director_stage_options(shot: dict[str, Any], xxx_only: bool) -> list[dict[str, Any]]:
    template = shot["context"]["outfit"]["template"]
    effective = effective_photoshoot_stages(template)
    unique: dict[str, dict[str, Any]] = {}
    for stage in effective:
        unique[stage["id"]] = stage
    explicit_base = next(stage for stage in effective if stage["level"] == "explicit")
    kinds = ["provocative_rear", "intimate_closeup", "masturbation"]
    if "panties" in template.get("slots", {}):
        kinds.insert(2, "panties_aside")
    for kind in kinds:
        stage = copy.deepcopy(explicit_base)
        stage["id"] = f"{explicit_base['id']}_director_{kind}"
        stage["plateau_kind"] = kind
        stage["visible_slots"] = (
            [
                slot for slot in ("panties", "legwear", "footwear", "accessories")
                if slot in template.get("slots", {})
            ]
            if kind == "panties_aside" else []
        )
        stage["body_visibility"] = ["breasts", "nipples", "pubic_area", "genitals"]
        unique[stage["id"]] = stage
    return list(unique.values())


def director_option(item: dict[str, Any], current: str | None, defaults: set[str] | None = None) -> dict[str, Any]:
    return {
        "id": item["id"],
        "label": item.get("menu_label", item.get("prompt", item["id"])),
        "prompt": item.get("prompt", ""),
        "current": item["id"] == current,
        "default": item["id"] in (defaults or set()),
    }


def director_required_overrides(
    db: dict[str, Any], category: str, item: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    category_by_id = {
        candidate["id"]: candidate_category
        for candidate_category, values in db["human_model_parts"].items()
        for candidate in values
    }
    enabled = [
        candidate
        for values in db["human_model_parts"].values()
        for candidate in values
        if not candidate.get("disabled", False)
    ]
    selected = {category: item}
    for _ in range(len(HUMAN_SELECTION_ORDER) * 3):
        available = set().union(*(tags(candidate) for candidate in selected.values()))
        missing_groups: list[set[str]] = []
        for candidate in selected.values():
            required = set(candidate.get("requires_tags", [])) - available
            missing_groups.extend({tag} for tag in required)
            required_any = set(candidate.get("requires_any_tags", []))
            if required_any and not required_any & available:
                missing_groups.append(required_any)
        if not missing_groups:
            return selected
        requirement = missing_groups[0]
        providers = [
            candidate for candidate in enabled
            if tags(candidate) & requirement
            and category_by_id[candidate["id"]] != category
        ]
        if not providers:
            raise AppError(
                f"No human trait provides required tags {sorted(requirement)}"
            )
        provider = providers[0]
        selected[category_by_id[provider["id"]]] = provider
    raise AppError(f"Could not resolve prerequisites for {item['id']}")


class WebState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.storyboards: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.previews: dict[str, dict[str, Any]] = {}

    def trim(self, mapping: dict[str, Any], maximum: int) -> None:
        while len(mapping) > maximum:
            mapping.pop(next(iter(mapping)))

    def create_storyboard(self, payload: dict[str, Any]) -> dict[str, Any]:
        db, _ = load_database()
        args = parse_run_config(payload, db)
        prompt_seed = args.prompt_seed if args.prompt_seed is not None else secrets.randbits(63)
        args.prompt_seed = prompt_seed
        rng = random.Random(prompt_seed)
        composer = Composer(db, rng)
        progression = db["settings"].get("photoshoot_progression", {})
        nsfw = float(progression.get("nsfw_final_percent", 50) if args.nsfw_percent is None else args.nsfw_percent)
        plateau = float(progression.get("explicit_plateau_percent", 30) if args.plateau_percent is None else args.plateau_percent)
        shots = build_storyboard(args, db, composer, rng, nsfw, plateau)
        storyboard_id = uuid.uuid4().hex
        record = {
            "id": storyboard_id,
            "created_at": _iso_now(),
            "db": db,
            "args": args,
            "composer": composer,
            "rng": rng,
            "shots": shots,
        }
        with self.lock:
            self.storyboards[storyboard_id] = record
            self.trim(self.storyboards, MAX_STORYBOARDS)
        return self.storyboard_payload(record)

    def storyboard_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        args = record["args"]
        scenes = [shot["scene"] for shot in record["shots"]]
        comparisons = 0
        changes = 0
        for previous, current in zip(scenes, scenes[1:]):
            for key in ("pose", "action", "furniture", "shot_size", "camera_angle", "framing", "focus_target"):
                comparisons += 1
                changes += previous[key]["id"] != current[key]["id"]
        return {
            "id": record["id"],
            "created_at": record["created_at"],
            "config": _args_dict(args),
            "total": len(record["shots"]),
            "diversity": round(changes * 100 / comparisons) if comparisons else 100,
            "shots": [serialize_shot(record["db"], shot) for shot in record["shots"]],
        }

    def get_storyboard(self, storyboard_id: str) -> dict[str, Any]:
        with self.lock:
            record = self.storyboards.get(storyboard_id)
        if record is None:
            raise AppError("Storyboard not found or expired")
        return record


    @staticmethod
    def _apply_director_customs(shot: dict[str, Any], scene: dict[str, Any], context: dict[str, Any]) -> None:
        merged = dict(context.get("custom_values", {}))
        merged.update(shot.get("custom_values", {}))
        if merged:
            scene["custom_values"] = merged
        else:
            scene.pop("custom_values", None)

    def director_payload(self, storyboard_id: str, number: int = 1) -> dict[str, Any]:
        record = self.get_storyboard(storyboard_id)
        if not 1 <= number <= len(record["shots"]):
            raise AppError("Shot number is out of range")
        shot = record["shots"][number - 1]
        db = record["db"]
        context = shot["context"]
        human_defaults = db["settings"].get("human_defaults", {}).get("pools", {})
        groups = []
        for group_name, categories in DIRECTOR_HUMAN_GROUPS:
            fields = []
            for category in categories:
                values = [
                    item for item in db["human_model_parts"][category]
                    if not item.get("disabled", False)
                ]
                selected = context["human"][category]
                if isinstance(selected, list):
                    current = selected[0]["id"] if selected else ""
                    options = [{
                        "id": "", "label": "None", "prompt": "",
                        "current": not selected, "default": False,
                    }]
                else:
                    current = selected["id"]
                    options = []
                options.extend(
                    director_option(item, current, set(human_defaults.get(category, [])))
                    for item in values
                )
                fields.append({
                    "key": f"human.{category}",
                    "label": DIRECTOR_LABELS[category],
                    "scope": "set",
                    "value": current,
                    "options": options,
                })
            groups.append({"id": group_name.lower(), "label": group_name, "fields": fields})

        template = context["outfit"]["template"]
        wardrobe_fields = [{
            "key": "outfit.template",
            "label": "Outfit recipe",
            "scope": "set",
            "value": template["id"],
            "options": [
                director_option(
                    item, template["id"],
                    {
                        candidate["id"] for candidate in db["outfit_templates"]
                        if candidate["wardrobe_category"] in set(
                            db["settings"]["scene_defaults"]["wardrobe_categories"]
                        )
                    },
                )
                for item in db["outfit_templates"] if not item.get("disabled", False)
            ],
        }]
        for slot, rule in template["slots"].items():
            garment = context["outfit"]["garments"].get(slot)
            candidates = [
                item for item in db["garments"][rule["catalog"]]
                if not item.get("disabled", False)
                and set(rule.get("required_tags", [])).issubset(tags(item))
                and (
                    not rule.get("required_any_tags")
                    or set(rule["required_any_tags"]) & tags(item)
                )
                and not set(rule.get("excludes_tags", [])) & tags(item)
                and set(item.get("requires_environment_tags", [])).issubset(tags(context["interior"]))
                and not set(item.get("excludes_environment_tags", [])) & tags(context["interior"])
            ]
            garment_options = [
                director_option(item, garment["id"] if garment else None)
                for item in candidates
            ]
            if not rule.get("required", False):
                garment_options.insert(0, {
                    "id": "", "label": "None", "prompt": "",
                    "current": garment is None, "default": garment is None,
                })
            wardrobe_fields.append({
                "key": f"outfit.garments.{slot}",
                "label": slot.replace("_", " ").title(),
                "scope": "set",
                "value": garment["id"] if garment else "",
                "options": garment_options,
            })
            if not garment:
                continue
            color = context["outfit"]["colors"][slot]
            allowed_colors = set(garment.get("allowed_colors") or [item["id"] for item in db["colors"]])
            wardrobe_fields.append({
                "key": f"outfit.colors.{slot}",
                "label": f"{slot.replace('_', ' ').title()} color",
                "scope": "set",
                "value": color["id"],
                "options": [
                    director_option(item, color["id"]) for item in db["colors"]
                    if item["id"] in allowed_colors and not item.get("disabled", False)
                ],
            })
            for section, key, label in (
                ("patterns", "patterns", "Pattern"),
                ("fabric_textures", "textures", "Texture"),
            ):
                current_item = context["outfit"].get(key, {}).get(slot)
                modifiers = [
                    item for item in db[section]
                    if not item.get("disabled", False)
                    and garment["id"] in item["allowed_garment_ids"]
                ]
                wardrobe_fields.append({
                    "key": f"outfit.{key}.{slot}",
                    "label": f"{slot.replace('_', ' ').title()} {label.lower()}",
                    "scope": "set",
                    "value": current_item["id"] if current_item else "",
                    "options": [{
                        "id": "", "label": "None / plain", "prompt": "",
                        "current": current_item is None, "default": True,
                    }] + [
                        director_option(item, current_item["id"] if current_item else None)
                        for item in modifiers
                    ],
                })
        groups.append({"id": "wardrobe", "label": "Wardrobe", "fields": wardrobe_fields})

        scene_defaults = db["settings"]["scene_defaults"].get("pools", {})
        scene_fields = []
        for key, section, label in (
            ("interior", "interiors", "Location"),
            ("mood", "moods", "Mood"),
            ("photography_style", "photography_styles", "Render style"),
        ):
            current_item = context[key]
            values = [item for item in db[section] if not item.get("disabled", False)]
            if key == "furniture":
                values = [
                    item for item in values
                    if compatible_with_requirements(item, tags(context["interior"]))
                ]
            scene_fields.append({
                "key": f"scene.{key}",
                "label": label,
                "scope": "set",
                "value": current_item["id"],
                "options": [
                    director_option(item, current_item["id"], set(scene_defaults.get(section, [])))
                    for item in values
                ],
            })
        groups.append({"id": "scene", "label": "Scene & treatment", "fields": scene_fields})

        camera_fields = []
        for key, section, label in (
            ("furniture", "furniture", "Surface / support"),
            ("editorial_role", "editorial_roles", "Editorial role"),
            ("shot_size", "shot_sizes", "Shot size"),
            ("camera_angle", "camera_angles", "Camera angle"),
            ("framing", "framings", "Framing"),
            ("focus_target", "focus_targets", "Focus target"),
        ):
            current_item = shot["scene"][key]
            camera_tags = (
                set(shot["stage"].get("body_visibility", []))
                | set(shot["stage"].get("visible_slots", []))
                | {shot["stage"]["level"]}
                | tags(shot["scene"]["interior"])
                | tags(shot["scene"]["furniture"])
                | tags(shot["scene"]["pose"])
                | tags(shot["scene"]["action"])
                | tags(shot["scene"]["editorial_role"])
                | tags(shot["scene"]["shot_size"])
                | tags(shot["scene"]["camera_angle"])
                | tags(shot["scene"]["framing"])
                | tags(shot["scene"]["focus_target"])
            )
            compatible = [
                item for item in db[section]
                if not item.get("disabled", False)
                and (
                    key == "furniture"
                    and compatible_with_requirements(item, tags(context["interior"]))
                    or key == "editorial_role"
                    or key not in {"furniture", "editorial_role"}
                    and shot["stage"]["level"] in item.get("allowed_levels", [shot["stage"]["level"]])
                    and compatible_with_requirements(item, camera_tags)
                )
            ]
            camera_fields.append({
                "key": f"shot.{key}", "label": label, "scope": "shot",
                "value": current_item["id"],
                "options": [director_option(item, current_item["id"]) for item in compatible],
            })
        compatible_recipes = [
            item for item in db["explicit_recipes"]
            if not item.get("disabled", False)
            and (
                not shot["stage"].get("plateau_kind")
                or item.get("plateau_kind") == shot["stage"].get("plateau_kind")
            )
        ]
        if shot["stage"]["level"] == "explicit" and compatible_recipes:
            current_recipe = shot["scene"].get("explicit_recipe")
            camera_fields.append({
                "key": "shot.explicit_recipe", "label": "Explicit recipe", "scope": "shot",
                "value": current_recipe["id"] if current_recipe else "",
                "options": [
                    director_option(item, current_recipe["id"] if current_recipe else None)
                    for item in compatible_recipes
                ],
            })
        camera_fields.append({
            "key": "shot.intensity", "label": "Visual intensity", "scope": "shot",
            "value": shot["scene"]["intensity"],
            "options": [
                {
                    "id": level, "label": level.title(),
                    "prompt": f"{level} visual intensity",
                    "current": level == shot["scene"]["intensity"],
                    "default": level == shot["scene"]["intensity"],
                }
                for level in ("fashion", "sensual", "erotic", "nude", "explicit", "peak")
            ],
        })
        groups.append({"id": "camera", "label": "Camera & editorial", "fields": camera_fields})

        direction_fields = []
        stages = director_stage_options(shot, record["args"].xxx_only)
        direction_fields.append({
            "key": "shot.stage", "label": "Stage / content", "scope": "shot",
            "value": shot["stage"]["id"],
            "options": [
                {
                    "id": item["id"],
                    "label": (item.get("plateau_kind") or item["level"]).replace("_", " ").title(),
                    "prompt": item["level"], "current": item["id"] == shot["stage"]["id"],
                    "default": item["id"] == shot["stage"]["id"],
                } for item in stages
            ],
        })
        for key, section, label in (
            ("pose", "poses", "Pose"),
            ("action", "actions", "Action"),
            ("expression", "expressions", "Expression"),
        ):
            current_item = shot["scene"][key]
            stage = shot["stage"]
            available = (
                set(stage.get("body_visibility", [])) | set(stage.get("visible_slots", []))
                | {stage["level"]} | tags(shot["scene"]["furniture"])
                | tags(shot["scene"]["interior"])
            )
            compatible = [item for item in db[section] if not item.get("disabled", False)]
            if key == "pose":
                compatible = [
                    item for item in compatible
                    if stage["level"] in item.get("allowed_levels", [stage["level"]])
                    and compatible_with_requirements(item, available)
                ]
                if stage["level"] == "explicit":
                    compatible = [item for item in compatible if "explicit_pose" in tags(item)]
                elif stage["level"] in {"topless", "nude"}:
                    compatible = [item for item in compatible if tags(item) & {"erotic_pose", "topless_pose", "nude_pose", "open_legs"}]
                plateau = stage.get("plateau_kind")
                plateau_tags = {
                    "provocative_rear": {"provocative_rear"},
                    "intimate_closeup": {"intimate_closeup"},
                    "masturbation": {"masturbation_pose"},
                    "panties_aside": {"open_legs"},
                }.get(plateau)
                if plateau_tags:
                    compatible = [item for item in compatible if tags(item) & plateau_tags]
                recipe = shot["scene"].get("explicit_recipe")
                if recipe and recipe.get("pose_tags"):
                    recipe_tags = set(recipe["pose_tags"])
                    compatible = [item for item in compatible if tags(item) & recipe_tags]
            elif key == "action":
                action_tags = available | tags(shot["scene"]["pose"])
                compatible = [
                    item for item in compatible
                    if stage["level"] in item.get("allowed_levels", [stage["level"]])
                    and compatible_with_requirements(item, action_tags)
                ]
                if stage["level"] == "explicit":
                    compatible = [item for item in compatible if "explicit_action" in tags(item)]
                elif stage["level"] in {"topless", "nude"}:
                    compatible = [item for item in compatible if tags(item) & {"erotic_action", "undressing_action"}]
                plateau = stage.get("plateau_kind")
                plateau_tags = {
                    "provocative_rear": {"provocative_action"},
                    "intimate_closeup": {"closeup_action"},
                    "masturbation": {"masturbation_action"},
                    "panties_aside": {"panties_aside_action"},
                }.get(plateau)
                if plateau_tags:
                    compatible = [item for item in compatible if tags(item) & plateau_tags]
                recipe = shot["scene"].get("explicit_recipe")
                if recipe and recipe.get("action_tags"):
                    recipe_tags = set(recipe["action_tags"])
                    compatible = [item for item in compatible if tags(item) & recipe_tags]
            else:
                required = set(shot["scene"]["action"].get("requires_expression_tags", []))
                if required:
                    compatible = [item for item in compatible if required.issubset(tags(item))]
            direction_fields.append({
                "key": f"shot.{key}", "label": label, "scope": "shot",
                "value": current_item["id"],
                "options": [director_option(item, current_item["id"]) for item in compatible],
            })
        direction_by_key = {field["key"]: field for field in direction_fields}
        direction_by_key["shot.stage"]["compatibility"] = {
            "poses": len(direction_by_key["shot.pose"]["options"]),
            "actions": len(direction_by_key["shot.action"]["options"]),
            "expressions": len(direction_by_key["shot.expression"]["options"]),
        }
        groups.append({"id": "direction", "label": "Shot direction", "fields": direction_fields})
        custom_values = dict(context.get("custom_values", {}))
        custom_values.update(shot.get("custom_values", {}))
        for group in groups:
            for director_field in group["fields"]:
                director_field["custom"] = custom_values.get(director_field["key"], "")
        return {
            "storyboard_id": storyboard_id,
            "shot": number,
            "total": len(record["shots"]),
            "photoshoot_index": shot["photoshoot_index"],
            "shot_index": shot["shot_index"],
            "summary": serialize_shot(db, shot),
            "groups": groups,
        }

    def _replace_director_context(
        self,
        record: dict[str, Any],
        shot_position: int,
        context: dict[str, Any],
        recalculate_stages: bool = False,
        preserve_photography: bool = False,
    ) -> None:
        args = record["args"]
        db = record["db"]
        source = record["shots"][shot_position]
        indices = [shot_position] if args.mode == "random" else [
            index for index, shot in enumerate(record["shots"])
            if shot["photoshoot_index"] == source["photoshoot_index"]
        ]
        progression = db["settings"].get("photoshoot_progression", {})
        nsfw = float(progression.get("nsfw_final_percent", 50) if args.nsfw_percent is None else args.nsfw_percent)
        plateau = float(progression.get("explicit_plateau_percent", 30) if args.plateau_percent is None else args.plateau_percent)
        replacements = []
        for index in indices:
            old = record["shots"][index]
            stage = old["stage"]
            if recalculate_stages:
                stage = (
                    xxx_only_stage(context["outfit"]["template"], old["shot_index"], args.count, args.mode, record["rng"])
                    if args.xxx_only else stage_for_index(
                        context["outfit"]["template"], old["shot_index"], args.count,
                        args.mode, record["rng"], nsfw, plateau,
                    )
                )
            scene = record["composer"].resolve_scene(context, stage)
            self._apply_director_customs(old, scene, context)
            if preserve_photography:
                scene["photography_style"] = context["photography_style"]
                scene["dependencies"] = record["composer"].resolve_dependencies(scene)
                record["composer"].validate_scene_rules(scene)
            replacements.append((index, stage, scene))
        for index, stage, scene in replacements:
            record["shots"][index]["context"] = context
            record["shots"][index]["stage"] = stage
            record["shots"][index]["scene"] = scene
            if recalculate_stages:
                record["shots"][index]["stage_manual"] = False

    def update_director(self, storyboard_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.get_storyboard(storyboard_id)
        with self.lock:
            active = any(
                job["storyboard_id"] == storyboard_id
                and job["status"] in {"queued", "running"}
                for job in self.jobs.values()
            )
        if active:
            raise AppError("Director editing is unavailable while this storyboard is rendering")
        number = _safe_int(payload.get("shot"), "Shot", 1, len(record["shots"]))
        field = str(payload.get("field", ""))
        value = str(payload.get("value", ""))
        position = number - 1
        shot = record["shots"][position]
        db = record["db"]
        index = {item["id"]: item for item in iter_content_items(db)}
        context = copy.deepcopy(shot["context"])
        recalculate_stages = False
        preserve_photography = False
        clear_custom = payload.get("clear_custom") is True
        if clear_custom and not field.startswith("shot."):
            context.setdefault("custom_values", {}).pop(field, None)

        if "custom_value" in payload:
            custom_value = payload.get("custom_value")
            if not isinstance(custom_value, str):
                raise AppError("Custom value must be text")
            custom_value = custom_value.strip()
            if len(custom_value) > 600:
                raise AppError("Custom value cannot exceed 600 characters")
            parts = field.split(".")
            valid = (
                (len(parts) == 2 and parts[0] == "human" and parts[1] in db["human_model_parts"])
                or field == "outfit.template"
                or (
                    len(parts) == 3 and parts[0] == "outfit"
                    and parts[1] in {"garments", "colors", "patterns", "textures"}
                    and parts[2] in context["outfit"]["template"]["slots"]
                )
                or field in {"scene.interior", "scene.furniture", "scene.mood", "scene.photography_style"}
                or field in {
                    "shot.stage", "shot.pose", "shot.action", "shot.expression",
                    "shot.furniture", "shot.editorial_role", "shot.shot_size",
                    "shot.camera_angle", "shot.framing", "shot.focus_target",
                    "shot.explicit_recipe", "shot.intensity", "shot.garment_transition",
                }
            )
            if not valid:
                raise AppError("Unknown Director field")
            if not field.startswith("shot."):
                custom_values = context.setdefault("custom_values", {})
                if custom_value:
                    custom_values[field] = custom_value
                else:
                    custom_values.pop(field, None)
                self._replace_director_context(record, position, context)
            else:
                custom_values = shot.setdefault("custom_values", {})
                if custom_value:
                    custom_values[field] = custom_value
                else:
                    custom_values.pop(field, None)
                self._apply_director_customs(shot, shot["scene"], shot["context"])
            return self.director_payload(storyboard_id, number)

        if field.startswith("remix."):
            target = field.split(".", 1)[1]
            if target == "shot":
                shot["scene"] = record["composer"].resolve_scene(
                    context, shot["stage"]
                )
                self._apply_director_customs(shot, shot["scene"], context)
                return self.director_payload(storyboard_id, number)
            if target == "subject":
                context["human"] = record["composer"].choose_human(
                    use_default_ethnicity=False, use_human_defaults=False
                )
            elif target == "wardrobe":
                context["outfit"] = record["composer"].choose_outfit(
                    context["outfit"]["template"], context["interior"]
                )
            elif target == "scene":
                interiors = [
                    item for item in db["interiors"]
                    if not item.get("disabled", False)
                ]
                context["interior"] = weighted_choice(record["rng"], interiors)
                furniture = [
                    item for item in db["furniture"]
                    if not item.get("disabled", False)
                    and compatible_with_requirements(item, tags(context["interior"]))
                ]
                context["furniture"] = weighted_choice(record["rng"], furniture)
                context["mood"] = weighted_choice(
                    record["rng"],
                    [item for item in db["moods"] if not item.get("disabled", False)],
                )
                context["photography_style"] = weighted_choice(
                    record["rng"],
                    [
                        item for item in db["photography_styles"]
                        if not item.get("disabled", False)
                    ],
                )
                try:
                    record["composer"].validate_outfit_environment(
                        context["outfit"], context["interior"]
                    )
                except AppError:
                    context["outfit"] = record["composer"].choose_outfit(
                        context["outfit"]["template"], context["interior"]
                    )
                preserve_photography = True
            else:
                raise AppError("Unknown remix action")
        elif field.startswith("human."):
            category = field.split(".", 1)[1]
            if category not in db["human_model_parts"]:
                raise AppError("Unknown human trait")
            if category == "facial_accents":
                if value:
                    item = index.get(value)
                    if item not in db["human_model_parts"][category]:
                        raise AppError("Unknown facial detail")
                    context["human"][category] = [item]
                else:
                    context["human"][category] = []
            else:
                item = index.get(value)
                if item not in db["human_model_parts"][category]:
                    raise AppError("Unknown human trait value")
                overrides = {
                    key: selected for key, selected in context["human"].items()
                    if key != "facial_accents" and isinstance(selected, dict)
                }
                overrides[category] = item
                try:
                    human = record["composer"].choose_human(
                        overrides, use_human_defaults=False
                    )
                except AppError:
                    required_overrides = director_required_overrides(
                        db, category, item
                    )
                    human = record["composer"].choose_human(
                        required_overrides, use_human_defaults=False
                    )
                human["facial_accents"] = [
                    accent for accent in context["human"].get("facial_accents", [])
                    if compatible_with_requirements(
                        accent, set().union(*(tags(part) for part in human.values() if isinstance(part, dict)))
                    )
                ]
                context["human"] = human
        elif field == "outfit.template":
            template = index.get(value)
            if template not in db["outfit_templates"]:
                raise AppError("Unknown outfit recipe")
            context["outfit"] = record["composer"].choose_outfit(template, context["interior"])
            recalculate_stages = True
        elif field.startswith("outfit."):
            _, section, slot = field.split(".", 2)
            outfit = context["outfit"]
            if slot not in outfit["template"]["slots"]:
                raise AppError("This outfit does not define that slot")
            if section == "garments":
                rule = outfit["template"]["slots"][slot]
                if not value:
                    if rule.get("required", False):
                        raise AppError("A required garment cannot be removed")
                    outfit["garments"].pop(slot, None)
                    outfit["colors"].pop(slot, None)
                    outfit.get("patterns", {}).pop(slot, None)
                    outfit.get("textures", {}).pop(slot, None)
                else:
                    garment = index.get(value)
                    required_tags = set(rule.get("required_tags", []))
                    required_any = set(rule.get("required_any_tags", []))
                    excluded_tags = set(rule.get("excludes_tags", []))
                    if (
                        garment not in db["garments"][rule["catalog"]]
                        or not required_tags.issubset(tags(garment))
                        or (required_any and not required_any & tags(garment))
                        or excluded_tags & tags(garment)
                    ):
                        raise AppError("Garment is incompatible with this outfit slot")
                    outfit["garments"][slot] = garment
                    allowed = [
                        color for color in db["colors"]
                        if color["id"] in set(
                            garment.get("allowed_colors")
                            or [item["id"] for item in db["colors"]]
                        )
                    ]
                    if outfit["colors"].get(slot) not in allowed:
                        outfit["colors"][slot] = allowed[0]
                    for modifier_key in ("patterns", "textures"):
                        modifier = outfit.get(modifier_key, {}).get(slot)
                        if modifier and garment["id"] not in modifier["allowed_garment_ids"]:
                            outfit[modifier_key].pop(slot, None)
            elif section == "colors":
                color = index.get(value)
                garment = outfit["garments"][slot]
                allowed_ids = set(garment.get("allowed_colors") or [item["id"] for item in db["colors"]])
                if color not in db["colors"] or color["id"] not in allowed_ids:
                    raise AppError("Color is incompatible with this garment")
                outfit["colors"][slot] = color
            elif section in {"patterns", "textures"}:
                source = "patterns" if section == "patterns" else "fabric_textures"
                if not value:
                    outfit.setdefault(section, {}).pop(slot, None)
                else:
                    modifier = index.get(value)
                    if modifier not in db[source] or outfit["garments"][slot]["id"] not in modifier["allowed_garment_ids"]:
                        raise AppError("Modifier is incompatible with this garment")
                    outfit.setdefault(section, {})[slot] = modifier
            else:
                raise AppError("Unknown wardrobe field")
            record["composer"].validate_outfit_environment(outfit, context["interior"])
        elif field.startswith("scene."):
            key = field.split(".", 1)[1]
            sections = {
                "interior": "interiors", "furniture": "furniture",
                "mood": "moods", "photography_style": "photography_styles",
            }
            if key not in sections or index.get(value) not in db[sections[key]]:
                raise AppError("Unknown scene selection")
            context[key] = index[value]
            if key == "interior":
                furniture = [
                    item for item in db["furniture"]
                    if not item.get("disabled", False)
                    and compatible_with_requirements(item, tags(context["interior"]))
                ]
                if context["furniture"] not in furniture:
                    context["furniture"] = weighted_choice(record["rng"], furniture)
                try:
                    record["composer"].validate_outfit_environment(context["outfit"], context["interior"])
                except AppError:
                    context["outfit"] = record["composer"].choose_outfit(
                        context["outfit"]["template"], context["interior"]
                    )
            preserve_photography = key == "photography_style"
        elif field.startswith("shot."):
            key = field.split(".", 1)[1]
            if key == "stage":
                stages = director_stage_options(shot, record["args"].xxx_only)
                stage = next((item for item in stages if item["id"] == value), None)
                if stage is None:
                    raise AppError("Unknown stage")
                scene = record["composer"].resolve_scene(context, stage)
                shot["stage"], shot["scene"] = stage, scene
                shot["stage_manual"] = True
                if clear_custom:
                    shot.setdefault("custom_values", {}).pop(field, None)
                self._apply_director_customs(shot, shot["scene"], context)
            elif key == "intensity":
                if value not in {"fashion", "sensual", "erotic", "nude", "explicit", "peak"}:
                    raise AppError("Unknown intensity")
                shot["scene"]["intensity"] = value
                if clear_custom:
                    shot.setdefault("custom_values", {}).pop(field, None)
                self._apply_director_customs(shot, shot["scene"], context)
            elif key in {
                "pose", "action", "expression", "furniture", "editorial_role",
                "shot_size", "camera_angle", "framing", "focus_target", "explicit_recipe",
            }:
                if value not in index:
                    raise AppError("Unknown direction")
                preserved = {
                    candidate: shot["scene"][candidate]["id"]
                    for candidate in (
                        "pose", "action", "expression", "furniture", "editorial_role",
                        "shot_size", "camera_angle", "framing", "focus_target", "explicit_recipe",
                    )
                    if candidate != key and shot["scene"].get(candidate)
                }
                preserved[key] = value
                try:
                    scene = record["composer"].resolve_scene(
                        context, shot["stage"], preserved
                    )
                except AppError:
                    scene = record["composer"].resolve_scene(
                        context, shot["stage"], {key: value}
                    )
                shot["scene"] = scene
                if clear_custom:
                    shot.setdefault("custom_values", {}).pop(field, None)
                self._apply_director_customs(shot, shot["scene"], context)
            else:
                raise AppError("Unknown shot field")
            return self.director_payload(storyboard_id, number)
        else:
            raise AppError("Unknown Director field")

        self._replace_director_context(
            record, position, context, recalculate_stages, preserve_photography
        )
        return self.director_payload(storyboard_id, number)

    def export_storyboard(self, storyboard_id: str) -> dict[str, Any]:
        record = self.get_storyboard(storyboard_id)
        db = record["db"]
        index = {item["id"]: item for item in iter_content_items(db)}
        shots = []
        for shot in record["shots"]:
            context = shot["context"]
            scene_delta = {
                key: value for key, value in shot["scene"].items()
                if key not in context or context[key] != value
            }
            shots.append({
                "n": shot["number"],
                "p": shot["photoshoot_index"],
                "s": shot["shot_index"],
                "seed": shot["inference_seed"],
                "stage": encode_database_refs(shot["stage"], index),
                "stage_manual": bool(shot.get("stage_manual", False)),
                "context": encode_database_refs(context, index),
                "scene": encode_database_refs(scene_delta, index),
                "custom": shot.get("custom_values", {}),
            })
        return {
            "format": STORYBOARD_FORMAT,
            "version": STORYBOARD_FORMAT_VERSION,
            "database": database_fingerprint(db),
            "created_at": record["created_at"],
            "config": _args_dict(record["args"]),
            "shots": shots,
        }

    def import_storyboard(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("format") != STORYBOARD_FORMAT:
            if all(key in payload for key in ("id", "config", "shots")):
                raise AppError(
                    "This file is a UI storyboard snapshot, not an export file. "
                    "Export the storyboard again with the updated server."
                )
            raise AppError("This is not a Project Valhalla storyboard export file")
        if payload.get("version") != STORYBOARD_FORMAT_VERSION:
            raise AppError("Unsupported storyboard format version")
        db, _ = load_database()
        if payload.get("database") != database_fingerprint(db):
            raise AppError(
                "Storyboard belongs to a different database version. "
                "Restore its matching database.json before importing it."
            )
        config = payload.get("config")
        compact_shots = payload.get("shots")
        if not isinstance(config, dict) or not isinstance(compact_shots, list):
            raise AppError("Storyboard file is missing its configuration or shots")
        if not compact_shots or len(compact_shots) > 10_000:
            raise AppError("Storyboard must contain between 1 and 10000 shots")
        args = parse_run_config(
            {key: value for key, value in config.items() if value is not None}, db
        )
        if args.prompt_seed is None:
            raise AppError("Storyboard file is missing its prompt seed")
        expected_total = args.count * (
            args.photoshoots if args.mode == "photoshoot" else 1
        )
        if len(compact_shots) != expected_total:
            raise AppError("Storyboard shot count does not match its configuration")
        rng = random.Random(args.prompt_seed)
        composer = Composer(db, rng)
        index = {item["id"]: item for item in iter_content_items(db)}
        shots = []
        for position, compact in enumerate(compact_shots, 1):
            if not isinstance(compact, dict):
                raise AppError(f"Storyboard shot {position} is invalid")
            context = decode_database_refs(compact.get("context"), index)
            stage = decode_database_refs(compact.get("stage"), index)
            scene_delta = decode_database_refs(compact.get("scene"), index)
            if not all(isinstance(value, dict) for value in (context, stage, scene_delta)):
                raise AppError(f"Storyboard shot {position} is incomplete")
            scene = dict(context)
            scene.update(scene_delta)
            custom_values = compact.get("custom", {})
            if not isinstance(custom_values, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in custom_values.items()
            ):
                raise AppError(f"Storyboard shot {position} has invalid custom values")
            shot = {
                "number": _safe_int(compact.get("n"), "Shot number", 1, 10_000),
                "photoshoot_index": _safe_int(
                    compact.get("p"), "Photoshoot index", 0, 10_000
                ),
                "shot_index": _safe_int(
                    compact.get("s"), "Shot index", 0, 10_000
                ),
                "inference_seed": _safe_int(
                    compact.get("seed"), "Inference seed", 0, 2**64 - 1
                ),
                "context": context,
                "stage": stage,
                "stage_manual": bool(compact.get("stage_manual", False)),
                "scene": scene,
                "custom_values": custom_values,
            }
            self._apply_director_customs(shot, scene, context)
            if shot["number"] != position:
                raise AppError("Storyboard shot numbers must be consecutive")
            serialize_shot(db, shot)
            shots.append(shot)
        storyboard_id = uuid.uuid4().hex
        record = {
            "id": storyboard_id,
            "created_at": str(payload.get("created_at") or _iso_now()),
            "db": db,
            "args": args,
            "composer": composer,
            "rng": rng,
            "shots": shots,
        }
        with self.lock:
            self.storyboards[storyboard_id] = record
            self.trim(self.storyboards, MAX_STORYBOARDS)
        return self.storyboard_payload(record)

    def reroll_shot(self, storyboard_id: str, number: int) -> dict[str, Any]:
        record = self.get_storyboard(storyboard_id)
        shots = record["shots"]
        if not 1 <= number <= len(shots):
            raise AppError("Shot number is out of range")
        with self.lock:
            shot = shots[number - 1]
            shot["scene"] = record["composer"].resolve_scene(shot["context"], shot["stage"])
            self._apply_director_customs(shot, shot["scene"], shot["context"])
            if record["args"].inference_seed is None:
                shot["inference_seed"] = secrets.randbelow(2**63)
            return serialize_shot(record["db"], shot)

    def randomize_shot_seed(self, storyboard_id: str, number: int) -> dict[str, Any]:
        record = self.get_storyboard(storyboard_id)
        if not 1 <= number <= len(record["shots"]):
            raise AppError("Shot number is out of range")
        with self.lock:
            if any(
                job["storyboard_id"] == storyboard_id
                and job["status"] in {"queued", "running"}
                for job in self.jobs.values()
            ):
                raise AppError("Image variation cannot change while this storyboard is rendering")
            shot = record["shots"][number - 1]
            previous = shot["inference_seed"]
            while shot["inference_seed"] == previous:
                shot["inference_seed"] = secrets.randbelow(2**63)
            shot["seed_manual"] = True
            return serialize_shot(record["db"], shot)

    def update_storyboard_seeds(
        self, storyboard_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        record = self.get_storyboard(storyboard_id)
        strategy = str(payload.get("inference_strategy", record["args"].inference_strategy))
        if strategy not in {"random", "fixed", "sequence"}:
            raise AppError("Inference seed strategy must be random, fixed, or sequence")
        base_seed = _optional_seed(
            payload.get("inference_seed"), "Image variation seed", 2**64 - 1
        )
        if strategy in {"fixed", "sequence"} and base_seed is None:
            base_seed = secrets.randbelow(2**63)
        with self.lock:
            if any(
                job["storyboard_id"] == storyboard_id
                and job["status"] in {"queued", "running"}
                for job in self.jobs.values()
            ):
                raise AppError("Image variation cannot change while this storyboard is rendering")
            record["args"].inference_strategy = strategy
            record["args"].inference_seed = base_seed
            for shot in record["shots"]:
                if strategy == "random":
                    seed = secrets.randbelow(2**63)
                elif strategy == "fixed":
                    seed = base_seed
                else:
                    material = (
                        f"{base_seed}:{shot['photoshoot_index']}:{shot['shot_index']}"
                    ).encode()
                    seed = int.from_bytes(
                        hashlib.sha256(material).digest()[:8], "big"
                    ) & (2**63 - 1)
                shot["inference_seed"] = seed
                shot["seed_manual"] = False
            return self.storyboard_payload(record)

    def create_job(self, storyboard_id: str, fast: bool, shot_numbers: list[int] | None = None) -> dict[str, Any]:
        record = self.get_storyboard(storyboard_id)
        shot_numbers = shot_numbers or [shot["number"] for shot in record["shots"]]
        if not shot_numbers or any(number < 1 or number > len(record["shots"]) for number in shot_numbers):
            raise AppError("Render selection contains an invalid shot")
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "storyboard_id": storyboard_id,
            "status": "queued",
            "fast": bool(fast),
            "created_at": _iso_now(),
            "started_at": None,
            "finished_at": None,
            "completed": 0,
            "total": len(shot_numbers),
            "shot_numbers": shot_numbers,
            "kind": "shot" if len(shot_numbers) == 1 else "storyboard",
            "attempt": 0,
            "retrying": False,
            "last_error": None,
            "current_shot": None,
            "progress": 0,
            "elapsed_seconds": 0,
            "eta_seconds": None,
            "outputs": [],
            "current_prompt": None,
            "logs": [{
                "time": _iso_now(), "type": "queued", "message": "Render job queued",
                "shot": None, "position": 0, "total": len(shot_numbers),
            }],
            "error": None,
            "cancel_requested": False,
        }
        with self.lock:
            if any(job["status"] in {"queued", "running"} for job in self.jobs.values()):
                raise AppError("Another render job is already active")
            if any(preview["status"] in {"queued", "running"} for preview in self.previews.values()):
                raise AppError("Wait for the active shot preview to finish")
            self.jobs[job_id] = job
            self.trim(self.jobs, MAX_JOBS)
        threading.Thread(target=self._run_job, args=(job_id,), daemon=True).start()
        return self.job_payload(job)

    def create_preview(
        self, storyboard_id: str, number: int, fast: bool
    ) -> dict[str, Any]:
        record = self.get_storyboard(storyboard_id)
        if not 1 <= number <= len(record["shots"]):
            raise AppError("Shot number is out of range")
        shot = record["shots"][number - 1]
        positive, negative, _ = compile_scene(record["db"], shot["scene"])
        preview_id = uuid.uuid4().hex
        preview = {
            "id": preview_id,
            "storyboard_id": storyboard_id,
            "shot": number,
            "status": "queued",
            "created_at": _iso_now(),
            "finished_at": None,
            "started_at": None,
            "elapsed_seconds": 0,
            "prompt_id": None,
            "image_bytes": None,
            "mime_type": None,
            "error": None,
            "db": record["db"],
            "positive": positive,
            "negative": negative,
            "seed": shot["inference_seed"],
        }
        with self.lock:
            if any(job["status"] in {"queued", "running"} for job in self.jobs.values()):
                raise AppError("Shot Preview is unavailable while a render job is active")
            if any(item["status"] in {"queued", "running"} for item in self.previews.values()):
                raise AppError("Another shot preview is already rendering")
            self.previews[preview_id] = preview
            self.trim(self.previews, MAX_PREVIEWS)
        threading.Thread(
            target=self._run_preview, args=(preview_id,), daemon=True
        ).start()
        return self.preview_payload(preview)

    def preview_payload(self, preview: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": preview["id"],
            "storyboard_id": preview["storyboard_id"],
            "shot": preview["shot"],
            "status": preview["status"],
            "created_at": preview["created_at"],
            "finished_at": preview["finished_at"],
            "prompt_id": preview["prompt_id"],
            "image_url": (
                f"/api/previews/{preview['id']}/image"
                if preview["status"] == "completed" else None
            ),
            "error": preview["error"],
            "type": "preview",
            "positive": preview["positive"],
            "negative": preview["negative"],
            "seed": preview["seed"],
            "started_at": preview["started_at"],
            "elapsed_seconds": preview["elapsed_seconds"],
        }
        if preview["status"] == "running" and preview.get("_started_monotonic") is not None:
            payload["elapsed_seconds"] = round(
                time.monotonic() - preview["_started_monotonic"], 1
            )
        return payload

    def get_preview(self, preview_id: str) -> dict[str, Any]:
        with self.lock:
            preview = self.previews.get(preview_id)
            if preview is None:
                raise AppError("Shot preview not found or expired")
            return self.preview_payload(preview)

    def preview_image(self, preview_id: str) -> tuple[bytes, str]:
        with self.lock:
            preview = self.previews.get(preview_id)
            if preview is None:
                raise AppError("Shot preview not found or expired")
            if preview["status"] != "completed" or preview["image_bytes"] is None:
                raise AppError("Shot preview image is not ready")
            return preview["image_bytes"], preview["mime_type"] or "image/png"

    def delete_preview(self, preview_id: str) -> dict[str, Any]:
        with self.lock:
            preview = self.previews.get(preview_id)
            if preview is None:
                return {"deleted": False}
            if preview["status"] in {"queued", "running"}:
                raise AppError("A rendering preview cannot be closed yet")
            self.previews.pop(preview_id, None)
        return {"deleted": True}

    def _run_preview(self, preview_id: str) -> None:
        with self.lock:
            preview = self.previews[preview_id]
            preview["status"] = "running"
            preview["started_at"] = _iso_now()
            preview["_started_monotonic"] = time.monotonic()
        try:
            db = preview["db"]
            _, db_path = load_database()
            workflow, mapping = load_workflow_runtime(db, db_path, True)
            prompt_id, image_bytes, mime_type = generate_preview_image(
                db,
                preview["positive"],
                preview["negative"],
                preview["seed"],
                workflow,
                mapping,
            )
            with self.lock:
                preview["prompt_id"] = prompt_id
                preview["image_bytes"] = image_bytes
                preview["mime_type"] = mime_type
                preview["status"] = "completed"
        except Exception as exc:
            with self.lock:
                preview["status"] = "failed"
                preview["error"] = str(exc)
        finally:
            with self.lock:
                preview["finished_at"] = _iso_now()
                preview["elapsed_seconds"] = round(
                    time.monotonic() - preview["_started_monotonic"], 1
                )

    def job_payload(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = {key: value for key, value in job.items() if not key.startswith("_")}
        if job["status"] == "running" and job.get("_started_monotonic") is not None:
            elapsed = time.monotonic() - job["_started_monotonic"]
            payload["elapsed_seconds"] = round(elapsed, 1)
            if job["completed"]:
                remaining = job["total"] - job["completed"]
                payload["eta_seconds"] = round(elapsed / job["completed"] * remaining, 1)
        return payload

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise AppError("Render job not found or expired")
            return self.job_payload(job)

    def jobs_payload(self) -> dict[str, Any]:
        with self.lock:
            jobs = [self.job_payload(job) for job in self.jobs.values()]
            visible_previews = [
                preview for preview in self.previews.values()
                if not preview.get("logger_hidden", False)
            ]
            latest_preview = (
                self.preview_payload(visible_previews[-1])
                if visible_previews else None
            )
        active = next(
            (job for job in reversed(jobs) if job["status"] in {"queued", "running"}),
            None,
        )
        return {
            "active_job": active,
            "jobs": list(reversed(jobs)),
            "latest_preview": latest_preview,
        }

    def clear_logger(self) -> dict[str, Any]:
        with self.lock:
            if any(job["status"] in {"queued", "running"} for job in self.jobs.values()):
                raise AppError("Logger cannot be cleared while a production render is active")
            if any(
                preview["status"] in {"queued", "running"}
                for preview in self.previews.values()
            ):
                raise AppError("Logger cannot be cleared while a preview render is active")
            cleared_jobs = len(self.jobs)
            self.jobs.clear()
            visible_previews = 0
            for preview in self.previews.values():
                if not preview.get("logger_hidden", False):
                    visible_previews += 1
                preview["logger_hidden"] = True
            return {
                "cleared": cleared_jobs + visible_previews,
                "jobs": cleared_jobs,
                "previews": visible_previews,
            }

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise AppError("Render job not found or expired")
            if job["status"] in {"queued", "running"}:
                if not job["cancel_requested"]:
                    job["cancel_requested"] = True
                    job["logs"].append({
                        "time": _iso_now(), "type": "cancel_requested",
                        "message": "Cancellation requested", "shot": job.get("current_shot"),
                        "position": job["completed"], "total": job["total"],
                    })
            return self.job_payload(job)

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job["status"] = "running"
            job["started_at"] = _iso_now()
            job["_started_monotonic"] = time.monotonic()
            job["logs"].append({
                "time": _iso_now(), "type": "started", "message": "Workflow started",
                "shot": None, "position": 0, "total": job["total"],
            })
        started = time.monotonic()
        try:
            record = self.get_storyboard(job["storyboard_id"])
            db = record["db"]
            _, db_path = load_database()
            workflow, mapping = load_workflow_runtime(db, db_path, job["fast"])
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            with self.lock:
                job["_run_id"] = run_id
            selected_shots = [record["shots"][number - 1] for number in job["shot_numbers"]]
            for completed_index, shot in enumerate(selected_shots, 1):
                shot_started = time.monotonic()
                with self.lock:
                    if job["cancel_requested"]:
                        job["status"] = "cancelled"
                        job["logs"].append({
                            "time": _iso_now(), "type": "cancelled", "message": "Render job cancelled",
                            "shot": None, "position": job["completed"], "total": job["total"],
                        })
                        break
                    job["current_shot"] = shot["number"]
                positive, negative, _ = compile_scene(db, shot["scene"])
                with self.lock:
                    job["current_prompt"] = {
                        "shot": shot["number"], "position": completed_index,
                        "positive": positive, "negative": negative,
                        "seed": shot["inference_seed"],
                    }
                    job["logs"].append({
                        "time": _iso_now(), "type": "shot_started",
                        "message": f"Rendering shot {shot['number']}",
                        "shot": shot["number"], "position": completed_index,
                        "total": len(selected_shots), "seed": shot["inference_seed"],
                        "positive": positive, "negative": negative,
                    })
                prompt_id = None
                paths = []
                for attempt in range(record["args"].retry_count + 1):
                    with self.lock:
                        job["attempt"] = attempt + 1
                        job["retrying"] = attempt > 0
                    seed = shot["inference_seed"]
                    if attempt and record["args"].inference_strategy != "fixed":
                        material = f"{seed}:retry:{attempt}".encode()
                        seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & (2**63 - 1)
                    try:
                        prompt_id, paths = generate_one(
                            db, db_path, positive, negative, seed,
                            record["args"].mode, shot["shot_index"], shot["photoshoot_index"],
                            run_id, job["fast"], workflow, mapping,
                        )
                        with self.lock:
                            job["last_error"] = None
                            job["retrying"] = False
                        break
                    except Exception as exc:
                        with self.lock:
                            job["last_error"] = str(exc)
                            job["logs"].append({
                                "time": _iso_now(), "type": "retry" if attempt < record["args"].retry_count else "error",
                                "message": str(exc), "shot": shot["number"],
                                "position": completed_index, "total": len(selected_shots),
                                "attempt": attempt + 1,
                            })
                        if attempt >= record["args"].retry_count:
                            raise
                elapsed = time.monotonic() - started
                completed = completed_index
                remaining = len(selected_shots) - completed
                with self.lock:
                    job["completed"] = completed
                    job["progress"] = round(completed * 100 / len(selected_shots), 1)
                    job["elapsed_seconds"] = round(elapsed, 1)
                    job["eta_seconds"] = round(elapsed / completed * remaining, 1) if remaining else 0
                    for path in paths:
                        job["outputs"].append({
                            "name": path.name,
                            "url": f"/api/outputs/{path.name}",
                            "prompt_id": prompt_id,
                            "shot": shot["number"],
                        })
                    job["logs"].append({
                        "time": _iso_now(), "type": "shot_completed",
                        "message": f"Shot {shot['number']} completed",
                        "shot": shot["number"], "position": completed,
                        "total": len(selected_shots),
                        "elapsed_seconds": round(elapsed, 1),
                        "duration_seconds": round(time.monotonic() - shot_started, 1),
                    })
            with self.lock:
                if job["status"] == "running":
                    job["status"] = "completed"
                    job["logs"].append({
                        "time": _iso_now(), "type": "completed", "message": "Render job completed",
                        "shot": None, "position": job["completed"], "total": job["total"],
                    })
        except Exception as exc:
            with self.lock:
                job["status"] = "failed"
                job["error"] = str(exc)
                job["logs"].append({
                    "time": _iso_now(), "type": "error", "message": str(exc),
                    "shot": job.get("current_shot"), "position": job["completed"], "total": job["total"],
                })
        finally:
            with self.lock:
                job["elapsed_seconds"] = round(time.monotonic() - started, 1)
                job["finished_at"] = _iso_now()
                job["current_shot"] = None


WEB_STATE = WebState()


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def output_directory() -> Path:
    db, db_path = load_database()
    return resolve_path(db_path.parent, db["settings"]["output_dir"])


def output_payload(path: Path) -> dict[str, Any]:
    match = re.search(r"_shot_(\d+)_", path.name)
    return {
        "name": path.name,
        "url": f"/api/outputs/{path.name}",
        "shot": int(match.group(1)) if match else None,
        "size": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
    }


def list_output_images() -> list[dict[str, Any]]:
    directory = output_directory()
    if not directory.is_dir():
        return []
    paths = [
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    paths.sort(key=lambda path: (path.stat().st_mtime, path.name))
    return [output_payload(path) for path in paths]


def ensure_outputs_idle() -> None:
    with WEB_STATE.lock:
        active = any(job["status"] in {"queued", "running"} for job in WEB_STATE.jobs.values())
    if active:
        raise AppError("Outputs cannot be deleted while a render job is active")


def delete_output_image(name: str) -> dict[str, Any]:
    if not name or Path(name).name != name:
        raise AppError("Invalid output filename")
    target = output_directory() / name
    if target.suffix.lower() not in IMAGE_SUFFIXES:
        raise AppError("Only generated image files can be deleted")
    if not target.is_file():
        raise AppError("Output not found")
    with WEB_STATE.lock:
        # A completed frame is safe to remove while the next frame renders. Guard
        # only a file from the active run that has not yet been published as an
        # output, because it may still be in the middle of being written.
        for job in WEB_STATE.jobs.values():
            if job["status"] not in {"queued", "running"}:
                continue
            run_id = job.get("_run_id")
            published = {item["name"] for item in job.get("outputs", [])}
            if run_id and name.startswith(f"{run_id}_") and name not in published:
                raise AppError("This frame is still being written and cannot be deleted yet")
        try:
            target.unlink()
        except OSError as exc:
            raise AppError(f"Could not delete output: {exc}") from exc
        # Prevent subsequent job polling from restoring a deleted card in the UI.
        for job in WEB_STATE.jobs.values():
            job["outputs"] = [
                item for item in job.get("outputs", []) if item["name"] != name
            ]
    return {"ok": True, "deleted": name}


def delete_all_output_images() -> dict[str, Any]:
    ensure_outputs_idle()
    directory = output_directory()
    if not directory.is_dir():
        return {"ok": True, "deleted": 0, "names": []}
    targets = [
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    deleted: list[str] = []
    for target in targets:
        try:
            target.unlink()
            deleted.append(target.name)
        except OSError as exc:
            raise AppError(
                f"Deleted {len(deleted)} images, then could not delete {target.name}: {exc}"
            ) from exc
    return {"ok": True, "deleted": len(deleted), "names": deleted}


def application_status(check_comfy: bool = True) -> dict[str, Any]:
    db, db_path = load_database()
    settings = db["settings"]
    workflow_path = resolve_path(db_path.parent, settings["workflow_file"])
    output_path = resolve_path(db_path.parent, settings["output_dir"])
    selectable = sum(1 for item in iter_content_items(db) if not item.get("disabled", False))
    comfy = {"url": settings["comfy_url"], "online": False, "message": "Not checked"}
    if check_comfy:
        try:
            session, url, _ = comfy_session(db)
            response = session.get(f"{url}/system_stats", timeout=2)
            response.raise_for_status()
            comfy.update(online=True, message="Connected")
        except Exception as exc:
            comfy["message"] = str(exc)
    progression = settings.get("photoshoot_progression", {})
    return {
        "app": "Project Valhalla",
        "version": "2.0-web",
        "comfy": comfy,
        "workflow": {"ready": workflow_path.is_file(), "name": workflow_path.name},
        "output": {"path": str(output_path), "exists": output_path.is_dir()},
        "catalog_records": selectable,
        "defaults": {
            "nsfw_percent": progression.get("nsfw_final_percent", 50),
            "plateau_percent": progression.get("explicit_plateau_percent", 30),
        },
    }


class ValhallaHandler(BaseHTTPRequestHandler):
    server_version = "Valhalla/2.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise AppError("Invalid Content-Length") from exc
        if length > 32_000_000:
            raise AppError("Request body is too large (maximum 32 MB)")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise AppError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise AppError("Request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/status":
                self.send_json(application_status())
            elif path.endswith("/export") and path.startswith("/api/storyboards/"):
                storyboard_id = path.split("/")[3]
                self.send_json(WEB_STATE.export_storyboard(storyboard_id))
            elif path.endswith("/director") and path.startswith("/api/storyboards/"):
                storyboard_id = path.split("/")[3]
                query = parse_qs(urlparse(self.path).query)
                shot = _safe_int(query.get("shot", ["1"])[0], "Shot", 1, 10_000)
                self.send_json(WEB_STATE.director_payload(storyboard_id, shot))
            elif path.startswith("/api/storyboards/"):
                storyboard_id = path.split("/")[3]
                self.send_json(WEB_STATE.storyboard_payload(WEB_STATE.get_storyboard(storyboard_id)))
            elif path == "/api/jobs":
                self.send_json(WEB_STATE.jobs_payload())
            elif path.startswith("/api/jobs/"):
                self.send_json(WEB_STATE.get_job(path.split("/")[3]))
            elif path.endswith("/image") and path.startswith("/api/previews/"):
                self.serve_preview_image(path.split("/")[3])
            elif path.startswith("/api/previews/"):
                self.send_json(WEB_STATE.get_preview(path.split("/")[3]))
            elif path == "/api/outputs":
                self.send_json({"outputs": list_output_images()})
            elif path.startswith("/api/outputs/"):
                self.serve_output(unquote(path.removeprefix("/api/outputs/")))
            elif path.startswith("/api"):
                self.send_json({"error": "API endpoint not found"}, HTTPStatus.NOT_FOUND)
            else:
                self.serve_static(path)
        except AppError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except BrokenPipeError:
            pass
        except Exception as exc:
            self.send_json({"error": f"Internal server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/storyboards":
                self.send_json(WEB_STATE.create_storyboard(self.read_json()), HTTPStatus.CREATED)
            elif path == "/api/storyboards/import":
                self.send_json(WEB_STATE.import_storyboard(self.read_json()), HTTPStatus.CREATED)
            elif path.endswith("/director") and path.startswith("/api/storyboards/"):
                storyboard_id = path.split("/")[3]
                self.send_json(WEB_STATE.update_director(storyboard_id, self.read_json()))
            elif path.endswith("/seeds") and path.startswith("/api/storyboards/"):
                storyboard_id = path.split("/")[3]
                self.send_json(WEB_STATE.update_storyboard_seeds(storyboard_id, self.read_json()))
            elif path.endswith("/reroll") and path.startswith("/api/storyboards/"):
                parts = path.split("/")
                self.send_json(WEB_STATE.reroll_shot(parts[3], _safe_int(parts[5], "Shot", 1, 10000)))
            elif path.endswith("/seed") and path.startswith("/api/storyboards/"):
                parts = path.split("/")
                self.send_json(WEB_STATE.randomize_shot_seed(parts[3], _safe_int(parts[5], "Shot", 1, 10000)))
            elif path.endswith("/render") and path.startswith("/api/storyboards/"):
                parts = path.split("/")
                payload = self.read_json()
                number = _safe_int(parts[5], "Shot", 1, 10_000)
                self.send_json(
                    WEB_STATE.create_job(parts[3], bool(payload.get("fast", False)), [number]),
                    HTTPStatus.ACCEPTED,
                )
            elif path == "/api/jobs":
                payload = self.read_json()
                self.send_json(
                    WEB_STATE.create_job(str(payload.get("storyboard_id", "")), bool(payload.get("fast", False))),
                    HTTPStatus.ACCEPTED,
                )
            elif path == "/api/previews":
                payload = self.read_json()
                self.send_json(
                    WEB_STATE.create_preview(
                        str(payload.get("storyboard_id", "")),
                        _safe_int(payload.get("shot"), "Shot", 1, 10_000),
                        bool(payload.get("fast", False)),
                    ),
                    HTTPStatus.ACCEPTED,
                )
            elif path.endswith("/cancel") and path.startswith("/api/jobs/"):
                self.send_json(WEB_STATE.cancel_job(path.split("/")[3]))
            elif path == "/api/workflow/capture":
                payload = self.read_json()
                db, db_path = load_database()
                capture(db, db_path, bool(payload.get("force", False)))
                self.send_json({"ok": True, "message": "Workflow captured successfully"})
            else:
                self.send_json({"error": "API endpoint not found"}, HTTPStatus.NOT_FOUND)
        except AppError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": f"Internal server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/outputs":
                self.send_json(delete_all_output_images())
            elif path == "/api/logger":
                self.send_json(WEB_STATE.clear_logger())
            elif path.startswith("/api/outputs/"):
                name = unquote(path.removeprefix("/api/outputs/"))
                self.send_json(delete_output_image(name))
            elif path.startswith("/api/previews/"):
                self.send_json(WEB_STATE.delete_preview(path.split("/")[3]))
            else:
                self.send_json({"error": "API endpoint not found"}, HTTPStatus.NOT_FOUND)
        except AppError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": f"Internal server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else unquote(path.lstrip("/"))
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            target = WEB_ROOT / "index.html"
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def serve_output(self, name: str) -> None:
        if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
            raise AppError("Only generated image files can be viewed")
        if not name or Path(name).name != name:
            raise AppError("Invalid output filename")
        db, db_path = load_database()
        target = resolve_path(db_path.parent, db["settings"]["output_dir"]) / name
        if not target.is_file():
            self.send_json({"error": "Output not found"}, HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def serve_preview_image(self, preview_id: str) -> None:
        body, content_type = WEB_STATE.preview_image(preview_id)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def serve(host: str, port: int, open_browser: bool) -> None:
    if not WEB_ROOT.joinpath("index.html").is_file():
        raise AppError(f"Web UI assets not found: {WEB_ROOT}")
    server = ThreadingHTTPServer((host, port), ValhallaHandler)
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{browser_host}:{server.server_port}/"
    print(f"Project Valhalla Web UI: {url}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Project Valhalla…")
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project Valhalla local Web UI server")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        serve(args.host, args.port, not args.no_browser)
        return 0
    except AppError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: could not start web server: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
