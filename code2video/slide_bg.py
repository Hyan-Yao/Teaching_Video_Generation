"""
Generate decorative background PNGs for Manim teaching scenes.
Produces visual elements only (grid, panel, accent bars) — no text.
Manim handles all text and animation rendering on top.
"""

from PIL import Image, ImageDraw
from pathlib import Path

from themes import normalize_theme

WIDTH, HEIGHT = 1920, 1080


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def _draw_grid(draw, color):
    c = _hex_to_rgb(color)
    for x in range(0, WIDTH, 60):
        draw.line([(x, 0), (x, HEIGHT)], fill=c, width=1)
    for y in range(0, HEIGHT, 60):
        draw.line([(0, y), (WIDTH, y)], fill=c, width=1)


def create_background(output_path, highlight_color=None, theme=None):
    """
    Generate a 1920x1080 decorative background PNG.
    Save to output_path. Returns the absolute path string.
    """
    palette = normalize_theme(theme)
    if highlight_color is None:
        highlight_color = palette["highlight"]

    hl_rgb = _hex_to_rgb(highlight_color)
    bg_rgb = _hex_to_rgb(palette["background"])

    img = Image.new("RGB", (WIDTH, HEIGHT), bg_rgb)

    draw = ImageDraw.Draw(img)
    _draw_grid(draw, palette["grid"])

    # Restrained theme accent and a subtle right-side animation panel.
    draw.rectangle([(0, 0), (WIDTH, 4)], fill=hl_rgb)
    panel = _hex_to_rgb(palette["panel"])
    draw.rounded_rectangle(
        [(WIDTH // 2 - 20, 105), (WIDTH - 75, HEIGHT - 75)],
        radius=28,
        outline=panel,
        width=2,
    )

    # Left accent bar
    # draw.rectangle([(60, 200), (66, 280)], fill=hl_rgb)

    # Bottom-right corner dots
    dot_x = WIDTH - 120
    for i in range(3):
        draw.ellipse(
            [(dot_x, HEIGHT - 60 + i * 2), (dot_x + 8, HEIGHT - 52 + i * 2)],
            fill=hl_rgb,
        )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))
    return str(out)
