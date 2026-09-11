# MLLM feedback


def get_prompt4_layout_feedback(section, position_table, current_code=""):
    numbered_code = "\n".join(
        f"{index}: {line}"
        for index, line in enumerate(current_code.splitlines(), start=1)
    )
    return f"""
1. ANALYSIS REQUIREMENTS:
- Analyze this Manim educational video ONLY for animation visual repair issues.
- Use the provided reference image for precise spatial analysis.
- Focus on eliminating overlaps, obstructions, unreadable labels, bad arrows,
  lingering objects, poor grid use, and mismatch between the current lecture line
  and the visible animation.
- You will see stable samples taken near the end of storyboard steps. Judge
  persistent states, not normal in-progress drawing. A partially drawn `Write`
  is not a defect unless it remains incomplete in consecutive stable samples.
- Minor cosmetic imperfections are acceptable. Request repair only when a major
  or blocker issue persists across stable samples and harms meaning/readability.

2. Content Context:
- Title: {section.title}
- Lecture Lines: {'; '.join(section.lecture_lines)}
- Storyboard step timing windows: {section.step_timings}
- Current Grid Occupancy: {position_table}
- Current numbered Manim code:
```python
{numbered_code}
```

3. Visual Anchor System (6*6 grid, right side only):
```
lecture |  A1  A2  A3  A4  A5  A6
        |  B1  B2  B3  B4  B5  B6
        |  C1  C2  C3  C4  C5  C6
        |  D1  D2  D3  D4  D5  D6
        |  E1  E2  E3  E4  E5  E6
        |  F1  F2  F3  F4  F5  F6
```
- Point positioning (point, one-word label): self.place_at_grid(obj, 'B2', scale_factor=0.8)
- Area positioning (over-two-words label, fomula, group): self.place_in_area(obj, 'A1', 'C3', scale_factor=0.7)

4. LAYOUT ASSESSMENT (Check ALL):
- Obstruction: Animations blocking left-side lecture notes [ATTENTION]
- Overlap: Animation elements (formulas, labels, shapes) overlapping
- Numeric/text collision: numbers or words drawn on top of other numbers, words,
  boxes, arrows, or outlines
- Readability: text too small, cramped, low contrast, or placed on top of shapes
- Arrows: arrows crossing through labels/text or pointing ambiguously
- Off-screen: Elements cut off or outside visible area [ESPECIALLY for LONG LABEL]
- Grid violations: Poor grid space utilization
- Stale visual state: old labels, shapes, arrows, highlights, or phrases remain
  visible after their lecture step and interfere with the current step
- Lecture mismatch: visible objects do not support the active lecture line

5. MANDATORY CONSTRAINTS:
- Color: Provide hexadecimal color codes for unclear colors.
- Font/Scale: Adjust font sizes and asset scales for grid positions.
- Consistency: Do not apply any animation to the lecture lines except for color changes; The lecture lines and title's size and position must remain unchanged.
- Asset: Only adjust Existing PNG assets' size and position.
- Proximity: Ensure labels stay within 1 grid unit of their objects.
- Cleanup: You may remove or fade out stale right-side animation objects from
  earlier steps, but never remove the fixed title, accent bar, or left-side
  lecture lines.

6. IMPORTANT: Output MUST follow this exact JSON structure:
{{
    "layout": {{
        "has_issues": true,
        "severity": "major",
        "persistent": true,
        "summary": "concise evidence-based finding",
        "improvements": [
            {{
                "action": "replace_placement",
                "line_number": 42,
                "object_name": "obj_name",
                "object_names": [],
                "method": "place_at_grid",
                "grid_position": "C3",
                "top_left": null,
                "bottom_right": null,
                "scale_factor": 0.75,
                "z_index": null,
                "style_attribute": null,
                "style_value": null
            }},
            ...
        ]
    }}
}}

7. SOLUTION REQUIREMENTS:
- Set severity to one of "minor", "major", or "blocker". Use major/blocker for
  overlap, unreadable content, off-screen content, stale objects that obscure the
  current step, or a visible state that communicates the wrong relationship.
- Set has_issues=false for no issue or minor-only issues. Set persistent=true only
  when the same defect remains in consecutive stable states.
- Provide specific grid coordinates in solutions
- List up to 3 layout problems that most affect the visual experience!
- Always include overlap or text collision as a top-priority problem when visible
  in any sampled frame.
- Do not give the video timestamp
- Give concise problem descriptions but detailed, actionable solutions
- Subsequent solution positions should not overlap with previous solution positions
- Prefer line-specific fixes to `place_at_grid(...)`, `place_in_area(...)`, scale
  factors, font sizes, and object fadeout/cleanup. Do not suggest rewriting the
  whole scene unless the layout cannot be repaired locally.
- Allowed action values only: replace_placement, insert_cleanup, replace_write,
  set_z_index, update_style. Every action is one local edit tied to an existing
  line number. Do not return free-form solutions or rewritten code.
- insert_cleanup uses method fade_out or remove and object_names. replace_write
  uses object_name. set_z_index uses object_name and z_index. update_style uses
  object_name, style_attribute (font_size or color), and style_value.
- For set_z_index, identify the object's creation line; the setter is inserted
  immediately after it. For update_style, identify an existing declaration line
  that already contains the named font_size or color argument.
- A place_at_grid/place_in_area solution must name the line of the existing
  placement call being replaced, not the object's creation line.
- A FadeOut/remove cleanup solution must name the first existing line before
  which that cleanup should be inserted.
- For stale old text or shapes, give a precise cleanup solution such as
  `Line X: self.play(FadeOut(old_label), FadeOut(old_arrow))` or
  `Line X: self.remove(old_label, old_arrow)`. Only target right-side animation
  objects created by the generated scene, not `self.title`, `self.lecture`, or
  static layout objects.
"""


def get_feedback_list_prefix(feedback_improvements):
    """
    Please specifically focus on:
    - Making sure animations correspond correctly to lecture content
    - Improving animation clarity and readability
    - Fixing any positioning or alignment issues
    - Removing or fading out stale right-side animation text/shapes from earlier steps
    - Ensuring proper visual hierarchy and focus
    """
    # -----------------------------------------------------------------------------
    return f"""       
MLLM FEEDBACK IMPROVEMENTS: Based on video analysis, please address these issues:
{chr(10).join([f"- {improvement}" for improvement in feedback_improvements])}
"""


def get_feedback_improve_code(feedback, code):
    return f"""
You are a Manim v0.19.0 educational animation expert.

MUST KEEP (MANDATORY):
- Based on the following feedback, improve the current Manim code.
- Use light colors in the animations or labels!
- Do not apply any animation to the lecture lines except for color changes; their size and position must remain unchanged.
- If old right-side animation phrases, labels, arrows, highlights, or shapes linger
  into later steps, add targeted `FadeOut(...)` or `self.remove(...)` calls for
  those objects before the next visual step. Do NOT fade out or remove `self.title`,
  `self.lecture`, the title underline/accent bar, or the fixed left lecture panel.
- Output only the updated full Python code. No explanation.

Feedback:
{feedback}

---

Current Code:
```python
{code}
```
"""
