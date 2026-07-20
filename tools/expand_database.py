#!/usr/bin/env python3
"""One-shot curated expansion for database.json; safe to rerun."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "database.json"
VARIANTS = ("studio", "editorial")


def add_unique(items, records):
    known = {item["id"] for item in items}
    for record in records:
        if record["id"] not in known:
            items.append(record)
            known.add(record["id"])
        else:
            existing = next(item for item in items if item["id"] == record["id"])
            items[items.index(existing)] = record


def simple_garments(prefix, prompts, tags, colors=None):
    return [
        {
            "id": f"{prefix}_{index:02d}", "prompt": prompt,
            "tags": list(tags), **({"allowed_colors": colors} if colors else {}),
        }
        for index, prompt in enumerate(prompts, 1)
    ]


def curated(db):
    common_colors = ["color_white", "color_black", "color_gray", "color_navy", "color_beige", "color_chocolate"]
    add_unique(db["interiors"], [
        {"id": f"interior_apartment_{slug}", "prompt": prompt, "tags": tags}
        for slug, prompt, tags in [
            ("compact_bedroom", "inside a compact ordinary apartment bedroom", ["indoor", "bedroom", "intimate", "apartment"]),
            ("sunny_bedroom", "inside a sunny rented apartment bedroom", ["indoor", "bedroom", "intimate", "apartment", "window"]),
            ("minimal_bedroom", "inside a simple minimalist apartment bedroom", ["indoor", "bedroom", "intimate", "apartment"]),
            ("attic_bedroom", "inside a private attic apartment bedroom", ["indoor", "bedroom", "intimate", "apartment", "window"]),
            ("studio_flat", "inside an open-plan studio flat", ["indoor", "living_room", "apartment", "private"]),
            ("small_living_room", "inside a small lived-in apartment living room", ["indoor", "living_room", "apartment", "private"]),
            ("modern_living_room", "inside a clean modern apartment living room", ["indoor", "living_room", "apartment", "private"]),
            ("vintage_living_room", "inside a modest vintage apartment living room", ["indoor", "living_room", "apartment", "private"]),
            ("loft_living_room", "inside a private brick-walled loft living room", ["indoor", "living_room", "apartment", "private"]),
            ("kitchen", "inside a simple private apartment kitchen", ["indoor", "kitchen", "apartment", "private"]),
            ("breakfast_nook", "inside a bright apartment breakfast nook", ["indoor", "kitchen", "apartment", "private", "window"]),
            ("hallway", "inside a quiet private apartment hallway", ["indoor", "hallway", "apartment", "private"]),
            ("entryway", "inside a tidy apartment entryway", ["indoor", "hallway", "apartment", "private"]),
            ("bathroom", "inside a clean ordinary apartment bathroom", ["indoor", "bathroom", "private", "wet"]),
            ("tile_bathroom", "inside a small softly lit tiled bathroom", ["indoor", "bathroom", "private", "wet"]),
            ("laundry", "inside a private apartment laundry room", ["indoor", "utility_room", "private"]),
            ("home_office", "inside a simple private home office", ["indoor", "office", "private", "apartment"]),
            ("dressing_room", "inside a modest private dressing room", ["indoor", "dressing_room", "private"]),
            ("walkin_closet", "inside a compact private walk-in closet", ["indoor", "dressing_room", "private"]),
            ("balcony", "on a secluded apartment balcony", ["outdoor", "balcony", "private", "apartment"]),
            ("basement_studio", "inside a plain private basement photo set", ["indoor", "studio", "private"]),
            ("paper_backdrop", "inside a simple studio with a seamless paper backdrop", ["indoor", "studio", "private"]),
            ("curtain_set", "inside a minimal private set with plain curtains", ["indoor", "studio", "private"]),
            ("daylight_set", "inside a small daylight photo studio", ["indoor", "studio", "private", "window"]),
        ]
    ])
    add_unique(db["furniture"], [
        {"id": "furniture_simple_mattress", "prompt": "on a simple neatly covered mattress", "tags": ["bed", "lying_surface", "sitting_surface"], "requires_tags": ["bedroom"]},
        {"id": "furniture_bed_edge", "prompt": "on the edge of an ordinary bed", "tags": ["bed", "sitting_surface"], "requires_tags": ["bedroom"]},
        {"id": "furniture_small_sofa", "prompt": "on a compact everyday sofa", "tags": ["sofa", "lying_surface", "sitting_surface"], "requires_tags": ["living_room"]},
        {"id": "furniture_floor_cushion", "prompt": "on a large floor cushion", "tags": ["floor", "lying_surface", "sitting_surface"], "requires_tags": ["indoor"]},
        {"id": "furniture_plain_wall", "prompt": "against a clean plain wall", "tags": ["wall", "standing_surface"], "requires_tags": ["indoor"]},
        {"id": "furniture_kitchen_counter", "prompt": "beside a clean apartment kitchen counter", "tags": ["counter", "standing_surface"], "requires_tags": ["kitchen"]},
        {"id": "furniture_breakfast_chair", "prompt": "on a simple breakfast chair", "tags": ["chair", "sitting_surface"], "requires_tags": ["kitchen"]},
        {"id": "furniture_bath_mat", "prompt": "on a clean soft bathroom mat", "tags": ["floor", "lying_surface", "sitting_surface"], "requires_tags": ["bathroom"]},
        {"id": "furniture_studio_floor", "prompt": "on a clean seamless studio floor", "tags": ["floor", "lying_surface", "sitting_surface", "standing_surface"], "requires_tags": ["studio"]},
        {"id": "furniture_window_ledge", "prompt": "beside a broad private window ledge", "tags": ["window", "sitting_surface", "standing_surface"], "requires_tags": ["window"]},
    ])

    garment_sets = {
        "upperwear": simple_garments("top_simple", ["plain crew-neck T-shirt", "soft ribbed tank top", "simple long-sleeve jersey top", "relaxed cotton henley", "basic fitted camisole", "cropped everyday sweatshirt", "plain scoop-neck top", "light cotton button-up shirt", "simple knit pullover", "fitted mock-neck top"], ["casual", "everyday", "normal_clothes"], common_colors),
        "lowerwear": simple_garments("bottom_simple", ["straight-leg everyday jeans", "plain lightweight jersey shorts", "soft lounge shorts", "simple fitted leggings", "casual denim skirt", "plain knee-length skirt", "relaxed jersey trousers", "high-waisted cotton shorts", "simple pleated skirt", "comfortable drawstring pants"], ["casual", "everyday", "normal_clothes"], common_colors),
        "full_body": simple_garments("dress_simple", ["simple cotton T-shirt dress", "plain fitted jersey dress", "casual button-front dress", "soft ribbed midi dress", "minimal sleeveless dress", "simple wrap dress", "relaxed sweater dress", "plain tank dress", "casual denim dress", "clean-lined knit dress"], ["dress", "casual", "normal_clothes"], common_colors),
        "outerwear": simple_garments("outer_simple", ["plain zip hoodie", "light everyday cardigan", "simple denim jacket", "unstructured cotton blazer", "soft lounge robe", "light rain jacket", "plain track jacket", "simple knitted cardigan"], ["casual", "normal_clothes"], common_colors),
        "bra": simple_garments("bra_simple", ["plain cotton bra", "smooth everyday T-shirt bra", "simple wireless bra", "minimal triangle bra", "soft ribbed bralette", "plain demi-cup bra", "simple balconette bra", "lightly lined everyday bra"], ["everyday", "lingerie"], common_colors),
        "panties": simple_garments("panties_simple", ["plain cotton briefs", "simple bikini panties", "smooth hipster panties", "soft high-waisted panties", "minimal seamless thong", "plain cheeky panties", "simple boyshort panties", "soft ribbed panties", "minimal high-cut panties", "smooth low-rise panties"], ["everyday"], common_colors),
        "legwear": simple_garments("legwear_simple", ["plain ankle socks", "soft knee-high socks", "simple opaque tights", "plain sheer pantyhose", "basic thigh-high stockings", "ribbed crew socks", "soft over-knee socks", "minimal sheer stockings"], ["socks", "everyday"], common_colors),
        "footwear": simple_garments("shoes_simple", ["plain white canvas sneakers", "simple black ballet flats", "low block-heel pumps", "minimal leather loafers", "soft house slippers", "basic ankle boots", "simple flat sandals", "clean running shoes", "low kitten heels", "plain court shoes", "casual slip-on sneakers", "simple suede flats", "minimal strappy heels", "comfortable platform sandals", "plain leather sneakers", "soft moccasin slippers", "simple heeled ankle boots", "basic rubber slides"], ["casual", "everyday", "normal_clothes"], common_colors),
        "accessories": simple_garments("accessory_simple", ["small hoop earrings", "fine chain necklace", "simple wristwatch", "thin leather belt", "minimal stud earrings", "soft fabric headband", "delicate ankle chain", "plain hair clip"], ["everyday"], common_colors),
    }
    for section, records in garment_sets.items():
        add_unique(db["garments"][section], records)

    add_unique(db["poses"], [
        {"id": f"pose_curated_{index:02d}", "prompt": prompt, "tags": tags, "requires_tags": requires, "allowed_levels": levels}
        for index, (prompt, tags, requires, levels) in enumerate([
            ("standing with one knee softly bent and weight on the back leg", ["standing"], [], ["covered", "lingerie", "topless", "nude"]),
            ("standing in a relaxed contrapposto with one hand at her waist", ["standing"], [], ["covered", "lingerie", "topless", "nude"]),
            ("sitting sideways on the edge with ankles crossed", ["sitting"], ["sitting_surface"], ["covered", "lingerie", "topless", "nude"]),
            ("sitting upright with both feet grounded and shoulders relaxed", ["sitting"], ["sitting_surface"], ["covered", "lingerie", "topless", "nude"]),
            ("kneeling upright with thighs together and hands resting lightly", ["kneeling"], ["floor"], ["covered", "lingerie", "topless", "nude"]),
            ("lying on her side with knees softly stacked", ["lying"], ["lying_surface"], ["lingerie", "topless", "nude"]),
            ("lying face-down with calves raised and feet loosely crossed", ["lying"], ["lying_surface"], ["lingerie", "topless", "nude"]),
            ("standing rear-facing with an arched lower back and legs apart", ["explicit_pose", "provocative_rear", "standing"], ["genitals"], ["explicit"]),
            ("kneeling rear-facing with hips raised and torso lowered", ["explicit_pose", "provocative_rear", "kneeling"], ["floor", "genitals"], ["explicit"]),
            ("on all fours with knees wide and hips angled toward camera", ["explicit_pose", "provocative_rear", "all_fours"], ["lying_surface", "genitals"], ["explicit"]),
            ("bent forward with hands braced and a direct rear presentation", ["explicit_pose", "provocative_rear", "standing"], ["standing_surface", "genitals"], ["explicit"]),
            ("lying back with knees drawn high and spread symmetrically", ["explicit_pose", "masturbation_pose", "open_legs", "lying", "legs_up"], ["lying_surface", "genitals"], ["explicit"]),
            ("reclining with one leg extended and the other opened wide", ["explicit_pose", "masturbation_pose", "open_legs", "lying"], ["lying_surface", "genitals"], ["explicit"]),
            ("sitting near the edge with knees wide and pelvis tipped forward", ["explicit_pose", "masturbation_pose", "open_legs", "sitting"], ["sitting_surface", "genitals"], ["explicit"]),
            ("kneeling with knees spread and torso held upright", ["explicit_pose", "masturbation_pose", "open_legs", "kneeling"], ["floor", "genitals"], ["explicit"]),
            ("lying back with ankles crossed above her chest", ["explicit_pose", "masturbation_pose", "open_legs", "lying", "legs_up"], ["lying_surface", "genitals"], ["explicit"]),
            ("reclining diagonally with one knee hooked outward", ["explicit_pose", "masturbation_pose", "open_legs", "lying"], ["lying_surface", "genitals"], ["explicit"]),
            ("squatting low with knees spread and balance held at the heels", ["explicit_pose", "masturbation_pose", "open_legs", "squatting"], ["floor", "genitals"], ["explicit"]),
            ("lying sideways with the upper leg lifted to expose her vulva", ["explicit_pose", "intimate_closeup", "open_legs", "lying"], ["lying_surface", "genitals"], ["explicit"]),
            ("reclining with thighs opened close to the lens for an intimate view", ["explicit_pose", "intimate_closeup", "open_legs", "lying"], ["lying_surface", "genitals"], ["explicit"]),
        ], 1)
    ])
    add_unique(db["actions"], [
        {"id": f"action_curated_{index:02d}", "prompt": prompt, "tags": tags, "requires_tags": requires, "allowed_levels": levels, **extra}
        for index, (prompt, tags, requires, levels, extra) in enumerate([
            ("adjusting the hem of her top with a casual natural gesture", ["fashion_action"], [], ["covered", "lingerie"], {}),
            ("sliding one hand through her hair while holding the pose", ["fashion_action"], [], ["covered", "lingerie", "topless", "nude"], {}),
            ("slowly drawing one shoulder strap down while keeping her chest covered", ["undressing_action", "erotic_action"], [], ["lingerie"], {}),
            ("unfastening her waistband with deliberate teasing eye contact", ["undressing_action", "erotic_action"], [], ["covered", "lingerie"], {}),
            ("pulling her panties down to mid-thigh in a deliberate reveal", ["explicit_action", "panties_aside_action"], ["genitals", "open_legs"], ["explicit"], {}),
            ("holding her panties aside with two fingers for an unobstructed view", ["explicit_action", "panties_aside_action"], ["genitals", "open_legs"], ["explicit"], {}),
            ("spreading her buttocks with both hands in a direct rear display", ["explicit_action", "provocative_action"], ["genitals", "provocative_rear"], ["explicit"], {}),
            ("looking back while gripping one buttock and presenting from behind", ["explicit_action", "provocative_action"], ["genitals", "provocative_rear"], ["explicit"], {}),
            ("reaching between her thighs and slowly rubbing her exposed clitoris", ["explicit_action", "masturbation_action"], ["genitals", "open_legs"], ["explicit"], {}),
            ("using two fingers in a steady circular motion over her clitoris", ["explicit_action", "masturbation_action"], ["genitals", "open_legs"], ["explicit"], {}),
            ("sliding two fingers inside herself while keeping her thighs spread", ["explicit_action", "masturbation_action"], ["genitals", "open_legs"], ["explicit"], {}),
            ("pumping her fingers inside herself with her pelvis lifted", ["explicit_action", "masturbation_action"], ["genitals", "open_legs"], ["explicit"], {"requires_expression_tags": ["pleasure_expression"]}),
            ("holding her labia open with one hand while rubbing with the other", ["explicit_action", "closeup_action", "masturbation_action"], ["genitals", "open_legs"], ["explicit"], {}),
            ("spreading her vulva open with both hands for a direct intimate display", ["explicit_action", "closeup_action"], ["genitals", "open_legs"], ["explicit"], {}),
            ("pressing firmly between her thighs while arching into her hand", ["explicit_action", "masturbation_action"], ["genitals", "open_legs"], ["explicit"], {"requires_expression_tags": ["pleasure_expression"]}),
            ("alternating slow penetration and clitoral rubbing with her fingers", ["explicit_action", "masturbation_action"], ["genitals", "open_legs"], ["explicit"], {"requires_expression_tags": ["pleasure_expression"]}),
            ("tugging gently at both nipples while keeping her legs spread", ["explicit_action", "closeup_action"], ["breasts", "nipples"], ["explicit"], {}),
            ("squeezing her breasts together for a tight frontal display", ["explicit_action", "closeup_action"], ["breasts", "nipples"], ["explicit"], {}),
            ("tensing through a hands-only climax with fingers still between her thighs", ["explicit_action", "masturbation_action", "explicit"], ["genitals", "open_legs"], ["explicit"], {"requires_expression_tags": ["intense_pleasure_expression"]}),
            ("holding herself open immediately after climax with visibly trembling thighs", ["explicit_action", "closeup_action", "explicit"], ["genitals", "open_legs"], ["explicit"], {"requires_expression_tags": ["intense_pleasure_expression"]}),
        ], 1)
    ])


def suffix_for(section, variant):
    suffixes = {
        "interiors": ("clean uncluttered setting, soft natural light", "subtle lived-in details, warm practical lighting"),
        "furniture": ("clean practical placement", "natural casual placement"),
        "poses": ("balanced weight, relaxed shoulders, natural spine", "stronger hip shift, elongated posture, defined body lines"),
        "actions": ("slow deliberate movement", "confident sustained movement"),
        "expressions": ("relaxed eyelids and natural facial tension", "focused eyes and clearly defined expression"),
        "garments": ("clean well-defined silhouette, realistic fabric", "natural fabric drape, crisp visible edges"),
        "garment_footwear": ("clean well-defined shape, realistic material", "crisp contours and polished finish"),
        "garment_accessories": ("minimal understated styling", "clearly visible refined detail"),
        "human": ("subtle natural asymmetry and realistic detail", "clearly defined natural features"),
        "camera": ("clean balanced composition", "strong perspective and tighter visual emphasis"),
        "explicit_recipes": ("clear natural anatomy and coherent body position", "direct tight composition and clearly visible anatomy"),
        "props": ("placed naturally within reach", "clearly visible in the composition"),
        "moods": ("soft restrained atmosphere", "strong cinematic atmosphere"),
        "photography_styles": ("clean commercial lighting and realistic detail", "cinematic contrast and crisp photographic detail"),
        "other": ("clean natural detail", "strong clear visual definition"),
    }
    return suffixes.get(section, suffixes["garments" if section.startswith("garment_") else "other"])[VARIANTS.index(variant)]


def variant_prompt(prompt, section, variant):
    if section == "colors":
        return f"{prompt}, {'low saturation' if variant == 'studio' else 'deep saturated tone'}"
    if section == "patterns":
        return f"{'small-scale subtle' if variant == 'studio' else 'bold high-contrast'} {prompt}"
    if section == "fabric_textures":
        return f"{'fine lightweight' if variant == 'studio' else 'pronounced tactile'} {prompt}"
    if section == "poses":
        folded = prompt.casefold()
        if any(word in folded for word in ("lying", "reclining", "face-down")):
            suffix = "relaxed limbs and natural spinal curve" if variant == "studio" else "elongated torso and clearly defined hip line"
            return f"{prompt}, {suffix}"
        if any(word in folded for word in ("rear", "all fours", "bent")):
            suffix = "natural spinal curve and balanced support" if variant == "studio" else "stronger lower-back arch and clearly defined hip line"
            return f"{prompt}, {suffix}"
    return f"{prompt}, {suffix_for(section, variant)}"


def clone_records(items, section, stage_ids=False):
    originals = [item for item in items if not item.get("expansion_source")]
    known = {item["id"] for item in items}
    mapping = {}
    additions = []
    for item in originals:
        for variant in VARIANTS:
            new_id = f"{item['id']}_{variant}"
            mapping.setdefault(item["id"], []).append(new_id)
            existing = next((candidate for candidate in items if candidate["id"] == new_id), None)
            record = copy.deepcopy(item)
            record["id"] = new_id
            record["expansion_source"] = item["id"]
            record["expansion_variant"] = variant
            if item.get("prompt"):
                record["prompt"] = variant_prompt(item["prompt"], section, variant)
            if record.get("menu_label"):
                record["menu_label"] = f"{record['menu_label']} · {variant.title()}"
            if stage_ids:
                for stage in record.get("stages", []):
                    stage["id"] = f"{stage['id']}_{variant}"
            record["weight"] = max(0.35, float(record.get("weight", 1)) * (0.86 if variant == "studio" else 0.72))
            if existing is None:
                additions.append(record)
                known.add(new_id)
            else:
                items[items.index(existing)] = record
    items.extend(additions)
    return mapping


def expand(db):
    mappings = {}
    for category, items in db["human_model_parts"].items():
        mappings.update(clone_records(items, "human"))
    mappings.update(clone_records(db["colors"], "colors"))
    for section in ("patterns", "fabric_textures"):
        mappings.update(clone_records(db[section], section))
    garment_mapping = {}
    for section, items in db["garments"].items():
        garment_mapping.update(clone_records(items, f"garment_{section}"))
    mappings.update(garment_mapping)
    clone_records(db["outfit_templates"], "other", stage_ids=True)
    for section in ("shot_sizes", "camera_angles", "framings", "focus_targets", "editorial_roles"):
        clone_records(db[section], "camera")
    for section in ("explicit_recipes", "props", "moods", "photography_styles"):
        clone_records(db[section], section)
    for section in ("poses", "actions", "expressions"):
        clone_records(db[section], section)
    for section in ("interiors", "furniture"):
        clone_records(db[section], section)

    for section in ("patterns", "fabric_textures"):
        for item in db[section]:
            expanded = []
            for garment_id in item.get("allowed_garment_ids", []):
                expanded.append(garment_id)
                expanded.extend(garment_mapping.get(garment_id, []))
            item["allowed_garment_ids"] = list(dict.fromkeys(expanded))
    for items in db["garments"].values():
        for item in items:
            expanded = []
            for color_id in item.get("allowed_colors", []):
                expanded.append(color_id)
                expanded.extend(mappings.get(color_id, []))
            if expanded:
                item["allowed_colors"] = list(dict.fromkeys(expanded))
    for pool in db["settings"].get("human_defaults", {}).get("pools", {}).values():
        for source in list(pool):
            pool.extend(item for item in mappings.get(source, []) if item not in pool)
    for pool in db["settings"].get("scene_defaults", {}).get("pools", {}).values():
        for source in list(pool):
            pool.extend(item for item in mappings.get(source, []) if item not in pool)


def main():
    db = json.loads(DB_PATH.read_text())
    curated(db)
    expand(db)
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
