# Project Valhalla Prompt Composer

A small Linux-first Python CLI that builds structured, rule-compatible image prompts and runs them through a captured Stability Matrix / ComfyUI workflow.

The project intentionally stays compact:

- `app.py` contains the CLI, resolver, prompt compiler, workflow capture, and ComfyUI client.
- `launcher.sh` provides an interactive wizard for all launch options.
- `database.json` contains settings and all manually editable content.
- `workflow.json` is the captured ComfyUI API workflow used as the render template.
- The configured output directory contains downloaded generated images.

Stability Matrix remains the visual workflow editor. This application handles content composition, photoshoot progression, workflow patching, and batch generation.

## Production content database

`database.json` is a production-scale, manually editable catalog with 663 selectable records. Its current balance includes roughly:

- 220 compositional adult-model traits;
- 215 garments and fashion accessories;
- 18 algorithmic outfit templates;
- 23 private interiors and secluded nature locations;
- 23 compatible pieces of furniture and posing surfaces;
- 56 fashion, lifestyle, boudoir, nude, close-up, and explicit poses;
- 34 actions, 13 non-sexual props, and dedicated action-compatible expressions;
- 24 mood and photography treatments.

The wardrobe covers everyday casual wear, office and evening fashion, homewear, pajamas, bathrobes, dresses, private-garden outfits, swimwear, bras, many cuts of panties and thongs, corsetry, lace, sheer garments, leather, fishnets, pantyhose, stockings, socks, high heels, boots, slippers, jewelry, garters, and editorial accessories. Templates are recipes rather than fixed outfits, so compatible pieces, matching tags, slots, and colors can be recombined into many coherent sets.

All locations are private. Outdoor content is limited to secluded gardens, private lawns, villa patios, remote cabin decks, and isolated nature clearings; the catalog intentionally contains no streets, clubs, shops, transit, or other public locations. Furniture uses location requirements so bathroom, pool, indoor, and outdoor surfaces are selected only where their required environmental tags exist.

Human models are always explicitly adult women aged 21 or 22 and are assembled from independently editable face, eyes, hair, complexion, stature, figure, breast, areola, nipple, pubic-hair, external-anatomy, makeup, manicure, and accent catalogs. Anatomical prompt fragments are emitted only at stages where the relevant body area is visible.

Every record has a globally unique descriptive ID. New records can usually be added by copying the nearest related item and changing `id`, `prompt`, tags, and colors. Run a large `dry-run` after edits; the validator rejects duplicate IDs, unknown colors and references, invalid stages, and incompatible resolved scenes before any GPU work starts.

Any selectable database record can be temporarily excluded without deleting it:

```json
{
  "id": "example_item",
  "prompt": "example prompt fragment",
  "disabled": true
}
```

When `disabled` is absent, the item is enabled by default. `"disabled": false` also keeps it enabled. The flag works uniformly for human traits, colors, garments, outfit templates, interiors, furniture, poses, actions, props, expressions, moods, and photography styles. Disabled records retain their IDs for convenient manual editing but are never selected, used as dependencies, or included in color choices. The validator rejects non-boolean flag values, active records that require disabled IDs, and required categories with no enabled records remaining.

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

## Interactive launcher

For a guided launch, run:

```bash
./launcher.sh
```

With `fzf` available, the launcher opens one compact configuration dashboard immediately after the main action is chosen. Generate versus dry-run is selected once in the main menu and is not repeated as another setting.

The dashboard shows:

- photoshoot versus independent random mode;
- normal/progressive versus full-XXX content;
- photoshoots, shots per SET, and calculated total image count;
- automatic versus interactive Director;
- prompt and inference seed behavior;
- NSFW ending and explicit plateau percentages with estimated frame counts;
- advanced seed/progression settings, reset, and return to the main menu.

The dashboard has one primary action. With automatic direction it launches the selected generate/dry-run command; with interactive direction it clearly changes to **Continue to Director**. Selecting a setting edits only that field and returns to the dashboard. Seeds and progression live in one Advanced submenu, and unavailable progression controls are hidden in random/full-XXX modes. Escape preserves the current value. Selecting the primary action proceeds immediately because the dashboard itself is the editable summary. Without `fzf`, the original linear wizard and final confirmation remain available for redirected input and automation. Capture overwrite protection continues to use its own confirmation flow.

`Director → Interactive` changes the dashboard’s primary action to **Continue to Director**. It builds the storyboard and opens Director's Desk; no ComfyUI generation is queued until the storyboard is explicitly accepted inside Director.

Set `PYTHON_BIN` when a different Python executable or virtual environment is needed:

```bash
PYTHON_BIN=.venv/bin/python ./launcher.sh
```

At startup, the launcher checks whether the selected Python can import `requests`. If necessary, it initializes `pip` through `ensurepip` and installs `requests` automatically before showing the main menu. It also detects `fzf`; when Homebrew is available, a missing `fzf` is installed automatically. If neither is available, the Director keeps working with numbered menus.

## Interactive Director's Desk

Choose `Interactive` on the launcher's **Director's Desk** screen, or add the CLI flag directly:

