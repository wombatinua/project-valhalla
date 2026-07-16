# MVP Handoff: Rule-Based Prompt Composer + Stability Matrix / ComfyUI Backend

## 1. Goal

Build a small Linux-first tool that:

1. Stores content-building data in a single JSON file.
2. Programmatically composes randomized but logically consistent prompts.
3. Keeps render/inference settings separate from content logic.
4. Reuses a Stability Matrix Inference configuration by capturing the actual ComfyUI workflow.
5. Sends generated jobs to ComfyUI through its HTTP API.
6. Supports iterative tuning in Stability Matrix, followed by batch generation from the custom tool.

The realistic implementation target is:

- Python + JSON, preferred for the MVP.
- Shell + JSON is possible for very small experiments, but Python is a better fit once rules, retries, workflow mutation, and batch tracking appear.

This is not intended to become a general ComfyUI workflow editor. Stability Matrix remains the visual tuning interface. The custom tool is the composition and automation layer.

---

## 2. Core Product Idea

The custom tool should act as a smart composition engine in front of ComfyUI.

High-level flow:

```text
Single JSON database
        ↓
Rule-based random selection
        ↓
Resolved structured scene
        ↓
Compiled positive / negative prompt
        ↓
Captured ComfyUI workflow template
        ↓
Patch runtime values
        ↓
POST /prompt to ComfyUI
        ↓
Track completion and outputs
```

The content database will focus primarily on:

- human appearance;
- clothing;
- underwear / legwear / outerwear;
- degree of dress / undress;
- poses;
- actions;
- furniture / surfaces;
- interiors;
- facial expressions;
- scene mood and style;
- prompt quality suffixes;
- logical relations between all of the above.

The relation rules should preferably live on the objects themselves rather than in a separate giant central rules file.

Examples of relationship types:

- requires;
- excludes;
- implies;
- prefers;
- allowed_with;
- forbidden_with;
- requires_tags;
- excludes_tags;
- occupies_slots;
- requires_surface;
- requires_scene;
- compatible_pose_tags;
- incompatible_pose_tags.

No final JSON schema is required yet. The first version may evolve organically.

---

## 3. Why the Existing Wildcard Prompt Is Not Enough

The current wildcard approach works:

```text
{option A|option B|option C}
```

but it becomes hard to manage because all concepts are flattened into one string.

Problems:

- mutually exclusive clothing items may be selected together;
- full-body clothing can conflict with separate upper/lower garments;
- pose and furniture can contradict each other;
- actions may require body positions or visible body parts;
- scene objects may be missing;
- style, exposure state, outfit, pose, action, and location are mixed;
- it becomes difficult to understand why a generated combination occurred;
- batch generation becomes hard to reproduce or audit.

The MVP should therefore randomize structured objects, not raw text fragments.

---

## 4. Architectural Separation

Keep the system split into four conceptual layers.

### 4.1 Content Database

The single JSON file contains arrays or arrays of objects for:

- looks;
- hair;
- body traits;
- clothing;
- underwear;
- legwear;
- footwear;
- accessories;
- poses;
- actions;
- expressions;
- interiors;
- furniture;
- surfaces;
- moods;
- style modifiers;
- negative prompt fragments;
- render profiles or references to captured workflow files.

The database is the source for semantic content and rule relationships.

### 4.2 Rule Resolver

The resolver selects compatible objects.

Responsibilities:

- resolve slots;
- enforce exclusions;
- satisfy requirements;
- retry invalid selections;
- honor fixed or locked choices;
- apply weighted randomness;
- produce warnings for impossible combinations;
- generate a fully resolved scene object before any prompt text is assembled.

### 4.3 Prompt Compiler

The compiler converts the resolved scene into:

- positive prompt;
- negative prompt;
- optional metadata summary;
- selected object IDs;
- selected tags;
- human-readable explanation of the selection.

The compiler should not choose content. It should only serialize already resolved content.

### 4.4 Render Adapter

The render adapter:

- loads a captured ComfyUI workflow;
- patches prompt nodes;
- patches seed and other selected runtime values;
- submits the workflow;
- tracks completion;
- records generated files and job metadata.

