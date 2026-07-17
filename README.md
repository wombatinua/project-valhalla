# Project Valhalla Prompt Composer

A small Linux-first Python CLI that builds structured, rule-compatible image prompts and runs them through a captured Stability Matrix / ComfyUI workflow.

The project intentionally stays compact:

- `app.py` contains the CLI, resolver, prompt compiler, workflow capture, and ComfyUI client.
- `launcher.sh` checks dependencies and opens the Python interactive wizard.
- `database.json` contains settings and all manually editable content.
- `workflow.json` is the captured ComfyUI API workflow used as the render template.
- The configured output directory contains downloaded generated images.

Stability Matrix remains the visual workflow editor. This application handles content composition, photoshoot progression, workflow patching, and batch generation.

## Production content database

`database.json` is a production-scale, manually editable catalog with 901 records. Its current balance includes roughly:

- 223 compositional adult-model traits;
- 342 garments and fashion accessories;
- 12 garment patterns and 8 fabric textures;
- 19 algorithmic outfit templates;
- 41 private interiors and secluded nature locations;
- 34 compatible pieces of furniture and posing surfaces;
- 80 fashion, lifestyle, boudoir, nude, close-up, and explicit poses;
- 59 actions, 14 non-sexual props, and dedicated action-compatible expressions;
- 32 mood and photography treatments.

The wardrobe covers everyday casual wear, office and evening fashion, homewear, pajamas, bathrobes, dresses, private-garden outfits, swimwear, bras, many cuts of panties and thongs, corsetry, lace, sheer garments, leather, fishnets, pantyhose, stockings, socks, high heels, boots, slippers, jewelry, garters, and editorial accessories. Templates are recipes rather than fixed outfits, so compatible pieces, matching tags, slots, and colors can be recombined into many coherent sets.

Patterns and fabric textures are independent compositional garment modifiers. `settings.garment_modifiers.pattern_chance` and `texture_chance` control their per-garment probability; the supplied defaults are `0.22` and `0.28`. Every modifier declares an explicit `allowed_garment_ids` list, so floral, gingham, pinstripe, plaid, polka-dot, geometric, heart, stripe, vine, ribbed, cotton, knit, denim, crinkled, and velour treatments appear only on deliberately compatible garments. If the chance does not trigger or the selected garment has no compatible modifier, it remains plain. Modifier choices are controlled by `prompt-seed`, fixed with the outfit throughout a photoshoot, included in the model output summary and selected IDs, and regenerated independently in random mode.

Wardrobe templates declare `wardrobe_category` as `normal` or `glamour`. Normal templates draw their main clothes from the `normal_clothes` pool; Glamour contains the remaining office, cocktail, evening, boudoir, lingerie, stockings, fetish, leather, swimwear, and editorial recipes. The unified wardrobe picker can randomize across all groups, randomize only Normal or Glamour, select one exact template, or remix the current template. The expanded Normal pool now contains 44 tops, 41 bottoms, 20 casual dresses, and 9 everyday footwear choices. It covers tanks, tees, fitted shirts, cardigans, knitwear, sweatshirts, denim, several jeans cuts, lounge and sporty pieces, shorts, leggings, everyday skirts, body-conscious day dresses, sneakers, flats, loafers, sandals, ankle boots, and house slides. New records use restrained everyday color lists instead of inheriting unsuitable fashion-print colors.

The panties catalog contains 44 cuts, including expanded floral, scalloped, embroidered, sheer, high-leg, low-rise, V-front, side-string, Brazilian, bikini, tanga, thong, cotton, modal, ribbed, and satin variants. During an intimate-closeup plateau shot, a compatible template can deterministically branch into `panties_aside`: panties remain visible while anatomy visibility is enabled, the resolver requires an open-legs pose, and `action_pull_panties_aside` describes pulling the crotch aside with one hand. This state cannot occur with closed-leg poses, absent panties, or non-explicit stages.

