# Project Valhalla Prompt Composer

A small Linux-first Python CLI that builds structured, rule-compatible image prompts and runs them through a captured Stability Matrix / ComfyUI workflow.

The project intentionally stays compact:

- `app.py` contains the CLI, resolver, prompt compiler, workflow capture, and ComfyUI client.
- `database.json` contains settings and all manually editable content.
- `workflow.json` is the captured ComfyUI API workflow used as the render template.
- The configured output directory contains downloaded generated images.

Stability Matrix remains the visual workflow editor. This application handles content composition, photoshoot progression, workflow patching, and batch generation.

## Requirements

- Python 3.11 or newer (currently tested with Python 3.13)
- A local or trusted-LAN ComfyUI instance
- `requests`

Install the Python dependency:

```bash
python3 -m pip install --user requests
```

The default ComfyUI URL is:

```text
http://127.0.0.1:8188
```

## Quick start

First configure and test an image in Stability Matrix. Then capture the latest successful workflow:

```bash
python3 app.py capture
```

Inspect ten prompts without using the GPU:

```bash
python3 app.py dry-run \
  --mode photoshoot \
  --count 10 \
  --prompt-seed 123 \
  --inference-seed 456
```

Generate a ten-image photoshoot:

```bash
python3 app.py generate \
  --mode photoshoot \
  --count 10
```

Generate ten unrelated randomized images:

```bash
python3 app.py generate \
  --mode random \
  --count 10
```

Run `python3 app.py COMMAND --help` for the complete options of a command.

## Commands

### `capture`

```bash
python3 app.py capture [--force]
```

`capture` reads ComfyUI history and finds the latest job that is successful, completed, and has image outputs. It then:

1. saves the submitted API workflow to `settings.workflow_file`;
2. detects the positive and negative text nodes;
3. detects scalar seed inputs on samplers and detailers;
4. updates only `node_mapping` in `database.json`.

An existing workflow is not overwritten unless `--force` is supplied:

```bash
python3 app.py capture --force
```

Capture can fail safely when multiple prompt nodes are ambiguous. In that case it prints candidates and leaves the existing files unchanged.

### `dry-run`

```bash
python3 app.py dry-run \
  --mode photoshoot|random \
  --count N \
  [--prompt-seed N] \
  [--inference-seed N] \
  [--nsfw-percent 0..100]
```

Resolves scenes and prints model signatures, selected IDs, prompts, stages, and seeds without contacting ComfyUI for generation.

Use this before a large batch to validate database changes without spending GPU time.

### `generate`

`generate` accepts the same arguments as `dry-run`. For each image it:

1. resolves and compiles a scene;
2. deep-copies `workflow.json`;
3. patches positive prompt, negative prompt, and all mapped inference seeds;
4. queues the workflow through `POST /prompt`;
5. polls `/history/{prompt_id}`;
6. downloads returned images through `/view`.

Jobs run sequentially. The batch stops on its first resolver, HTTP, ComfyUI, or timeout error.

## Modes

### Photoshoot

`--mode photoshoot` creates a connected model photoshoot:

- one compositional human model is fixed for the complete batch;
- outfit pieces, colors, location, furniture, mood, and photography style stay fixed;
- poses, actions, props, and expressions vary;
- outfit stages advance without dressing backwards;
- the configured final percentage becomes progressively NSFW.

The model signature contains every selected human trait, including traits that are not visible in a clothed frame.

### Random

`--mode random` independently assembles every frame. Human traits, outfit, stage, location, pose, and action can all change.

`--nsfw-percent` is intentionally unavailable in random mode because random mode selects independent stages.

## NSFW photoshoot progression

The default is stored in `database.json`:

```json
"photoshoot_progression": {
  "nsfw_final_percent": 30
}
```

For a ten-image photoshoot at `30`, the final three images are:

1. topless with an erotic pose/action;
2. fully nude with an erotic pose/action;
3. explicit with an explicit pose/action and a compatible adult prop when required.

Override the percentage for one command:

```bash
python3 app.py generate \
  --mode photoshoot \
  --count 10 \
  --nsfw-percent 50
```

Use `--nsfw-percent 0` to disable the forced NSFW ending. Values from `0` through `100` are accepted.

If an outfit template does not define topless, nude, or explicit terminal stages, the application derives safe terminal stages from the template's available garment slots.

## Seeds

Prompt and inference randomness are independent.

### Prompt seed

`--prompt-seed` controls content selection:

- human traits;
- garments and colors;
- outfit template and stages;
- location, poses, actions, props, expressions, and style.