This adapter should hide ComfyUI graph details from the rest of the codebase.

---

## 5. Stability Matrix and ComfyUI Model

Stability Matrix Inference should be treated as a visual frontend and workflow builder on top of ComfyUI.

The relevant execution model is:

```text
Stability Matrix Inference UI
        ↓
builds a ComfyUI workflow
        ↓
POST /prompt
        ↓
ComfyUI executes nodes
        ↓
SaveImage writes output to disk
```

One generation is typically queued using one HTTP request:

```http
POST /prompt
```

The request contains the entire workflow in ComfyUI API format.

The response returns a `prompt_id`.

Completion and output retrieval are separate steps:

- WebSocket `/ws` for live status, or
- `GET /history/{prompt_id}` for completion and outputs;
- `GET /view?...` to download/view an image when needed.

The `SaveImage` node in the workflow saves the image to ComfyUI's output directory. Stability Matrix is not the component that directly writes the final image file.

---

## 6. Capturing Non-Prompt Inference Settings

The main challenge is preserving settings from the Stability Matrix Inference tab, including:

- model;
- workflow family;
- encoder;
- VAE;
- precision;
- CLIP skip;
- text encoders;
- encoder shift;
- LoRAs / LyCORIS;
- LoRA strengths;
- sampler;
- scheduler;
- steps;
- CFG;
- width;
- height;
- addons;
- Face Detailer;
- bbox model;
- segmentation model;
- other stage-specific nodes.

Do not manually reimplement all Stability Matrix UI fields in the MVP.

### Recommended Capture Method

Use a real generated ComfyUI workflow as the source of truth.

Workflow:

1. Configure everything in Stability Matrix Inference.
2. Generate one test image.
3. Identify the resulting `prompt_id`.
4. Retrieve the executed workflow through ComfyUI history.
5. Save the full submitted workflow JSON.
6. Treat that workflow as a render template.
7. Patch only known runtime values when generating from the custom tool.

Conceptually:

```text
Tune in Stability Matrix
        ↓
Generate one image
        ↓
Capture latest workflow from ComfyUI
        ↓
Save as render profile/template
        ↓
Reuse from Python
```

### Why This Is Better Than Parsing the UI

- It captures the exact graph that actually ran.
- It includes hidden implementation details and node connections.
- It works with models, LoRAs, detailers, addons, and custom workflows.
- It avoids duplicating Stability Matrix logic.
- It reduces coupling to Stability Matrix's internal project format.

### Alternative Sources

Possible but less preferred for the MVP:

- `.smproj` files;
- PNG metadata;
- an HTTP reverse proxy logging `POST /prompt`;
- direct inspection of Stability Matrix source or state files.

Recommended MVP source of truth:

```text
Captured ComfyUI API workflow JSON
```

---

## 7. Render Profile Design

A render profile should consist of two levels.

### 7.1 Raw Workflow

The exact captured ComfyUI API workflow.

This is the executable source of truth.

Suggested storage:

```text
profiles/
  zimage_turbo_default.workflow.json
```

### 7.2 Profile Metadata

A smaller sidecar JSON or a section in the main database containing:

- profile ID;
- display name;
- workflow file path;
- model name;
- workflow type;
- sampler;
- scheduler;
- default steps;
- default CFG;
- default resolution;
- LoRA summary;
- detailer summary;
- node mapping;
- notes;
- capture date;
- Stability Matrix / ComfyUI version if known.

Example concept only:

```json
{
  "id": "zimage_turbo_default",
  "workflow_file": "profiles/zimage_turbo_default.workflow.json",
  "node_map": {
    "positive_prompt": "12",
    "negative_prompt": "13",
    "seed": "25",
    "width": "18",
    "height": "18",
    "steps": "25",
    "cfg": "25"
  }
}
```

The raw workflow stays untouched as a baseline. Each submitted job should use a deep copy.

---

## 8. Node Mapping Strategy

The application needs a stable way to patch values inside a captured workflow.

For the MVP, use an explicit node map stored with each render profile.

Possible mapped fields:

