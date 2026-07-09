import os


def get_prompt3_code(regenerate_note, section, base_class):
    target_seconds = getattr(section, "target_seconds", None) or 12
    line_count = max(1, len(section.lecture_lines))
    seconds_per_line = target_seconds / line_count
    return f"""
You are an expert Manim animator using Manim Community Edition v0.19.0.
Please generate a high-quality Manim class based on the following teaching script.
{regenerate_note}

1. Basic Requirements:
- Use the provided TeachingScene base class WITHOUT modification — it sets up the dark background, gold title, cyan accent bar, and left-side lecture panel automatically.
- Each lecture line must have a matching color with its corresponding animation elements.
- Color changes on lecture lines MUST use the `.animate` API:
  `self.play(self.lecture[n].animate.set_color(COLOR))`
  DO NOT use the deprecated `self.play(obj.set_color, COLOR)` syntax.

2. Visual Anchor System (MANDATORY):
- Use 6x6 grid system (A1-F6) for precise positioning (right side only).
- Pay attention to the positioning of elements to avoid occlusions (e.g., labels and formulas).
- All labels must be positioned within 1 grid unit of their corresponding objects.
- Grid layout (right side only):
```
lecture |  A1  A2  A3  A4  A5  A6
        |  B1  B2  B3  B4  B5  B6
        |  C1  C2  C3  C4  C5  C6
        |  D1  D2  D3  D4  D5  D6
        |  E1  E2  E3  E4  E5  E6
        |  F1  F2  F3  F4  F5  F6
```

3. POSITIONING METHODS:
- Point example: self.place_at_grid(obj, 'B2', scale_factor=0.8)
- Area example: self.place_in_area(obj, 'A1', 'C3', scale_factor=0.7)
- NEVER use .to_edge(), .move_to(), or manual np.array positioning on animation elements!

4. ANTI-OVERLAP RULES:
- Text must never overlap shapes, arrows, cards, icons, or other text.
- If a label is inside a shape, make the shape large enough and use a small font so the full label fits with visible padding.
- If a label does not comfortably fit inside a shape, place it outside the shape using `.next_to(..., buff=0.15)` or put it in its own nearby grid cell.
- Do not put multiple labels on the same grid point.
- Do not draw arrows through text labels. Route arrows between object edges using `buff`.
- Before writing the final code, mentally inspect each visual block and adjust positions if any object could cover another object.

5. TEACHING CONTENT:
- Title: {section.title}
- Lecture Lines: {section.lecture_lines}
- Animation Description: {'; '.join(section.animations)}
- Target narration duration: about {target_seconds:.1f} seconds total.
- Timing budget: about {seconds_per_line:.1f} seconds per lecture line/animation block.

6. AUDIO-VISUAL TIMING ALIGNMENT:
- The rendered Manim scene should last about {target_seconds:.1f} seconds, matching
  the narration duration. Do not create a very short animation that freezes during
  narration, and do not create a much longer animation that makes audio end early.
- Each `# === Animation for Lecture Line N ===` block should consume roughly
  {seconds_per_line:.1f} seconds including `self.play(..., run_time=...)` and
  `self.wait(...)`.
- Use explicit `run_time` values for important animations. Avoid default short
  timings like only `self.wait(0.5)` unless the block has already used enough time.
- The visual for lecture line N must appear while lecture line N is highlighted.
  Do not show visuals for later lecture lines early.
- Before moving to the next lecture line, fade out or remove stale right-side
  labels/shapes/arrows that would confuse the next step. Do not remove the fixed
  title or left lecture panel.
- Keep the final visual on screen only for the final block; earlier visual states
  should not linger unless they are intentionally reused and do not overlap.

7. STRUCTURE FOR CODE:
Use the following comment format to indicate which block corresponds to which line:
```python
# === Animation for Lecture Line 1 ===
```

8. EXAMPLE STRUCTURE:
```python
from manim import *

{base_class}

class {section.id.title().replace('_', '')}Scene(TeachingScene):
    def construct(self):
        self.setup_layout("{section.title}", {section.lecture_lines})

        # === Animation for Lecture Line 1 ===
        self.play(self.lecture[0].animate.set_color("#FFD166"))
        obj = Circle(radius=0.5, color="#FFD166", fill_opacity=0.3)
        self.place_at_grid(obj, 'C3', scale_factor=1.0)
        self.play(FadeIn(obj))
        self.wait(0.5)

        # === Animation for Lecture Line 2 ===
        self.play(self.lecture[1].animate.set_color("#00F5D4"))
        ...
```

9. RICH TEXT & VISUAL STYLING — AIGC Dark Theme (animation area only):
The scene uses a dark `#0a0a0f` background. Apply these color palette and techniques:
- Primary accent (gold): `#FFD166`  Secondary accent (cyan): `#00F5D4`  Pop accent (pink): `#F72585`
- Gradient on math/text: `obj.set_color_by_gradient("#FFD166", "#00F5D4")`
- Soft highlight box: `SurroundingRectangle(obj, color="#00F5D4", corner_radius=0.1, buff=0.08)`
- Underline key labels: `Underline(text_obj, color="#FFD166")`
- Mixed rich text: `MarkupText('<b><span foreground="#FFD166">Term</span></b>: definition', font_size=22)`
- Dark panel behind elements: `BackgroundRectangle(obj, color="#1a1a2e", fill_opacity=0.4)`
- Glowing numbers: `DecimalNumber(...).set_color_by_gradient("#F72585", "#FFD166")`
Use AT LEAST ONE of these techniques per scene to match the AIGC visual theme.

10. MANDATORY CONSTRAINTS:
- Colors: Prefer the AIGC palette (`#FFD166`, `#00F5D4`, `#F72585`) over plain white/red/blue.
- Scaling: Maintain appropriate font sizes and object scales for readability on a 480p render.
- Consistency: Do NOT apply any animation to lecture lines except `.animate.set_color()`; size and position of lecture lines and title must stay unchanged.
- Assets: If provided, MUST use elements in Animation Description formatted as [Asset: XXX/XXX.png].
- Simplicity: Avoid 3D, complex camera moves, external dependencies, or overly nested VGroups.
- Visual density: Keep only 1-3 main right-side visual groups visible at a time.
  Do not build large tables, many rows, or many simultaneous labels. If a concept
  has many examples, show one example at a time and clean it up before the next.
- Safe API only: Use only well-tested Manim CE v0.19.0 methods. Prefer `FadeIn`, `FadeOut`, `Write`, `GrowArrow` (on single Arrow), `Create`, `Transform`. For `GrowArrow` use a single Arrow, not a VGroup.
"""


def get_regenerate_note(attempt, MAX_REGENERATE_TRIES):
    return f"""    
**IMPORTANT NOTE:** This is attempt {attempt}/{MAX_REGENERATE_TRIES} to generate working code.
The previous attempts failed to run correctly. Please:
1. Use only basic, well-tested Manim functions
2. Avoid complex animations that might cause errors
3. Use simple, reliable Manim patterns
"""
