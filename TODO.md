# Project Valhalla — Roadmap

This file tracks agreed future work. Unchecked items are not implemented.

## Project constraints

- Keep one `app.py`, one manually editable `database.json`, one active local `workflow.json`, and one `launcher.sh`.
- Preserve compatibility with different checkpoint families through the captured workflow.
- Do not add FaceID, IPAdapter, PuLID, reference-image, or architecture-specific identity pipelines.
- Use adult women aged 21–22 only.
- Keep all scenes solo and locations private.
- Do not add mirrors, sexual toys, male subjects, or partner interactions.

## Completed foundation

- [x] Resolve the complete batch before rendering.
- [x] Keep model, outfit, palette, interior, mood, and photography style fixed within each photoshoot.
- [x] Support independent context assembly for every random-mode image.
- [x] Build a progressive stage sequence that does not move backward.
- [x] Guarantee an explicit final plateau and support full-XXX mode from the first frame.
- [x] Stop the batch when a scene cannot be resolved.
- [x] Provide an interactive Director's Desk before any GPU job.
- [x] Support complete-storyboard reroll, single-shot reroll, stage selection, and compatible pose/action/expression selection.
- [x] Provide Casting & Set Design for subject, wardrobe, interior, surface, mood, and photography style.
- [x] Support constrained subject, wardrobe, interior, and surface remixing.
- [x] Prevent manually edited stages from reversing photoshoot progression.
- [x] Keep automatic operation available without storyboard review.
- [x] Use `fzf` for fixed-choice screens with a numbered non-TTY fallback.
- [x] Provide a compact editable launcher dashboard with totals, advanced settings, and a clear path to Director.
- [x] Group high-level menu actions under non-action text headings.
- [x] Support `disabled: true` across selectable database records.
- [x] Remove mirrors, sexual toys, and non-functional identity-consistency prompt procedures.
- [x] Maintain README documentation alongside implementation.

## P0 — Storyboard editorial planning

- [ ] Plan shot size, camera angle, framing, pose family, action family, and expression intensity across the complete series.
- [ ] Build a deliberate editorial arc: establishing → medium → reveal → nude → explicit plateau.
- [ ] Plan `xxx-only` as a complete explicit storyboard rather than independent explicit frames.
- [ ] Pass planned storyboard choices into the resolver without random replacement.
- [ ] Give every frame an explainable role in the series.
- [ ] Prevent unjustified duplicate compositions in adjacent frames.

Ready when:

- The same prompt seed reproduces the identical storyboard.
- Every frame has an explicit editorial role.
- Progression never moves backward.
- Adjacent frames do not repeat composition without a deliberate rule.

## P0 — Camera grammar

- [ ] Add `shot_sizes`, `camera_angles`, `framings`, and `focus_targets` to `database.json`.
- [ ] Support full body, three-quarter, medium, portrait, torso close-up, breast close-up, intimate macro, and rear close-up.
- [ ] Support eye-level, low, high, overhead, rear, and over-the-shoulder angles.
- [ ] Support centered, diagonal editorial, symmetrical, tight-crop, and environmental framing.
- [ ] Resolve camera grammar against pose, action, furniture, visibility, and exposure stage.
- [ ] Reject combinations such as intimate macro with full-body framing.
- [ ] Require rear angles for rear-display recipes and suitable close-ups for intimate actions.

Ready when:

- Every resolved scene has a shot size, angle, framing, and focus target.
- Validation finds unreachable or incompatible camera records.
- A 5,000-frame dry-run produces no framing conflicts.

## P0 — Weighted shuffle bags and diversity

- [ ] Replace independent weighted selection for major shot categories with weighted shuffle bags.
- [ ] Avoid repeating pose, action, expression, shot size, or angle before the compatible pool is exhausted.
- [ ] Keep separate bags for each photoshoot and stage family.
- [ ] Permit reuse after exhaustion while preventing identical adjacent shots.
- [ ] Calculate a storyboard diversity score.
- [ ] Penalize repeated pose family, action family, camera angle, shot size, and surface.
- [ ] Do not penalize intentionally fixed model, outfit, location, palette, or lighting.

Ready when:

- All available plateau recipes are used before repetition.
- Adjacent shots do not share the same pose/action pair.
- One prompt seed reproduces shuffle-bag order exactly.

## P0 — Deterministic inference-seed sequence

- [ ] Preserve current fixed and random-per-image strategies.
- [ ] Add a deterministic-sequence strategy.
- [ ] Derive each frame seed from a base seed, photoshoot index, and shot index using a stable hash algorithm.
- [ ] Do not use Python `hash()`, which changes between processes.
- [ ] Print the base seed and effective frame seed.
- [ ] Add strategy selection to the launcher Advanced menu.
- [ ] Preserve literal seed reuse in fixed mode.

