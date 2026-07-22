#!/usr/bin/env python3
"""Small deterministic Visual QA batches rendered through PreviewImage only."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server as app


DEFAULT_PHOTOSHOOTS = 10
DEFAULT_SHOTS = 8
MAX_PHOTOSHOOTS = 20
MAX_SHOTS = 12
MAX_REVIEW_BYTES = 100_000
REVIEW_FLAGS = (
    "anatomy",
    "orientation",
    "pose_match",
    "action_match",
    "camera_match",
    "clothing_leakage",
    "garment_layering",
    "framing",
)


def case_kind(shot: dict[str, Any]) -> str:
    scene = shot["scene"]
    stage = shot["stage"]
    recipe = scene.get("explicit_recipe") or {}
    plateau = stage.get("plateau_kind") or recipe.get("plateau_kind")
    if plateau:
        return f"explicit:{plateau}:{recipe.get('id', 'no_recipe')}"
    return f"stage:{stage['level']}"


def _uses_non_default_subject(record: dict[str, Any], number: int) -> bool:
    human = record["shots"][number - 1]["context"]["human"]
    pools = record["db"]["settings"].get("human_defaults", {}).get("pools", {})
    return any(
        category in pools
        and isinstance(value, dict)
        and value["id"] not in set(pools[category])
        for category, value in human.items()
    )


def build_record(photoshoots: int, shots: int, master_seed: int) -> dict[str, Any]:
    """Resolve a deterministic 50/50 board and broaden each shoot in Director."""
    state = app.WebState()
    board = state.create_storyboard({
        "mode": "photoshoot",
        "count": shots,
        "photoshoots": photoshoots,
        "prompt_seed": master_seed,
        "inference_seed": master_seed + 1,
        "inference_strategy": "sequence",
        "nsfw_percent": 50,
        "plateau_percent": 25,
    })
    storyboard_id = board["id"]
    for photoshoot in range(photoshoots):
        first_shot = photoshoot * shots + 1
        # Director remixes intentionally draw from the complete enabled database,
        # not only the casual default pools. Retrying is deterministic because the
        # storyboard RNG is itself seeded by master_seed.
        for _ in range(8):
            state.update_director(storyboard_id, {
                "shot": first_shot, "field": "remix.subject", "value": "1",
            })
            record = state.get_storyboard(storyboard_id)
            if _uses_non_default_subject(record, first_shot):
                break
        for _ in range(8):
            try:
                state.update_director(storyboard_id, {
                    "shot": first_shot, "field": "remix.scene", "value": "1",
                })
                break
            except app.AppError:
                # A random interior can make the fixed wardrobe impossible.
                # Replacements are atomic, so retrying advances the seeded RNG
                # without corrupting the last valid context.
                continue
    return state.get_storyboard(storyboard_id)


def audit_entry(shot: dict[str, Any], index: int) -> dict[str, Any]:
    scene = shot["scene"]
    positive, negative, selected_ids = app.compile_scene(scene["_qa_db"], scene)
    return {
        "case": index,
        "photoshoot": shot["photoshoot_index"] + 1,
        "frame": shot["shot_index"] + 1,
        "kind": case_kind(shot),
        "shot": shot["number"],
        "seed": shot["inference_seed"],
        "stage": shot["stage"].get("plateau_kind") or shot["stage"]["level"],
        "recipe": (scene.get("explicit_recipe") or {}).get("id"),
        "pose": scene["pose"]["id"],
        "action": scene["action"]["id"],
        "camera": {
            key: scene[key]["id"]
            for key in ("shot_size", "camera_angle", "framing", "focus_target")
        },
        "selected_ids": selected_ids,
        "positive": positive,
        "negative": negative,
        "review": {flag: None for flag in REVIEW_FLAGS},
        "notes": "",
    }


def write_report(directory: Path, manifest: list[dict[str, Any]]) -> None:
    sections = []
    for item in manifest:
        image_name = html.escape(item["image"])
        metadata = html.escape(json.dumps({
            key: item.get(key) for key in (
                "photoshoot", "frame", "kind", "seed", "recipe", "pose", "action",
                "camera", "elapsed_seconds", "review_status", "notes"
            )
        }, ensure_ascii=False, indent=2))
        positive = html.escape(item["positive"])
        negative = html.escape(item["negative"])
        checks = "".join(
            f'<label><input type="checkbox"> {html.escape(flag.replace("_", " ").title())}</label>'
            for flag in REVIEW_FLAGS
        )
        sections.append(
            f'<section id="case-{item["case"]}"><div class="visual">'
            f'<img src="{image_name}" loading="lazy"><div class="checks">{checks}</div></div>'
            f'<article><h2>Case {item["case"]}: {html.escape(item["kind"])}</h2>'
            f'<pre>{metadata}</pre><h3>Positive prompt</h3><p>{positive}</p>'
            f'<h3>Negative prompt</h3><p>{negative or "(empty)"}</p></article></section>'
        )
    document = """<!doctype html><meta charset="utf-8"><title>Valhalla Preview QA</title>