```bash
python3 app.py dry-run \
  --mode photoshoot \
  --count 10 \
  --review-storyboard
```

Before any GPU job is queued, the application resolves the complete batch and displays a compact table containing each shot's photoshoot number, stage, pose, action, and expression. The director can then:

- accept the storyboard and begin generation;
- reroll the complete storyboard;
- open **Casting & Set Design**, choose a photoshoot SET, and use the explicit **Cast / remix subject** action or replace its wardrobe, location, surface, mood, photography style, or complete set;
- reroll one shot while preserving its model, outfit, location, and stage;
- direct one shot by changing its stage/XXX category, pose, action, or expression;
- reroll the complete composition of one shot;
- inspect the full positive and negative prompt;
- cancel without contacting ComfyUI.

Every fixed-choice screen uses an `fzf` picker, including the launcher, confirmation screens, storyboard actions, shot selection, SET design, stages, and all content catalogs. Higher-level menus are divided by dimmed semantic text headings such as Run, Production, Randomness, Casting, Styling, Location, and Navigation. Heading rows are non-actions: selecting one simply keeps the same picker open. Large fuzzy-search catalogs remain flat so headings do not interfere with filtering. Director command pickers use a compact lower-screen window so the SET card and storyboard remain visible above them; larger searchable catalogs expand only when opened. When a picker is active, the redundant numbered list and visible default row are hidden. Type to search, press Enter to select, or Escape to silently use the current default/keep the automatic choice. Numeric values such as counts, seeds, and percentages remain ordinary input fields. Pose and action lists contain only variants that the resolver can successfully combine with that shot. Expression choices are filtered against the selected action's required expression tags. When a stage is edited in photoshoot mode, the application rejects changes that would make undressing progression move backward. Set changes are resolved for the complete selected photoshoot, while random mode changes only the selected independent shot. Redirected/non-TTY runs retain the visible numbered-menu fallback for automation.

The SET designer supports constrained remixing instead of forcing a completely new random selection:

- subject: randomize everything, preserve ethnic appearance, or remix only face, hair, body/anatomy, or styling;
- wardrobe: choose another template or generate new compatible pieces and colors inside the current template;
- location: choose any interior, stay within the current location family, or keep the exact interior and remix its surface;
- surface: choose any compatible furniture or stay within the current surface type.

Each remix presents several resolved candidates. Compatibility rules are applied before the candidate is shown, and the accepted context remains fixed across the selected photoshoot.

The same desk works with `dry-run`, `generate`, normal progression, `--xxx-only`, photoshoot batches, and independent random images. Interactive editing happens in memory and does not create another database or modify `database.json`. Without `--review-storyboard`, behavior remains fully automatic.

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

Generate five different ten-image photoshoots:

```bash
python3 app.py generate \
  --mode photoshoot \
  --photoshoots 5 \
  --count 10
```

Generate ten unrelated randomized images:

```bash
python3 app.py generate \
  --mode random \
  --count 10
```

Start immediately with a completely explicit photoshoot:

```bash
python3 app.py generate \
  --mode photoshoot \
  --photoshoots 3 \
  --count 12 \
  --xxx-only
```

Generate unrelated randomized XXX images with a new model and set for every frame:

```bash
python3 app.py generate \
  --mode random \
  --count 50 \
  --xxx-only
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
  [--photoshoots N] \
  [--prompt-seed N] \
  [--inference-seed N] \
  [--xxx-only] \
  [--review-storyboard] \
  [--nsfw-percent 0..100] \
  [--plateau-percent 0..100]
```

Resolves scenes and prints model signatures, selected IDs, prompts, stages, and seeds without contacting ComfyUI for generation.

In photoshoot mode, `--count` is the number of images in each photoshoot and `--photoshoots` is the number of distinct photoshoots. The default is one photoshoot. In random mode, `--count` is the total image count and `--photoshoots` must remain `1`.

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
- the configured final percentage becomes progressively NSFW;
- its final explicit plateau follows a predictable peak-shot sequence.

With `--photoshoots N`, each photoshoot independently assembles a new human model, outfit, color palette, location, mood, and complete progression. Continuity is preserved only within each individual photoshoot.

The model signature contains every selected human trait, including traits that are not visible in a clothed frame.

Photoshoot mode reuses the same resolved human traits and `model_signature` in every prompt. This keeps the requested appearance stable at the prompt-composition level, but it is not an identity-control mechanism and does not give the backend information about previous frames.

### Random

`--mode random` independently assembles every frame. Human traits, outfit, stage, location, pose, and action can all change.

`--nsfw-percent` and `--plateau-percent` are intentionally unavailable in random mode because random mode selects independent stages.

## Full XXX mode

`--xxx-only` bypasses clothed, lingerie, topless, and nude-transition stages. Every generated prompt starts at the fully explicit plateau with all anatomical visibility enabled and no garment slots visible.

With `--mode photoshoot`, the adult model, identity lock, private location, lighting, and overall visual treatment remain fixed. The complete batch is divided predictably and as evenly as possible into:

1. provocative explicit rear views;
2. extreme intimate and breast close-ups;
3. hands-only masturbation actions with compatible expressions.

