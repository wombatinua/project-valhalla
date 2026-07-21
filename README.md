# Valhalla Photo Studio

Valhalla Photo Studio is a local, browser-based production interface for composing rule-compatible image prompts and rendering them through a captured Stability Matrix / ComfyUI workflow.

The project intentionally does not preserve backward compatibility for internal configuration or storyboard formats. When a format changes, keep the current implementation direct and reject obsolete files instead of adding legacy fields, aliases, or migration paths.

The application now uses a web-first architecture:

- `app.py` contains the composition engine, ComfyUI client, HTTP API, background job runner, and static-file server.
- `web/` contains the responsive production interface.
- `launcher.sh` checks the Python dependency, starts the local server, and opens the browser.
- `database.json` is the manually editable production content catalog.
- `workflows/` contains named ComfyUI API workflows and the active Production/Preview selections.
- `outputs/` contains downloaded generated images.

There is no terminal wizard and no `fzf` dependency. The terminal is used only for server startup and operational logs.

## Interface

The Photo Studio is designed around a review-before-render workflow:

1. Configure the production mode, content direction, batch size, progression, render mode, and seed strategy.
2. Select **Resolve storyboard** to assemble every compatible shot without using the GPU.
3. Review stage, pose, action, expression, set, and surface for every shot.
4. Inspect positive and negative prompts or reroll individual compositions.
5. Select **Generate images** when the storyboard is ready.
6. Follow live progress and ETA while outputs appear in the gallery.

When the application opens without a recoverable storyboard, Studio performs one automatic resolve using the visible defaults. Manual Resolve remains available for deliberate rerolls and configuration changes.

The UI includes:

- responsive desktop, tablet, and mobile layouts;
- automatic operating-system light/dark appearance through `prefers-color-scheme`;
- a session theme switcher for System, Light, and Dark modes;
- live ComfyUI, workflow, and catalog status;
- progressive and full-XXX production controls;
- deterministic prompt seeds plus random, fixed, and stable per-frame inference-seed strategies;
- production and Preview render profiles;
- automatic recovery of the active storyboard, settings, render progress, ETA, outputs, and polling after a browser reload;
- editorially planned storyboard cards with camera grammar, roles, diversity scoring, one-shot reroll/render, prompt inspection, temporary Fast Preview, and compact JSON export/import tied to the exact semantic database version;
- a dedicated Director’s Desk with exact subject, anatomy, hair, styling, wardrobe, modifier, location, mood, render style, stage, pose/action, surface, editorial role, shot size, angle, framing, focus, and explicit-recipe controls;
- cancellable FIFO background render jobs that accept additional work while rendering and fail each job clearly on its first generation error;
- a reload-safe Production Logbook with live frame counts, elapsed/estimated time, current seed, formatted positive/negative prompts, copy actions, a chronological error/completion timeline, and safe history clearing that leaves proofs and the displayed preview intact;
- shared Studio/Director render controls and draggable, memory-only single-shot Fast Preview windows;
- a persistent, virtualized output gallery with bounded DOM size, a browser-fullscreen lightbox, auto-hiding fullscreen controls, real-size 100% default, adjacent Fit/zoom controls, center-anchored 25–300% scaling, retained settings across images/reloads, timed 1–10 second slideshow, previous/next navigation, swipe, downloads, individual deletion, confirmed bulk deletion, and return-to-grid alignment on the last viewed image;
- safe or forced workflow capture from the latest successful ComfyUI run.

## Requirements

- Python 3.11 or newer
- a local or trusted-LAN ComfyUI instance
- `requests`
- a modern browser

The configured ComfyUI URL defaults to:

```text
http://127.0.0.1:8188
```

## Start

Run:

```bash
./launcher.sh
```

The launcher installs `requests` through pip if it is missing, starts the server at `http://127.0.0.1:8765/`, and asks Python to open that address in the default browser.

Environment overrides:

```bash
PYTHON_BIN=python3 VALHALLA_HOST=127.0.0.1 VALHALLA_PORT=9000 ./launcher.sh
```

You can also start the application directly:

```bash
python3 app.py
python3 app.py --host 127.0.0.1 --port 9000
python3 app.py --no-browser
```

### Gallery benchmark

Test large-gallery behavior without rendering or copying thousands of images:

```bash
python3 app.py gallery-benchmark --count 2000
```