The pose/action catalog balances candid everyday direction with explicit plateau variety. Everyday additions include natural standing weight shifts, relaxed stretches, floor, chair, sofa, bed, wall, kneeling, and reclining compositions plus clothing adjustments and candid gestures. Explicit additions are divided across rear-display, breast and intimate close-up, and hands-only masturbation families. Every surface-specific pose requires its exact bed, sofa, chair, floor, wall, or window tag; explicit actions require matching visibility, pose, and pleasure-expression tags. No action introduces a toy, partner, male subject, or mirror.

Garments can declare `requires_environment_tags` or `excludes_environment_tags`. Automatic assembly and Director wardrobe/location remixes enforce these rules against interior tags. Sunglasses require `outdoor`, so they never appear in bedrooms, studios, bathrooms, indoor pools, sunrooms, conservatories, or other indoor scenes.

Environments are divided into two Director categories. An interior with the `luxury` tag belongs to **Luxury**; every other interior belongs to **Normal**. The location picker can select all environments, randomize only Normal or Luxury, or select one exact room. The storyboard SET summary prints the selected category beside the interior ID.

All locations are private. The indoor catalog deliberately balances editorial settings with ordinary homes: small and older apartments, rental bedrooms and living rooms, compact studio flats, spare and suburban bedrooms, everyday kitchens and bathrooms, a home office, and a quiet apartment hallway. These normal interiors have increased selection weights and compatible simple beds, fabric sofas, wooden chairs, apartment rugs, laminate counters, standard bathtubs, and tiled showers. Explicitly luxurious canopy/velvet furniture requires a `luxury` environment and cannot appear in ordinary rooms.

Outdoor content is limited to secluded gardens, private lawns, villa patios, remote cabin decks, and isolated nature clearings; the catalog intentionally contains no streets, clubs, shops, transit, or other public locations. Furniture uses location requirements so bathroom, pool, indoor, outdoor, ordinary, and luxury surfaces are selected only where their environmental tags fit.

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

`launcher.sh` is intentionally only a bootstrap wrapper. It checks Python and `requests`, detects or installs `fzf` through Homebrew when possible, and executes `python3 app.py wizard`. All menu state, validation, FZF rendering, numbered fallback, configuration, and Director behavior live in `app.py`.

The Python wizard opens one compact configuration dashboard after `New run`. Main menu contains only New run, Capture workflow, Help, and Exit; output action is deliberately deferred until the user is ready to continue.

The dashboard shows:

- photoshoot versus independent random mode;
- normal/progressive versus full-XXX content;
- photoshoots, shots per SET, and calculated total image count;
- automatic versus interactive Director;
- prompt and inference seed behavior;
- NSFW ending and explicit plateau percentages with estimated frame counts;
- advanced seed/progression settings, reset, and return to the main menu.

The dashboard has one primary action: **Start run** for automatic direction or **Open Director** for interactive direction. Current values appear directly in short setting labels and in the summary. Selecting a setting edits only that field and returns to the dashboard. Seeds and progression live in Advanced, and unavailable progression controls are hidden in random/full-XXX modes. Automatic mode asks Generate/Dry run only after Start run; Quality appears only after Generate. Interactive mode opens the storyboard immediately and places both Generate and Print prompts in Director's Run group. Escape always goes back and confirmation Escape always cancels; it never launches work. Without `fzf`, the same Python state machine renders numbered menus rather than maintaining a separate shell wizard.

Generation output identifies every prompt as `PHOTOSHOOT x/y · IMAGE x/y · BATCH x/y`, followed by its stage, resolved scene fields, and positive/negative prompts. After ComfyUI returns, the same image block prints the image generation time, total job elapsed time, running average per image, remaining image count, estimated time remaining, local estimated finish time, exact generated filename, and output directory. The ETA starts after the first completed image and is recalculated after every subsequent result. Timing covers queue submission, ComfyUI execution, polling, and downloading all returned files. Workflows that return multiple files list every filename separately while counting the workflow job as one storyboard image.