<style>:root{color-scheme:dark}*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:#11151b;color:#e8ebf0;font:15px/1.5 system-ui}
header{position:sticky;top:0;z-index:3;padding:14px 24px;background:#11151bf2;border-bottom:1px solid #303743}
header h1{display:inline;margin:0 24px 0 0;font-size:18px}nav{display:inline-flex;gap:8px}
nav a{color:#c7c1ff;text-decoration:none;padding:5px 9px;border:1px solid #3b4351;border-radius:7px}
main{max-width:1500px;margin:auto;padding:24px}section{display:grid;grid-template-columns:minmax(420px,1.15fr) minmax(420px,1fr);gap:24px;min-height:calc(100vh - 92px);padding:0 0 36px;margin:0 0 36px;border-bottom:1px solid #303743}
.visual{position:sticky;top:78px;align-self:start}.visual img{display:block;width:100%;max-height:calc(100vh - 150px);object-fit:contain;background:#090b0f;border-radius:12px}
.checks{display:flex;flex-wrap:wrap;gap:8px 16px;padding:12px 2px;color:#c8ced8}.checks label{white-space:nowrap}
article{overflow:hidden;border:1px solid #303743;border-radius:14px;background:#1a2029;padding:18px}
h2{margin-top:0;font-size:18px}h3{margin:22px 0 7px;color:#aaa2ff;font-size:14px}
pre,p{white-space:pre-wrap;overflow-wrap:anywhere;color:#c8ced8;font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}
@media(max-width:900px){section{grid-template-columns:1fr}.visual{position:static}.visual img{max-height:75vh}}</style>
<header><h1>Valhalla Preview QA</h1><nav>""" + "".join(
        f'<a href="#case-{item["case"]}">{item["case"]}</a>' for item in manifest
    ) + "</nav></header><main>" + "".join(sections) + "</main>"
    (directory / "report.html").write_text(document, encoding="utf-8")


def write_review_packet(directory: Path, entry: dict[str, Any]) -> None:
    packet = {
        key: entry[key]
        for key in (
            "case", "photoshoot", "frame", "kind", "image", "review_bytes",
            "seed", "stage", "recipe",
            "pose", "action", "camera", "positive", "negative", "review", "notes",
        )
    }
    (directory / f'case_{entry["case"]:02d}.json').write_text(
        json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def review_jpeg(image_bytes: bytes) -> bytes:
    """Encode an in-memory preview as a bounded JPEG without saving the source."""
    for max_side in (1024, 900, 768, 640, 512):
        for quality in (5, 8, 12, 16, 22, 28, 31):
            result = subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-i", "pipe:0", "-frames:v", "1",
                    "-vf", f"scale='min({max_side},iw)':-2",
                    "-q:v", str(quality), "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
                ],
                input=image_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode == 0 and 0 < len(result.stdout) <= MAX_REVIEW_BYTES:
                return result.stdout
    raise RuntimeError("Could not encode preview below 100 KB")


def run(photoshoots: int, shots: int, master_seed: int, directory: Path) -> list[dict[str, Any]]:
    database, database_path = app.load_database()
    workflow, mapping = app.load_workflow_runtime(database, database_path, True)
    record = build_record(photoshoots, shots, master_seed)
    for shot in record["shots"]:
        shot["scene"]["_qa_db"] = record["db"]
    cases = record["shots"]
    manifest = []
    directory.mkdir(parents=True, exist_ok=True)
    database_bytes = database_path.read_bytes()
    (directory / "run.json").write_text(json.dumps({
        "profile": "balanced-visual-qa-v1",
        "photoshoots": photoshoots,
        "shots_per_photoshoot": shots,
        "sfw_per_photoshoot": shots // 2,
        "nsfw_per_photoshoot": shots // 2,
        "master_seed": master_seed,
        "seed_source": "random per run; recorded here for exact replay",
        "database": str(database_path),
        "database_sha256": hashlib.sha256(database_bytes).hexdigest(),
        "review_jpeg_max_bytes": MAX_REVIEW_BYTES,
        "render_path": "PreviewImage",
        "command": (
            f"python tests/qa_preview_audit.py --photoshoots {photoshoots} "
            f"--shots {shots} --master-seed {master_seed}"
        ),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    for index, shot in enumerate(cases, 1):
        entry = audit_entry(shot, index)
        started = time.monotonic()
        prompt_id, image_bytes, mime_type = app.generate_preview_image(
            database,
            entry["positive"],
            entry["negative"],
            entry["seed"],
            workflow,
            mapping,
        )
        encoded = review_jpeg(image_bytes)
        image_name = f"case_{index:02d}.jpg"
        (directory / image_name).write_bytes(encoded)
        entry.update({
            "image": image_name,
            "mime_type": "image/jpeg",
            "review_bytes": len(encoded),
            "source_mime_type": mime_type,
            "prompt_id": prompt_id,
            "elapsed_seconds": round(time.monotonic() - started, 1),
        })
        manifest.append(entry)
        write_review_packet(directory, entry)
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_report(directory, manifest)
        print(f'[{index}/{len(cases)}] {entry["kind"]} -> {image_name}', flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photoshoots", type=int, default=DEFAULT_PHOTOSHOOTS)
    parser.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    parser.add_argument(
        "--master-seed", type=int,
        help="Exact replay seed; omit for a fresh random test run",
    )
    parser.add_argument("--output", type=Path, help="Temporary audit directory")
    args = parser.parse_args()
    if not 1 <= args.photoshoots <= MAX_PHOTOSHOOTS:
        parser.error(f"--photoshoots must be between 1 and {MAX_PHOTOSHOOTS}")
    if not 2 <= args.shots <= MAX_SHOTS or args.shots % 2:
        parser.error(f"--shots must be an even number between 2 and {MAX_SHOTS}")
    master_seed = args.master_seed if args.master_seed is not None else secrets.randbelow(2**63)
    directory = args.output or Path(tempfile.mkdtemp(prefix="valhalla-preview-qa-"))
    print(f"Random master seed: {master_seed}", flush=True)
    run(args.photoshoots, args.shots, master_seed, directory)
    print(f"Report: {directory / 'report.html'}")
    print("Preview artifacts are temporary; delete the directory after review.")


if __name__ == "__main__":
    main()