- positive prompt node ID and input key;
- negative prompt node ID and input key;
- seed node ID and input key;
- width node ID and input key;
- height node ID and input key;
- steps node ID and input key;
- CFG node ID and input key;
- sampler node ID and input key;
- scheduler node ID and input key;
- checkpoint/model node ID and input key;
- VAE node ID and input key;
- text encoder node ID and input key;
- LoRA node IDs and strength input keys;
- detailer enable/disable node or bypass method;
- output filename prefix node.

Prefer mappings shaped like:

```json
{
  "positive_prompt": {
    "node": "12",
    "input": "text"
  },
  "seed": {
    "node": "25",
    "input": "seed"
  }
}
```

Do not rely only on node numbers being self-explanatory.

Later, node detection can be partially automated by inspecting `class_type`, titles, and input structure. For MVP, manual mapping is acceptable and safer.

---

## 9. Content Data Model Principles

The first release uses one JSON database file.

Suggested top-level concept:

```text
database.json
```

The exact schema is intentionally not fixed yet.

Important principles:

### 9.1 Every Object Should Have a Stable ID

Use IDs such as:

```text
crop_top_black
long_dress_red
pose_sitting_sofa
interior_modern_living_room
```

Prompt text may change later, while IDs should remain stable.

### 9.2 Use Tags Extensively

Tags make generic relationships possible.

Examples:

- `upperwear`;
- `lowerwear`;
- `full_body`;
- `casual`;
- `elegant`;
- `indoor`;
- `bedroom`;
- `standing`;
- `sitting`;
- `lying`;
- `requires_sofa`;
- `revealing`;
- `outerwear`.

Rules can refer to IDs for exact relationships and tags for broad relationships.

### 9.3 Use Slots for Clothing

Likely slots:

- upperwear;
- lowerwear;
- full_body;
- underwear;
- legwear;
- outerwear;
- footwear;
- headwear;
- neck_accessory;
- hand_accessory.

A full-body item may occupy both upper and lower slots.

### 9.4 Store Prompt Fragments on Objects

Each object may have one or more prompt fragments:

- default fragment;
- alternate fragments;
- model-specific fragment;
- positive fragment;
- negative fragment;
- trigger token;
- weight syntax if needed.

### 9.5 Keep Relationships on Objects

Preferred style:

```text
object.excludes
object.requires
object.prefers
object.occupies_slots
object.requires_tags
object.excludes_tags
```

Avoid one enormous global matrix unless later performance or complexity requires it.

---

## 10. Rule Resolution

The resolver should generate a complete structured scene before compiling text.

Possible resolution order:

1. Select or lock the render profile.
2. Select a high-level scene/interior.
3. Select surface/furniture.
4. Select body position.
5. Select pose.
6. Select action.
7. Select exposure/dress state.
8. Select outfit style.
9. Fill clothing slots.
10. Select expression.
11. Add optional modifiers.
12. Validate all relations.
13. Retry conflicting categories.
14. Emit resolved scene.

The exact order can change, but deterministic ordering makes debugging easier.

### Rule Types for MVP

Implement only a small core first:

- `requires`: exact object IDs;
- `excludes`: exact object IDs;
- `requires_tags`;
- `excludes_tags`;
- `occupies_slots`;
- `weight`.

These are enough to make the first useful system.

Later additions:

- `prefers`;
- `implies`;
- conditional probability modifiers;
- model compatibility;
- LoRA compatibility;
- scene-specific prompt transformations.

### Invalid Selection Handling

Recommended behavior:

1. Attempt weighted selection.
2. Validate candidate.
3. Retry within the same category.
4. Stop after a configurable retry limit.
5. If unresolved:
   - skip optional category, or
   - fail the job with a readable error.

Never allow infinite retry loops.

---

## 11. Interactive and Batch Modes

The MVP should support two workflows.

### 11.1 Interactive Mode

Purpose:

- tune one image at a time;
- inspect resolved combinations;
- adjust profile overrides;
- validate prompt output;
- quickly test changes.

Possible CLI flow:

```bash
python app.py generate \
  --profile zimage_turbo_default \
  --count 1 \
  --show-prompt
```