`Director → Interactive` changes the dashboard’s primary action to **Open Director**. It builds the storyboard and opens Director's Desk without an extra output or confirmation screen; no ComfyUI generation is queued until Generate is explicitly selected inside Director.

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

Every fixed-choice screen uses the same Python `fzf` picker, including the wizard, confirmation, storyboard actions, shot selection, SET design, stages, and content catalogs. Catalog screens follow one predictable hierarchy: **All groups** allows every compatible item, **Any Group** makes a prompt-seed-controlled weighted choice inside that section, and a concrete row fixes that exact item. Ungrouped properties provide **Any value** plus exact values. Disabled and incompatible records are removed before these choices are built. Mood and Camera use Everyday/Romantic/Editorial and Amateur/Studio/Editorial/Explicit groups; wardrobe, locations, surfaces, hair, poses, actions, and expressions use their own semantic groups. Director command pickers use a compact lower-screen window so the SET card and storyboard remain visible above them. Type to search, press Enter to select, or Escape to go back. Numeric values remain ordinary input fields. Stage editing rejects changes that reverse photoshoot progression. Set changes affect the complete selected photoshoot, while random mode changes only the selected independent shot. Redirected/non-TTY runs use the same state machine with numbered menus.

The SET designer supports constrained remixing instead of forcing a completely new random selection:

- subject: randomize everything, preserve the current ethnic appearance, explicitly choose any enabled ethnic-appearance ID (including Slavic appearance), select exact adult age 21 or 22, or remix only face, hair, body/anatomy, or styling;
- wardrobe: choose all templates, one semantic category, one exact template, or generate new compatible pieces and colors inside the current template;
- location and surface: choose all compatible values, one semantic category/type, or one exact item;
- surface: choose any compatible furniture or stay within the current surface type.

The Subject menu is organized into Whole subject, Identity & face, Hair & beauty, and Body groups. It remains open after each change so several traits can be directed in one visit; `Back` returns to SET design. Hair length, style, texture, and color can each be selected directly. Length and style choices are grouped as Short, Medium, and Long, and changing length or texture automatically repairs an incompatible hairstyle. Face, body, hair, and styling remixes show only the section being changed. Makeup, manicure, breast size, body type, pubic hair, and vulva appearance also have focused selectors. Every fixed-choice screen ends with `Back`.

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
4. detects the base sampler, its direct VAE Decode, and image-output targets for fast-test mode;
5. saves only the clean API workflow; no workflow-specific node IDs are written to `database.json`.

An existing workflow is not overwritten unless `--force` is supplied:

```bash
python3 app.py capture --force
```

Capture can fail safely when prompt or fast-mode nodes are ambiguous. In that case it prints candidates and leaves the existing workflow unchanged. The detected mapping is used only for validation and console reporting, then discarded.

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

Resolves scenes and prints model signatures, selected IDs, prompts, stages, and seeds without contacting ComfyUI for generation. Console output is formatted as a production sheet: a Run summary, one card per SET, structured Shot blocks, wrapped Positive/Negative prompts, and a final completion marker. Output width follows the terminal up to 120 columns; redirected files remain plain text without ANSI escape codes.

In photoshoot mode, `--count` is the number of images in each photoshoot and `--photoshoots` is the number of distinct photoshoots. The default is one photoshoot. In random mode, `--count` is the total image count and `--photoshoots` must remain `1`.

Use this before a large batch to validate database changes without spending GPU time.

### `generate`

`generate` accepts the same arguments as `dry-run`, including the optional `--fast` render profile. For each image it:

1. resolves and compiles a scene;
2. loads `workflow.json` once and detects prompt, seed, and optional Fast-mode targets in memory;
3. deep-copies the loaded workflow and patches positive prompt, negative prompt, and every detected inference seed;
4. queues the workflow through `POST /prompt`;
5. polls `/history/{prompt_id}`;
6. downloads returned images through `/view`.

