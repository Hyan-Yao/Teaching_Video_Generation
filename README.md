# Teaching Video Generator

**One OpenAI key + one structured request → a narrated teaching video.**

This repo has two parts:

| Directory     | What it is                                                                 |
|---------------|----------------------------------------------------------------------------|
| **`teachgen/`** | The orchestrator and entry point. Plans a lesson, routes each segment to the best visual, narrates it, composites the video, and runs an MLLM review loop. |
| **`code2video/`** | The upstream **Code2Video** project — generates polished Manim animations. teachgen drives it as its `animation` renderer. See `code2video/README.md`. |
| `runs/`        | Generated output (`runs/<topic>/...`).                                     |

## Quickstart

```bash
pip install -r requirements.txt          # core deps (+ system ffmpeg)
export OPENAI_API_KEY=sk-...

python -m teachgen --request-json examples/regression_request.json

# same entry point when using uv
uv run python -m teachgen --request-json examples/regression_request.json

# use the evaluator as the outer video-level refiner
python -m teachgen --request-json examples/regression_request.json --feedback-mode evaluator

# enable the inner plan-level refiner before rendering
python -m teachgen --request-json examples/regression_request.json --plan-refinement-mode evaluator

# run both refiners and save a final evaluator report
python -m teachgen --request-json examples/regression_request.json \
  --plan-refinement-mode evaluator --feedback-mode evaluator --eval-baseline

# just the plan (cheap), before producing media
python -m teachgen --request-json examples/regression_request.json --plan-only
```

The output video lands at `runs/<topic>/video/final.mp4`. With
`--feedback-mode evaluator`, the original draft is kept at
`runs/<topic>/video/draft_r0.mp4`, evaluator feedback output lands under
`runs/<topic>/evaluator_feedback_r<n>/`, and the router-ready review lands at
`runs/<topic>/review_r<n>.json`. With `--eval-baseline`, the final evaluator report
lands at `runs/<topic>/evaluator_baseline/evaluation_result.json`. See
**`teachgen/README.md`** for the architecture, the two-phase flow, the three
renderers, evaluator usage, and how to extend it.

## Code logic

The whole run is driven by `teachgen/pipeline.py::generate(cfg)`, which builds a single
`Provider` (one OpenAI key behind one interface) and executes two phases. Every stage
communicates only through the pydantic schema objects in `teachgen/schema.py`
(`LessonPlan`, `Segment`, `VisualAsset`, `NarrationAudio`, `ReviewResult`) — never
through each other's internals. That decoupling is what lets renderers be swapped and
the feedback loop target one segment at a time.

```
cli → Config.from_env → pipeline.generate
        │
        ├─ Phase 1  phase1_plan
        │     content_writer.write_content   structured request → objectives + spoken segments (text)
        │     route.plan_lesson              each segment → modality + visual_brief → LessonPlan
        │     _enforce_slide_only_last       hard rule: slide only on the final recap segment
        │     → runs/<topic>/lesson_plan.json   (human-inspectable checkpoint; --plan-only stops here)
        │
        └─ Phase 2  phase2_produce  (loop up to max_feedback_rounds + 1 times)
              _produce_assets       per dirty segment, in a thread pool:
                  narrator.narrate      narration → TTS audio + word timings (audio duration = segment length)
                  _render_segment       dispatch to planned renderer; fall back concept_image → slide on failure
              compositor.assemble   visuals + audio → draft_r<n>.mp4 / final.mp4
              --plan-refinement-mode evaluator
                  plan_evaluator → lesson_plan_refiner → refined LessonPlan
              --feedback-mode original
                  reviewer.review → ReviewResult → router.apply
              --feedback-mode evaluator
                  evaluator → outer_repair_decider
                      ├─ plan repair  → lesson_plan_refiner → regenerate full video
                      └─ asset repair → evaluation_adapter → router.apply
```

