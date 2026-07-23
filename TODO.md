# Valhalla Photo Studio — Roadmap

This file describes the verified implementation state and the agreed next work.
Checked items are implemented and covered by the current application or regression suite.
Unchecked items are planned work, not claims about missing historical features.

## Project constraints

- Keep one `server.py`, one local `config.json`, one manually editable `database.json`, a server-side `workflows/` library, one `launcher.sh`, and static assets under `client/`.
- Preserve compatibility with different checkpoint families through the captured workflow.
- Do not add FaceID, IPAdapter, PuLID, reference-image, or architecture-specific identity pipelines.
- Do not add an image-quality detector or external vision model in the current roadmap.
- Use adult women aged 21–23 only.
- Keep all scenes solo and locations private.
- Do not add mirrors, sexual toys, male subjects, or partner interactions.
- Preserve the review-before-render, web-first workflow; add CLI commands only for validation or automation that the Web UI does not already provide.

## Completed foundation

- [x] Resolve the complete batch before rendering and stop visibly when a scene or render fails.
- [x] Support coherent photoshoots and independent random-mode shots.
- [x] Keep model, outfit, palette, interior, mood, and photography style fixed within each photoshoot.
- [x] Build progressive stages that do not move backward and support Full XXX from the first frame.
- [x] Provide Studio, Director’s Desk, complete-storyboard reroll, single-shot reroll, exact Director controls, and compatible remixes.
- [x] Prevent render and preview actions from using stale structural settings.
- [x] Apply Image Variation changes without rebuilding scene direction.
- [x] Provide deterministic Storyboard seeds plus fixed, random, and stable per-frame Image Variation strategies.
- [x] Derive stable per-frame seeds from base seed, photoshoot index, and shot index with SHA-256 rather than Python `hash()`.
- [x] Display the base Image Variation seed in active configuration and each effective frame seed in Studio, Director, and Logger.
- [x] Resolve one default storyboard when no recoverable storyboard exists.
- [x] Provide cancellable production jobs, memory-only Fast Preview, reload-safe Logger state, ETA, prompts, seeds, and generation events.
- [x] Queue additional production jobs during an active render and execute them in deterministic FIFO order.
- [x] Support one-shot render/regeneration from Studio and Director.
- [x] Provide compact database-bound storyboard export and import.
- [x] Remove Studio generation-count maximums while retaining positive-integer validation.
- [x] Provide an output gallery with full-screen inspection, zoom, navigation, download, individual deletion, and bulk deletion.
- [x] Generate 512 px JPEG gallery thumbnails on demand without writing thumbnail files to disk.
- [x] Cache encoded thumbnails in a bounded 128 MB RAM LRU cache, invalidate deleted outputs, and version replacements by file metadata.
- [x] Load gallery thumbnails lazily with asynchronous browser decoding while reserving original files for viewer and download actions.
- [x] Return from the fullscreen lightbox with the last viewed output aligned to the top of the thumbnail grid when layout permits.
- [x] Provide true browser fullscreen and a configurable 1–10 second lightbox slideshow that survives manual image skips.
- [x] Auto-hide the fullscreen control panel and reveal it when the pointer returns to the top edge.
- [x] Support `disabled: true` across selectable database records.
- [x] Provide an enforced SFW-only content mode across Studio, Director, rerolls, and imports.
- [x] Maintain more than 1,100 semantically distinct catalog records with validated IDs, tags, dependencies, stage rules, and compatible modifiers.
- [x] Reject duplicate, internal, or overlong catalog fragments and preserve the complete deduplicated prompt without destructive truncation.

## Current implementation cycle

The next work is deliberately split into independently testable increments.

### P0 — Output Gallery scale and memory

- [x] Stop gallery cards from loading and decoding full-resolution originals.
- [x] Add versioned thumbnail URLs and long-lived browser caching.
- [x] Bound the server-side thumbnail cache by encoded byte size.
- [x] Coalesce simultaneous requests for the same uncached thumbnail so it is generated only once.
- [x] Virtualize gallery cards when the collection is large, keeping the viewport plus a small overscan window in the DOM.
- [x] Keep keyboard navigation, deletion indexes, lightbox navigation, and scroll position correct with virtualization.
- [x] Add regression coverage for cache eviction, invalidation, concurrent cache misses, and thumbnail-generation failures.
- [ ] Measure a gallery containing at least 2,000 outputs and record network transfer, decoded browser memory, and scroll responsiveness.
  - Manual checkpoint: 4,000 unique synthetic thumbnail URLs remained responsive; exact network and decoded-memory figures are still pending.