Jobs run sequentially. The batch stops on its first resolver, HTTP, ComfyUI, or timeout error.

### Fast test

```bash
python3 app.py generate \
  --mode photoshoot \
  --count 10 \
  --fast
```

`--fast` reconnects every mapped image output directly to the VAE Decode immediately following the base sampler. The workflow is then pruned to ancestors of those outputs, so Face/Hand Detailers, Hires Fix, secondary samplers, refiners, upscalers, and their detector/model nodes are not submitted to ComfyUI. LoRA model and CLIP links are reconnected to their inputs before pruning; unsupported custom LoRA nodes stop with a clear error instead of silently running.

Fast-mode targets are detected in memory from the current workflow at batch startup. If the captured graph has no unique base sampler fed by an empty latent, no direct VAE Decode, or no image-output node, Fast mode fails safely because an automatic bypass would be ambiguous. Production mode does not require Fast-mode detection and never changes or prunes the captured workflow.

Fast-test filenames contain `fast_`, and the Run summary reports `Render profile  Fast test`. This profile is intended for checking composition, prompts, stages, and general model behavior. Final detail, faces, resolution, and sometimes composition can differ from production output.

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

With `--mode photoshoot`, the resolved model signature, private location, lighting, and overall visual treatment remain fixed. This preserves prompt-level continuity without claiming backend identity memory. The complete batch is divided predictably and as evenly as possible into:

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

Known structurally unstable compositions can remain in the editable catalog with `disabled: true` and a `disabled_reason`; disabled poses are omitted from automatic composition and every Director selector. The rear spread close-up remains enabled but uses a constrained eye-level three-quarter composition: lower back, pelvis, hips, and upper thighs stay aligned, torso and pelvis face the same direction, and hand placement is left entirely to the selected action instead of being described twice. It belongs only to the `provocative_rear` family; rear-facing poses are excluded from the front-oriented `panties_aside` resolver branch.

Rear plateau prompts use orientation-aware anatomy compilation. Breast and nipple traits are omitted from `provocative_rear` prompts so the checkpoint is not asked to show a frontal chest and rear-facing pelvis simultaneously. The rear prefix explicitly keeps the back, torso, and buttocks facing away while allowing only the face to look over one shoulder; its stage-specific negative prompt rejects a front-facing chest, simultaneous front/rear view, reversed torso, impossible spinal rotation, disconnected waist, and fisheye hip distortion. The generic XXX negative suffix does not force visible breasts in genital- or rear-focused frames.

The global anatomy-integrity suffix requests a complete body with two arms, two legs, two hands, two feet, and correct hands and feet. Its negative counterpart rejects missing, amputated, detached, duplicated, fused, or malformed limbs as well as common hand, finger, foot, and toe defects. Extreme overhead contortion poses and actions that pull both legs by the ankles or knees are intentionally excluded because they disproportionately produce missing-leg failures.

Every mode is strictly solo-woman content. The positive prefix anchors a single adult woman, while the global negative prompt rejects men, male bodies or hands, penises, testicles, additional people, and duplicate subjects.

`prompt_defaults` are intentionally compact. Subject count, anatomical integrity, identity, XXX framing, and negative safeguards use short non-repetitive fragments so pose and action instructions retain more conditioning influence. `positive_prefix` supports `{age}`; the compiler replaces it with the selected `human_model_parts.age` prompt, producing an emphasized prefix such as `(solo 21-year-old adult woman:1.4)` without repeating age later in the prompt.

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

Runtime settings live near the top of `database.json`. The excerpt below keeps the
human pool compact for readability. The supplied database currently lists all
human-model categories, but pools may be omitted when unrestricted defaults are wanted:

```json
"settings": {
  "comfy_url": "http://127.0.0.1:8188",
  "workflow_file": "./workflow.json",
  "output_dir": "./outputs",
  "human_defaults": {
    "pools": {
      "makeup": ["makeup_no_makeup", "makeup_natural"],
      "manicure": ["manicure_none", "manicure_nude"],
      "height": ["height_petite", "height_average"],
      "body_frame": ["body_slender", "body_petite", "body_lithe"],
      "waist": ["waist_tiny", "waist_slender"],
      "hips": ["hips_petite", "hips_narrow"],
      "breast_size": ["breasts_very_small", "breasts_small"],
      "breast_shape": ["breasts_round", "breasts_teardrop"],
      "areola_size": ["areola_very_small", "areola_small"],
      "nipple_size": ["nipples_tiny", "nipples_small"],
      "nipple_shape": ["nipples_soft", "nipples_flat"],
      "pubic_hair": ["pubic_shaved", "pubic_very_short", "pubic_natural"],
      "genital_appearance": ["genitals_small_delicate", "genitals_subtle", "genitals_compact"],
      "hair_length": ["hair_length_shoulder", "hair_length_long", "hair_length_very_long"]
    }
  },
  "scene_defaults": {
    "wardrobe_categories": ["normal"],
    "environment_categories": ["normal"],
    "pools": {
      "interiors": ["interior_small_apartment_bedroom", "interior_ordinary_apartment_bedroom", "interior_rental_bedroom", "interior_compact_studio_apartment", "interior_small_apartment_living_room", "interior_ordinary_living_room"],
      "furniture": ["furniture_simple_double_bed", "furniture_unmade_home_bed", "furniture_compact_fabric_sofa", "furniture_worn_home_sofa", "furniture_simple_wooden_chair", "furniture_thin_apartment_rug"],
      "moods": ["mood_everyday_relaxed", "mood_ordinary_afternoon", "mood_casual_private"],
      "photography_styles": ["photo_amateur_home", "photo_casual_handheld", "photo_simple_window"],
      "explicit_photography_styles": ["photo_explicit_home_clear", "photo_explicit_handheld_close"]
    }
  },
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

The supplied `human_defaults.pools.ethnic_appearance` contains only `appearance_slavic`, making it the automatic default. Director can still choose another ethnicity or request a completely random subject. Removing that pool enables every available ethnic appearance for automatic casting.
`human_defaults.pools` contains randomized default pools. When a category contains IDs, the composer uses only those enabled IDs after applying compatibility rules. A missing category and an explicitly empty array `[]` are equivalent: both use every enabled and compatible item from the corresponding `human_model_parts` catalog. `disabled: true` items are never eligible. This makes new database categories automatically usable without requiring a matching settings edit, while `[]` can document an intentionally unrestricted category.

Automatic casting makes a weighted prompt-seed-controlled choice from each compatible pool or unrestricted catalog. A photoshoot resolves the choices once and keeps them for its complete SET; random mode resolves them for every independent frame.

The supplied curated defaults use Slavic appearance and only its compatible light skin tones, facial traits, eye traits, hair textures, and light-skin areola colors. They also use a petite/slender and small/natural anatomy profile, shoulder-length or longer hair, simple medium/long hairstyles, blonde, brown/brunette, or dark-brown hair, and only subtle freckles, a beauty mark, or dimples as optional facial accents. Other ethnic traits, dark skin tones, black hair, short or glamorous hairstyles, pronounced beauty styling, distinctive natural shades, fashion colors, and all other catalog traits remain available through Director. Exact Director choices and section remixes override the defaults.

`scene_defaults.wardrobe_categories` and `scene_defaults.environment_categories` are automatic category pools. The supplied configuration contains only `normal`, so automatic photoshoots and random frames start with basic clothes and Normal environments. Adding `glamour` or `luxury` to the respective array enables weighted random selection from both categories. Director category choices remain explicit overrides and are not restricted by these defaults.

`scene_defaults.pools` optionally narrows exact interiors, furniture, moods, and photography styles. Missing keys and `[]` mean all enabled compatible items, matching `human_defaults.pools` semantics. The supplied pools deliberately use small or ordinary apartments, everyday beds and sofas, relaxed day-to-day moods, ordinary light, and amateur-style framing. `explicit_photography_styles` changes only automatically composed explicit shots to clear close-range home photography; a photography style explicitly selected in Director is preserved. Editorial, magazine, cinematic, boudoir, outdoor, and luxury content remains available through Director and direct database customization.

Normal wardrobe templates include simple basics plus a broad sexy-casual catalog: fitted shirts, deep- or scoop-neck T-shirts, tanks, camisoles, crop and wrap tops, bodysuit-style tops, skinny and shaping jeans, denim hot pants, leggings, short and ultra-short casual skirts, and body-shaping mini dresses. A dedicated normal dress template makes `full_body` casual dresses reachable instead of limiting automatic outfits to upperwear/lowerwear combinations. Optional socks, pantyhose, stockings, fishnets, and lace legwear remain available, while the underwear pool combines everyday panties with non-fetish lace variants. Slot-level `required_any_tags` expresses alternatives and `excludes_tags` removes explicit, fetish, leather, or luxury garments without incorrectly reclassifying those catalog items as ordinary clothes.

Body-contouring leggings, yoga/bike shorts, shaping jeans, and selected fitted, seamless, or lace panties declare `"reveals_cameltoe": true`. Whenever one of those garments is visible, the compiler emits `prompt_defaults.cameltoe_prompt` exactly once. The detail disappears automatically when all supporting garments are hidden or removed by the current stage. Set the property only on garments whose fabric and cut can plausibly produce that contour.

ComfyUI may return images from a `PreviewImage` node as temporary files. The application downloads both `temp` and permanent `output` images into `settings.output_dir`.

Photoshoot filenames include the run ID, photoshoot number, and shot number, for example:

```text
20260716_170000_000000_photoshoot_002_shot_007_12345_image_01.png
```

## Editing the database

`database.json` is the source of truth for content.

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

Human models are assembled from age, appearance, skin, face, eyes, hair, body, anatomy, makeup, and detail categories. Selection is compositional but not blindly independent: accumulated tags are checked before every later trait is chosen.

Ethnic-appearance records declare a unique `heritage_*` tag and their allowed skin-tone tags. Skin tone, ancestry-linked face shapes, natural eye pigmentation, nose/lip variants, hair texture, and natural hair colors use `requires_tags` or `requires_any_tags` to declare compatible heritage groups. This prevents combinations such as European/Slavic appearance with deep or ebony skin, Slavic appearance with coily/curly texture, or East Asian appearance with unsupported natural pigmentation. Mixed heritage intentionally permits the complete trait catalog.

Universal variants remain available across groups, while fashion-dyed silver and rose-gold hair remain unrestricted styling choices. Hair style is additionally checked against selected hair length and texture, and areola color against skin tone. Partial face/hair remix operations preserve the current ethnicity while resolving new compatible traits.

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
- workflow prompt and seed targets in memory before generation.

Common errors:

- **`requests` is missing:** install it with `python3 -m pip install --user requests`.
- **ComfyUI cannot be reached:** verify `settings.comfy_url` and confirm ComfyUI is running.
- **Workflow already exists:** use `capture --force` only when intentionally replacing it.
- **Workflow node detection is ambiguous:** keep clear `positive` and `negative` names on the two text-node IDs, then recapture the workflow.
- **No compatible choices remain:** use `dry-run` and inspect the selected template's tags, colors, and match groups.
- **Generation times out:** increase `settings.generation_timeout_seconds`.

## Current MVP boundaries

- One application file and one content database
- One captured workflow/render profile
- No GUI, WebSocket progress, resume support, or JSONL job log
- Sequential generation only
- Model, LoRA, VAE, sampler, CFG, detailers, and resolution remain controlled by the captured workflow
