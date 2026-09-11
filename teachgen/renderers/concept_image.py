"""`concept_image` renderer — wraps teachgen's concept_image.py two-step flow.

We reuse concept_image's exact prompt-engineering (a GPT writes a rich English
image prompt) but route both calls through teachgen's Provider so the whole system
still needs only one key. Static output: kind="image".
"""

from __future__ import annotations

import json
import re

from ..schema import ConceptImageValidation, Modality, Segment, VisualAsset
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
        debug_dir = ctx.cfg.run_dir / "image_debug" / seg.id / f"round_{ctx.render_round}"
        debug_dir.mkdir(parents=True, exist_ok=True)
        feedback = ""
        validation = ConceptImageValidation(has_major_issues=True, severity="major")
        png = b""
        image_prompt = ""
        for attempt in range(ctx.cfg.concept_image_validation_retries + 1):
            static_timing_rule = (
                "\n\nNARRATION CONTEXT:\n"
                f"{seg.narration}\n\n"
                "STATIC TIMING RULE: This one image remains visible for the entire "
                "segment. If the narration explicitly asks the learner to pause, "
                "calculate, predict, choose, or answer and supplies the solution later, "
                "show only the problem setup. Do not place the answer, completed "
                "calculation, highlighted result, or solution state anywhere in the "
                "image. The spoken narration will provide the later answer."
            )
            image_prompt = ctx.provider.chat(
                ci.build_user_brief(seg.visual_brief, ctx.cfg.audience, _STYLE)
                + static_timing_rule
                + (f"\n\nPrevious image validator feedback to correct:\n{feedback}" if feedback else ""),
                system=ci.PROMPT_SYSTEM,
                max_tokens=800,
                model=ctx.cfg.models.visual_text,
            )
            png = ctx.provider.image(image_prompt, size="1536x1024", quality="high")
            attempt_path = debug_dir / f"attempt_{attempt + 1}.png"
            attempt_path.write_bytes(png)
            (debug_dir / f"prompt_{attempt + 1}.txt").write_text(image_prompt, encoding="utf-8")
            try:
                validation = _validate_image(seg, ctx, png)
            except Exception as exc:
                validation = ConceptImageValidation(
                    has_major_issues=True,
                    severity="blocker",
                    issues=[f"validator failure: {type(exc).__name__}: {exc}"],
                    summary="The generated image could not be validated safely.",
                )
            (debug_dir / f"validation_{attempt + 1}.json").write_text(
                validation.model_dump_json(indent=2), encoding="utf-8"
            )
            if not validation.has_major_issues:
                break
            feedback = "\n".join(validation.issues) or validation.summary

        if validation.has_major_issues:
            raise RuntimeError(
                "concept image failed factual/readability validation after one retry: "
                + (validation.summary or "; ".join(validation.issues))
            )
        png_path = ctx.out_dir / f"{seg.id}.png"
        png_path.write_bytes(png)
        return VisualAsset(
            segment_id=seg.id,
            kind="image",
            path=str(png_path),
            intended_modality=seg.modality,
            rendered_modality=Modality.CONCEPT_IMAGE,
            validation_status=(
                "passed" if validation.severity == "minor" and not validation.issues
                else "passed_with_minor_issues"
            ),
        )


_VALIDATOR_SYSTEM = """\
You validate one generated educational concept image. Report only observable,
meaningful defects. Minor style preferences are allowed. A major issue is malformed
or unreadable text, a wrong equation/label/count/mapping, a contradiction with the
narration, or clutter that prevents understanding. Return only JSON matching the
requested schema. Do not require the image to contain every narration detail.
Because the image remains visible for the full segment, it is also a major issue if
the image displays the solution to an explicit learner task before narration provides
that solution. Prompt-only static images must contain only the problem setup.
"""


def _validate_image(seg: Segment, ctx: RenderContext, png: bytes) -> ConceptImageValidation:
    plan = ctx.plan
    objectives = plan.objectives if plan else []
    key_points = plan.key_learning_points if plan else ctx.cfg.request.course.key_learning_points
    prompt = (
        f"Segment title: {seg.title}\n"
        f"Narration (instructional truth): {seg.narration}\n"
        f"Visual brief: {seg.visual_brief}\n"
        f"Lesson-wide objectives (context): {json.dumps(objectives, ensure_ascii=False)}\n"
        f"Lesson-wide key points (context): {json.dumps(key_points, ensure_ascii=False)}\n\n"
        "Check exact facts, equations, labels, object counts, mappings, readability, "
        "and clutter. Do not penalize omitted narration details when the image still "
        "supports the central concept. Only enforce objectives/key points relevant to "
        "this target segment; one image need not depict the whole lesson. If narration "
        "contains an explicit learner task followed later by its answer, reject the "
        "image when that answer or completed solution is already visible."
    )
    raw = ctx.provider.vision(
        prompt,
        [png],
        system=_VALIDATOR_SYSTEM,
        max_tokens=1200,
        model=ctx.cfg.models.vision,
    )
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    try:
        return ConceptImageValidation.model_validate_json(cleaned)
    except Exception as exc:
        raise RuntimeError(f"concept image validator returned invalid JSON: {exc}") from exc
