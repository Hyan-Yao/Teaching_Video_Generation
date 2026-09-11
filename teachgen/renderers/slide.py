"""`slide` renderer — a polished slide rasterized directly to PNG via PIL.

We reuse make_slide.py's text parsing (Title / bullets / Diagram markers) and its
navy+moss+cream palette, but draw straight to a 1920x1080 image with Pillow instead
of going pptx -> LibreOffice -> poppler. That removes two heavy system dependencies
and makes the slide path fast, deterministic, and portable.

(teachgen/make_slide.py still exists for users who want an editable .pptx artifact;
this renderer just doesn't need it for video frames.)

Static output: kind="image"; the compositor stretches it to the narration duration.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..schema import Modality, Segment, SlideSpec, VisualAsset
from .base import RenderContext
from .. import make_slide  # the standalone helper, now a teachgen module

# Palette (mirrors make_slide.py) as plain RGB tuples.
NAVY = (0x1B, 0x3A, 0x6B)
MOSS = (0x7A, 0x9A, 0x6B)
PAPER = (0xF7, 0xF6, 0xF0)
INK = (0x2A, 0x2A, 0x2A)
ACCENT = (0x2D, 0x6C, 0xDF)
ACCENT_BG = (0xEA, 0xF0, 0xFB)
WHITE = (0xFF, 0xFF, 0xFF)

W, H = 1920, 1080

SYSTEM = """\
Convert one visual brief into a concise deterministic teaching-slide specification.

Use one of these layouts:
- none: title and bullets only.
- pipeline: 2-4 ordered nodes connected left-to-right. This is a sequence, never A+B=C.
- comparison: two titled columns with up to four short items each.
- cells: one exact row of up to 12 symbols or values, such as an 8-bit register.

Rules:
- Keep the title short and use at most five bullets of at most 12 words each.
- Copy required equations, code, bit strings, labels, and numeric values exactly.
- Never invent a relationship merely to fill a diagram.
- Do not use Markdown, checkbox glyphs, emoji, superscript glyphs, or decorative symbols.
- Prefer plain ASCII notation such as 2^3.
- The slide remains visible for the entire segment. If narration explicitly asks the
  learner to pause, calculate, predict, choose, or answer and then gives the solution,
  render only the problem setup. Do not include the answer, completed calculation,
  highlighted result, or solution state anywhere on that static slide.
