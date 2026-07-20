# Project Valhalla Production Studio

Project Valhalla is a local, browser-based production interface for composing rule-compatible image prompts and rendering them through a captured Stability Matrix / ComfyUI workflow.

The application now uses a web-first architecture:

- `app.py` contains the composition engine, ComfyUI client, HTTP API, background job runner, and static-file server.
- `web/` contains the responsive production interface.
- `launcher.sh` checks the Python dependency, starts the local server, and opens the browser.
- `database.json` is the manually editable production content catalog.
- `workflow.json` is the captured ComfyUI API workflow.
- `outputs/` contains downloaded generated images.

There is no terminal wizard and no `fzf` dependency. The terminal is used only for server startup and operational logs.

## Interface

The Production Studio is designed around a review-before-render workflow:

1. Configure the production mode, content direction, batch size, progression, and seeds.
2. Select **Resolve storyboard** to assemble every compatible shot without using the GPU.
3. Review stage, pose, action, expression, set, and surface for every shot.
4. Inspect positive and negative prompts or reroll individual compositions.
5. Select **Generate images** when the storyboard is ready.
6. Follow live progress and ETA while outputs appear in the gallery.

The UI includes:

- responsive desktop, tablet, and mobile layouts;
- automatic operating-system light/dark appearance through `prefers-color-scheme`;
- a session theme switcher for System, Light, and Dark modes;
- live ComfyUI, workflow, and catalog status;
- progressive and full-XXX production controls;
- deterministic prompt seeds and optional fixed inference seeds;
- production and fast-test render profiles;
- automatic recovery of the active storyboard, settings, render progress, ETA, outputs, and polling after a browser reload;
- storyboard cards with one-shot reroll, prompt inspection, temporary Fast Preview, and compact JSON export/import tied to the exact semantic database version;
- a dedicated Director’s Desk with exact subject, anatomy, hair, styling, wardrobe, modifier, location, mood, render-style, stage, pose, action, and expression controls plus constrained SET/shot remixes;
- cancellable background render jobs;
- shared Studio/Director render controls and draggable, memory-only single-shot Fast Preview windows;
- a persistent output gallery with full-screen preview, real-size 100% default, adjacent Fit/zoom controls, center-anchored 25–300% scaling, retained settings across images/reloads, previous/next navigation, swipe, downloads, individual deletion, and confirmed bulk deletion;
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
| `POST` | `/api/jobs` | Start a background render job for a storyboard |
| `GET` | `/api/jobs` | Discover the active render job and recover browser state after reload |
| `GET` | `/api/jobs/{id}` | Read render progress, ETA, errors, and outputs |
| `POST` | `/api/jobs/{id}/cancel` | Request cancellation between images |
| `POST` | `/api/previews` | Start a temporary Fast Preview for one storyboard shot |
| `GET` | `/api/previews/{id}` | Read temporary preview status |
| `GET` | `/api/previews/{id}/image` | Read the completed in-memory preview image |
| `DELETE` | `/api/previews/{id}` | Discard the temporary preview and its in-memory bytes |
| `POST` | `/api/workflow/capture` | Capture the latest successful ComfyUI workflow |
| `GET` | `/api/outputs` | List generated image files in the output directory |
| `GET` | `/api/outputs/{filename}` | View or download a generated output |
| `DELETE` | `/api/outputs/{filename}` | Permanently delete one generated image |
| `DELETE` | `/api/outputs` | Permanently delete every generated image in the output directory |

Storyboard and job state is intentionally in memory. Restarting the server clears browser-session planning state but never removes generated files.

## Production modes

### Photoshoot

A photoshoot keeps the model, outfit, palette, interior, mood, and photography treatment fixed within each set. Stages progress forward across the configured shot count. Multiple photoshoots in one run are assembled as distinct sets.

### Random

Random mode resolves a complete independent context for every shot. The photoshoot count and progressive percentage controls are hidden because they do not apply.

### Progressive content

`NSFW ending` controls the percentage of final photoshoot frames assigned to topless, nude, and explicit stages. `Explicit plateau` controls how much of the complete run remains at the final explicit level. The plateau cannot exceed the NSFW ending.

### Full XXX

Full XXX begins at the explicit level from the first frame. Progressive percentage controls are disabled, while each shot still receives a rule-compatible explicit composition.

## Seeds

The prompt seed controls all compositional decisions. Leaving it empty creates a new random seed; entering a value reproduces the same resolved storyboard.

The inference seed is sent to ComfyUI. Leaving it empty produces a different seed for every image. Entering a value deliberately reuses the same literal seed for the complete run.

The compact storyboard format stores catalog references by ID and includes a semantic SHA-256 fingerprint of the complete database. Import succeeds only against the matching database content; reordering JSON keys does not break compatibility, but changing catalog data does. Imported storyboards remain fully reviewable, rerollable, and renderable.

## Director’s Desk

Resolve or import a storyboard, then open **Director** in the sidebar. The editor is organized in production order: identity, face, hair, body and anatomy, styling, wardrobe, scene and treatment, then shot direction. Every enabled database preset is available through its relevant control. Current selections remain selected, curated database-pool values carry a **Default** marker, and the global search locates fields by both setting and preset text.

Subject, wardrobe, location, mood, and render-style changes apply to the complete photoshoot SET; in Random mode they affect only that independent shot. Stage, pose, action, and expression affect the selected shot. Director exposes every stage compatible with the active outfit recipe, including safe, terminal, and explicit variants, even when the storyboard began in Full XXX mode. A manually selected stage may intentionally depart from automatic progression and immediately rebuilds the compatible pose, action, and expression choices. Changing a foundational choice automatically repairs dependent traits, furniture, clothing, or composition when necessary. Optional outfit slots can be added or removed. Incompatible records remain excluded, and all updates are rejected while that storyboard is rendering.

Quick actions provide constrained remixes for the subject, current wardrobe recipe, complete scene/treatment, or selected shot. Director edits remain part of the in-memory storyboard and are preserved by compact JSON export.

Breast size and shape presets define a separate `covered_prompt` for clothing and lingerie stages. These prompts describe only the clothed bust silhouette and are paired with `prompt_defaults.covered_chest_negative`, which rejects bare breasts and visible nipples while the stage marks the chest as covered. Topless/nude stages continue to use the anatomical prompt instead. Areola, nipple, pubic-hair, and genital details remain strictly visibility-gated because they should not affect a covered silhouette.

## Workflow capture

First complete a representative workflow successfully in ComfyUI. Then choose **Capture workflow** in the top bar.

Safe capture refuses to overwrite an existing `workflow.json`. Enable **Replace existing workflow** only when the active template should be replaced. Capture detects positive and negative prompt inputs, inference seed targets, and the fast-test sampler/output mapping before saving.

## Fast test

Fast test patches the captured graph to keep the base sampler and VAE output while bypassing LoRA application and pruning downstream refiners/detailers. It is intended for rapid prompt and composition checks. With Fast test enabled, any Studio shot—or the selected Director shot—can be rendered alone through **Preview**. Preview output nodes use ComfyUI temporary previews, Project Valhalla keeps the returned image only in memory, and closing the draggable preview window discards it without adding anything to the output gallery. Production mode runs the complete captured workflow.

## Database

`database.json` contains 901 selectable production records covering adult-model traits, garments, modifiers, outfit templates, private locations, surfaces, poses, actions, expressions, moods, and photography treatments.

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