### 11.2 Batch Randomized Mode

Purpose:

- freeze model/LoRA/detailer/settings;
- generate many randomized compatible scenes;
- compare output quality;
- evaluate render profile changes.

Example:

```bash
python app.py batch \
  --profile zimage_turbo_default \
  --count 50 \
  --seed random
```

Each batch item should store:

- batch ID;
- item index;
- random seed;
- selected object IDs;
- positive prompt;
- negative prompt;
- render profile ID;
- submitted `prompt_id`;
- final output filenames;
- status;
- error if any.

This metadata is critical for reproducing good results.

---

## 12. Recommended MVP Technology

### Preferred: Python + JSON

Python is the most practical choice because the tool needs:

- JSON manipulation;
- recursive rule validation;
- random weighted selection;
- deep copies of workflows;
- HTTP requests;
- WebSocket or polling support;
- batch state;
- retries;
- file handling;
- logging;
- possible CLI commands.

Suggested standard/simple dependencies:

```text
Python 3.11+
requests
websocket-client or websockets
```

Optional:

```text
pydantic
typer
rich
```

For the first pass, even the standard library plus `requests` is enough.

### Shell + jq

Shell can be used for:

- testing `/prompt`;
- capturing `/history`;
- storing example workflows;
- quick prototype scripts.

It becomes awkward for:

- relation resolution;
- weighted random selection;
- recursive validation;
- structured batch metadata;
- workflow patching;
- robust error handling.

Recommendation:

```text
Use shell for diagnostics and capture helpers.
Use Python for the actual MVP.
```

---

## 13. Proposed Repository Layout

```text
prompt-composer/
├── app.py
├── database.json
├── config.json
├── profiles/
│   ├── zimage_turbo_default.workflow.json
│   └── zimage_turbo_default.profile.json
├── batches/
├── outputs/
├── src/
│   ├── database.py
│   ├── resolver.py
│   ├── compiler.py
│   ├── profiles.py
│   ├── comfy_client.py
│   ├── capture.py
│   ├── batch.py
│   └── models.py
├── scripts/
│   ├── capture_latest.sh
│   └── comfy_smoke_test.sh
└── README.md
```

A smaller initial version is also fine:

```text
prompt-composer/
├── app.py
├── database.json
├── workflow.json
└── profile.json
```

Do not over-engineer the first iteration.

---

## 14. Suggested CLI Commands

Possible MVP commands:

### Capture

```bash
python app.py capture \
  --name zimage_turbo_default
```

Responsibilities:

- fetch ComfyUI history;
- identify latest completed job;
- save its workflow;
- print candidate prompt/seed/size/sampler nodes;
- ask for or accept node mapping.

### Inspect

```bash
python app.py inspect-profile zimage_turbo_default
```

Print:

- node classes;
- mapped fields;
- model;
- sampler;
- LoRAs;
- detailer-related nodes.

### Resolve Only

```bash
python app.py resolve \
  --profile zimage_turbo_default
```

Print structured selection and compiled prompt without rendering.

### Generate One

```bash
python app.py generate \
  --profile zimage_turbo_default
```

### Generate Batch

```bash
python app.py batch \
  --profile zimage_turbo_default \
  --count 20
```

### Dry Run

```bash
python app.py batch \
  --profile zimage_turbo_default \
  --count 20 \
  --dry-run
```

Dry-run is important for validating the content database before burning GPU time.

---

## 15. ComfyUI Client Responsibilities

The `ComfyClient` should provide a very small API.

Conceptual methods:

```python
get_history()
get_history_item(prompt_id)
queue_workflow(workflow, client_id=None)
wait_for_completion(prompt_id)
get_output_files(prompt_id)
interrupt()
```

For MVP, polling history is simpler than WebSocket:

1. `POST /prompt`;
2. receive `prompt_id`;
3. poll `/history/{prompt_id}`;
4. stop when outputs or error appear.

WebSocket can be added later for:

- live progress;
- previews;
- reduced polling;
- better cancellation feedback.

---

## 16. Capturing the Latest Workflow

A simple capture algorithm:

