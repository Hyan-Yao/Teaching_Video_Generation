"""Visual themes shared by every TeachGen renderer.

The canonical Approach 1 palette is the only supported visual style.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ThemeConfig:
    """Serializable colors and renderer-specific style behavior for one run."""

    name: str
    background: str
    primary: str
    secondary: str
    highlight: str
    body: str
    panel: str
    grid: str

    def to_code2video(self) -> dict[str, str]:
        """Return the animation palette passed through Code2Video's RunConfig."""
        return {
            "name": self.name,
            "background": self.background,
            "primary": self.primary,
            "secondary": self.secondary,
            "highlight": self.highlight,
            "body": self.body,
            "panel": self.panel,
            "grid": self.grid,
        }

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def concept_style(self) -> str:
        return (
            "clean modern academic infographic using this exact canonical palette: "
            f"background {self.background}, primary text and structure {self.primary}, "
            f"secondary accents {self.secondary}, highlights {self.highlight}, body text "
            f"{self.body}, and subtle panels or grid lines {self.panel}. Use no pure black "
            "or pure white and introduce no unrelated palette colors"
        )

    def concept_constraint(self) -> str:
        """Final image-model constraint; appended after model-expanded content."""
        return (
            f"FINAL HOUSE-STYLE CONSTRAINT: Use background {self.background}, primary "
            f"text and structure {self.primary}, secondary accents {self.secondary}, "
            f"highlights {self.highlight}, body text {self.body}, and subtle grids/panels "
            f"{self.panel}. Do not use pure black, pure white, or unrelated palette "
            "colors. Flat vector academic infographic; no photorealism, clutter, or "
            "watermark."
        )


SHARED_LIGHT_THEME = ThemeConfig(
    name="shared-light",
    background="#F7F6F0",
    primary="#1B3A6B",
    secondary="#0F766E",
    highlight="#9A6700",
    body="#2A2A2A",
    panel="#E4E0D5",
    grid="#E4E0D5",
)
