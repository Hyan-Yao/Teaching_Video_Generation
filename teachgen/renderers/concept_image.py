"""`concept_image` renderer — wraps teachgen's concept_image.py two-step flow.

We reuse concept_image's exact prompt-engineering (a GPT writes a rich English
image prompt) but route both calls through teachgen's Provider so the whole system
still needs only one key. Static output: kind="image".
"""

from __future__ import annotations

from ..schema import Modality, Segment, VisualAsset
from .base import RenderContext
from .. import concept_image as ci  # the standalone helper, now a teachgen module


_STYLE = (
    "clean, uncluttered educational illustration in a modern academic style; "
    "one central visual idea with generous whitespace, not a dense poster; "
    "soft neutral background (cream or light beige); "
    "use at most 3-5 short labels total, each 1-3 words, with no paragraphs, "
    "no long bullet lists, no tiny captions, and no crowded text blocks; "
    "show only the most important objects needed to support the narration; "
    "prefer one simple diagram, comparison, metaphor, or left-to-right flow; "
    "avoid numbered multi-section layouts unless the concept absolutely requires a sequence; "
    "limited color palette: teal accents, gold highlights, dark gray text on cream ground; "
    "large readable labels, clear spacing between objects, simple arrows only when useful; "
    "minimal, elegant, slide-ready, highly readable at a glance"
)


class ConceptImageRenderer:
    modality = Modality.CONCEPT_IMAGE

    def render(self, seg: Segment, ctx: RenderContext) -> VisualAsset:
        # Step 1: expand the brief into a detailed English image prompt.
        image_prompt = ctx.provider.chat(
            ci.build_user_brief(seg.visual_brief, ctx.cfg.audience, _STYLE),
            system=ci.PROMPT_SYSTEM,
            max_tokens=800,
            model=ctx.cfg.models.visual_text,
        )
        # Step 2: render it. concept_image targets 3:2 landscape for slide framing.
        png = ctx.provider.image(image_prompt, size="1536x1024", quality="high")

        png_path = ctx.out_dir / f"{seg.id}.png"
        png_path.write_bytes(png)
        return VisualAsset(segment_id=seg.id, kind="image", path=str(png_path))
