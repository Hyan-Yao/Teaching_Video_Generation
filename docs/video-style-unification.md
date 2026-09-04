# Unifying the visual style of TeachGen videos

## Implementation status

Approach 1 is implemented as the only visual style in both TeachGen and the standalone
Code2Video entry point. Historical comparisons are performed by rendering this branch
and then rendering `main`, using the original topic-driven CLI on both branches.

### Branch comparison commands

Run these in one terminal so the shell variables survive branch changes. The feature
branch must be committed before switching branches.

```bash
cd /Users/rayankazi/Developer/sandbox/Teaching_Video_Generation
git switch codex/unified-video-gen-styling

export OPENAI_API_KEY="sk-..."
TOPIC="Vectors"
NEW_RUN="runs/style-test/new"
OLD_RUN="runs/style-test/old"

# Generate the complete video using the new visual style.
.venv/bin/python -m teachgen --topic "$TOPIC" --run-dir "$NEW_RUN" \
  --no-feedback --no-parallel

# Switch to the historical implementation and run its normal workflow.
git switch main
.venv/bin/python -m teachgen --topic "$TOPIC" --run-dir "$OLD_RUN" \
  --no-feedback --no-parallel

# Return to the implementation branch when finished.
git switch codex/unified-video-gen-styling
```

The outputs are `runs/style-test/new/vectors/video/final.mp4` and
`runs/style-test/old/vectors/video/final.mp4`. The commands differ only in output
directory. Each branch generates its own plan and video through its normal workflow.

## Recommendation

Use **Approach 1: a shared light theme** when the integration can be redesigned cleanly. Use **Approach 2: a TeachGen-side canonical-palette override** when `code2video/` must remain an untouched upstream dependency. Both use the same palette; Approach 1 makes it native to every renderer, while Approach 2 enforces it at the integration boundary.

## What was happening before Approach 1

The mismatch is deterministic, not an occasional model choice.