Ready when:

- Reusing a base seed reproduces every inference seed.
- Different frames receive different seeds.
- Photoshoots in one batch do not overlap seed sequences.

## P1 — Prompt Compiler v2

- [ ] Order prompts by diffusion priority: solo/adult constraint → camera → pose/action → visible anatomy → human traits → visible garments → location → expression → lighting/quality.
- [ ] Keep each human trait in one prompt block only.
- [ ] Add `compact`, `balanced`, and `detailed` prompt profiles.
- [ ] Give each profile an approximate token budget.
- [ ] Trim low-priority fragments without removing adult, pose, or action constraints.
- [ ] Make negative prompts stage-specific.
- [ ] Remove irrelevant negatives from fashion stages.
- [ ] Strengthen coverage and censorship negatives only for explicit stages.
- [ ] Add linting for duplicate subjects, conflicting framing, contradictory clothing, and repeated fragments.

Ready when:

- Pose and action remain in the high-priority prompt section.
- Compact prompts preserve subject traits and stage semantics.
- Compiled prompts contain no repeated trait fragments.
- One resolved scene compiles deterministically.

## P1 — Visual trait prioritization

- [ ] Keep the complete `model_signature` for reproducibility and console output.
- [ ] Define a shorter visual-trait subset for prompt-budget decisions without claiming cross-frame identity control.
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
- [ ] Allow different compatible surfaces within the same interior.
- [ ] Add zones such as bed, bed edge, wall, vanity, window, rug, sofa, chair, pool edge, and garden surface.
- [ ] Match poses and shot sizes to surface capabilities.
- [ ] Preserve recognizable room identity while changing surfaces.

Ready when:

- A photoshoot retains one recognizable location.
- Surfaces vary without logical conflicts.
- Bathroom, pool, bedroom, and outdoor surface families do not mix incorrectly.

## P1 — Exact garment transitions

- [ ] Compare visible garment slots with the previous stage.
- [ ] Calculate exactly which slots were removed or revealed.
- [ ] Select an undressing action matching the actual garment type.
- [ ] Add actions for zippers, buttons, straps, bra hooks, skirts, dresses, panties, stockings, and footwear.
- [ ] Support intentionally retained stockings, heels, garters, and accessories.
- [ ] Never describe removing a garment that is absent or already removed.
- [ ] Never restore removed clothing during progressive photoshoots.

Ready when:

- Every undressing action matches the garment state difference.
- Dry-runs contain no impossible removal actions.
- Anatomy becomes visible only after the corresponding transition.

## P1 — Explicit plateau recipes

- [ ] Replace the three broad plateau kinds with a catalog of concrete recipes.
- [ ] Add rear standing, rear all-fours, bent-over, legs-up, legs-wide, intimate macro, breast-focus, hands-only stimulation, and climax recipes.
- [ ] Define pose tags, action tags, camera grammar, visibility, furniture, and expression intensity for every recipe.
- [ ] Add configurable recipe weights to `database.json`.
- [ ] Allow individual recipe families to be disabled.
- [ ] Distribute active recipe families across the plateau before repeating them.
- [ ] Use weighted shuffle bags in `random --xxx-only`.

Ready when:

- Every active recipe is reachable.
- Recipes never combine incompatible pose, action, camera, or surface components.
- Hands-only actions never add external objects.
- Expression intensity matches the action.

## P1 — Intensity scale

- [ ] Add a shared `fashion`, `sensual`, `erotic`, `nude`, `explicit`, and `peak` scale.
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

## P2 — Retry policy and frame regeneration

- [ ] Add configurable retry counts for HTTP, ComfyUI, and missing-output failures.
- [ ] Retry the same resolved prompt with a new inference seed when the selected strategy permits it.
- [ ] Never alter the storyboard during a technical retry.
- [ ] Add regeneration of one frame from printed metadata.
- [ ] Stop the batch after retries are exhausted.
- [ ] Do not add an image-quality detector or external vision model in this phase.

Ready when:

- A transient failure does not discard the entire photoshoot.
- Retry behavior is visible and explainable in console output.

## Recommended implementation order

1. Camera grammar and database records.
2. Storyboard editorial arc.
3. Shuffle bags and diversity scoring.
4. Deterministic inference-seed sequence.
5. Dynamic location surfaces.
6. Prompt Compiler v2 and prompt budgets.
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