**Phase 1 — plan (text only).** `content_writer` asks the model for objectives plus an
ordered list of spoken segments. `route.plan_lesson` then assigns each segment a
`Modality` (`animation` / `concept_image` / `slide`) and a concrete `visual_brief`.
`_enforce_slide_only_last` deterministically guarantees the rule the prompt only
requests: any non-final `slide` is demoted to `concept_image`, and the last segment is
promoted to `slide`, so the lesson always closes on a recap deck. The plan is written to
`lesson_plan.json` as the review checkpoint (`--plan-only` returns here).

**Phase 2 — produce (media + feedback loop).** Two caches keyed by segment id
(`audio_cache`, `visual_cache`) mean each feedback round only redoes what changed.
For every *dirty* segment, `_produce_assets` runs `narrator.narrate` (the TTS duration
defines the segment's length) and `_render_segment`, fanned out across a
`ThreadPoolExecutor` when `parallel` is set. `_render_segment` tries the planned renderer
and degrades gracefully along `planned → concept_image → slide` so a failed animation
never injects a stray slide on a non-recap segment. `compositor.assemble` stretches
static images to the narration duration and freezes/pads animation clips to fit, then
writes an H.264 mp4 (`yuv420p + faststart`).

**Inner plan refiner.** With `--plan-refinement-mode evaluator`, Phase 1 no longer
stops at the first `LessonPlan`. The plan evaluator grades the plan against the
structured request, and `lesson_plan_refiner` rewrites the plan before any media is
rendered. Outputs land in:

```text
runs/<topic>/lesson_plan_initial.json
runs/<topic>/plan_eval_r<n>.json
runs/<topic>/lesson_plan_refined_r<n>.json
```

**Outer video refiner.** With `--feedback-mode evaluator`, the produced draft video is
evaluated after each outer round. The evaluator drives one of two repair paths:

- `plan` repair: low pedagogical/content metrics trigger a full lesson-plan revision,
  then the whole video is regenerated from the revised plan.
- `asset` repair: low visual/multimedia metrics are adapted into segment-level fixes
  (`rewrite_narration`, `change_modality`, `re_render`, `adjust_timing`) and only
  dirty segments are regenerated.

**Evaluator mode.** To use the evaluator during refinement:

```bash
python -m teachgen --request-json examples/regression_request.json --feedback-mode evaluator
```

To also save a final evaluator report after refinement:

```bash
python -m teachgen --request-json examples/regression_request.json --feedback-mode evaluator --eval-baseline
```

Saved outputs:

```text
runs/<topic>/video/draft_r0.mp4
runs/<topic>/video/final.mp4
runs/<topic>/evaluator_feedback_r<n>/evaluation_result.json
runs/<topic>/evaluator_feedback_r<n>/repair_plan.json
runs/<topic>/asset_review_r<n>.json                 # asset branch only
runs/<topic>/outer_repair_decision_r<n>.json
runs/<topic>/outer_plan_feedback_r<n>.json          # plan branch only
runs/<topic>/outer_lesson_plan_refined_r<n>.json    # plan branch only
runs/<topic>/outer_plan_eval_after_r<n>.json        # plan branch only
runs/<topic>/evaluator_baseline/evaluation_result.json   # only with --eval-baseline
```

## Install notes

- **Core** (`requirements.txt`): planner + slide + concept-image + audio + compositing.
- **System:** `ffmpeg` is required. LibreOffice is **not** (slides rasterize via Pillow).
- **Animation renderer (optional):** needs Manim + code2video's own deps —
  `pip install -r code2video/requirements.txt`. Without Manim, animation segments
  fall back to concept images.

## Layout

```
code2video/   Manim animation engine (upstream Code2Video) + prompts/, json_files/, assets/
teachgen/     orchestrator: planner, renderers, audio, compositor, feedback
              + make_slide.py and concept_image.py (the slide / image helpers)
runs/         generated lessons
```
