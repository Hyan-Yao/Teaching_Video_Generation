"""
Generate decorative background PNGs for Manim teaching scenes.
Produces visual elements only (grid, glow, accent bars) — no text.
Manim handles all text and animation rendering on top.
"""

from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path

COLORS = {
    "highlight": "#FFD166",
    "cyan": "#00F5D4",
    "pink": "#F72585",
    "background": "#0a0a0f",
    "grid": "#1a1a25",
}

WIDTH, HEIGHT = 1920, 1080


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def _draw_grid(draw):
    # Slightly brighter than background (#0a0a0f) to be subtly visible
    c = (22, 22, 32)
    for x in range(0, WIDTH, 60):
        draw.line([(x, 0), (x, HEIGHT)], fill=c, width=1)
    for y in range(0, HEIGHT, 60):
        draw.line([(0, y), (WIDTH, y)], fill=c, width=1)


def create_background(output_path, highlight_color=None):
    """
    Generate a 1920x1080 decorative background PNG.
    Save to output_path. Returns the absolute path string.
    """
    if highlight_color is None:
        highlight_color = COLORS["highlight"]

    hl_rgb = _hex_to_rgb(highlight_color)
    bg_rgb = _hex_to_rgb(COLORS["background"])

    img = Image.new("RGB", (WIDTH, HEIGHT), bg_rgb)

    # Gaussian glow: draw a center spot then blur it
    glow_layer = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    cx, cy = WIDTH // 2, HEIGHT // 2
    gd.ellipse([(cx - 80, cy - 80), (cx + 80, cy + 80)], fill=hl_rgb)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=120))
    img = Image.blend(img, glow_layer, alpha=0.55)

    draw = ImageDraw.Draw(img)
    _draw_grid(draw)

    # Top accent bar
    draw.rectangle([(0, 0), (WIDTH, 4)], fill=hl_rgb)

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
