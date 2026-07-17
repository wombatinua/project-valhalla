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
import textwrap
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    if "menu_label" in item and (
        not isinstance(item["menu_label"], str) or not item["menu_label"].strip()
    ):
        raise AppError(f"{context}.{item['id']}: menu_label must be a non-empty string")
    if "menu_group" in item and (
        not isinstance(item["menu_group"], str) or not item["menu_group"].strip()
    ):
        raise AppError(f"{context}.{item['id']}: menu_group must be a non-empty string")
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
        "expressions", "moods", "photography_styles",
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
        order = list(parts)
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
            candidates = list(self.db["garments"][rule["catalog"]])
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
        elif plateau_kind == "panties_aside":
            poses = [
                item for item in poses
                if "open_legs" in tags(item) and "provocative_rear" not in tags(item)
            ]
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
        elif plateau_kind == "panties_aside":
            actions = [item for item in actions if "panties_aside_action" in tags(item)]
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
    if plateau_kind == "provocative_rear":
        visibility -= {"breasts", "nipples"}
    xxx_prompt = defaults.get("xxx_plateau_prompts", {}).get(plateau_kind, "")
    age_prompt = scene["human"]["age"]["prompt"]
    positive_prefix = defaults.get("positive_prefix", "").replace("{age}", age_prompt)
    fragments = [xxx_prompt, positive_prefix]
    fragments.extend(human_fragments(scene["human"], visibility))
    visible_slots = set(stage.get("visible_slots", []))
    outfit = scene["outfit"]
    reveals_cameltoe = False
    for slot in outfit["template"]["slots"]:
        if slot in visible_slots and slot in outfit["garments"]:
            garment = outfit["garments"][slot]
            garment_parts = [outfit["colors"][slot]["prompt"]]
            if slot in outfit.get("patterns", {}):
                garment_parts.append(outfit["patterns"][slot]["prompt"])
            if slot in outfit.get("textures", {}):
                garment_parts.append(outfit["textures"][slot]["prompt"])
            garment_parts.append(garment["prompt"])
            fragments.append(" ".join(garment_parts))
            reveals_cameltoe = reveals_cameltoe or garment.get("reveals_cameltoe", False)
    if reveals_cameltoe:
        fragments.append(defaults["cameltoe_prompt"])
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
            f"       wardrobe={wardrobe_category(context['outfit']['template'])}:"
            f"{context['outfit']['template']['id']} | "
            f"location={environment_category(context['interior'])}:"
            f"{context['interior']['id']} | surface={context['furniture']['id']}"
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
                    "--header=Type to search • Enter select • Esc go back",
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
MENU_BACK = object()


@dataclass(frozen=True)
class MenuPool:
    """A deferred, prompt-seed-controlled choice from a Director menu group."""

    values: tuple[tuple[Any, float], ...]


def menu_pool(values: Iterable[tuple[Any, float]]) -> MenuPool:
    pool = tuple(values)
    if not pool:
        raise AppError("A Director menu group cannot be empty")
    return MenuPool(pool)


def resolve_menu_choice(value: Any, rng: random.Random) -> Any:
    if not isinstance(value, MenuPool):
        return value
    values, weights = zip(*value.values)
    if any(weight <= 0 for weight in weights):
        raise AppError("Every selectable item weight must be greater than zero")
    return rng.choices(values, weights=weights, k=1)[0]


def fzf_group(title: str) -> tuple[str, Any]:
    return (f"── {title.upper()} " + "─" * max(1, 28 - len(title)), FZF_GROUP)


