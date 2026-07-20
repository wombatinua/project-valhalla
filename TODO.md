# Project Valhalla — Roadmap

This file tracks agreed future work. Unchecked items are not implemented.

## Project constraints

- Keep one `app.py`, one manually editable `database.json`, one active local `workflow.json`, one `launcher.sh`, and static assets under `web/`.
- Preserve compatibility with different checkpoint families through the captured workflow.
- Do not add FaceID, IPAdapter, PuLID, reference-image, or architecture-specific identity pipelines.
- Use adult women aged 21–23 only.
- Keep all scenes solo and locations private.
- Do not add mirrors, sexual toys, male subjects, or partner interactions.

## Completed foundation

- [x] Resolve the complete batch before rendering.
- [x] Keep model, outfit, palette, interior, mood, and photography style fixed within each photoshoot.
- [x] Support independent context assembly for every random-mode image.
- [x] Build a progressive stage sequence that does not move backward.
- [x] Guarantee an explicit final plateau and support full-XXX mode from the first frame.
- [x] Stop the batch when a scene cannot be resolved.
- [x] Provide an interactive browser-based Director’s Desk before any GPU job.
- [x] Support complete-storyboard reroll, single-shot reroll, stage selection, and compatible pose/action/expression selection.
- [x] Provide Casting & Set Design for subject, wardrobe, interior, surface, mood, and photography style.
- [x] Support constrained subject, wardrobe, interior, and surface remixing.
- [x] Support all-groups, semantic-group, and exact-item choices across Director catalogs.
- [x] Prevent manually edited stages from reversing photoshoot progression.
- [x] Keep automatic operation available without storyboard review.
- [x] Provide accessible browser-native controls for every production choice.
- [x] Provide a responsive production dashboard with totals, advanced settings, and a clear path to Director.
- [x] Group high-level Web UI actions into clear production sections.
- [x] Distinguish active storyboard configuration from pending global setup changes.
- [x] Prevent render and preview actions from using stale mode, count, progression, or Storyboard-seed settings.
- [x] Show progression percentages as concrete frame counts and couple NSFW/explicit sliders safely.
- [x] Apply Image variation settings immediately while confirming destructive rebuilds after manual shot edits.
- [x] Provide draggable, resizable, memory-only Fast Preview windows with responsive viewport limits and automatic cleanup on close.
- [x] Provide a persistent Render Logger tab with live frame counts, elapsed/remaining time, seeds, formatted prompts, errors, and generation events.
- [x] Include Preview renders in Logger and keep the previous preview visible until its replacement finishes.
- [x] Allow the visible preview to be rendered again directly from its popup header.
- [x] Make preview refresh follow the currently open Director shot, spin only its glyph, and clear Logger history without deleting outputs or displayed preview data.
- [x] Automatically re-resolve the storyboard and refresh Director after Studio seed or seed-strategy changes.
- [x] Automatically resolve one default storyboard when the application opens with no recoverable storyboard.
- [x] Present seeds as Storyboard and Image Variation concepts, expose generated values, and randomize one shot’s inference seed without changing its direction.
- [x] Recalculate storyboard image-variation seeds in place without resetting custom Director fields or resolved scenes.
- [x] Provide independent one-click regeneration controls for Storyboard and Image Variation seeds.
- [x] Order Studio and Director frame actions by edit, inspect, vary, preview, and render workflow.
- [x] Support `disabled: true` across selectable database records.
- [x] Remove mirrors, sexual toys, and non-functional identity-consistency prompt procedures.
- [x] Maintain README documentation alongside implementation.
- [x] Maintain more than 1,100 semantically unique production records while preserving tags, dependencies, stage rules, pools, and Director performance.
- [x] Remove mechanical Studio/Editorial copies and derive variety from distinct pieces plus compatible color, pattern, fabric-texture, and surface modifiers.
- [x] Normalize catalog prompts for Lumina2/Qwen and general image-model conditioning, reject duplicate/internal/overlong fragments, and preserve the complete deduplicated prompt.

## P0 — Storyboard editorial planning

- [x] Plan shot size, camera angle, framing, pose family, action family, and expression intensity across the complete series.
- [x] Build a deliberate editorial arc: establishing → medium → reveal → nude → explicit plateau.
- [ ] Plan `xxx-only` as a complete explicit storyboard rather than independent explicit frames.
- [x] Pass planned storyboard choices into the resolver without random replacement.
- [x] Give every frame an explainable role in the series.
- [x] Prevent unjustified duplicate compositions in adjacent frames.

Ready when:

- The same prompt seed reproduces the identical storyboard.
- Every frame has an explicit editorial role.
- Progression never moves backward.
- Adjacent frames do not repeat composition without a deliberate rule.

## P0 — Camera grammar