When supplied, it reproduces the complete prompt sequence. When omitted, one random prompt seed is generated for the command and printed.

### Inference seed

`--inference-seed` controls ComfyUI diffusion and all mapped sampler/detailer seed fields.

- When supplied, the exact seed is reused for every image in the batch.
- When omitted, every image receives a new random inference seed.
- Accepted values are `0` through `18446744073709551615`.

Reusing an inference seed and model signature helps visual continuity, but strict identity consistency still depends on the captured model and workflow. Reference-image, IPAdapter, or character-LoRA nodes can be configured in Stability Matrix and preserved through capture.

## Settings

Runtime settings live near the top of `database.json`:

```json
"settings": {
  "comfy_url": "http://127.0.0.1:8188",
  "workflow_file": "./workflow.json",
  "output_dir": "./outputs",
  "http_timeout_seconds": 15,
  "poll_interval_seconds": 1,
  "generation_timeout_seconds": 600,
  "max_scene_attempts": 100,
  "photoshoot_progression": {
    "nsfw_final_percent": 30
  }
}
```

Relative paths are resolved from the directory containing `database.json`. Absolute paths are also accepted.

ComfyUI may return images from a `PreviewImage` node as temporary files. The application downloads both `temp` and permanent `output` images into `settings.output_dir`.

## Editing the database

`database.json` is the source of truth for content. Its `_guide` section documents the compact item format and is ignored by the application.

A minimal item needs only an ID and prompt:

```json
{
  "id": "eyes_almond",
  "prompt": "almond-shaped eyes"
}
```

Optional rule fields are added only when needed:

```json
{
  "id": "example_item",
  "prompt": "example prompt fragment",
  "weight": 1,
  "tags": ["example_tag"],
  "requires": ["another_item_id"],
  "excludes": ["incompatible_item_id"],
  "requires_tags": ["required_tag"],
  "excludes_tags": ["forbidden_tag"],
  "occupies_slots": ["upperwear"],
  "allowed_colors": ["color_black"]
}
```

Important rules:

- IDs must be globally unique and stable.
- `requires` and `excludes` refer to exact IDs.
- `requires_tags` and `excludes_tags` define generic compatibility.
- `weight` must be greater than zero.
- A lower weight makes an item less likely; a higher weight makes it more likely.
- Do not add empty optional arrays unless they improve readability.

The main content sections are:

- `human_model_parts`
- `colors`
- `garments`
- `outfit_templates`
- `interiors` and `furniture`
- `poses`, `actions`, and `props`
- `expressions`, `moods`, and `photography_styles`

### Human model parts

Human models are assembled from independent age, appearance, skin, face, eyes, hair, body, anatomy, makeup, and detail categories.

In a photoshoot, every selected trait stays fixed. Anatomy fragments are visibility-aware: covered anatomy remains in the model signature but is not emitted into the image prompt until the relevant body area is visible.

The starter database contains only explicitly adult models aged 21 or 22 and excludes teen-coded language.

### Garments and outfit templates

Garments are grouped by slot:

- `upperwear`, `lowerwear`, and `full_body`
- `bra` and `panties`
- `legwear`, `footwear`, `outerwear`, and `accessories`

Outfit templates are recipes rather than fixed prompt strings. They select garments by catalog and tags, coordinate colors, match compatible set pieces, and define progressive visibility stages.

Reusable color modifiers live in the top-level `colors` list. Add a color once and reference its ID through a garment's `allowed_colors`.

## Validation and troubleshooting

Every command validates the database before doing work. Validation covers:

- required sections and settings;
- duplicate or missing IDs;
- invalid references and colors;
- weights and probability ranges;
- outfit catalogs, slots, and stages;
- node mappings before generation.

Common errors:

- **`requests` is missing:** install it with `python3 -m pip install --user requests`.
- **ComfyUI cannot be reached:** verify `settings.comfy_url` and confirm ComfyUI is running.
- **Workflow already exists:** use `capture --force` only when intentionally replacing it.
- **Node mapping is missing:** generate once in Stability Matrix, then run `capture`.
- **No compatible choices remain:** use `dry-run` and inspect the selected template's tags, colors, and match groups.
- **Generation times out:** increase `settings.generation_timeout_seconds`.

## Current MVP boundaries

- One application file and one content database
- One captured workflow/render profile
- No GUI, WebSocket progress, resume support, or JSONL job log
- Sequential generation only
- Model, LoRA, VAE, sampler, CFG, detailers, and resolution remain controlled by the captured workflow