The read-only benchmark requires at least one existing image in `outputs/`. It exposes 2,000 unique synthetic gallery records that cycle through at most ten real images, gives every thumbnail a unique browser URL to exercise network transfer and decoding, opens directly on Proofs, disables deletion, and reports both the record count and current `.output-card` DOM count. The server still reuses its RAM thumbnail cache, so no image copies are created. Stop it with `Ctrl+C`, then start the normal production server again.

In browser developer tools, record initial network transfer and browser memory, scroll from the first record to the last, open and navigate the lightbox, and confirm that the displayed DOM-card count remains bounded rather than approaching 2,000.

Keep the default loopback host unless access from another machine is explicitly required. The application has no user authentication and is intended for a trusted local environment.

## HTTP layout

The Web UI is served from `/`. All application endpoints are under `/api`.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/status` | ComfyUI, workflow, output, and catalog status |
| `POST` | `/api/storyboards` | Validate configuration and resolve a complete storyboard |
| `GET` | `/api/storyboards/{id}` | Retrieve a resolved storyboard |
| `GET` | `/api/storyboards/{id}/export` | Export a compact, database-bound storyboard JSON |
| `GET` | `/api/storyboards/{id}/director?shot={number}` | Read current and compatible Director controls |
| `POST` | `/api/storyboards/{id}/director` | Apply one validated SET- or shot-level direction |
| `POST` | `/api/storyboards/import` | Validate and restore a complete exported storyboard |
| `POST` | `/api/storyboards/{id}/shots/{number}/reroll` | Resolve a new compatible composition for one shot |
| `POST` | `/api/jobs` | Append a storyboard render job to the production queue |
| `GET` | `/api/jobs` | Discover the active render job and recover browser state after reload |
| `GET` | `/api/jobs/{id}` | Read render progress, ETA, errors, and outputs |
| `POST` | `/api/jobs/{id}/cancel` | Request cancellation between images |
| `POST` | `/api/previews` | Start a temporary Fast Preview for one storyboard shot |
| `GET` | `/api/previews/{id}` | Read temporary preview status |
| `GET` | `/api/previews/{id}/image` | Read the completed in-memory preview image |
| `DELETE` | `/api/previews/{id}` | Discard the temporary preview and its in-memory bytes |
| `GET` | `/api/workflow/profiles` | List captured rendering profiles and active selections |
| `GET` | `/api/workflow/capture-candidate` | Inspect the latest successful ComfyUI workflow and suggest a model-based name |
| `POST` | `/api/workflow/capture` | Capture or explicitly replace a named rendering profile |
| `POST` | `/api/workflow/profiles/select` | Select Production and Preview profiles |
| `GET` | `/api/outputs` | List generated image files in the output directory |
| `GET` | `/api/outputs/{filename}` | View or download a generated output |
| `DELETE` | `/api/outputs/{filename}` | Permanently delete one generated image |
| `DELETE` | `/api/outputs` | Permanently delete every generated image in the output directory |

Storyboard and job state is intentionally in memory. Restarting the server clears browser-session planning state but never removes generated files.

## Production modes

### SFW only

SFW only keeps every frame fully covered. It excludes lingerie, topless, nude, and explicit stages; prevents visible breasts, nipples, pubic area, or genitals; removes explicit recipes from resolution; and limits Director stage and intensity controls to compatible covered choices. The rule is enforced by the server for automatic resolution, rerolls, Director edits, and storyboard imports.

### Photoshoot

A photoshoot keeps the model, outfit, palette, interior, mood, and photography treatment fixed within each set. Stages progress forward across the configured shot count. Multiple photoshoots in one run are assembled as distinct sets.

### Random

Random mode resolves a complete independent context for every shot. The photoshoot count and progressive percentage controls are hidden because they do not apply.

### Progressive content

`NSFW ending` controls the percentage of final photoshoot frames assigned to topless, nude, and explicit stages. `Explicit plateau` controls how much of the complete run remains at the final explicit level. The plateau cannot exceed the NSFW ending.

Global structure controls are compared with the active resolved storyboard. Changing mode, content, counts, progression, or the Storyboard seed creates an explicit **Pending settings** state; render and per-shot preview actions first update the storyboard instead of silently using stale frames. The active and pending configurations remain visible together. When manual Director or shot adjustments exist, rebuilding requires confirmation. The NSFW controls show both percentages and calculated frame counts, clamp Explicit plateau to NSFW ending, and disable the plateau at 0%. Image variation seed and strategy remain non-structural and apply immediately without rebuilding direction.

### Full XXX

Full XXX begins at the explicit level from the first frame. Progressive percentage controls are disabled, while each shot still receives a rule-compatible explicit composition.

## Seeds

The UI calls the prompt seed **Storyboard seed** because it controls all compositional decisions. Leaving it empty creates a new seed and immediately writes the effective value back into the field; entering a value reproduces the same resolved storyboard.

Each global seed field has its own `↻` action. Refreshing Storyboard seed resolves a new direction; refreshing Image variation seed recalculates only frame variations and preserves Director edits.

The UI calls the inference seed **Image variation seed** because it changes rendered pixels without changing the direction. **Unique and repeatable per shot** derives a stable, distinct seed for every set/shot from the entered base seed. **Same variation for every shot** deliberately reuses one literal seed. **Fresh random variation per shot** creates independent seeds. Studio and Director provide **New variation** for changing only one shot’s inference seed; its prompt, composition and Director settings remain intact. The chosen strategy and every effective frame seed are stored in storyboard export.

After a storyboard exists, changing the Storyboard seed automatically resolves a replacement after a short typing delay because it controls the direction. Changing the Image variation seed or its mode updates only frame seeds in place: scenes, prompts, manually selected directions, and custom Director values remain intact. Studio cards and Director are refreshed together.

The prompt compiler keeps the subject constraint first, promotes camera and direction, removes exact duplicate fragments, and reports prompt-lint warnings without silently changing or truncating Director choices.

The compact storyboard format stores catalog references by ID and includes a semantic SHA-256 fingerprint of the complete database. Import succeeds only against the matching database content; reordering JSON keys does not break compatibility, but changing catalog data does. Imported storyboards remain fully reviewable, rerollable, and renderable.

## Director’s Desk

Resolve or import a storyboard, then open **Director** in the sidebar. The editor is organized in production order: identity, face, hair, body and anatomy, styling, wardrobe, scene and treatment, camera and editorial intent, then shot direction. Every compatible database preset is available through its relevant control. Current selections remain selected, curated database-pool values carry a **Default** marker, and the global search locates fields by both setting and preset text.

Subject, wardrobe, location, mood, and render-style changes apply to the complete photoshoot SET; in Random mode they affect only that independent shot. Stage, surface, camera, editorial role, explicit recipe, pose, action, and expression affect the selected shot. Director exposes every stage compatible with the active outfit recipe, including safe, terminal, and explicit variants. A manually selected stage may intentionally depart from automatic progression and immediately rebuilds all compatible shot controls. Incompatible records remain excluded, and all updates are rejected while that storyboard is rendering.

The planner keeps the model, wardrobe, location, mood, and treatment coherent per set while varying compatible surfaces and compositions. It assigns every shot an editorial role and resolves shot size, angle, framing, and focus against stage, pose, action, and surface. Exact garment-state differences are added as transition instructions only when a present garment disappears. Explicit stages use concrete database recipes with constrained pose/action/camera grammar.

Cross-field camera validation rejects contradictory tuples after resolution, during Director edits, and on storyboard import. Intimate actions require intimate focus and a three-quarter-or-closer treatment; intimate macro cannot use environmental framing; and rear-display recipes require rear-compatible angle, focus, and framing. Diagnostics include the exact conflicting catalog IDs.

Quick actions provide constrained remixes for the subject, current wardrobe recipe, complete scene/treatment, or selected shot. Director edits remain part of the in-memory storyboard and are preserved by compact JSON export.

Breast size and shape presets define a separate `covered_prompt` for clothing and lingerie stages. These prompts describe only the clothed bust silhouette and are paired with `prompt_defaults.covered_chest_negative`, which rejects bare breasts and visible nipples while the stage marks the chest as covered. Topless/nude stages continue to use the anatomical prompt instead. Areola, nipple, pubic-hair, and genital details remain strictly visibility-gated because they should not affect a covered silhouette.

## Workflow capture

First complete a representative workflow successfully in ComfyUI. Then open **Studio files → Rendering profiles**. The manager detects the main model name, proposes an editable profile name, and saves the graph as a recognizable `<profile>.workflow.json` file under `workflows/`.

Safe capture refuses to overwrite a matching profile unless **Replace matching profile** is enabled. Production and Preview can select different profiles. Profiles are independently validated, can be renamed or deleted from the manager, and every queued render snapshots its selected profile name. Active selections are stored in `workflows/profiles.json`; selected profiles cannot be deleted, and profile files cannot be renamed or deleted while the render queue is active.

## Preview render

Preview render patches the captured graph to keep the base sampler and VAE output while bypassing LoRA application and pruning downstream refiners/detailers. The synchronized Studio and Director split-buttons switch between **Preview storyboard** and **Render storyboard**, and their primary action runs the selected workflow. Individual **Preview** buttons always use the preview workflow. The refresh action targets the shot currently open in Director, falling back to the displayed preview shot elsewhere. Only its glyph spins during rendering; the button container remains stationary. While a replacement preview renders, the previous image remains visible; it is swapped and discarded only after the new preview succeeds. Preview activity, prompts, seed and elapsed time are shown in Logbook. Closing the draggable preview window discards its temporary image without adding anything to Proofs.

While production is active, using **Preview storyboard** or **Render storyboard** again appends another immutable storyboard snapshot to the FIFO render queue. The current image is never interrupted, queued jobs start automatically in submission order, and cancelling the active job advances to the next queued job after the current image finishes.

## Database

`database.json` contains more than 1,100 semantically distinct production records covering adult-model traits, garments, modifiers, outfit templates, private locations, surfaces, poses, actions, expressions, moods, camera grammar, explicit recipes, intimate arousal appearance, and photography treatments. Intimate arousal modifiers are selected deterministically only for explicit recipes with a visible intimate focus; they are excluded from rear, breast-focus, nude, and clothed compositions. Mechanical Studio/Editorial copies are prohibited: every selectable record must describe a distinct trait, garment construction, place, composition, or action. Combinatorial variety comes from composing real items with compatible colors, patterns, fabric textures, and surface finishes rather than duplicating records.

Full-XXX direction includes asymmetric side-lying, half-roll, overhead, and edge-seated open-leg compositions plus non-penetrative intimate hand direction. These records use the normal pose/action compatibility system and are available to both automatic resolution and Director.

Catalog wording is optimized for the captured Lumina2 workflow’s Qwen text encoder and remains broadly suitable for modern natural-language image conditioning: short concrete visual phrases, common garment/interior/anatomy/photography vocabulary, no internal taxonomy jargon, no duplicate prompt fragments, and no catalog fragment longer than 48 words. Database validation enforces these constraints. Clothing supports compatible color, pattern, and fabric-texture composition; suitable beds, sofas, chairs, rugs, cushions, and other textile surfaces support independent color and texture finishes. The compiler always preserves the complete deduplicated prompt; unusually long prompts produce a diagnostic warning instead of being modified.

The catalog follows the order in which a scene is assembled, so related material stays easy to find:

1. `settings` — defaults, progression, limits, and server timing.
2. `human_model_parts` — subject identity, face, hair, body, and styling.
3. `colors`, `patterns`, `fabric_textures`, `garments`, `outfit_templates` — wardrobe building blocks and complete outfits.
4. `poses`, `actions`, `props`, `expressions` — what the subject is doing and how it reads.
5. `interiors`, `furniture` — location and physical scene context.
6. `moods`, `photography_styles` — atmosphere and visual treatment.
7. `prompt_defaults` — final prompt compiler defaults and safety exclusions.

Within `human_model_parts`, traits progress from identity and complexion through face and hair to body and styling. Garments progress from upper/lower/full-body layers through lingerie, legwear, footwear, and accessories.

Records can be temporarily excluded without deletion:

```json
{
  "id": "example_item",
  "prompt": "example prompt fragment",
  "disabled": true
}
```

Validation rejects duplicate IDs, invalid references, incompatible dependencies, bad weights, invalid stage definitions, and empty required pools before a storyboard or GPU job can begin.

- Output deletion is permanent and always requires confirmation in the Web UI. In the lightbox, `Delete` and macOS `Backspace` open the same confirmation.
- Deletion is disabled while a render job is queued or running. Bulk deletion removes supported image files only and leaves unrelated files and directories untouched.
## Operational notes

- Generated files are written to the configured `settings.output_dir`.
- A render cancellation takes effect after the current ComfyUI image finishes.
- Closing the browser does not stop the server or an active render job.
- Stop the server with `Ctrl+C` in the launcher terminal.
- ComfyUI connection failures and workflow validation errors appear as non-blocking UI notifications and structured API errors.