1. Query `/history`.
2. Sort entries by execution order or timestamp if present.
3. Select latest completed entry.
4. Extract the submitted prompt/workflow object.
5. Save it verbatim.
6. Inspect nodes to locate likely mutable fields.
7. Store explicit node mappings in the profile metadata.

Potential ambiguity:

- other generations may be running;
- multiple clients may share the same ComfyUI instance;
- history ordering may not be obvious.

More robust future approach:

1. record current history IDs;
2. trigger a known test generation in Stability Matrix;
3. poll history;
4. detect the new prompt ID;
5. capture exactly that item.

Another future approach is a local reverse proxy that logs `POST /prompt`, but it is not needed for the MVP.

---

## 17. Workflow Mutation Rules

Always:

- load baseline workflow;
- deep-copy it;
- patch the copy;
- submit the copy.

Never mutate the saved baseline in place during generation.

Initially patch only:

- positive prompt;
- negative prompt;
- seed;
- filename prefix.

Optionally patch:

- width;
- height;
- steps;
- CFG;
- sampler;
- scheduler.

Model, LoRA, detailer, encoder, and VAE changes can be added after the basic flow is reliable.

This keeps the first milestone small while preserving the future direction.

---

## 18. Model / LoRA / Detailer Strategy

The application eventually needs UI or CLI controls for:

- model;
- LoRAs;
- LoRA strengths;
- detailers;
- bbox model;
- segmentation model;
- sampler;
- scheduler;
- steps;
- CFG;
- resolution.

For MVP:

### Recommended Approach

Treat the captured workflow as the profile.

Create separate profiles for materially different setups:

```text
zimage_turbo_default
zimage_turbo_lora_a
zimage_turbo_no_detailer
zimage_turbo_detailer_b
```

This avoids needing to dynamically rebuild graph topology.

Later:

- expose mapped LoRA strengths;
- enable/disable known nodes;
- switch model file names;
- change detailer model inputs;
- add UI controls.

Important distinction:

```text
Content randomization
```

should remain separate from:

```text
Render configuration randomization
```

During model/LoRA/detailer comparison, keep content seeds or resolved scenes fixed when useful. Otherwise it becomes impossible to know whether the render setting or the content caused the difference.

---

## 19. Batch Reproducibility

Every generated item should be reproducible.

Store:

- application RNG seed;
- model diffusion seed;
- database version/hash;
- selected IDs;
- compiled prompts;
- render profile ID;
- workflow file hash;
- runtime overrides;
- ComfyUI prompt ID;
- output file metadata.

Suggested batch metadata file:

```text
batches/2026-07-16_001.jsonl
```

Use JSON Lines so each item can be appended as it progresses.

Each line represents one job.

This is simpler and safer than rewriting one large JSON file after every item.

---

## 20. Logging and Failure Handling

The MVP should log:

- database load errors;
- invalid references;
- unsatisfied requirements;
- exhausted retries;
- missing node mappings;
- ComfyUI connection failure;
- rejected workflows;
- node execution errors;
- missing output files.

Recommended job states:

```text
planned
resolved
compiled
queued
running
completed
failed
```

On restart, incomplete batch jobs can later be resumed.

Resume support is not required for the first milestone, but the metadata format should not prevent it.

---

## 21. Security and Network Assumptions

Assume ComfyUI runs locally or on the trusted LAN.

Config example:

```json
{
  "comfy_url": "http://127.0.0.1:8188"
}
```

Do not expose unauthenticated ComfyUI directly to the public internet.

If remote access becomes necessary later:

- use VPN;
- use SSH tunneling;
- or place an authenticated reverse proxy in front.

---

## 22. MVP Milestones

### Milestone 1: ComfyUI Smoke Test

- submit a known workflow;
- patch positive prompt;
- patch seed;
- receive `prompt_id`;
- detect completion;
- list output files.

Success criterion:

```text
A Python command generates one image using a captured workflow.
```

### Milestone 2: Capture Profile

- fetch latest history;
- save workflow;
- store node mapping;
- replay captured workflow.

Success criterion:

```text
A Stability Matrix setup can be captured and replayed outside Stability Matrix.
```

### Milestone 3: Database Load and Resolve

