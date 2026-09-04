import os

from themes import normalize_theme


def _style_guidance(theme):
    return f"""7. RICH TEXT & VISUAL STYLING — Shared Light Academic Theme (animation area only):
The scene uses paper `{theme['background']}`. All generated objects, labels, formulas, and panels must maintain strong contrast on it.
- Primary text/structure: `{theme['primary']}`  Secondary accent: `{theme['secondary']}`  Highlight: `{theme['highlight']}`
- Body text: `{theme['body']}`  Subtle panel/grid: `{theme['panel']}`
- Gradient: `obj.set_color_by_gradient("{theme['primary']}", "{theme['secondary']}")`
- Highlight box: `SurroundingRectangle(obj, color="{theme['secondary']}", corner_radius=0.1, buff=0.08)`
- Underline: `Underline(text_obj, color="{theme['highlight']}")`
- Mixed rich text: `MarkupText('<b><span foreground="{theme['primary']}">Term</span></b>: definition', font_size=22)`
- Restrained panel: `BackgroundRectangle(obj, color="{theme['panel']}", fill_opacity=0.45)`
Use at least one technique per scene. Never use white lecture/body text, neon colors, dark panels, or low-contrast gold text on the paper background."""


def get_prompt3_code(regenerate_note, section, base_class, theme=None):
    theme = normalize_theme(theme)
    style_guidance = _style_guidance(theme)
    return f"""
You are an expert Manim animator using Manim Community Edition v0.19.0.
Please generate a high-quality Manim class based on the following teaching script.
{regenerate_note}

1. Basic Requirements:
- Use the provided TeachingScene base class WITHOUT modification. It owns the `{theme['name']}` background, title, accent bar, and left-side lecture layout.
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

4. TEACHING CONTENT:
- Title: {section.title}
- Lecture Lines: {section.lecture_lines}
- Animation Description: {'; '.join(section.animations)}

5. STRUCTURE FOR CODE:
Use the following comment format to indicate which block corresponds to which line:
```python
# === Animation for Lecture Line 1 ===
```

6. EXAMPLE STRUCTURE:
```python
from manim import *

{base_class}

class {section.id.title().replace('_', '')}Scene(TeachingScene):
    def construct(self):
        self.setup_layout("{section.title}", {section.lecture_lines})

        # === Animation for Lecture Line 1 ===
        self.play(self.lecture[0].animate.set_color("{theme['highlight']}"))
        obj = Circle(radius=0.5, color="{theme['highlight']}", fill_opacity=0.3)
        self.place_at_grid(obj, 'C3', scale_factor=1.0)
        self.play(FadeIn(obj))
        self.wait(0.5)

        # === Animation for Lecture Line 2 ===
        self.play(self.lecture[1].animate.set_color("{theme['secondary']}"))
        ...
```

{style_guidance}

8. MANDATORY CONSTRAINTS:
- Colors: Use only the supplied theme palette (`{theme['primary']}`, `{theme['secondary']}`, `{theme['highlight']}`, `{theme['body']}`, `{theme['panel']}`) unless semantic red/green is essential.
- Scaling: Maintain appropriate font sizes and object scales for readability on a 480p render.
- Consistency: Do NOT apply any animation to lecture lines except `.animate.set_color()`; size and position of lecture lines and title must stay unchanged.
- Assets: If provided, MUST use elements in Animation Description formatted as [Asset: XXX/XXX.png].
- Simplicity: Avoid 3D, complex camera moves, external dependencies, or overly nested VGroups.
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