- [x] Add `shot_sizes`, `camera_angles`, `framings`, and `focus_targets` to `database.json`.
- [x] Support full body, three-quarter, medium, portrait, torso close-up, breast close-up, intimate macro, and rear close-up.
- [x] Support eye-level, low, high, overhead, rear, and over-the-shoulder angles.
- [x] Support centered, diagonal editorial, symmetrical, tight-crop, and environmental framing.
- [x] Resolve camera grammar against pose, action, furniture, visibility, and exposure stage.
- [ ] Reject combinations such as intimate macro with full-body framing.
- [ ] Require rear angles for rear-display recipes and suitable close-ups for intimate actions.

Ready when:

- Every resolved scene has a shot size, angle, framing, and focus target.
- Validation finds unreachable or incompatible camera records.
- A 5,000-frame dry-run produces no framing conflicts.

## P0 — Weighted shuffle bags and diversity

- [ ] Replace independent weighted selection for major shot categories with weighted shuffle bags.
- [x] Avoid repeating pose, action, expression, shot size, or angle before the compatible pool is exhausted.
- [ ] Keep separate bags for each photoshoot and stage family.
- [ ] Permit reuse after exhaustion while preventing identical adjacent shots.
- [x] Calculate a storyboard diversity score.
- [x] Penalize repeated pose family, action family, camera angle, shot size, and surface.
- [ ] Do not penalize intentionally fixed model, outfit, location, palette, or lighting.

Ready when:

- All available plateau recipes are used before repetition.
- Adjacent shots do not share the same pose/action pair.
- One prompt seed reproduces shuffle-bag order exactly.

## P0 — Deterministic inference-seed sequence

- [x] Preserve current fixed and random-per-image strategies.
- [x] Add a deterministic-sequence strategy.
- [x] Derive each frame seed from a base seed, photoshoot index, and shot index using a stable hash algorithm.
- [x] Do not use Python `hash()`, which changes between processes.
- [ ] Print the base seed and effective frame seed.
- [x] Add strategy selection to the launcher Advanced menu.
- [x] Preserve literal seed reuse in fixed mode.

Ready when:

- Reusing a base seed reproduces every inference seed.
- Different frames receive different seeds.
- Photoshoots in one batch do not overlap seed sequences.

## P1 — Prompt Compiler v2

- [ ] Order prompts by diffusion priority: solo/adult constraint → camera → pose/action → visible anatomy → human traits → visible garments → location → expression → lighting/quality.
- [ ] Keep each human trait in one prompt block only.
- [x] Remove misleading prompt profiles that differed only through destructive trimming.
- [x] Remove unsafe approximate prompt budgeting; warn about unusually long prompts without truncating them.
- [x] Preserve every selected fragment; report long prompts diagnostically without modifying them.
- [ ] Make negative prompts stage-specific.
- [ ] Remove irrelevant negatives from fashion stages.
- [ ] Strengthen coverage and censorship negatives only for explicit stages.
- [x] Add linting for duplicate subjects, conflicting framing, contradictory clothing, and repeated fragments.

Ready when:

- Pose and action remain in the high-priority prompt section.
- Compact prompts preserve subject traits and stage semantics.
- Compiled prompts contain no repeated trait fragments.
- One resolved scene compiles deterministically.

## P1 — Visual trait prioritization

- [ ] Keep the complete `model_signature` for reproducibility and console output.
- [ ] Define a concise visual-trait summary for diagnostics without dropping Director choices or claiming cross-frame identity control.
- [ ] Prioritize face, hair, skin, and body traits that materially affect the rendered subject.
- [ ] Select one or two distinctive beauty details when available.
- [ ] Add more compatible beauty marks and facial accents.
- [ ] Keep the concise `solo adult woman` and `single subject` constraints at the prompt start.
- [ ] Avoid temporal or cross-frame identity language that the backend cannot understand.

Ready when:

- The selected trait subset is fixed within a photoshoot.
- Human traits appear only once in the compiled prompt.
- The full model signature remains available in console output.

## P1 — Dynamic location surfaces

- [ ] Fix interior, palette, mood, time of day, and lighting family per photoshoot.
- [x] Allow different compatible surfaces within the same interior.
- [ ] Add zones such as bed, bed edge, wall, vanity, window, rug, sofa, chair, pool edge, and garden surface.
- [ ] Match poses and shot sizes to surface capabilities.
- [ ] Preserve recognizable room identity while changing surfaces.

Ready when:

- A photoshoot retains one recognizable location.
- Surfaces vary without logical conflicts.
- Bathroom, pool, bedroom, and outdoor surface families do not mix incorrectly.

## P1 — Exact garment transitions

- [x] Compare visible garment slots with the previous stage.
- [x] Calculate exactly which slots were removed or revealed.
- [ ] Select an undressing action matching the actual garment type.
- [ ] Add actions for zippers, buttons, straps, bra hooks, skirts, dresses, panties, stockings, and footwear.
- [ ] Support intentionally retained stockings, heels, garters, and accessories.
- [x] Never describe removing a garment that is absent or already removed.
- [ ] Never restore removed clothing during progressive photoshoots.