Ready when:

- Scrolling never fetches full-resolution originals.
- Repeated thumbnail requests are served from browser or RAM cache.
- Server thumbnail memory remains within its configured bound.
- A 2,000-output gallery remains responsive and DOM size remains bounded.

### P0 — Camera grammar validation

- [x] Add `shot_sizes`, `camera_angles`, `framings`, and `focus_targets` to `database.json`.
- [x] Resolve camera candidates against stage, pose, action, furniture, recipe tags, and visibility requirements.
- [x] Add explicit cross-field rules that reject intimate macro with full-body or environmental framing.
- [x] Require rear-compatible angles and framing for rear-display recipes.
- [x] Require suitable close-ups and focus targets for intimate actions.
- [x] Report the exact conflicting IDs when a camera combination is rejected.
- [x] Add a deterministic camera-aware stress test covering at least 10,000 planned scenes.

Ready when:

- Every resolved scene has a shot size, angle, framing, and focus target.
- Invalid camera tuples cannot be produced automatically or selected in Director.
- The 10,000-scene stress test reports no camera conflicts.

### P0 — Full-XXX storyboard planning and shuffle bags

- [x] Replace the three broad Full-XXX stage kinds with planning over the concrete enabled recipe catalog.
- [x] Plan Full XXX as an explicit editorial arc rather than a sequence of independently selected explicit frames.
- [x] Start at explicit intensity, build variation deliberately, and reserve peak intensity for a suitable closing shot.
- [x] Implement seeded weighted shuffle bags for explicit recipes, pose families, action families, shot sizes, and angles.
- [x] Keep bags separate by photoshoot and compatible stage/recipe family.
- [x] Exhaust compatible recipe families before reuse, then refill deterministically.
- [x] Prevent identical adjacent pose/action/camera tuples even after a bag refill.
- [x] Use the same deterministic bag rules in photoshoot and Random Full-XXX modes.

Ready when:

- One Storyboard seed reproduces the complete recipe and shuffle-bag order.
- Every enabled compatible recipe is used before repetition.
- Adjacent explicit shots have deliberate, explainable variation.
- The final shot uses a compatible peak role, intensity, expression, and camera treatment.

### P0 — Standalone validation and statistics

- [x] Add `python server.py validate` without changing normal Web UI startup.
- [x] Stress-test every enabled outfit template through the resolver.
- [x] Validate camera tuples, explicit recipes, garment transitions, and stage reachability.
- [ ] Find unreachable IDs and records unused by every recipe, template, and configured pool.
- [x] Return a non-zero exit code for structural, reachability, or stress-test failures.
- [ ] Add `python server.py stats` for record counts, tags, recipe coverage, and candidate-pool sizes.
- [ ] Document both commands and make them optionally accessible from `launcher.sh` without adding an interactive terminal wizard.

Ready when:

- Production validation no longer depends on redirecting a large dry-run.
- CI or a local script can distinguish warnings from validation failures.
- Coverage reports identify narrow or unreachable candidate pools before rendering.

## P1 — Prompt Compiler v2

- [x] Keep a concise solo adult subject constraint at the prompt start.
- [x] Preserve selected prompt fragments and warn about unusual length without truncation.
- [x] Deduplicate exact normalized fragments and lint repeated subjects, conflicting framing, and contradictory clothing.
- [x] Add covered-chest, layered-hosiery, explicit-plateau, and recipe-specific negative additions.
- [x] Define and test one explicit diffusion-priority order for subject → camera/direction → anatomy → traits/garments → location/treatment.
- [x] Keep each human trait in exactly one semantic prompt block.
- [x] Replace incremental negative additions with named stage-specific negative profiles.
- [x] Remove explicit-anatomy and censorship negatives from covered fashion stages when they are irrelevant.
- [x] Strengthen coverage negatives only where clothing must remain opaque and explicit negatives only where anatomy must remain visible.

Ready when:

- Prompt ordering is intentional, documented, and regression-tested.
- Compiled prompts contain no repeated human trait fragments.
- Covered, lingerie, nude, and explicit stages receive distinct relevant negatives.
- One resolved scene compiles deterministically.

## P1 — Visual trait prioritization

- [x] Preserve the complete deterministic `model_signature` for reproducibility.
- [x] Provide a concise model description for Studio and Director diagnostics.
- [x] Keep Director-selected traits available even when a concise summary is displayed.
- [x] Avoid prompts that claim cross-frame identity mechanisms the backend does not have.
- [x] Apply seeded arousal-moisture appearance only to explicit recipes with a visible intimate focus.
- [x] Add reachable asymmetric Full-XXX poses and non-penetrative intimate hand-direction actions.
- [x] Separate visually dominant traits from low-impact detail in compiler ordering.
- [x] Select one or two compatible distinctive facial accents when available.
- [x] Expand compatible beauty marks and facial accents without creating mechanical variants.
- [x] Add regression coverage proving each human trait is emitted once and visibility-gated anatomy is emitted only when visible.

Ready when:

- The complete selected trait set remains fixed within a photoshoot.
- Important face, hair, skin, and body traits appear before minor styling details.
- The concise UI summary never changes or discards the resolved model signature.

## P1 — Dynamic location surfaces

- [x] Fix interior, palette, mood, and photography treatment per photoshoot.
- [x] Allow different compatible surfaces within the same interior.
- [x] Preserve recognizable room identity while surface, pose, and camera direction vary.
- [x] Model zones explicitly: bed, bed edge, wall, vanity, window, rug, sofa, chair, pool edge, and garden surface.
- [x] Add zone capabilities for standing, seated, reclining, kneeling, supported, and close-up compositions.
- [x] Match pose, action, shot size, and camera angle to zone capabilities.
- [x] Validate that bathroom, pool, bedroom, and outdoor zone families cannot mix incorrectly.

Ready when:

- Surface variation never changes the photoshoot’s location identity.
- Every selected pose is physically compatible with its zone.
- Location-family conflicts are rejected with an exact diagnostic.

## P1 — Exact garment transitions

- [x] Compare visible garment slots with the previous stage.
- [x] Calculate which slots disappeared and never describe removal of an absent garment.
- [x] Track removed slots explicitly across the whole photoshoot and prevent restoration in progressive mode.
- [x] Describe the exact removed garment slots as state, without adding a second hand action that can conflict with the selected shot action.
- [x] Support intentionally retained stockings, heels, garters, and accessories as planned terminal state.
- [x] Add regression and stress tests proving a garment is never removed twice or restored unintentionally.

Ready when:

- Every transition action matches the actual garment-state difference.
- Anatomy becomes visible only after the corresponding garment transition.
- Dry-runs contain no impossible, repeated, or reversed removal actions.

## P1 — Intensity system

- [x] Add the shared `fashion`, `sensual`, `erotic`, `nude`, `explicit`, and `peak` labels.
- [x] Assign allowed intensity ranges to poses, actions, expressions, recipes, camera framing, and treatment.
- [x] Reject incompatible intensity combinations and unexplained jumps.
- [x] Increase intensity monotonically in progressive photoshoots.
- [x] Integrate intensity into Full-XXX editorial planning and shuffle-bag selection.

Ready when:

- Expression and camera treatment match action and recipe intensity.
- Progressive intensity never moves backward.
- Peak shots receive suitable role, framing, action, and expression.

## P2 — Review artifacts and reporting

- [x] Review a resolved storyboard without GPU work in Studio.
- [x] Inspect the full resolved prompt and key shot metadata in Studio and Director.
- [ ] Add a printable/exportable local HTML contact sheet only if the persistent Output Gallery does not cover the review need.
- [ ] If implemented, show thumbnails, shot index, stage, pose/action, seeds, model signature, and collapsible prompts.
- [ ] Include sufficient metadata to reproduce a frame manually without JSONL output.
- [ ] Reuse the existing thumbnail endpoint/cache rather than generating a second thumbnail system.

## P1 — Output Gallery photoshoot grouping