With `--mode random`, every image independently assembles a different adult model, outfit context, private location, furniture, lighting, pose, action, prop, and expression. Every frame remains explicit, while the three XXX categories are selected randomly.

`--xxx-only` works with both `dry-run` and `generate`, including multi-photoshoot batches. It cannot be combined with `--nsfw-percent` or `--plateau-percent` because those percentages describe the progressive mode that XXX-only bypasses.

## NSFW photoshoot progression

The default is stored in `database.json`:

```json
"photoshoot_progression": {
  "nsfw_final_percent": 50,
  "explicit_plateau_percent": 30
}
```

The plateau percentage is part of the NSFW percentage and cannot be larger than it. With the defaults, a ten-image photoshoot is divided into:

1. images 1–5: clothed-to-lingerie progression;
2. image 6: topless transition;
3. image 7: fully nude transition;
4. image 8: provocative explicit rear view;
5. image 9: explicit intimate close-up;
6. image 10: masturbation with action-compatible expression and adult prop when required.

For a longer plateau, rear views, close-ups, and masturbation each occupy a contiguous part of the plateau. This makes the final sequence predictable while poses, framing, hands-only actions, and expressions remain randomized within the appropriate category.

Plateau shots receive dedicated high-priority XXX prompt prefixes before the model description. All garment slots are removed, full anatomy fragments are enabled, and a plateau-specific negative suffix discourages censorship, covered anatomy, underwear, implied nudity, and non-explicit boudoir framing. These strings are manually editable in `prompt_defaults.xxx_plateau_prompts` and `prompt_defaults.xxx_negative_additions`.

The application guarantees an unambiguous XXX workflow prompt and stage. The diffusion model still has final control over the rendered pixels; a model that strongly resists explicit content may require a different checkpoint or workflow tuning in Stability Matrix.

NSFW pose selection also includes visibility-compatible intimate close-ups of breasts, nipples, hips/buttocks, the pubic area, and explicit anatomy. Close-ups are randomized with other eligible NSFW poses and cannot be selected for covered or lingerie-only stages.

Explicit actions also constrain facial-expression selection. Masturbation is exclusively hands-only: manual stimulation uses pleasure or intense-pleasure expressions according to the action. Sexual toys are absent from the selectable database and explicitly discouraged by the global negative prompt. The resolver validates the action/expression relationship before compiling the prompt.

Mirrors and reflections are excluded from the scene catalog because they frequently create duplicate subjects and anatomical glitches. Mirror furniture and mirror-dependent poses are unavailable, while the global negative prompt also discourages mirrors, reflections, mirrored walls, and reflected people.

The global anatomy-integrity suffix requests a complete body with two arms, two legs, two hands, two feet, and correct hands and feet. Its negative counterpart rejects missing, amputated, detached, duplicated, fused, or malformed limbs as well as common hand, finger, foot, and toe defects. Extreme overhead contortion poses and actions that pull both legs by the ankles or knees are intentionally excluded because they disproportionately produce missing-leg failures.

Every mode is strictly solo-woman content. The positive prefix anchors a single adult woman, while the global negative prompt rejects men, male bodies or hands, penises, testicles, additional people, and duplicate subjects.

`prompt_defaults` are intentionally compact. Subject count, anatomical integrity, identity, XXX framing, and negative safeguards use short non-repetitive fragments so pose and action instructions retain more conditioning influence.

Override the percentage for one command:

```bash
python3 app.py generate \
  --mode photoshoot \
  --count 10 \
  --nsfw-percent 60 \
  --plateau-percent 40
```

Use `--nsfw-percent 0 --plateau-percent 0` to disable the forced NSFW ending. Values from `0` through `100` are accepted, and the plateau must not exceed the NSFW percentage.

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

For a multi-photoshoot batch, one prompt seed reproduces the ordered set of every photoshoot and every shot within them.

### Inference seed

`--inference-seed` controls ComfyUI diffusion and all mapped sampler/detailer seed fields.

- When supplied, the exact seed is reused for every image in the batch.
- When omitted, every image receives a new random inference seed.
- Accepted values are `0` through `18446744073709551615`.

Reusing an inference seed can also repeat composition, crop, or pose tendencies. It is passed literally to the captured sampler nodes; the application does not claim that it preserves identity between independent generations.

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
      "nsfw_final_percent": 50,
      "explicit_plateau_percent": 30
    }
}
```

Relative paths are resolved from the directory containing `database.json`. Absolute paths are also accepted.

ComfyUI may return images from a `PreviewImage` node as temporary files. The application downloads both `temp` and permanent `output` images into `settings.output_dir`.

Photoshoot filenames include the run ID, photoshoot number, and shot number, for example:

```text
20260716_170000_000000_photoshoot_002_shot_007_12345_image_01.png
```

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
  "requires_expression_tags": ["expression_tag"],
  "occupies_slots": ["upperwear"],
  "allowed_colors": ["color_black"]
}
```

Important rules:

- IDs must be globally unique and stable.
- `requires` and `excludes` refer to exact IDs.
- `requires_tags` and `excludes_tags` define generic compatibility.
- `requires_expression_tags` restricts an action to expressions carrying all listed tags.
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