Ready when:

- Every undressing action matches the garment state difference.
- Dry-runs contain no impossible removal actions.
- Anatomy becomes visible only after the corresponding transition.

## P1 — Explicit plateau recipes

- [ ] Replace the three broad plateau kinds with a catalog of concrete recipes.
- [x] Add rear standing, rear all-fours, bent-over, legs-up, legs-wide, intimate macro, breast-focus, hands-only stimulation, and climax recipes.
- [x] Define pose tags, action tags, camera grammar, visibility, furniture, and expression intensity for every recipe.
- [x] Add configurable recipe weights to `database.json`.
- [x] Allow individual recipe families to be disabled.
- [ ] Distribute active recipe families across the plateau before repeating them.
- [ ] Use weighted shuffle bags in `random --xxx-only`.

Ready when:

- Every active recipe is reachable.
- Recipes never combine incompatible pose, action, camera, or surface components.
- Hands-only actions never add external objects.
- Expression intensity matches the action.

## P1 — Intensity scale

- [x] Add a shared `fashion`, `sensual`, `erotic`, `nude`, `explicit`, and `peak` scale.
- [ ] Assign intensity to poses, actions, expressions, camera framing, and lighting.
- [ ] Reject incompatible intensity jumps.
- [ ] Increase intensity smoothly in progressive photoshoots.
- [ ] Start `xxx-only` at explicit and finish at peak.

Ready when:

- Expression intensity matches action intensity.
- Progressive intensity never moves backward.
- Peak shots receive suitable framing, action, and expression.

## P2 — `plan` command

- [ ] Add `python app.py plan` with the normal mode, seed, and count options.
- [ ] Print a compact storyboard without full prompts.
- [ ] Include stage, shot size, angle, pose, action, expression, and surface.
- [ ] Add `--verbose` for the complete resolved prompt.
- [ ] Add `plan` to the launcher.

Ready when:

- A storyboard can be reviewed without GPU work.
- `plan` and `generate` produce identical scenes from identical seeds.

## P2 — `validate` and `stats` commands

- [ ] Add a standalone `validate` command.
- [ ] Stress-test every outfit template through the resolver.
- [ ] Validate camera combinations and plateau recipes.
- [ ] Find unreachable IDs.
- [ ] Find records unused by every recipe and template.
- [ ] Add a `stats` command for counts, tags, coverage, and candidate-pool sizes.
- [ ] Add both commands to the launcher.

Ready when:

- Production validation does not require redirecting a large dry-run.
- Structural or reachability conflicts produce a non-zero exit code.

## P2 — HTML contact sheet

- [ ] Create a directory for each photoshoot.
- [ ] Generate a local dependency-free `index.html`.
- [ ] Show thumbnails, shot index, stage, pose/action, and seeds.
- [ ] Put the model signature and resolved prompt in collapsible details.
- [ ] Include a ready-to-run reproduction command.
- [ ] Do not create JSONL output.
- [ ] Make contact-sheet generation configurable.

Ready when:

- A complete series can be reviewed from one local HTML page.
- Metadata is sufficient to reproduce a frame manually.

## P2 — Failure handling and frame regeneration

- [x] Fail the batch immediately and visibly when a frame cannot be generated.
- [x] Add regeneration of one frame from printed metadata.
- [ ] Do not add an image-quality detector or external vision model in this phase.

Ready when:

- A generation failure is visible and explainable in Logger.

## Recommended implementation order

1. Camera grammar and database records.
2. Storyboard editorial arc.
3. Shuffle bags and diversity scoring.
4. Deterministic inference-seed sequence.
5. Dynamic location surfaces.
6. Prompt Compiler v2 and non-destructive prompt diagnostics.
7. Visual trait prioritization.
8. Exact garment transitions.
9. Plateau recipes and intensity scale.
10. `plan`, `validate`, and `stats`.
11. HTML contact sheet.
12. Retry policy and frame regeneration.

## Regression checklist

- [x] The same prompt seed reproduces the model signature, context, and prompt sequence.
- [x] Photoshoot mode keeps one model, outfit, location, and palette per set.
- [x] Random mode rebuilds context for every frame.
- [x] Progressive stages never move backward.
- [x] Full-XXX mode contains no covered or lingerie stages.
- [x] Positive prompts describe one solo adult woman only.
- [x] No sexual toy is selectable or emitted in a positive prompt.
- [x] Outdoor locations are private rather than public.
- [x] Python compilation, JSON validation, shell syntax, and `git diff --check` pass.
- [ ] Deterministic inference strategy reproduces all frame seeds.
- [ ] No garment is removed twice or after it disappears.
- [ ] Camera-aware stress test of 10,000 planned scenes passes.