- [x] Add a frontend-only toggle between the current flat Outputs grid and a grouped Photoshoots view.
- [x] Derive photoshoot groups entirely from existing output metadata and filenames without moving, copying, or rewriting output files.
- [x] Represent each photoshoot as one thumbnail card using a representative frame and show its frame count.
- [x] Open a photoshoot card into a focused grid containing only that photoshoot’s outputs.
- [x] Provide an immediate, obvious way to return from an opened photoshoot to the photoshoot-thumbnail list.
- [x] Allow switching back to the current flat representation at any time.
- [x] Keep lightbox navigation, downloads, deletion, live render additions, and virtualized rendering correct in flat and grouped views.
- [x] Remember the user’s scroll position and last focused output in flat view while they inspect grouped photoshoots, and restore both when returning.
- [x] Persist the selected gallery representation for the browser session.

Ready when:

- A large multi-photoshoot output collection can be browsed by set without changing server files or API state.
- Entering and leaving a photoshoot requires one obvious action in either direction.
- Returning to flat view restores the user’s previous browsing position.
- Outputs arriving from an active render join the correct photoshoot without resetting navigation.

## P1 — Named workflow rendering profiles

- [x] Replace the single captured-workflow model with a server-side directory of workflow profiles.
- [x] Extract the main checkpoint/model name from each captured workflow and use a sanitized form as the default profile name.
- [x] Allow the user to review and edit the proposed profile name before saving.
- [x] Include the sanitized profile name in its workflow filename so the profile directory remains understandable without the Web UI.
- [x] Store each captured workflow as an independently selectable profile file without overwriting unrelated profiles.
- [x] Rename the profile file atomically when its profile name changes, and reject filename collisions before modifying anything.
- [x] List available profiles in the Web UI and clearly show the active profile.
- [x] Allow selecting which profile is used for production rendering and Preview rendering.
- [x] Validate every profile independently, including prompt, seed, sampler, VAE, save-output, and Preview-path mappings.
- [x] Prevent ambiguous duplicate profile names and report exact invalid or missing profile files.
- [x] Preserve safe capture behavior when replacing an existing profile and require explicit confirmation for replacement.
- [x] Keep profile selection in storyboard/job metadata so Logger and recovered render state identify the workflow used.
- [x] Define deterministic behavior when a selected profile is renamed, deleted, invalid, or unavailable after server restart.
- [x] Update status reporting, capture endpoints, documentation, and regression tests for the profile directory.

Ready when:

- Multiple checkpoint families can each retain their own captured workflow and preview mapping.
- A user can capture, name, select, replace, and diagnose profiles without manually renaming JSON files, while filenames remain recognizable from their profile names.
- Every render and preview records the exact selected profile.
- Missing or invalid profiles fail before GPU work with an actionable diagnostic.

The old `python server.py plan` proposal is removed from the active roadmap because Studio already provides a richer GPU-free plan. CLI work is reserved for `validate` and `stats`.

## Regression checklist

- [x] The same Storyboard seed reproduces model signature, context, and prompts; the same base Image Variation seed also reproduces deterministic frame seeds.
- [x] Photoshoot mode keeps one model, outfit, location, palette, mood, and treatment per set.
- [x] Random mode rebuilds context for every frame.
- [x] Progressive stages never move backward.
- [x] Full-XXX mode contains no covered or lingerie stages.
- [x] Positive prompts describe one solo adult woman only.
- [x] No sexual toy is selectable or emitted in a positive prompt.
- [x] Outdoor locations are private rather than public.
- [x] Python compilation, JSON validation, shell syntax, unit tests, and `git diff --check` pass.
- [ ] No garment is removed twice or restored after removal.
- [x] Camera-aware stress test of 10,000 planned scenes passes.
- [ ] A 2,000-output gallery remains responsive with bounded DOM and thumbnail memory.

## Planned implementation order

1. Measure and document the 2,000-output gallery acceptance case.
2. Add standalone `validate`, then `stats`, using the same resolver and validation rules as the Web UI.
3. Replace the single captured workflow with named, selectable workflow profiles.
4. Replace broad Full-XXX kinds with deterministic recipe planning and weighted shuffle bags.
5. Integrate the intensity system with progressive and Full-XXX planning.
6. Implement explicit garment-state tracking and matching transition actions.
7. Refactor Prompt Compiler v2 and visual-trait ordering.
8. Add location zones and physical surface capabilities.
9. Reassess whether an HTML contact sheet adds value beyond the optimized Output Gallery.
