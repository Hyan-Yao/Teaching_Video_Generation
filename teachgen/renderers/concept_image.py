"""`concept_image` renderer — wraps teachgen's concept_image.py two-step flow.

We reuse concept_image's exact prompt-engineering (a GPT writes a rich English
image prompt) but route both calls through teachgen's Provider so the whole system
still needs only one key. Static output: kind="image".
"""

from __future__ import annotations

from ..schema import Modality, Segment, VisualAsset
from .base import RenderContext
from .. import concept_image as ci  # the standalone helper, now a teachgen module


class ConceptImageRenderer:
    modality = Modality.CONCEPT_IMAGE

    def render(self, seg: Segment, ctx: RenderContext) -> VisualAsset:
        # Step 1: expand the brief into a detailed English image prompt.
        image_prompt = ctx.provider.chat(
            ci.build_user_brief(seg.visual_brief, ctx.cfg.audience, ""),
            system=ci.PROMPT_SYSTEM,
            max_tokens=800,
        )
        # Step 2: render it. concept_image targets 3:2 landscape for slide framing.
        png = ctx.provider.image(image_prompt, size="1536x1024", quality="high")

        png_path = ctx.out_dir / f"{seg.id}.png"
        png_path.write_bytes(png)
        return VisualAsset(segment_id=seg.id, kind="image", path=str(png_path))