def director_menu_choice(
    prompt: str,
    choices: list[tuple[str, Any]],
    default: str,
) -> str:
    if director_uses_fzf():
        escape_value = next(
            (value for _, value in choices if value == "0"), default
        )
        selected = fzf_select(
            prompt,
            choices,
            escape_value,
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


def human_section_label(human: dict[str, Any], parts: list[str]) -> str:
    labels = {
        "age": "Age", "ethnic_appearance": "Appearance", "skin_tone": "Skin",
        "face_shape": "Face", "eye_shape": "Eyes", "eye_color": "Eye color",
        "eyebrows": "Brows", "nose": "Nose", "lips": "Lips",
        "cheekbones": "Cheekbones", "jawline": "Jaw", "facial_accents": "Details",
        "hair_texture": "Texture", "hair_length": "Length", "hair_style": "Style",
        "hair_color": "Color", "height": "Height", "body_frame": "Build",
        "waist": "Waist", "hips": "Hips", "breast_size": "Breasts",
        "breast_shape": "Shape", "areola_size": "Areola size",
        "areola_color": "Areola color", "nipple_size": "Nipple size",
        "nipple_shape": "Nipple shape", "pubic_hair": "Pubic hair",
        "genital_appearance": "Genitals", "makeup": "Makeup", "manicure": "Manicure",
    }
    fragments = []
    for part in parts:
        value = human[part]
        if isinstance(value, list):
            prompt = ", ".join(item["prompt"] for item in value) or "none"
        else:
            prompt = value["prompt"]
        fragments.append(f"{labels[part]}: {prompt}")
    return "  ·  ".join(fragments)


def human_cast_label(human: dict[str, Any]) -> str:
    return human_section_label(human, [
        "age", "ethnic_appearance", "skin_tone", "face_shape", "eye_color",
        "hair_color", "hair_style", "body_frame",
    ])


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

HUMAN_SECTION_ORDER = {
    "face": [
        "face_shape", "eye_shape", "eye_color", "eyebrows", "nose", "lips",
        "cheekbones", "jawline", "facial_accents",
    ],
    "hair": ["hair_texture", "hair_length", "hair_style", "hair_color"],
    "body": [
        "height", "body_frame", "waist", "hips", "breast_size", "breast_shape",
        "areola_size", "areola_color", "nipple_size", "nipple_shape", "pubic_hair",
        "genital_appearance",
    ],
    "styling": ["makeup", "manicure"],
}


def remixed_human(
    composer: Composer,
    current: dict[str, Any],
    replace_parts: set[str] | None = None,
    keep_parts: set[str] | None = None,
) -> dict[str, Any]:
    overrides = {}
    if replace_parts is not None or (keep_parts and "ethnic_appearance" in keep_parts):
        overrides["ethnic_appearance"] = current["ethnic_appearance"]
    fresh = composer.choose_human(
        overrides,
        use_human_defaults=replace_parts is None,
    )
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


def choose_intimate_details(
    composer: Composer, current: dict[str, Any]
) -> dict[str, Any]:
    working = current
    while True:
        mode = select_labeled(
            "VULVA & PUBIC HAIR — choose what to change",
            [
                ("Choose pubic hair", "pubic_hair"),
                ("Choose vulva", "genital_appearance"),
            ],
        )
        if mode is None:
            return working
        if mode == "pubic_hair":
            title = "INTIMATE DETAILS — choose pubic hair"
        else:
            title = "INTIMATE DETAILS — choose vulva appearance"
        items = [
            item
            for item in composer.db["human_model_parts"][mode]
            if not item.get("disabled", False)
        ]
        selected = select_labeled(
            title,
            any_catalog_choices(items, [
                (item.get("menu_label", item["prompt"]), item)
                for item in items
            ]),
        )
        if selected is None:
            continue
        selected = resolve_menu_choice(selected, composer.rng)
        updated = dict(working)
        updated[mode] = selected
        working = updated


def _choose_subject_remix_once(
    composer: Composer, current: dict[str, Any]
) -> dict[str, Any] | None:
    mode = select_labeled(
        "SUBJECT — choose what to change",
        [
            fzf_group("Whole subject"),
            ("Generate new subject", "all"),
            ("Reroll same ethnicity", "ethnic"),
            fzf_group("Identity & face"),
            ("Choose ethnic appearance", "choose_ethnic"),
            ("Choose age", "choose_age"),
            ("Remix facial features", "face"),
            fzf_group("Hair & beauty"),
            ("Hair length", "choose_hair_length"),
            ("Hair style", "choose_hair_style"),
            ("Hair texture", "choose_hair_texture"),
            ("Hair color", "choose_hair_color"),
            ("Choose makeup", "choose_makeup"),
            ("Choose manicure", "choose_manicure"),
            ("Remix hair", "hair"),
            ("Remix styling", "styling"),
            fzf_group("Body"),
            ("Choose body type", "choose_body_type"),
            ("Choose breast size", "choose_breast_size"),
            ("Intimate details", "intimate_details"),
            ("Remix body anatomy", "body"),
        ],
    )
    if mode is None:
        return None
    if mode == "intimate_details":
        return choose_intimate_details(composer, current)
    if mode == "choose_age":
        age_options = [
            item for item in composer.db["human_model_parts"]["age"]
            if not item.get("disabled", False)
        ]
        selected_age = select_labeled(
            "CASTING CALL — choose age",
            any_catalog_choices(age_options, [(item["prompt"], item) for item in age_options]),
        )
        if selected_age is None:
            return current
        updated = dict(current)
        updated["age"] = resolve_menu_choice(selected_age, composer.rng)
        return updated
    if mode in {"choose_breast_size", "choose_body_type"}:
        if mode == "choose_breast_size":
            category = "breast_size"
            title = "CASTING CALL — choose breast size"
            choices = [
                ("Tiny", "breasts_very_small"),
                ("Small", "breasts_small"),
                ("Medium", "breasts_medium"),
                ("Large", "breasts_large"),
            ]
        else:
            category = "body_frame"
            title = "CASTING CALL — choose body type"
            choices = [
                ("Thin", "body_slender"),
                ("Normal", "body_average"),
                ("Petite", "body_petite"),
                ("Athletic", "body_athletic"),
                ("Fit", "body_fitness"),
                ("Curvy", "body_curvy"),
                ("Hourglass", "body_hourglass"),
                ("Soft", "body_soft"),
                ("Voluptuous", "body_voluptuous"),
                ("Plus-size curvy", "body_plus_curvy"),
            ]
        items = {
            item["id"]: item
            for item in composer.db["human_model_parts"][category]
            if not item.get("disabled", False)
        }
        selected = select_labeled(
            title,
            any_catalog_choices(list(items.values()), [
                (label, items[item_id])
                for label, item_id in choices if item_id in items
            ]),
        )
        if selected is None:
            return current
        updated = dict(current)
        updated[category] = resolve_menu_choice(selected, composer.rng)
        return updated
    if mode in {"choose_hair_length", "choose_hair_style", "choose_hair_texture"}:
        category = {
            "choose_hair_length": "hair_length",
            "choose_hair_style": "hair_style",
            "choose_hair_texture": "hair_texture",
        }[mode]
        available_tags: set[str] = set()
        for key, value in current.items():
            if key in {category, "hair_style"}:
                continue
            if isinstance(value, list):
                for item in value:
                    available_tags |= tags(item)
            else:
                available_tags |= tags(value)
        items = [
            item for item in composer.db["human_model_parts"][category]
            if not item.get("disabled", False)
            and compatible_with_requirements(item, available_tags)
        ]
        if category == "hair_length":
            choices: list[tuple[str, Any]] = [
                ("All groups", menu_pool((item, float(item.get("weight", 1))) for item in items))
            ]
            for group, tag in (("Short", "short_hair"), ("Medium", "medium_hair"), ("Long", "long_hair")):
                grouped = [item for item in items if tag in tags(item)]
                if grouped:
                    choices.append(fzf_group(group))
                    choices.append((
                        f"Any {group}",
                        menu_pool((item, float(item.get("weight", 1))) for item in grouped),
                    ))
                    choices.extend((compact_item_label(item, ("hair_length_",)), item) for item in grouped)
        elif category == "hair_style":
            choices = [
                ("All groups", menu_pool((item, float(item.get("weight", 1))) for item in items))
            ]
            assigned_styles: set[str] = set()
            for group, tag in (("Short", "short_hairstyle"), ("Medium", "medium_hairstyle"), ("Long", "long_hairstyle")):
                grouped = [
                    item for item in items
                    if item["id"] not in assigned_styles and tag in tags(item)
                ]
                if grouped:
                    choices.append(fzf_group(group))
                    choices.append((
                        f"Any {group}",
                        menu_pool((item, float(item.get("weight", 1))) for item in grouped),
                    ))
                    choices.extend((compact_item_label(item, ("hair_style_",)), item) for item in grouped)
                    assigned_styles.update(item["id"] for item in grouped)
        else:
            choices = any_catalog_choices(
                items,
                [(compact_item_label(item, ("hair_texture_",)), item) for item in items],
            )
        selected = select_labeled(f"CASTING — {category.replace('_', ' ')}", choices)
        if selected is None:
            return current
        selected = resolve_menu_choice(selected, composer.rng)
        updated = dict(current)
        updated[category] = selected
        if category != "hair_style":
            style_tags = set()
            for key, value in updated.items():
                if key == "hair_style":
                    continue
                if isinstance(value, list):
                    for item in value:
                        style_tags |= tags(item)
                else:
                    style_tags |= tags(value)
            current_style = updated["hair_style"]
            if not compatible_with_requirements(current_style, style_tags):
                styles = [
                    item for item in composer.db["human_model_parts"]["hair_style"]
                    if not item.get("disabled", False)
                    and compatible_with_requirements(item, style_tags)
                ]
                updated["hair_style"] = weighted_choice(composer.rng, styles)
        return updated
    if mode in {"choose_hair_color", "choose_makeup", "choose_manicure"}:
        category = {
            "choose_hair_color": "hair_color",
            "choose_makeup": "makeup",
            "choose_manicure": "manicure",
        }[mode]
        available_tags: set[str] = set()
        for key, value in current.items():
            if key == category:
                continue
            if isinstance(value, list):
                for item in value:
                    available_tags |= tags(item)
            else:
                available_tags |= tags(value)
        options = [
            item for item in composer.db["human_model_parts"][category]
            if not item.get("disabled", False)
            and compatible_with_requirements(item, available_tags)
        ]
        if category == "hair_color":
            labels = [
                ("All groups", menu_pool((item, float(item.get("weight", 1))) for item in options))
            ]
            for group, predicate in (
                ("Natural", lambda item: "natural_hair_color" in tags(item)),
                ("Fashion", lambda item: "natural_hair_color" not in tags(item)),
            ):
                grouped = [item for item in options if predicate(item)]
                if not grouped:
                    continue
                labels.append(fzf_group(group))
                labels.append((
                    f"Any {group}",
                    menu_pool((item, float(item.get("weight", 1))) for item in grouped),
                ))
                labels.extend(
                    (compact_item_label(item, ("hair_",)), item) for item in grouped
                )
            title = "CASTING CALL — choose hair color"
        elif category == "manicure":
            exact_labels = [
                (
                    "No manicure" if item["id"] == "manicure_none"
                    else item["id"].removeprefix("manicure_").replace("_", " ").title(),
                    item,
                )
                for item in options
            ]
            labels = any_catalog_choices(options, exact_labels)
            title = "CASTING CALL — choose manicure"
        else:
            exact_labels = [
                (
                    "No makeup" if item["id"] == "makeup_no_makeup"
                    else item["id"].removeprefix("makeup_").replace("_", " ").title(),
                    item,
                )
                for item in options
            ]
            labels = any_catalog_choices(options, exact_labels)
            title = "CASTING CALL — choose makeup"
        selected = select_labeled(title, labels)
        if selected is None:
            return current
        selected = resolve_menu_choice(selected, composer.rng)
        updated = dict(current)
        updated[category] = selected
        return updated
    selected_ethnic = None
    if mode == "choose_ethnic":
        ethnic_options = [
            item for item in composer.db["human_model_parts"]["ethnic_appearance"]
            if not item.get("disabled", False)
        ]
        selected_ethnic = select_labeled(
            "CASTING CALL — choose ethnic appearance",
            any_catalog_choices(ethnic_options, [
                (item["id"].removeprefix("appearance_").replace("_", " ").title(), item)
                for item in ethnic_options
            ]),
        )
        if selected_ethnic is None:
            return current
        selected_ethnic = resolve_menu_choice(selected_ethnic, composer.rng)
    candidates: list[dict[str, Any]] = []
    for _ in range(8):
        if mode == "all":
            candidate = composer.choose_human(use_default_ethnicity=False)
        elif mode == "ethnic":
            candidate = remixed_human(composer, current, keep_parts={"ethnic_appearance"})
        elif mode == "choose_ethnic":
            candidate = composer.choose_human({"ethnic_appearance": selected_ethnic})
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
    if mode in HUMAN_SECTION_ORDER:
        title = f"CASTING CALL — choose {mode}"
        label_parts = HUMAN_SECTION_ORDER[mode]
    else:
        title = "CASTING CALL — choose subject"
        label_parts = [
            "age", "ethnic_appearance", "skin_tone", "face_shape", "eye_color",
            "hair_color", "hair_style", "body_frame",
        ]
    selected = select_labeled(
        title,
        [(human_section_label(candidate, label_parts), candidate) for candidate in candidates],
    )
    return selected if selected is not None else current


def choose_subject_remix(
    composer: Composer, current: dict[str, Any]
) -> dict[str, Any] | None:
    original = current
    working = current
    while True:
        updated = _choose_subject_remix_once(composer, working)
        if updated is None:
            return working if working is not original else None
        working = updated


def outfit_label(outfit: dict[str, Any], limit: int = 4) -> str:
    garments = []
    for slot, item in outfit["garments"].items():
        parts = [outfit["colors"][slot]["prompt"]]
        if slot in outfit.get("patterns", {}):
            parts.append(outfit["patterns"][slot]["prompt"])
        if slot in outfit.get("textures", {}):
            parts.append(outfit["textures"][slot]["prompt"])
        parts.append(item["prompt"])
        garments.append(" ".join(parts))
    visible = garments[:limit]
    if len(garments) > limit:
        visible.append(f"+{len(garments) - limit} more")
    return "  ·  ".join(visible)


def template_label(template: dict[str, Any]) -> str:
    return template["id"].removeprefix("template_").replace("_", " ").title()


def compact_item_label(
    item: dict[str, Any], prefixes: tuple[str, ...] = (), maximum_words: int = 3
) -> str:
    label = item.get("menu_label")
    if not label:
        raw = item["id"]
        for prefix in prefixes:
            raw = raw.removeprefix(prefix)
        label = raw.replace("_", " ").title()
    words = str(label).split()
    return " ".join(words[:maximum_words])


def any_catalog_choices(
    items: list[dict[str, Any]], labels: Iterable[tuple[str, dict[str, Any]]]
) -> list[tuple[str, Any]]:
    """Offer a seed-controlled unrestricted value followed by exact values."""
    return [
        (
            "Any value",
            menu_pool((item, float(item.get("weight", 1))) for item in items),
        ),
        *labels,
    ]


def grouped_catalog_choices(
    items: list[dict[str, Any]],
    prefixes: tuple[str, ...],
    group_order: tuple[str, ...],
) -> list[tuple[str, Any]]:
    choices: list[tuple[str, Any]] = [
        (
            "All groups",
            menu_pool((item, float(item.get("weight", 1))) for item in items),
        )
    ]
    groups = {str(item.get("menu_group", "Other")) for item in items}
    ordered = [group for group in group_order if group in groups]
    ordered.extend(sorted(groups - set(ordered)))
    for group in ordered:
        group_items = [
            item for item in items if item.get("menu_group", "Other") == group
        ]
        choices.append(fzf_group(group))
        choices.append((
            f"Any {group}",
            menu_pool((item, float(item.get("weight", 1))) for item in group_items),
        ))
        choices.extend(
            (compact_item_label(item, prefixes), item)
            for item in group_items
        )
    return choices


def wardrobe_category(template: dict[str, Any]) -> str:
    return str(template["wardrobe_category"])


def grouped_template_choices(templates: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    choices: list[tuple[str, Any]] = [
        (
            "All groups",
            menu_pool((item, float(item.get("weight", 1))) for item in templates),
        )
    ]
    for category in ("normal", "glamour"):
        items = [item for item in templates if wardrobe_category(item) == category]
        if items:
            choices.append(fzf_group(category))
            choices.append((
                f"Any {category.title()}",
                menu_pool((item, float(item.get("weight", 1))) for item in items),
            ))
            choices.extend((template_label(item), item) for item in items)
    return choices


def choose_wardrobe_remix(
    db: dict[str, Any],
    composer: Composer,
    current: dict[str, Any],
    interior: dict[str, Any],
) -> dict[str, Any] | None:
    templates = [
        template for template in db["outfit_templates"]
        if not template.get("disabled", False)
    ]
    template = select_labeled(
        "WARDROBE — choose scope or outfit",
        [("Same template", current["template"])] + grouped_template_choices(templates),
    )
    if template is None:
        return None
    template = resolve_menu_choice(template, composer.rng)
    candidates = [composer.choose_outfit(template, interior) for _ in range(8)]
    return select_labeled(
        f"WARDROBE DEPARTMENT — choose {template_label(template)} variation",
        [(outfit_label(outfit), outfit) for outfit in candidates],
    )


def location_family(interior: dict[str, Any]) -> set[str]:
    generic = {"indoor", "private", "luxury", "cozy", "intimate"}
    return tags(interior) - generic


def environment_category(interior: dict[str, Any]) -> str:
    return "luxury" if "luxury" in tags(interior) else "normal"


def grouped_location_choices(
    candidates: list[tuple[str, tuple[dict[str, Any], dict[str, Any]]]],
) -> list[tuple[str, Any]]:
    grouped: list[tuple[str, Any]] = [
        (
            "All groups",
            menu_pool(
                (value, float(value[0].get("weight", 1)))
                for _, value in candidates
            ),
        )
    ]
    for category in ("normal", "luxury"):
        category_items = [
            candidate for candidate in candidates
            if environment_category(candidate[1][0]) == category
        ]
        if category_items:
            grouped.append(fzf_group(category))
            grouped.append((
                f"Any {category.title()}",
                menu_pool(
                    (value, float(value[0].get("weight", 1)))
                    for _, value in category_items
                ),
            ))
            grouped.extend(category_items)
    return grouped


def outfit_environment_compatible(
    composer: Composer,
    outfit: dict[str, Any],
    interior: dict[str, Any],
) -> bool:
    try:
        composer.validate_outfit_environment(outfit, interior)
        return True
    except AppError:
        return False


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
    db: dict[str, Any],
    composer: Composer,
    current: dict[str, Any],
    outfit: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    interiors = [item for item in db["interiors"] if not item.get("disabled", False)]
    interiors = [
        interior for interior in interiors
        if outfit_environment_compatible(composer, outfit, interior)
    ]
    candidates = resolved_location_candidates(db, composer, interiors)
    selected = select_labeled(
        "LOCATION — choose scope or room",
        grouped_location_choices(candidates),
    )
    if selected is None:
        return None
    return resolve_menu_choice(selected, composer.rng)


def choose_surface_remix(
    db: dict[str, Any], composer: Composer, current_interior: dict[str, Any]
) -> dict[str, Any] | None:
    surface_types = {
        "bed", "sofa", "chair", "bathtub", "floor", "wall", "windowsill",
        "table", "shower", "bench", "stool",
    }
    candidates = [
        item for item in db["furniture"]
        if not item.get("disabled", False)
        and compatible_with_requirements(item, tags(current_interior))
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        group = next((kind for kind in sorted(surface_types) if kind in tags(item)), "other")
        groups.setdefault(group, []).append(item)
    choices: list[tuple[str, Any]] = [
        (
            "All groups",
            menu_pool((item, float(item.get("weight", 1))) for item in candidates),
        )
    ]
    for group, items in sorted(groups.items()):
        choices.append(fzf_group(group))
        choices.append((
            f"Any {group.title()}",
            menu_pool((item, float(item.get("weight", 1))) for item in items),
        ))
        choices.extend((compact_item_label(item, ("surface_", "furniture_")), item) for item in items)
    selected = select_labeled("SURFACE — choose scope or item", choices)
    if selected is None:
        return None
    return resolve_menu_choice(selected, composer.rng)


def select_labeled(
    prompt: str,
    choices: list[tuple[str, Any]],
    preamble: str | None = None,
) -> Any | None:
    menu_choices = list(choices)
    if not any(value is MENU_BACK for _, value in menu_choices):
        menu_choices.append(("Back", MENU_BACK))
    if director_uses_fzf():
        director_clear()
        if preamble:
            print(preamble + "\n")
        selected = fzf_select(prompt, menu_choices)
        return None if selected is MENU_BACK else selected
    director_clear()
    if preamble:
        print(preamble + "\n")
    print(prompt + "\n")
    selectable = []
    for label, value in menu_choices:
        if value is FZF_GROUP:
            title = label.removeprefix("── ").split(" ─", 1)[0]
            print(f"\n{title}")
            continue
        selectable.append((label, value))
        print(f"{len(selectable):>2}) {label}")
    selected = choose_number("\nChoose: ", len(selectable), allow_zero=False)
    if not selected:
        return None
    value = selectable[selected - 1][1]
    return None if value is MENU_BACK else value


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
            print("1) Edit subject")
            print("2) Edit wardrobe")
            print("3) Edit location")
            print("4) Edit surface")
            print("5) Edit mood")
            print("6) Edit camera")
            print("7) Reroll SET")
            print("0) Back")
        choice = director_menu_choice(
            "Set designer's choice",
            [
                fzf_group("Casting"),
                ("Edit subject", "1"),
                fzf_group("Styling"),
                ("Edit wardrobe", "2"),
                ("Edit mood", "5"),
                ("Edit camera", "6"),
                fzf_group("Location"),
                ("Edit location", "3"),
                ("Edit surface", "4"),
                fzf_group("Complete SET"),
                ("Reroll SET", "7"),
                ("Back", "0"),
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
            outfit = choose_wardrobe_remix(
                db, composer, context["outfit"], context["interior"]
            )
            if outfit is None:
                continue
            new_context["outfit"] = outfit
            recalculate_stages = True
        elif choice == "3":
            selected = choose_location_remix(
                db, composer, context["interior"], context["outfit"]
            )
            if selected is None:
                continue
            new_context["interior"], new_context["furniture"] = selected
        elif choice == "4":
            surface = choose_surface_remix(db, composer, context["interior"])
            if surface is None:
                continue
            new_context["furniture"] = surface
        elif choice == "5":
            moods = [item for item in db["moods"] if not item.get("disabled", False)]
            mood = select_labeled(
                "MOOD",
                grouped_catalog_choices(moods, ("mood_",), ("Everyday", "Romantic", "Editorial")),
            )
            if mood is None:
                continue
            new_context["mood"] = resolve_menu_choice(mood, composer.rng)
        elif choice == "6":
            styles = [
                item for item in db["photography_styles"]
                if not item.get("disabled", False)
            ]
            style = select_labeled(
                "CAMERA STYLE",
                grouped_catalog_choices(
                    styles, ("photo_",), ("Amateur", "Studio", "Editorial", "Explicit")
                ),
            )
            if style is None:
                continue
            new_context["photography_style"] = resolve_menu_choice(style, composer.rng)
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
    grouped: list[tuple[str, Any]] = [
        (
            "All groups",
            menu_pool((scene, float(item.get("weight", 1))) for item, scene in candidates),
        )
    ]
    if key == "pose":
        group_specs = (
            ("Everyday", lambda item: not tags(item) & {"erotic_pose", "explicit_pose", "nude_pose", "topless_pose"}),
            ("Erotic", lambda item: "explicit_pose" not in tags(item) and bool(tags(item) & {"erotic_pose", "nude_pose", "topless_pose"})),
            ("Explicit", lambda item: "explicit_pose" in tags(item)),
        )
    else:
        group_specs = (
            ("Everyday", lambda item: not tags(item) & {"undressing_action", "erotic_action", "sensual_action", "explicit_action", "explicit"}),
            ("Undressing", lambda item: "undressing_action" in tags(item)),
            ("Erotic", lambda item: "undressing_action" not in tags(item) and "explicit_action" not in tags(item) and "explicit" not in tags(item)),
            ("Explicit", lambda item: bool(tags(item) & {"explicit_action", "explicit"})),
        )
    assigned: set[str] = set()
    for group, predicate in group_specs:
        items = [(item, scene) for item, scene in candidates if item["id"] not in assigned and predicate(item)]
        if items:
            grouped.append(fzf_group(group))
            grouped.append((
                f"Any {group}",
                menu_pool((scene, float(item.get("weight", 1))) for item, scene in items),
            ))
            grouped.extend(
                (compact_item_label(item, ("pose_", "action_")), scene)
                for item, scene in items
            )
            assigned.update(item["id"] for item, _ in items)
    selected = select_labeled(
        f"Compatible {key}s for shot {shot['number']}",
        grouped,
    )
    if selected is None:
        return None
    return resolve_menu_choice(selected, composer.rng)


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
    grouped: list[tuple[str, Any]] = [
        (
            "All groups",
            menu_pool((scene, float(item.get("weight", 1))) for item, scene in candidates),
        )
    ]
    assigned_expressions: set[str] = set()
    for group, tag in (
        ("Natural", None),
        ("Intense", "intense_pleasure_expression"),
        ("Aroused", "aroused_expression"),
        ("Sensual", "pleasure_expression"),
    ):
        items = [
            (item, scene) for item, scene in candidates
            if item["id"] not in assigned_expressions
            and (not tags(item) if tag is None else tag in tags(item))
        ]
        if items:
            grouped.append(fzf_group(group))
            grouped.append((
                f"Any {group}",
                menu_pool((scene, float(item.get("weight", 1))) for item, scene in items),
            ))
            grouped.extend(
                (compact_item_label(item, ("expression_",)), scene)
                for item, scene in items
            )
            assigned_expressions.update(item["id"] for item, _ in items)
    selected = select_labeled(
        f"Compatible expressions for shot {shot['number']}",
        grouped,
    )
    if selected is None:
        return None
    return resolve_menu_choice(selected, composer.rng)


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
            print("1) Stage / XXX")
            print("2) Pose")
            print("3) Action")
            print("4) Expression")
            print("5) Reroll shot")
            print("6) View prompt")
            print("0) Back")
        choice = director_menu_choice(
            "Director's choice",
            [
                fzf_group("Composition"),
                ("Stage / XXX", "1"),
                ("Pose", "2"),
                ("Action", "3"),
                ("Expression", "4"),
                ("Reroll shot", "5"),
                fzf_group("Review & navigation"),
                ("View prompt", "6"),
                ("Back", "0"),
            ],
            "0",
        )
        if choice == "0":
            return
        if choice == "1":
            options = director_stage_options(shot, args.xxx_only)
            stage_choices: list[tuple[str, Any]] = []
            for level in ("covered", "lingerie", "topless", "nude", "explicit"):
                stages = [stage for stage in options if stage["level"] == level]
                if stages:
                    stage_choices.append(fzf_group(level))
                    stage_choices.extend(
                        (compact_item_label(stage, maximum_words=3), stage)
                        for stage in stages
                    )
            stage = select_labeled(
                f"Stage for shot {shot['number']}",
                stage_choices,
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
    render: bool | None,
) -> str:
    while True:
        show_storyboard(storyboard)
        if render is None:
            run_choices = [("Generate", "1"), ("Print prompts", "2")]
            reroll_code, design_code, reroll_shot_code = "3", "4", "5"
            direct_code, inspect_code = "6", "7"
        else:
            run_choices = [(("Generate" if render else "Print prompts"), "1")]
            reroll_code, design_code, reroll_shot_code = "2", "3", "4"
            direct_code, inspect_code = "5", "6"
        if not director_uses_fzf():
            for label, code in run_choices:
                print(f"{code}) {label}")
            print(f"{reroll_code}) Reroll storyboard")
            print(f"{design_code}) Design SET")
            print(f"{reroll_shot_code}) Reroll shot")
            print(f"{direct_code}) Direct shot")
            print(f"{inspect_code}) Inspect prompt")
            print("0) Cancel")
        choice = director_menu_choice(
            "Director's choice",
            [
                fzf_group("Run"),
                *run_choices,
                ("Reroll storyboard", reroll_code),
                fzf_group("Direct"),
                ("Design SET", design_code),
                ("Reroll shot", reroll_shot_code),
                ("Direct shot", direct_code),
                ("Inspect prompt", inspect_code),
                fzf_group("Exit"),
                ("Cancel", "0"),
            ],
            "1",
        )
        if choice == "1":
            return "generate" if render is None or render else "dry-run"
        if render is None and choice == "2":
            return "dry-run"
        if choice == reroll_code:
            return "reroll"
        if choice == "0":
            return "cancel"
        if choice in {design_code, reroll_shot_code, direct_code, inspect_code}:
            if choice == design_code and args.mode == "photoshoot":
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
                noun = "Choose an independent shot as its SET" if choice == design_code else "Choose a shot"
            index = select_labeled(
                noun,
                selection_choices,
            )
            if index is None:
                continue
            number = index + 1
            if choice == design_code:
                direct_set(args, db, composer, storyboard, index)
            elif choice == reroll_shot_code:
                shot = storyboard[index]
                shot["scene"] = composer.resolve_scene(shot["context"], shot["stage"])
                if args.inference_seed is None:
                    shot["inference_seed"] = secrets.randbelow(2**63)
            elif choice == direct_code:
                direct_one_shot(args, db, composer, storyboard, index)
            else:
                shot = storyboard[index]
                positive, negative, _ = compile_scene(db, shot["scene"])
                director_clear()
                print(f"SHOT {number}\n\nPOSITIVE\n{positive}\n\nNEGATIVE\n{negative}\n")
                director_input("Press Enter to return...")


def report_width() -> int:
    return max(72, min(shutil.get_terminal_size((100, 24)).columns, 120))


def report_heading(title: str, heavy: bool = False) -> None:
    width = report_width()
    fill = "═" if heavy else "─"
    label = f" {title} "
    remaining = max(0, width - len(label))
    left = remaining // 2
    print(f"{fill * left}{label}{fill * (remaining - left)}")


def report_field(label: str, value: Any) -> None:
    prefix = f"{label:<16} "
    lines = textwrap.wrap(
        str(value),
        width=max(20, report_width() - len(prefix)),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    print(prefix + lines[0])
    for line in lines[1:]:
        print(" " * len(prefix) + line)


def report_prompt(title: str, prompt: str) -> None:
    print(f"\n{title}")
    print("─" * min(len(title), report_width()))
    for line in textwrap.wrap(
        prompt,
        width=report_width(),
        initial_indent="  ",
        subsequent_indent="  ",
        break_long_words=False,
        break_on_hyphens=False,
    ) or ["  —"]:
        print(line)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)} min {remainder:.1f} s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours} h {minutes} min {remainder:.1f} s"


def run_batch(args: argparse.Namespace, render: bool | None) -> None:
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
        choose_output = render is None
        while True:
            decision = review_storyboard(args, db, composer, storyboard, render)
            if decision in {"generate", "dry-run"}:
                render = decision == "generate"
                if choose_output and render:
                    quality = select_labeled(
                        "QUALITY", [("Production", False), ("Fast test", True)]
                    )
                    if quality is None:
                        render = None
                        continue
                    args.fast = quality
                elif not render:
                    args.fast = False
                break
            if decision == "cancel":
                print("Cancelled by director.")
                return
            storyboard = build_storyboard(args, db, composer, rng, nsfw_percent, plateau_percent)

    if render is None:
        raise AppError("Output action was not selected")

    workflow_template: dict[str, Any] | None = None
    workflow_mapping: dict[str, Any] | None = None
    if render:
        workflow_template, workflow_mapping = load_workflow_runtime(
            db, db_path, args.fast
        )

    director_clear() if args.review_storyboard else None
    report_heading("VALHALLA RUN", heavy=True)
    report_field("Action", "Generate images" if render else "Print prompts")
    report_field("Mode", args.mode.title())
    report_field("Content", "Full XXX" if args.xxx_only else "Progressive")
    report_field("Photoshoots", photoshoot_count)
    report_field("Images", len(storyboard))
    report_field("Prompt seed", prompt_seed)
    report_field("Inference seed", args.inference_seed if args.inference_seed is not None else "Random per image")
    if render:
        report_field("Render profile", "Fast test" if args.fast else "Production")
    if args.mode == "photoshoot" and not args.xxx_only:
        report_field("NSFW ending", f"{nsfw_percent:g}%")
        report_field("XXX plateau", f"{plateau_percent:g}%")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_started = time.monotonic()
    announced_photoshoot = -1
    for shot in storyboard:
        photo = shot["photoshoot_index"]
        scene = shot["scene"]
        if args.mode == "photoshoot" and photo != announced_photoshoot:
            context = shot["context"]
            print()
            report_heading(f"SET {photo + 1} OF {photoshoot_count}", heavy=True)
            report_field("Subject", model_signature(context["human"]).replace("+", " + "))
            report_field("Wardrobe", template_label(context["outfit"]["template"]))
            report_field("Outfit", outfit_label(context["outfit"], limit=6))
            report_field("Location", context["interior"]["prompt"])
            report_field("Surface", context["furniture"]["prompt"])
            report_field("Mood", context["mood"]["prompt"])
            report_field("Camera", context["photography_style"]["prompt"])
            announced_photoshoot = photo
        positive, negative, selected_ids = compile_scene(db, scene)
        print()
        shot_title = (
            f"PHOTOSHOOT {photo + 1}/{photoshoot_count} · "
            f"IMAGE {shot['shot_index'] + 1}/{args.count} · "
            f"BATCH {shot['number']}/{len(storyboard)} · "
            f"{shot['stage']['level'].upper()}"
        )
        report_heading(shot_title)
        report_field("Photoshoot", f"{photo + 1}/{photoshoot_count}")
        report_field("Image", f"{shot['shot_index'] + 1}/{args.count}")
        report_field("Batch progress", f"{shot['number']}/{len(storyboard)}")
        if args.mode == "random":
            report_field("Subject", model_signature(scene["human"]).replace("+", " + "))
            report_field("Wardrobe", template_label(scene["outfit"]["template"]))
            report_field("Location", scene["interior"]["prompt"])
        report_field("Stage", shot["stage"]["id"])
        report_field("Inference seed", shot["inference_seed"])
        report_field("Pose", scene["pose"]["prompt"])
        report_field("Action", scene["action"]["prompt"])
        report_field("Expression", scene["expression"]["prompt"])
        report_field("Selected IDs", ", ".join(selected_ids))
        report_prompt("POSITIVE PROMPT", positive)
        report_prompt("NEGATIVE PROMPT", negative)
        if render:
            assert workflow_template is not None and workflow_mapping is not None
            generation_started = time.monotonic()
            prompt_id, paths = generate_one(
                db, db_path, positive, negative, shot["inference_seed"], args.mode,
                shot["shot_index"], photo, run_id, args.fast,
                workflow_template, workflow_mapping,
            )
            generation_seconds = time.monotonic() - generation_started
            completed_images = shot["number"]
            remaining_images = len(storyboard) - completed_images
            batch_elapsed = time.monotonic() - batch_started
            average_seconds = batch_elapsed / completed_images
            remaining_seconds = average_seconds * remaining_images
            estimated_finish = datetime.now() + timedelta(seconds=remaining_seconds)
            print()
            report_heading("RENDER RESULT")
            report_field("Prompt ID", prompt_id)
            report_field("Generation time", format_duration(generation_seconds))
            report_field("Job elapsed", format_duration(batch_elapsed))
            report_field("Average / image", format_duration(average_seconds))
            report_field("Images remaining", remaining_images)
            report_field("Time remaining", format_duration(remaining_seconds))
            report_field(
                "Estimated finish",
                estimated_finish.strftime("%Y-%m-%d %H:%M:%S"),
            )
            for path in paths:
                report_field("File", path.name)
                report_field("Saved to", path.parent)
    print()
    report_heading("RUN COMPLETE", heavy=True)


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


@dataclass
class WizardState:
    mode: str = "photoshoot"
    count: int = 10
    photoshoots: int = 1
    prompt_seed: int | None = None
    inference_seed: int | None = None
    xxx_only: bool = False
    review_storyboard: bool = True
    nsfw_percent: float | None = None
    plateau_percent: float | None = None


def wizard_input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError as exc:
        raise AppError("Interactive input closed") from exc


def wizard_integer(prompt: str, current: int, minimum: int = 1) -> int:
    while True:
        raw = wizard_input(f"{prompt} [{current}]: ")
        if not raw:
            return current
        try:
            value = int(raw)
        except ValueError:
            value = minimum - 1
        if value >= minimum:
            return value
        print(f"Enter a whole number of at least {minimum}.")


def wizard_optional_integer(
    prompt: str, current: int | None, maximum: int | None = None
) -> int | None:
    shown = "Random" if current is None else str(current)
    while True:
        raw = wizard_input(f"{prompt} [{shown}; blank keeps]: ")
        if not raw:
            return current
        if raw.lower() in {"r", "random", "none"}:
            return None
        try:
            value = int(raw)
        except ValueError:
            print("Enter a whole number or 'random'.")
            continue
        if maximum is not None and not 0 <= value <= maximum:
            print(f"Enter a value from 0 through {maximum}.")
            continue
        return value


def wizard_percent(prompt: str, current: float) -> float:
    while True:
        raw = wizard_input(f"{prompt} [{current:g}]: ")
        if not raw:
            return current
        try:
            return percent_value(raw)
        except (ValueError, argparse.ArgumentTypeError):
            print("Enter a number from 0 through 100.")


def wizard_summary(state: WizardState, db: dict[str, Any]) -> str:
    progression = db["settings"].get("photoshoot_progression", {})
    nsfw = state.nsfw_percent
    if nsfw is None:
        nsfw = float(progression.get("nsfw_final_percent", 50))
    plateau = state.plateau_percent
    if plateau is None:
        plateau = float(progression.get("explicit_plateau_percent", 30))
    batch = (
        f"{state.photoshoots} × {state.count} = {state.photoshoots * state.count}"
        if state.mode == "photoshoot" else str(state.count)
    )
    rows = [
        f"Mode            {state.mode.title()}",
        f"Content         {'Full XXX' if state.xxx_only else 'Progressive'}",
        f"Batch           {batch} images",
        f"Director        {'Interactive' if state.review_storyboard else 'Automatic'}",
    ]
    rows.extend([
        f"Prompt seed     {state.prompt_seed if state.prompt_seed is not None else 'Random'}",
        f"Inference seed  {state.inference_seed if state.inference_seed is not None else 'Random per image'}",
    ])
    if state.mode == "photoshoot" and not state.xxx_only:
        total = state.photoshoots * state.count
        rows.extend([
            f"NSFW ending     {nsfw:g}% (~{math.ceil(total * nsfw / 100)})",
            f"XXX plateau     {plateau:g}% (~{math.ceil(total * plateau / 100)})",
        ])
    return "\n".join(rows)


def wizard_advanced(state: WizardState, db: dict[str, Any]) -> None:
    progression = db["settings"].get("photoshoot_progression", {})
    while True:
        choices: list[tuple[str, Any]] = [
            fzf_group("Randomness"),
            (f"Prompt · {state.prompt_seed if state.prompt_seed is not None else 'Random'}", "prompt"),
            (f"Inference · {state.inference_seed if state.inference_seed is not None else 'Random'}", "inference"),
        ]
        if state.mode == "photoshoot" and not state.xxx_only:
            nsfw = state.nsfw_percent
            if nsfw is None:
                nsfw = float(progression.get("nsfw_final_percent", 50))
            plateau = state.plateau_percent
            if plateau is None:
                plateau = float(progression.get("explicit_plateau_percent", 30))
            choices.extend([
                fzf_group("Progression"),
                (f"NSFW · {nsfw:g}%", "nsfw"),
                (f"Plateau · {plateau:g}%", "plateau"),
            ])
        selected = select_labeled("ADVANCED", choices)
        if selected is None:
            return
        if selected == "prompt":
            state.prompt_seed = wizard_optional_integer("Prompt seed", state.prompt_seed)
        elif selected == "inference":
            state.inference_seed = wizard_optional_integer(
                "Inference seed", state.inference_seed, 2**64 - 1
            )
        elif selected in {"nsfw", "plateau"}:
            default_nsfw = float(progression.get("nsfw_final_percent", 50))
            default_plateau = float(progression.get("explicit_plateau_percent", 30))
            if selected == "nsfw":
                state.nsfw_percent = wizard_percent(
                    "NSFW ending", state.nsfw_percent if state.nsfw_percent is not None else default_nsfw
                )
            else:
                state.plateau_percent = wizard_percent(
                    "XXX plateau", state.plateau_percent if state.plateau_percent is not None else default_plateau
                )


def wizard_namespace(
    state: WizardState, action: str = "dry-run", fast: bool = False
) -> argparse.Namespace:
    return argparse.Namespace(
        command=action,
        mode=state.mode,
        count=state.count,
        photoshoots=state.photoshoots if state.mode == "photoshoot" else 1,
        prompt_seed=state.prompt_seed,
        inference_seed=state.inference_seed,
        fast=fast if action == "generate" else False,
        xxx_only=state.xxx_only,
        review_storyboard=state.review_storyboard,
        nsfw_percent=state.nsfw_percent if state.mode == "photoshoot" and not state.xxx_only else None,
        plateau_percent=state.plateau_percent if state.mode == "photoshoot" and not state.xxx_only else None,
    )


def wizard_configure(state: WizardState, db: dict[str, Any]) -> bool:
    while True:
        mode = state.mode.title()
        content = "Full XXX" if state.xxx_only else "Progressive"
        batch = f"{state.photoshoots} × {state.count}" if state.mode == "photoshoot" else f"{state.count} images"
        director = "Interactive" if state.review_storyboard else "Automatic"
        choices: list[tuple[str, Any]] = [
            fzf_group("Run"),
            (("Open Director" if state.review_storyboard else "Start run"), "start"),
            fzf_group("Setup"),
            (f"Mode · {mode}", "mode"),
            (f"Content · {content}", "content"),
            (f"Batch · {batch}", "batch"),
            (f"Director · {director}", "director"),
        ]
        choices.extend([fzf_group("Options"), ("Advanced", "advanced"), ("Reset", "reset")])
        selected = select_labeled(
            "CONFIGURE", choices, preamble=wizard_summary(state, db)
        )
        if selected is None:
            return False
        if selected == "start":
            progression = db["settings"].get("photoshoot_progression", {})
            nsfw = state.nsfw_percent if state.nsfw_percent is not None else float(progression.get("nsfw_final_percent", 50))
            plateau = state.plateau_percent if state.plateau_percent is not None else float(progression.get("explicit_plateau_percent", 30))
            if plateau > nsfw:
                director_input("XXX plateau exceeds NSFW ending. Press Enter...")
                continue
            if state.review_storyboard:
                run_batch(wizard_namespace(state), render=None)
                return True
            action = select_labeled(
                "OUTPUT", [("Generate", "generate"), ("Dry run", "dry-run")]
            )
            if action is None:
                continue
            fast = False
            if action == "generate":
                quality = select_labeled(
                    "QUALITY", [("Production", False), ("Fast test", True)]
                )
                if quality is None:
                    continue
                fast = quality
            confirmed = select_labeled(
                "CONFIRM", [("Start run", True), ("Cancel", MENU_BACK)],
                preamble=(
                    wizard_summary(state, db)
                    + f"\nOutput          {'Generate' if action == 'generate' else 'Dry run'}"
                    + (f"\nQuality         {'Fast test' if fast else 'Production'}" if action == "generate" else "")
                ),
            )
            if confirmed:
                run_batch(
                    wizard_namespace(state, action=action, fast=fast),
                    render=action == "generate",
                )
                return True
        elif selected == "mode":
            value = select_labeled("MODE", [("Photoshoot", "photoshoot"), ("Random", "random")])
            if value:
                state.mode = value
        elif selected == "content":
            value = select_labeled("CONTENT", [("Progressive", False), ("Full XXX", True)])
            if value is not None:
                state.xxx_only = value
        elif selected == "batch":
            director_clear()
            if state.mode == "photoshoot":
                state.photoshoots = wizard_integer("Photoshoots", state.photoshoots)
            state.count = wizard_integer("Images", state.count)
        elif selected == "director":
            value = select_labeled("DIRECTOR", [("Automatic", False), ("Interactive", True)])
            if value is not None:
                state.review_storyboard = value
        elif selected == "advanced":
            wizard_advanced(state, db)
        elif selected == "reset":
            state.__dict__.update(WizardState().__dict__)


def run_wizard(parser: argparse.ArgumentParser) -> None:
    db, db_path = load_database()
    state = WizardState()
    while True:
        selected = select_labeled(
            "MAIN MENU",
            [
                fzf_group("Create"),
                ("New run", "run"),
                fzf_group("Tools"),
                ("Capture workflow", "capture"),
                ("Help", "help"),
                fzf_group("Exit"),
                ("Exit", MENU_BACK),
            ],
            preamble=(
                f"ComfyUI  {db['settings']['comfy_url']}\n"
                f"Workflow {db['settings']['workflow_file']}\n"
                f"Output   {db['settings']['output_dir']}"
            ),
        )
        if selected is None:
            return
        if selected == "run":
            if wizard_configure(state, db):
                return
        elif selected == "capture":
            capture_mode = select_labeled(
                "CAPTURE", [("Capture safe", False), ("Replace workflow", True)]
            )
            if capture_mode is not None:
                capture(db, db_path, capture_mode)
                return
        elif selected == "help":
            director_clear()
            parser.print_help()
            director_input("\nPress Enter...")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rule-based prompt composer for ComfyUI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("wizard", help="Open the interactive FZF launcher")
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
            "--fast",
            action="store_true",
            help="Render only the base sampler and VAE output, bypassing LoRA and pruning refiners/detailers",
        )
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
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "wizard":
            run_wizard(parser)
        elif args.command == "capture":
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