"""


class SlideRenderer:
    modality = Modality.SLIDE

    def render(self, seg: Segment, ctx: RenderContext) -> VisualAsset:
        spec = ctx.provider.chat_json(
            f"Visual brief: {seg.visual_brief}\n\nNarration (for timing and context): "
            f"{seg.narration}\n\nRemember that this is one static image shown for "
            "the full narration. An explicit learner prompt must not display its later "
            "answer early.",
            SlideSpec,
            system=SYSTEM,
            max_tokens=1000,
            model=ctx.cfg.models.visual_text,
        )
        spec = _validate_slide_spec(spec)

        png_path = ctx.out_dir / f"{seg.id}.png"
        _draw_slide(spec, png_path)
        spec_path = ctx.out_dir / f"{seg.id}.slide.json"
        spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        debug_dir = ctx.cfg.run_dir / "slide_debug" / seg.id / f"round_{ctx.render_round}"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "slide_spec.json").write_text(
            spec.model_dump_json(indent=2), encoding="utf-8"
        )
        return VisualAsset(
            segment_id=seg.id,
            kind="image",
            path=str(png_path),
            intended_modality=seg.modality,
            rendered_modality=Modality.SLIDE,
            validation_status="passed",
        )


# --------------------------------------------------------------------- drawing
def _draw_slide(spec: SlideSpec, out_path: Path) -> None:
    title = spec.title.replace("**", "")
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # double rounded border (navy outer, moss inner)
    d.rounded_rectangle([34, 34, W - 34, H - 34], radius=28, outline=NAVY, width=7)
    d.rounded_rectangle([60, 60, W - 60, H - 60], radius=22, outline=MOSS, width=3)

    title_font = _font(64, bold=True)
    bullet_font = _font(40)
    bullet_bold = _font(40, bold=True)

    # title (wrapped)
    margin = 140
    y = 110
    for line in _wrap(title, title_font, W - 2 * margin, d):
        d.text((margin, y), line, font=title_font, fill=NAVY)
        y += int(title_font.size * 1.2)

    # moss underline under the title
    y += 10
    d.line([(margin, y), (margin + 520, y)], fill=MOSS, width=5)
    d.ellipse([margin - 24, y - 9, margin - 6, y + 9], fill=MOSS)
    y += 60

    # bullets
    has_diagram = spec.layout != "none"
    bullets_bottom = (H - 360) if has_diagram else (H - 120)
    line_h = int(bullet_font.size * 1.55)
    for b in spec.bullets:
        if y > bullets_bottom:
            break
        d.ellipse([margin, y + 14, margin + 18, y + 32], fill=NAVY)
        _draw_runs(d, margin + 44, y, b, make_slide.split_bold, bullet_font, bullet_bold,
                   W - margin - 44, line_h)
        # advance by however many wrapped lines the bullet took
        n_lines = max(1, len(_wrap(_plain(b), bullet_font, W - margin - 44, d)))
        y += line_h * n_lines + 16

    if spec.layout == "pipeline":
        _draw_pipeline(d, spec.pipeline_nodes, spec.caption)
    elif spec.layout == "comparison":
        _draw_comparison(d, spec)
    elif spec.layout == "cells":
        _draw_cells(d, spec.cells, spec.cells_label, spec.caption)

    img.save(out_path, format="PNG")


def _draw_runs(d, x, y, text, split_bold, font, bold_font, max_w, line_h):
    """Draw a bullet, honoring **bold** lead-ins, with naive wrapping."""
    cur_x, cur_y = x, y
    for chunk, is_bold in split_bold(text):
        f = bold_font if is_bold else font
        col = NAVY if is_bold else INK
        chunk = chunk.replace("**", "")  # drop any unpaired bold markers left over
        for word in chunk.split(" "):
            if not word:
                continue
            w = d.textlength(word + " ", font=f)
            if cur_x + w > x + max_w:
                cur_x = x
                cur_y += line_h
            d.text((cur_x, cur_y), word + " ", font=f, fill=col)
            cur_x += w


def _draw_pipeline(d, nodes, caption):
    if len(nodes) < 2:
        return
    count = len(nodes)
    left, right, cy = 180, W - 180, H - 245
    gap = 70
    box_w = int((right - left - gap * (count - 1)) / count)
    for index, label in enumerate(nodes):
        x0 = left + index * (box_w + gap)
        x1 = x0 + box_w
        d.rounded_rectangle([x0, cy - 75, x1, cy + 75], radius=15,
                            fill=ACCENT_BG, outline=ACCENT, width=5)
        font = _fit_font(d, label, box_w - 30, 42, bold=True)
        _centered(d, label, font, (x0 + x1) / 2, cy, NAVY)
        if index < count - 1:
            start, end = x1 + 12, x1 + gap - 12
            d.line([(start, cy), (end, cy)], fill=MOSS, width=7)
            d.polygon([(end - 18, cy - 14), (end, cy), (end - 18, cy + 14)], fill=MOSS)
    if caption:
        _centered(d, caption, _fit_font(d, caption, W - 300, 32), W / 2, H - 95, INK)


def _draw_comparison(d, spec: SlideSpec):
    top, bottom = H - 390, H - 90
    columns = [(150, W // 2 - 35, spec.left_title, spec.left_items, NAVY),
               (W // 2 + 35, W - 150, spec.right_title, spec.right_items, MOSS)]
    for x0, x1, title, items, color in columns:
        d.rounded_rectangle([x0, top, x1, bottom], radius=16,
                            fill=WHITE, outline=color, width=5)
        _centered(d, title, _fit_font(d, title, x1 - x0 - 40, 38, bold=True),
                  (x0 + x1) / 2, top + 50, color)
        y = top + 105
        for item in items:
            d.ellipse([x0 + 32, y + 10, x0 + 47, y + 25], fill=color)
            d.text((x0 + 65, y), item, font=_fit_font(d, item, x1 - x0 - 100, 30), fill=INK)
            y += 50


def _draw_cells(d, cells, label, caption):
    if not cells:
        return
    left, right, cy = 210, W - 210, H - 245
    cell_w = min(150, int((right - left) / len(cells)))
    total_w = cell_w * len(cells)
    x0 = int((W - total_w) / 2)
    for index, value in enumerate(cells):
        xa = x0 + index * cell_w
        d.rounded_rectangle([xa, cy - 70, xa + cell_w - 6, cy + 70], radius=10,
                            fill=WHITE, outline=NAVY, width=5)
        _centered(d, value, _fit_font(d, value, cell_w - 24, 58, bold=True),
                  xa + (cell_w - 6) / 2, cy, NAVY)
    if label:
        _centered(d, label, _fit_font(d, label, W - 300, 34, bold=True), W / 2, cy - 115, MOSS)
    if caption:
        _centered(d, caption, _fit_font(d, caption, W - 300, 32), W / 2, H - 80, INK)


def _fit_font(d, text, max_width, start_size, *, bold=False):
    size = start_size
    while size > 18 and d.textlength(text, font=_font(size, bold=bold)) > max_width:
        size -= 2
    return _font(size, bold=bold)


def _validate_slide_spec(spec: SlideSpec) -> SlideSpec:
    values = [spec.title, *spec.bullets, *spec.pipeline_nodes, spec.left_title,
              *spec.left_items, spec.right_title, *spec.right_items, *spec.cells,
              spec.cells_label, spec.caption]
    for value in values:
        if value.count("**") % 2:
            raise ValueError("slide text contains unpaired Markdown emphasis")
        if any(char in value for char in ("\ufffd", "\u25a1", "\u2610")):
            raise ValueError("slide text contains an unsupported placeholder glyph")
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("slide text contains unsupported control characters")
    if spec.layout == "pipeline" and not 2 <= len(spec.pipeline_nodes) <= 4:
        raise ValueError("pipeline slides require 2-4 nodes")
    if spec.layout == "comparison" and not (spec.left_title and spec.right_title):
        raise ValueError("comparison slides require two column titles")
    if spec.layout == "cells" and not spec.cells:
        raise ValueError("cells slides require at least one cell")
    return spec


# ----------------------------------------------------------------------- utils
def _centered(d, text, font, cx, cy, color):
    w = d.textlength(text, font=font)
    asc, desc = font.getmetrics()
    d.text((cx - w / 2, cy - (asc + desc) / 2), text, font=font, fill=color)


def _wrap(text, font, max_w, d):
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _plain(text: str) -> str:
    return text.replace("**", "")


def _initials(label: str) -> str:
    label = label.strip()
    if not label:
        return "?"
    if any("一" <= c <= "鿿" for c in label):
        return label[:2]
    return label[0].upper()


_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int, *, bold: bool = False):
    for path in (_BOLD_CANDIDATES if bold else []) + _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()
