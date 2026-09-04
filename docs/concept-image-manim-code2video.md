# Concept-image prompts, Manim rendering, and Code2Video integration

This document describes the implementation used by the active `python -m teachgen` path. It distinguishes that path from Code2Video's larger standalone workflow, whose source and prompts are also present in this repository but are mostly not called by TeachGen.

## 1. Concept-image generation and every prompt that affects it

### 1.1 Active data flow

```text
lesson narration
    |
    v
router system + user prompts
    |  choose `concept_image` and write Segment.visual_brief
    v
concept-image prompt-engineer system prompt
    + generated user brief (visual_brief + audience + fixed style payload)
    |
    v
text model returns one detailed image prompt
    |
    v
OpenAI image API receives that returned prompt verbatim
    |
    v
runs/<topic>/assets/<segment-id>.png
```

There are two direct model calls for a concept image: one text-model call to expand a brief, then one image-model call to render the expanded prompt. The image API is **not** given a separate hard-coded system prompt.

### 1.2 Prompt inventory

The following are all the active prompt sources that create or can rewrite the input to concept-image generation.

| Role | Source | What it contributes | Direct or upstream? |
|---|---|---|---|
| Renderer router system prompt | [`teachgen/planner/route.py:16`](../teachgen/planner/route.py#L16) | Defines when to select `concept_image` and requires its brief to name a central metaphor/diagram, 2–5 labeled components, compositional flow, and color/contrast mood. | Upstream: creates `Segment.visual_brief`. |
| Renderer router user prompt | [`teachgen/planner/route.py:57`](../teachgen/planner/route.py#L57) | Supplies topic, audience, every segment title/narration, and asks the model to preserve order and count. | Upstream: supplies the content from which the brief is written. |
| Image-prompt engineer system prompt | [`teachgen/concept_image.py:65`](../teachgen/concept_image.py#L65) | Requires one presentation-ready educational illustration with labeled parts, directional flow, simple metaphors, short labels, a restrained palette, whitespace, a light background, landscape composition, and no photorealism/clutter/watermark. It requires a single prose paragraph and no preamble/Markdown. | Direct: system message for the text-model expansion call. |
| Image-prompt engineer user-message template | [`teachgen/concept_image.py:88`](../teachgen/concept_image.py#L88) | Builds `Concept to illustrate: ...`, optional `Target audience: ...`, optional `Preferred visual style: ...`, and `Produce the detailed English image prompt now.` | Direct: user message for the text-model expansion call. |
| TeachGen's fixed style payload | [`teachgen/renderers/concept_image.py:15`](../teachgen/renderers/concept_image.py#L15) | Adds the cream/beige academic-poster treatment, serif headings, sans-serif body, numbered sections, diagrams, teal/gold/dark-gray palette, and “textbook meets modern design” aesthetic. | Direct: passed as the `style` value in the user-message template. |
| Image API prompt | [`teachgen/renderers/concept_image.py:33`](../teachgen/renderers/concept_image.py#L33) | The text model's returned paragraph is passed verbatim to `provider.image(...)`. | Direct: this dynamic paragraph is the sole image API prompt. |
| Content-issue visual-brief rewrite | [`teachgen/feedback/plan_refiner.py:54`](../teachgen/feedback/plan_refiner.py#L54) | Given the renderer type, issue, suggestion, narration, and current brief, asks for a rewritten brief describing only what to show. | Upstream on later feedback rounds. |
| Rendering-quality visual-brief rewrite | [`teachgen/feedback/visual_refiner.py:33`](../teachgen/feedback/visual_refiner.py#L33) | Given a poor render, issue, suggestion, narration, and current brief, requests cleaner and more legible rendering guidance. | Upstream on later feedback rounds. |

The outer reviewer supplies the `issue` and `suggestion` used by those two rewrite prompts. Its review prompt is at [`teachgen/feedback/outer_reviewer.py:20`](../teachgen/feedback/outer_reviewer.py#L20), and its dynamic topic/plan/frame prompt is assembled at [`teachgen/feedback/outer_reviewer.py:41`](../teachgen/feedback/outer_reviewer.py#L41). It samples 12 evenly spaced silent frames by default; it does not send the full MP4 or its audio to the model.

`teachgen/feedback/router.py` contains an older/alternate critique-routing implementation with another visual-brief rewrite prompt at [`teachgen/feedback/router.py:65`](../teachgen/feedback/router.py#L65). It is **not imported by the active pipeline**, which imports `outer_reviewer`, `plan_refiner`, and `visual_refiner` instead ([`teachgen/pipeline.py:12`](../teachgen/pipeline.py#L12)). It therefore does not affect a normal current run.

### 1.3 The direct prompt as assembled at runtime

For a normal concept-image segment, the text model receives:

```text
SYSTEM:
<PROMPT_SYSTEM from teachgen/concept_image.py>

USER:
Concept to illustrate: <segment.visual_brief>
Target audience: <Config.audience>
Preferred visual style: <the complete _STYLE string from the renderer>
Produce the detailed English image prompt now.
```

The resulting one-paragraph response becomes:

```python
ctx.provider.image(image_prompt, size="1536x1024", quality="high")
```

The default TeachGen models are `gpt-4o` for the expansion call and `gpt-image-2` for the render ([`teachgen/config.py:15`](../teachgen/config.py#L15)). The OpenAI provider invokes `images.generate` with `n=1`, returns inline base64 bytes when available, and otherwise downloads the returned URL ([`teachgen/providers/openai_provider.py:126`](../teachgen/providers/openai_provider.py#L126)). The PNG is written to `runs/<topic>/assets/<segment-id>.png`.

The expanded image prompt is not persisted to a file by the active renderer. Only the final PNG and the lesson plan's shorter `visual_brief` are persisted. Logging or saving the exact expanded prompt would require an implementation change.

### 1.4 Standalone helper versus active renderer

`teachgen/concept_image.py` can also run as a standalone CLI. That path uses the same `PROMPT_SYSTEM` and `build_user_brief`, but it has important differences:

- Its text-model default is `gpt-4o-mini`; its image-model default is `gpt-image-2` ([`teachgen/concept_image.py:158`](../teachgen/concept_image.py#L158)).
- `--raw-prompt` bypasses the text-model expansion call.
- `--dry-run` prints the expanded prompt without rendering.
- `--exact-169` center-crops the 3:2 image to 1280×720.
- The active `ConceptImageRenderer` does not call the CLI, does not use `--raw-prompt`, and does not perform the exact-16:9 crop. The final compositor simply resizes the 1536×1024 image to 1920×1080, changing the aspect ratio from 3:2 to 16:9.

### 1.5 Routing and fallback details that affect concept images

- The planner is instructed to use concept images for intuition, metaphors, or one big idea captured by a static labeled diagram. Animation is preferred for evolving processes and derivations ([`teachgen/planner/route.py:16`](../teachgen/planner/route.py#L16)).
- Code enforces the final slide convention: a non-final slide chosen by the model is converted to `concept_image`, and the final segment is converted to `slide` ([`teachgen/planner/route.py:94`](../teachgen/planner/route.py#L94)).
- Renderer failure uses `planned modality -> concept_image -> slide` ([`teachgen/pipeline.py:152`](../teachgen/pipeline.py#L152)). Consequently, failed Manim segments also use the concept-image renderer.
- A fallback does **not** rewrite the `visual_brief` for the new modality. If an animation fails, its animation-oriented brief is passed directly into the concept-image prompt engineer. This is robust operationally but can produce a less-than-ideal static composition.
- Static images have no intrinsic screen duration. MoviePy keeps each image on screen for its narration-audio duration ([`teachgen/compositor/compositor.py:42`](../teachgen/compositor/compositor.py#L42)).

## 2. How Manim animation rendering works

### 2.1 Segment-to-scene pipeline

For a segment routed to `animation`, the active sequence is:

1. `AnimationRenderer` sends the title, narration, visual brief, and approximate target duration to a structured storyboard prompt ([`teachgen/renderers/animation.py:94`](../teachgen/renderers/animation.py#L94)).
2. The storyboard system prompt requires 2–5 aligned lecture lines and animation descriptions. Lecture lines must be at most eight words; visuals must use simple 2D vector objects only ([`teachgen/renderers/animation.py:33`](../teachgen/renderers/animation.py#L33)). Pydantic validates the two lists' types, although there is no custom validator that actually enforces equal lengths or the 2–5 count.
3. Those lists are wrapped in Code2Video's `Section(id, title, lecture_lines, animations)` dataclass ([`code2video/agent.py:21`](../code2video/agent.py#L21)).
4. `TeachingVideoAgent.generate_section_code()` calls the Stage 3 Manim-specialist prompt and writes the returned Python to `<Code2Video output dir>/<segment-id>.py` ([`code2video/agent.py:296`](../code2video/agent.py#L296)).
5. Markdown fences are stripped, then Code2Video forcibly replaces or inserts its canonical `TeachingScene` base class. This prevents the model from permanently modifying the shared layout ([`code2video/agent.py:343`](../code2video/agent.py#L343), [`code2video/utils.py:91`](../code2video/utils.py#L91)).
6. Before rendering, Code2Video generates `bg.png`, then invokes `manim -ql <segment-id>.py <SceneName>` in that output directory with a 180-second timeout ([`code2video/agent.py:357`](../code2video/agent.py#L357), [`code2video/agent.py:528`](../code2video/agent.py#L528)).
7. On success it looks for `<output>/media/videos/<segment-id>/480p15/<SceneName>.mp4`, with a second legacy path fallback. TeachGen copies the clip to `runs/<topic>/assets/<segment-id>.mp4` ([`teachgen/renderers/animation.py:82`](../teachgen/renderers/animation.py#L82)).
8. During final composition, the low-quality Manim clip is resized to 1920×1080 and the final video is encoded at 24 fps with H.264/AAC ([`teachgen/compositor/compositor.py:31`](../teachgen/compositor/compositor.py#L31)). This is an upscale/re-encode, not a new high-resolution Manim render or motion interpolation.

The scene name is derived from the segment ID: `seg3` becomes `Seg3Scene`. The Stage 3 prompt tells the model to generate precisely that class name ([`code2video/prompts/stage3.py:47`](../code2video/prompts/stage3.py#L47)).

### 2.2 Prompts used for active animation generation

Only these generation prompts are active inside TeachGen's animation route:

| Prompt | Source | Purpose |
|---|---|---|
| TeachGen animation storyboard system prompt | [`teachgen/renderers/animation.py:33`](../teachgen/renderers/animation.py#L33) | Converts one TeachGen segment to 2–5 short lecture lines plus aligned animation descriptions. |
| TeachGen animation storyboard user prompt | [`teachgen/renderers/animation.py:94`](../teachgen/renderers/animation.py#L94) | Supplies title, narration, visual brief, and approximate target duration. |
| Code2Video Stage 3 code-generation prompt | [`code2video/prompts/stage3.py:4`](../code2video/prompts/stage3.py#L4) | Requests complete Manim CE 0.19.0 code using the canonical layout, grid, palette, safe APIs, and class structure. |
| Whole-scene regeneration note | [`code2video/prompts/stage3.py:90`](../code2video/prompts/stage3.py#L90) | On later generation attempts, tells the model to simplify and use basic, reliable patterns. |
| Scoped/local repair prompt | [`code2video/scope_refine.py:578`](../code2video/scope_refine.py#L578) | Repairs only an extracted failing line/function/section block. |
| Full repair prompt | [`code2video/scope_refine.py:402`](../code2video/scope_refine.py#L402) | Escalates from focused fix to comprehensive review to complete rewrite while including the traceback and current code. |

Code2Video's Stage 4 layout-feedback prompt exists at [`code2video/prompts/stage4.py:4`](../code2video/prompts/stage4.py#L4), but TeachGen sets `use_feedback=False`, so it is inactive. The ScopeRefine traceback-driven repair prompts remain active because they are part of `debug_and_fix_code`, not the Stage 4 video-feedback loop.

### 2.3 The specific templates used

There is no Jinja template, scene catalog, or fixed lesson-specific animation template on the active path. There are three template-like inputs:

#### A. Canonical `TeachingScene` base-class template — active and enforced

The actual reusable code template is the `base_class` string in [`code2video/prompts/base_class.py:1`](../code2video/prompts/base_class.py#L1). It defines:

- `TeachingScene(Scene)`;
- an optional local `bg.png`, with fallback camera color `#0a0a0f`;
- a 30-point bold gold title at the top;
- a thin cyan separator;
- a left lecture panel made of gold dots and 20-point white text, scaled to 85%;
- a thin cyan bar beside the lecture panel;
- a 6×6 right-side logical grid named `A1` through `F6`;
- `place_at_grid(...)` and `place_in_area(...)` helper methods.

Grid coordinates are generated as `[0.5 + column, 2.2 - row, 0]` with one Manim unit between anchors. The prompt forbids lesson-specific animation elements from using manual `move_to`, `to_edge`, or `np.array` positioning, although this is a model instruction rather than a post-generation validator.

The Stage 3 prompt embeds this base class as a few-shot code skeleton. After generation, `replace_base_class()` replaces any generated `TeachingScene` definition with the canonical string or inserts it before the first class. Therefore, the base class is not merely advisory; its presence is enforced in the emitted Python source.

#### B. Stage 3 example structure — active as prompt guidance, not copied code

[`code2video/prompts/stage3.py:41`](../code2video/prompts/stage3.py#L41) shows the desired lesson-scene skeleton:

```python
from manim import *

<canonical TeachingScene base class>

class <SegmentId>Scene(TeachingScene):
    def construct(self):
        self.setup_layout("<title>", <lecture_lines>)
        # === Animation for Lecture Line 1 ===
        ...
```

It also specifies the dark AIGC palette (`#FFD166`, `#00F5D4`, `#F72585`), requires at least one rich styling technique, tells the model to highlight lecture rows only with `.animate.set_color()`, and recommends safe Manim APIs such as `FadeIn`, `FadeOut`, `Write`, `GrowArrow`, `Create`, and `Transform`. The `construct()` body remains generated per segment.

#### C. Decorative background template — active and deterministic

[`code2video/slide_bg.py:1`](../code2video/slide_bg.py#L1) creates a fresh 1920×1080 `bg.png` before each section render. It contains:

- the dark `#0a0a0f` base;
- a subtle 60-pixel grid;
- a blurred gold center glow;
- a four-pixel gold top bar; and
- three small bottom-right gold dots.

It contains no text or lesson content. Manim draws the title, lecture panel, and generated animation objects over it.

Files already found under `code2video/CASES/.../<segment-id>.py` are generated run artifacts and useful examples, not reusable templates. For example, [`code2video/CASES/tg_how-to-turn-a-matrix-into-row-echelon-form/0-Matrix_Operations_Overview/seg3.py:1`](../code2video/CASES/tg_how-to-turn-a-matrix-into-row-echelon-form/0-Matrix_Operations_Overview/seg3.py#L1) contains one generated matrix scene with the injected base class.

### 2.4 Rendering and repair retry behavior

TeachGen constructs this restricted Code2Video configuration ([`teachgen/renderers/animation.py:62`](../teachgen/renderers/animation.py#L62)):

| Setting | TeachGen value | Effect |
|---|---:|---|
| `use_feedback` | `False` | Disables Code2Video's rendered-video/layout MLLM loop. |
| `use_assets` | `False` | Disables icon discovery/download and asset insertion. |
| `max_code_token_length` | `10000` | Code-generation/repair response budget passed into Code2Video. |
| `max_regenerate_tries` | `2` | At most two whole-scene generations in `render_section`. |
| `max_fix_bug_tries` | `3` | At most three Manim execution/fix cycles for each whole-scene generation. |

The retry nesting is important:

```text
whole-scene generation attempt (up to 2)
    -> Manim execution/fix cycle (up to 3)
        -> analyze traceback and try a scoped block fix
        -> if needed, full-repair escalation (up to 3 model attempts)
        -> syntax compile check
        -> import/scene-instantiation dry run
        -> next Manim execution
```

The “dry run” does not execute the animation body. It rewrites `construct()` to wait 0.1 seconds and return immediately, then imports and instantiates the scene ([`code2video/scope_refine.py:345`](../code2video/scope_refine.py#L345)). Passing it verifies syntax/import/class construction, not that every original animation instruction will render.

If all configured attempts fail, `AnimationRenderer` raises. The pipeline then tries the concept-image renderer and finally the slide renderer. The comment in `animation.py` saying it falls back directly to a slide is stale; [`teachgen/pipeline.py:152`](../teachgen/pipeline.py#L152) is the authoritative implementation.

### 2.5 Timing and audio behavior

Code2Video does not receive narration audio or word timestamps. It receives short lecture lines and animation descriptions. The approximate segment duration appears in the TeachGen storyboard prompt, but duration is not a field on Code2Video's `Section` and is not included in the Stage 3 code prompt. Consequently, generated `self.wait(...)` and animation runtimes are model-chosen rather than deterministically synchronized to speech.

The compositor reconciles the durations afterward:

- if the Manim clip is shorter than narration, its last frame is frozen to the narration duration;
- if the Manim clip is longer, it remains full length and narration is padded with trailing silence;
- if narration is longer than the selected target in `_fit_audio`, it is clipped to the visual duration, although the earlier freeze normally makes a short visual match narration;
- all segment clips are concatenated in lesson-plan order and encoded to the final MP4.

The relevant implementation is [`teachgen/compositor/compositor.py:31`](../teachgen/compositor/compositor.py#L31).

## 3. Video generation and the Code2Video integration

### 3.1 The integration boundary

TeachGen treats Code2Video as a **single-segment Manim backend**, not as the top-level video generator. The adapter is entirely in [`teachgen/renderers/animation.py`](../teachgen/renderers/animation.py).

The integration performs these concrete steps:

1. Lazy-loads `code2video/agent.py` by adding the repository root and `code2video/` to `sys.path`, then importing the top-level module name `agent` ([`teachgen/renderers/animation.py:127`](../teachgen/renderers/animation.py#L127)).
2. Converts one TeachGen `Segment` into one Code2Video `Section`.
3. Creates a Code2Video `RunConfig` with TeachGen-specific limits and disabled assets/video feedback.
4. Wraps the active TeachGen `Provider` in a callable returning the response shape Code2Video expects: `(response, usage)`, where `response.choices[0].message.content` contains the text ([`teachgen/renderers/animation.py:108`](../teachgen/renderers/animation.py#L108)).
5. Creates a `TeachingVideoAgent` for that one segment.
6. Deletes an existing `<segment-id>.py` before generation so an outer feedback round cannot silently reuse old code.
7. Calls only `generate_section_code(section, attempt=1)` and `render_section(section)`.
8. Copies the successful MP4 into TeachGen's normalized run assets directory and returns a `VisualAsset(kind="video")`.

This adapter is why Code2Video's Manim generation uses TeachGen's configured text model and the same `OPENAI_API_KEY`. The adapter reports zero usage counts to Code2Video, so `TeachingVideoAgent.token_usage` does not reflect these TeachGen-routed calls. Billing still occurs normally through the provider.

`_load_code2video()` also imports and returns `prompts.base_class`, but the local `base_class` variable in `AnimationRenderer.render()` is unused. Code2Video's `agent.py` already imports `base_class` into its own module namespace through `from prompts import *`; that module-level value is the one passed to Stage 3 and to `replace_base_class()`.

### 3.2 Code2Video working and output paths

TeachGen gives Code2Video this base folder:

```text
code2video/CASES/tg_<run-directory-name>/
```

`TeachingVideoAgent` then calls `get_output_dir(idx=0, knowledge_point=<segment title>, ...)`, producing:

```text
code2video/CASES/tg_<run-directory-name>/0-<safe-segment-title>/
    bg.png
    <segment-id>.py
    media/videos/<segment-id>/480p15/<SceneName>.mp4
    ...Manim intermediate media...
```

The successful MP4 is copied to:

```text
runs/<topic>/assets/<segment-id>.mp4
```

The Code2Video working files are not cleaned after copying. Because every single-segment agent uses `idx=0` and derives its directory from the segment title, duplicate titles in one run can resolve to the same working directory.

Although assets and Code2Video video feedback are disabled, `TeachingVideoAgent.__init__()` still creates its shared icon directory and unconditionally reads `code2video/json_files/long_video_ref_mapping.json` ([`code2video/agent.py:83`](../code2video/agent.py#L83)). It also records the reference-grid image path, but that image is only consumed by the disabled Stage 4 video-feedback path.

### 3.3 Which Code2Video stages are used or bypassed

| Code2Video capability | TeachGen status | Reason/evidence |
|---|---|---|
| Stage 1 topic outline (`prompts/stage1.py`) | Bypassed | TeachGen's content writer and router own the lesson plan. `generate_outline()` is never called by `AnimationRenderer`. |
| Stage 2 whole storyboard (`prompts/stage2.py`) | Bypassed | TeachGen uses its own small per-segment storyboard prompt. `generate_storyboard()` is never called. |
| Asset download/placement prompts (`stage2.py`, `external_assets.py`) | Bypassed | `use_assets=False`. |
| Stage 3 Manim code prompt (`prompts/stage3.py`) | **Used** | Called by `generate_section_code()`. |
| ScopeRefine traceback repair (`scope_refine.py`) | **Used on Manim failure** | Called by `debug_and_fix_code()`. |
| Stage 4 rendered-video layout feedback (`prompts/stage4.py`) | Bypassed | `use_feedback=False`. |
| Stage 5 aesthetic evaluation/unlearning (`prompts/stage5_*.py`) | Bypassed | Evaluation/research utilities are not called by TeachGen. |
| Code2Video `generate_codes()`/`render_all_sections()` | Bypassed | TeachGen calls the single-section methods itself and handles parallelism at the segment level. |
| Code2Video `merge_videos()` | Bypassed | TeachGen's MoviePy compositor merges animation, concept-image, and slide segments with narration. |
| Code2Video `GENERATE_VIDEO()` and `run_Code2Video()` | Bypassed | These are the standalone top-level workflow, not the adapter entry points. |

The complete standalone sequence remains in [`code2video/agent.py:711`](../code2video/agent.py#L711): outline → storyboard → all code → all renders → FFmpeg merge. Running `python code2video/agent.py` uses `code2video/gpt_request.py` and Code2Video's own environment variables. Running `python -m teachgen` does not use that top-level path.

### 3.4 End-to-end video generation around Code2Video

Code2Video is only one branch of the larger TeachGen flow:

```text
topic + audience
    -> write teaching content
    -> route each segment to animation / concept_image / slide
    -> save runs/<topic>/lesson_plan.json
    -> for each dirty segment, in parallel when enabled:
         synthesize narration + word timings
         render selected visual
           animation -> Code2Video -> Manim MP4
           concept_image -> image API -> PNG
           slide -> Pillow -> PNG
    -> MoviePy combines each visual with its segment narration
    -> concatenate segments -> draft_rN.mp4 or final.mp4
    -> optionally sample 12 frames for outer review
    -> rewrite only affected narration/briefs and re-render dirty segments
```

The orchestration lives in [`teachgen/pipeline.py:24`](../teachgen/pipeline.py#L24). Segment narration is produced before its visual, and multiple segments can be produced in a `ThreadPoolExecutor` with six workers by default ([`teachgen/pipeline.py:130`](../teachgen/pipeline.py#L130)). Code2Video's own process-pool renderer is not used.

The final compositor, not Code2Video, owns mixed-media ordering, duration fitting, 1920×1080 output, 24 fps, H.264 video, AAC audio at 192 kbps, `yuv420p`, and `faststart` ([`teachgen/compositor/compositor.py:31`](../teachgen/compositor/compositor.py#L31)). FFmpeg must therefore be installed even though TeachGen bypasses Code2Video's own FFmpeg concatenation method.

## 4. Source-of-truth file map

| Concern | Primary source |
|---|---|
| Concept-image routing/brief prompt | [`teachgen/planner/route.py`](../teachgen/planner/route.py) |
| Concept-to-image-prompt system and user template | [`teachgen/concept_image.py`](../teachgen/concept_image.py) |
| Active concept-image renderer and fixed style payload | [`teachgen/renderers/concept_image.py`](../teachgen/renderers/concept_image.py) |
| Active animation adapter and provider shim | [`teachgen/renderers/animation.py`](../teachgen/renderers/animation.py) |
| Code2Video agent, Manim invocation, and retry loops | [`code2video/agent.py`](../code2video/agent.py) |
| Canonical Manim base-class template | [`code2video/prompts/base_class.py`](../code2video/prompts/base_class.py) |
| Active Manim generation prompt | [`code2video/prompts/stage3.py`](../code2video/prompts/stage3.py) |
| Scoped Manim repair prompts and checks | [`code2video/scope_refine.py`](../code2video/scope_refine.py) |
| Decorative Manim background template | [`code2video/slide_bg.py`](../code2video/slide_bg.py) |
| Final mixed-media composition and timing | [`teachgen/compositor/compositor.py`](../teachgen/compositor/compositor.py) |
| End-to-end orchestration/fallback/feedback | [`teachgen/pipeline.py`](../teachgen/pipeline.py) |