- load one JSON database;
- randomly select compatible content;
- support `requires`, `excludes`, `occupies_slots`, and `weight`;
- print resolved structure.

Success criterion:

```text
The resolver produces valid combinations without rendering.
```

### Milestone 4: Prompt Compiler

- turn resolved structure into positive prompt;
- assemble negative prompt;
- store selected IDs and fragments.

Success criterion:

```text
Dry-run can generate 100 valid prompt records.
```

### Milestone 5: Batch Rendering

- resolve N scenes;
- compile N prompts;
- queue them;
- record outputs and errors.

Success criterion:

```text
A batch of randomized, rule-valid images is generated and fully logged.
```

### Milestone 6: Parameter Overrides

- expose width/height;
- steps;
- CFG;
- sampler;
- selected LoRA strengths;
- optional detailer toggles.

Success criterion:

```text
Known mapped settings can be changed without editing workflow JSON manually.
```

---

## 23. Explicit MVP Non-Goals

Do not build these yet:

- graphical node editor;
- full replacement for Stability Matrix;
- generic support for every ComfyUI custom node;
- automatic migration between arbitrary workflow versions;
- relational database;
- web frontend;
- elaborate desktop GUI;
- complex AI-based prompt rewriting;
- output scoring;
- automatic image tagging;
- user accounts;
- remote multi-GPU scheduler.

The MVP should be a dependable local automation tool, not a platform.

---

## 24. Initial Technical Recommendation

Use:

```text
Python + one content database JSON
```

Keep:

```text
captured workflow JSON files
```

outside or referenced from that main database.

The main database can still contain render-profile metadata and workflow paths, while the full workflows remain separate because they may be large and difficult to edit.

Recommended first commands to implement:

```text
capture
resolve
generate
batch
```

Recommended first mutable workflow fields:

```text
positive prompt
negative prompt
seed
filename prefix
```

Everything else can initially be fixed by the captured render profile.

---

## 25. Definition of Done for the First Useful Version

The MVP is useful when the following workflow works:

1. Open Stability Matrix.
2. Tune model, encoder, VAE, LoRAs, sampler, detailer, dimensions, and other settings.
3. Generate one verified test image.
4. Run the custom capture command.
5. Save that setup as a render profile.
6. Edit the single content database JSON.
7. Run a dry batch and inspect composed prompts.
8. Run a real batch.
9. Receive images saved by ComfyUI.
10. Find a metadata record for every generated image showing exactly what was selected and rendered.

That is the complete initial product loop.

---

## 26. Recommended Codex Starting Task

Suggested first implementation request for Codex:

```text
Create a minimal Python CLI project for Linux that talks to a local ComfyUI instance.

Implement:
1. config loading from config.json;
2. GET /history;
3. capture the latest completed workflow into profiles/<name>.workflow.json;
4. load a profile metadata JSON containing explicit node mappings;
5. deep-copy the workflow;
6. patch positive prompt, negative prompt, seed, and filename prefix;
7. POST the workflow to /prompt;
8. poll /history/{prompt_id} until completion or failure;
9. write a JSONL job record containing prompt_id, prompts, seed, status, and output filenames.

Do not implement the content database or rule resolver yet.
Keep the code modular so resolver.py and compiler.py can be added next.
Use argparse and requests, with type hints and clear errors.
```

After that works, the second Codex task should implement:

```text
Load a single database.json and add a rule resolver supporting:
- stable IDs;
- categories;
- prompt fragments;
- weight;
- requires;
- excludes;
- requires_tags;
- excludes_tags;
- occupies_slots.

Add a dry-run command that generates N resolved scenes and outputs JSONL without invoking ComfyUI.
```

---

## 27. Final Architectural Decision

Use Stability Matrix as:

```text
visual workflow configuration and tuning interface
```

Use ComfyUI as:

```text
execution backend and image writer
```

Use the custom Python tool as:

```text
content database
+ relationship resolver
+ prompt compiler
+ batch orchestrator
+ workflow patcher
```

This preserves the convenient Inference tab while adding the structured randomization and logical consistency that wildcard prompts cannot provide.