| Visual path | Previous source of style | Previous result |
|---|---|---|
| Concept image | [`teachgen/concept_image.py:65`](../teachgen/concept_image.py#L65) requires cream/white; [`teachgen/renderers/concept_image.py:15`](../teachgen/renderers/concept_image.py#L15) repeats cream, teal, gold, and dark-gray styling | Light |
| Manim animation | [`code2video/slide_bg.py:10`](../code2video/slide_bg.py#L10) creates a dark `bg.png`; [`code2video/prompts/base_class.py:1`](../code2video/prompts/base_class.py#L1) injects dark-theme layout colors; [`code2video/prompts/stage3.py:69`](../code2video/prompts/stage3.py#L69) tells the model to generate bright objects for that dark theme | Dark |
| Final recap / emergency slide | [`teachgen/renderers/slide.py:24`](../teachgen/renderers/slide.py#L24) draws a fixed cream-paper, navy, and moss layout | Light |

The `camera.background_color = "#0a0a0f"` line visible in the supplied screenshot was only the fallback. In normal rendering, Code2Video first creates `bg.png`, and the base class loads that image instead. Changing only `background_color` therefore would not have changed normal renders.

There is already evidence that this matters beyond aesthetics: [`runs/vectors/review_r0.json:11`](../runs/vectors/review_r0.json#L11) marks three dark animation segments as major contrast/clarity problems.

## Approach 1 — shared light theme (Code2Video changes allowed)

Make the cream academic style a first-class theme and pass it to all three renderers.

**Canonical palette**

| Role | Suggested value |
|---|---|
| Background | `#F7F6F0` |
| Primary text / structure | `#1B3A6B` |
| Secondary accent | `#0F766E` or current moss `#7A9A6B` |
| Highlight | dark gold such as `#9A6700` |
| Body text | `#2A2A2A` |
| Subtle grid / panel | `#E4E0D5` |

Implementation scope:

1. Add one theme object to TeachGen configuration and have concept-image prompt text and the deterministic slide renderer read from it. This prevents palette values from drifting across files.
2. Pass the same serializable theme through Code2Video's `RunConfig` in [`teachgen/renderers/animation.py:62`](../teachgen/renderers/animation.py#L62).
3. Update [`code2video/slide_bg.py`](../code2video/slide_bg.py) to render paper, a subtle light grid, and a low-opacity accent instead of a black field and glow.
4. Generate the enforced base-class string in [`code2video/prompts/base_class.py`](../code2video/prompts/base_class.py) from the theme: paper fallback, navy title, dark lecture text, and restrained teal/gold accents.
5. Rewrite the dark-theme block and examples in [`code2video/prompts/stage3.py`](../code2video/prompts/stage3.py) so generated shapes, labels, panels, and formulas have sufficient contrast on the light background. In particular, do not retain white lecture text or bright cyan/gold as body text on cream.
6. For Code2Video's standalone workflow as well as TeachGen, also remove the fixed-black instruction in [`code2video/prompts/stage2.py:45`](../code2video/prompts/stage2.py#L45). Stage 2 is bypassed by TeachGen, so this is optional for the active pipeline but necessary for repository-wide consistency.

**Why this is preferred:** concept images and recap slides need little visual change, the resulting video avoids abrupt light-to-black cuts, and the palette has better text contrast. The cost is a wider integration patch and future care when syncing changes from upstream Code2Video.

## Approach 2 — TeachGen-side canonical-palette override (no `code2video/` changes)

Leave Code2Video's tracked source completely untouched and override its dark defaults from the TeachGen adapter at runtime. Pin all three visual paths to the same canonical palette used by Approach 1. **No file under `code2video/` is edited.**

| Role | Canonical value |
|---|---|
| Background | `#F7F6F0` |
| Primary text / structure | `#1B3A6B` |
| Secondary accent | `#0F766E` (or existing moss `#7A9A6B`) |
| Highlight | `#9A6700` |
| Body text | `#2A2A2A` |
| Subtle grid / panel | `#E4E0D5` |

Implementation scope:

1. Add a TeachGen-owned compatibility module, for example `teachgen/manim_light_theme.py`, containing:
   - a drop-in `TeachingScene` base-class string using background `#F7F6F0`, navy title/structure, dark body text, teal secondary accents, and dark-gold highlights;
   - a deterministic 1920×1080 background generator using `#F7F6F0` with an optional `#E4E0D5` grid/panel treatment; and
   - a Stage 3 prompt transformer that replaces Code2Video's dark-theme block with equivalent light-theme instructions before the prompt reaches the model.
2. In [`teachgen/renderers/animation.py`](../teachgen/renderers/animation.py), install those overrides on the imported `agent` module before calling `generate_section_code()`:
   - replace the runtime `base_class` symbol with the light base class;
   - replace the runtime `create_background` symbol with the canonical light-background generator; and
   - pass Stage 3 requests through the light-prompt transformer in the existing provider shim.
   These are in-memory substitutions only; Code2Video source remains byte-for-byte unchanged.
3. Make installation idempotent and thread-safe because TeachGen renders segments concurrently. Add fail-fast assertions that the generated `bg.png` has `#F7F6F0` as its dominant background and the injected base class contains the canonical foreground palette; never silently fall back to dark output.
4. Tighten [`teachgen/concept_image.py:65`](../teachgen/concept_image.py#L65) and [`teachgen/renderers/concept_image.py:15`](../teachgen/renderers/concept_image.py#L15) to require the exact canonical background and foreground colors. Both prompt layers must agree.
5. Keep the active slide palette in [`teachgen/renderers/slide.py:24`](../teachgen/renderers/slide.py#L24) aligned with the canonical values, replacing its current blue accent values where necessary. Update [`teachgen/make_slide.py`](../teachgen/make_slide.py) too only if standalone editable PPTX output must match.
6. Keep the stored `visual_brief` content-only; do not repeatedly rewrite it with palette text. At each renderer boundary, compose the effective request as `visual_brief + CANONICAL_THEME`, with the theme treated as the final style constraint:
   - the concept-image renderer supplies it through its system/style prompt;
   - the animation renderer includes it in the TeachGen-owned Stage 3 final prompt; and
   - the slide renderer applies it directly through deterministic drawing constants.
   Feedback may continue rewriting what a segment should show. If an animation falls back to a concept image or slide, the receiving renderer applies the same theme automatically.

**Why choose it:** the whole video gets the same cream/navy/teal/gold identity without creating a Code2Video fork, and upstream upgrades remain easy. The tradeoff is adapter fragility: if Code2Video renames imported symbols or substantially rewrites its Stage 3 prompt, the compatibility checks must fail and be updated. Deterministic prompt transformation is preferable to merely appending a contradictory style sentence.

## Validation for either approach

- Render one lesson containing an animation, a concept image, and the final slide, plus one forced animation failure to exercise the `animation → concept_image → slide` fallback in [`teachgen/pipeline.py:152`](../teachgen/pipeline.py#L152).
- Sample the first, middle, and last frame of every segment and check background, text contrast, palette, and transition continuity. Use at least 4.5:1 contrast for normal text and 3:1 for large text.
- Assert that the expanded concept-image prompt contains the canonical values. For Approach 2, require `#F7F6F0`, `#1B3A6B`, `#0F766E`/`#7A9A6B`, `#9A6700`, `#2A2A2A`, and `#E4E0D5`; reject black, pure white, and unrelated palette instructions.
- Search active prompts for stale `dark`, `black`, `cream`, `white`, and old hex values.
- Re-render existing animation assets after the change. Saved MP4s and PNGs do not restyle themselves, although TeachGen does force fresh Manim source generation when a segment is rendered again ([`teachgen/renderers/animation.py:77`](../teachgen/renderers/animation.py#L77)).

## Decision summary

| | Approach 1: shared light | Approach 2: canonical-palette adapter |
|---|---|---|
| Edits `code2video/` | Yes | **No** |
| Visual direction | Canonical cream/navy/teal/gold | Same canonical palette |
| Main files changed | All renderer theme surfaces | TeachGen adapter, concept, and slide only |
| Reliability | Highest; native theme propagation | High with fail-fast compatibility checks |
| Maintenance | More upstream integration work | No fork, but adapter tracks upstream interfaces |
| Recommendation | Cleanest architecture | **Use when the upstream boundary is strict** |
