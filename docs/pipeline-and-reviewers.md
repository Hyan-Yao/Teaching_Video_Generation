# Pipeline Overview & Reviewer Switches

_Branch: `animation-critic-backbone-split`_

## Pipeline

**Phase 1 — Lesson Plan**
1. `plan_lesson()` generates the lesson plan (GPT-5).
2. *Optional* plan reviewer: `plan_evaluator.evaluate_plan()` scores the plan (Bloom/ICAP
   alignment, objective coverage, etc.); if any metric scores ≤3,
   `lesson_plan_refiner.refine_plan()` rewrites the plan. Loops up to `max_plan_rounds`.

**Phase 2 — Per-Segment Asset Production** (parallel across segments)
- Narration (TTS) + visual rendering, dispatched by modality: `slide` / `concept_image` /
  `animation`.
- For `animation` segments specifically:
  1. **GPT-5** always generates the initial Manim code and runs its own compile-error fix
     loop — same backbone as every other method, regardless of `--animation-mode`.
  2. If `--animation-mode code2video_critic` is set: after the video renders, **Claude**
     (via OpenRouter) reviews the sampled frames, flags issues, and rewrites/repairs the
     code — this critic pass never touches the initial generation.

**Phase 3 — Composite + Outer Video Review**
- Segments are stitched into a draft video.
- *Optional* video reviewer: the outer loop (`original` or `evaluator` reviewer) scores
  the draft, and if below `--score-threshold`, triggers repair candidates (re-render,
  change modality, adjust timing, plan repair) for up to `--max-rounds`.

```
Phase 1: plan_lesson (GPT-5)
           │
           ├─ [plan reviewer, optional] evaluate_plan → refine_plan (loop, max_plan_rounds)
           ▼
Phase 2: per-segment production (parallel)
           │
           ├─ slide / concept_image renderers
           └─ animation renderer:
                 GPT-5 generates Manim code + fixes compile errors
                 │
                 └─ [critic, optional: --animation-mode code2video_critic]
                    Claude judges rendered frames → Claude rewrites/repairs code
           ▼
Phase 3: composite draft video
           │
           └─ [video reviewer, optional] score draft → repair candidates (loop, max_rounds)
           ▼
        final video
```

## Reviewer On/Off Switches

**Master switch — turns off both reviewers at once:**
```bash
python -m teachgen --request-json request.json --no-reviewer
```
Use this for a clean, no-review baseline run. It forces `plan_refinement_mode="none"`
and `feedback_mode="none"` no matter what the flags below are set to
(`Config.use_reviewer=False` in `teachgen/config.py`).

**Fine-grained control** (used when the master switch is left off):

| Flag | Controls | Values |
|---|---|---|
| `--plan-refinement-mode` | lesson-plan reviewer | `none` (default) \| `evaluator` |
| `--feedback-mode` / `--no-feedback` | video reviewer | `original` (default) \| `evaluator` \| `none` |
| `--animation-mode` | Claude critic pass for animation segments specifically | `basic` (default, GPT-5 only) \| `code2video_critic` |

**Enable everything for a full-quality run:**
```bash
python -m teachgen --request-json request.json \
  --plan-refinement-mode evaluator \
  --feedback-mode evaluator \
  --animation-mode code2video_critic
```

**No reviewers at all (fastest, cheapest, GPT-5-only baseline):**
```bash
python -m teachgen --request-json request.json --no-reviewer
```

> Note: `--no-reviewer` does not touch `--animation-mode` — that's a separate,
> per-segment critic toggle. Leave `--animation-mode basic` if you also want the
> animation path to skip Claude entirely.

## Why the animation backbone was split

Previously, `--animation-mode code2video_critic` routed *both* the initial generation
and the critic/repair pass through Claude, which was inconsistent with every other
method using GPT-5 — a problem for fair comparison. Now:

- Initial Manim code generation (including its own compile-error retry loop) always
  goes through GPT-5 (`_provider_api` in `teachgen/renderers/animation.py`).
- Code2Video's `RunConfig` (`code2video/agent.py`) gained two independent callables,
  `critic_api` and `critic_vision_api`. These are swapped in only during the
  post-render "judge issues + rewrite code" phase (`optimize_with_feedback`), routed
  through Claude via OpenRouter, then swapped back immediately after.
- `_openrouter_claude_vision_api` (new) is a Claude-based vision critic that replaces
  the previously hardcoded GPT vision critic — so both "spot the issues" and "fix the
  code" now come from the same Claude backbone.
