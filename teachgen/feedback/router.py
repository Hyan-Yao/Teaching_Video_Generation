"""Critique -> targeted revision of the LessonPlan.

The router turns reviewer feedback into the smallest change that fixes it, so the
next loop iteration re-renders only what's broken instead of rebuilding the whole
video. It mutates the plan and returns the set of segment ids that must be redone;
the pipeline reuses cached audio/visuals for everything else.
"""

from __future__ import annotations

from ..providers.base import Provider
from ..schema import Critique, LessonPlan, Modality, ReviewResult, Segment


def apply(provider: Provider, plan: LessonPlan, review: ReviewResult) -> set[str]:
    """Apply actionable critiques in place. Returns segment ids needing re-render."""
    dirty_full, dirty_visual = apply_with_cache_hints(provider, plan, review)
    return dirty_full | dirty_visual


def apply_with_cache_hints(
    provider: Provider,
    plan: LessonPlan,
    review: ReviewResult,
) -> tuple[set[str], set[str]]:
    """Apply critiques in place. Returns (audio+visual dirty, visual-only dirty)."""
    dirty_full: set[str] = set()
    dirty_visual: set[str] = set()
    by_id = {s.id: s for s in plan.segments}

    for c in review.critiques:
        if c.severity == "minor":
            continue  # don't burn another render round on cosmetics
        seg = by_id.get(c.segment_id) if c.segment_id else None
        if seg is None:
            continue  # whole-video notes are advisory; nothing targeted to redo

        if c.fix_action == "rewrite_narration":
            seg.narration = _rewrite_narration(provider, plan, seg, c)
            dirty_full.add(seg.id)  # audio and timing-driven visual must regen
        elif c.fix_action == "change_modality":
            original_modality = seg.modality
            seg.modality = _pick_alternative(seg.modality, c)
            seg.visual_brief = _rewrite_brief(
                provider,
                plan,
                seg,
                c,
                original_modality=original_modality,
            )
            dirty_visual.add(seg.id)
        elif c.fix_action == "re_render":
            seg.visual_brief = _rewrite_brief(provider, plan, seg, c)
            if seg.modality == Modality.ANIMATION:
                seg.hints["animation_critic_repair_attempts"] = (
                    int(seg.hints.get("animation_critic_repair_attempts", 0)) + 1
                )
            dirty_visual.add(seg.id)
        elif c.fix_action == "adjust_timing":
            # Timing-only: nudge the target and let the compositor refit. Cheap path —
            # mark dirty only for animation, whose length is intrinsic.
            if seg.modality == Modality.ANIMATION:
                dirty_visual.add(seg.id)

    dirty_visual -= dirty_full
    return dirty_full, dirty_visual


def _pick_alternative(current: Modality, critique: Critique | None = None) -> Modality:
    """Choose a replacement that retains any timing capability the repair needs."""
    if (
        current in {Modality.CONCEPT_IMAGE, Modality.SLIDE}
        and critique is not None
        and critique.repair_scope == "timing"
    ):
        return Modality.ANIMATION
    ladder = {
        Modality.ANIMATION: Modality.CONCEPT_IMAGE,
        Modality.CONCEPT_IMAGE: Modality.SLIDE,
        Modality.SLIDE: Modality.CONCEPT_IMAGE,
    }
    return ladder[current]


def _rewrite_narration(provider: Provider, plan: LessonPlan, seg: Segment, c: Critique) -> str:
    return provider.chat(
        "Rewrite only the target segment narration to fix the critique.\n\n"
        f"{_lesson_context(plan)}\n\n"
        f"{_segment_context(plan, seg)}\n\n"
        "Critique to fix:\n"
        f"Issue: {c.issue}\n"
        f"Detail: {c.detail}\n\n"
        "Non-negotiables:\n"
        "- Preserve the segment's role in the lesson sequence.\n"
        "- Preserve required concepts, examples, comparisons, labels, equations, and terms.\n"
        "- Do not introduce unrelated new content.\n"
        "- Keep the narration aligned to the learning goal, objectives, key learning points, "
        "Bloom levels, ICAP level, and student persona.\n"
        "- Keep it 2-5 spoken sentences and in the same lesson order.\n"
        "- Return only the revised narration text.",
        max_tokens=400,
        model=_refinement_model(provider),
    )


def _rewrite_brief(
    provider: Provider,
    plan: LessonPlan,
    seg: Segment,
    c: Critique,
    *,
    original_modality: Modality | None = None,
) -> str:
    original = original_modality or seg.modality
    brief = provider.chat(
        "Rewrite only the target segment visual brief to fix the critique.\n\n"
        f"{_lesson_context(plan)}\n\n"
        f"{_segment_context(plan, seg, original_modality=original_modality)}\n\n"
        "Critique to fix:\n"
        f"Issue: {c.issue}\n"
        f"Detail: {c.detail}\n\n"
        f"Original renderer/modality: {original.value}\n"
        f"Target renderer/modality: {seg.modality.value}\n\n"
        "Design goal:\n"
        "Redesign the visual so it supports the narration clearly at a glance. "
        "The narration is the source of the full instructional explanation; the "
        "visual should make the main idea easier to understand, not restate every "
        "detail as on-screen text.\n\n"
        "Examples of good visual repair:\n"
        "- ASCII repair: If narration says \"ASCII maps A to decimal 65, stored as "
        "binary 01000001,\" a bad repair preserves a full ASCII table with tiny "
        "cells. A good repair shows one large pipeline: A -> 65 -> 01000001, with "
        "one 8-bit register and a short caption such as \"characters are stored as "
        "bytes.\"\n"
        "- Phishing repair: If narration explains phishing red flags, a bad repair "
        "preserves three full email bodies with tiny text. A good repair shows one "
        "large readable email card with three highlighted cues: sender, urgency, "
        "and suspicious link. The narration carries the category details.\n\n"
        "Non-negotiables:\n"
        "- Preserve the required concept the segment must teach, using the narration, "
        "rationale, learning goal, objectives, and key learning points as the source of truth.\n"
        "- Treat the current visual brief as a starting point, not a contract. Simplify, "
        "replace, or omit visual implementation details that caused clutter, tiny text, "
        "cramping, unreadability, or weak narration-visual alignment.\n"
        "- Do not remove concepts that are required by the target segment narration, "
        "learning objectives, or key learning points.\n"
        "- Prefer icons, diagrams, contrast pairs, pipelines, callouts, and simple labels "
        "over dense tables, full bullet lists, full email bodies, code snippets, long "
        "filenames, or many tiny labels.\n"
        "- Preserve the segment's role in the lesson sequence and its connection to nearby segments.\n"
        "- Do not add unrelated concepts or remove key learning points.\n"
        "- Fix the visual production problem by changing layout, sequencing, density, labels, "
        "or modality-specific rendering instructions.\n"
        "- If the target renderer is animation, keep the animation simple: few objects, large "
        "readable text, no cramped bullet lists, no overlapping labels, and clear step-by-step motion.\n"
        "- If the original renderer was animation and the target renderer is concept_image or slide, "
        "convert the same instructional idea into a simpler static visual. Do not try to describe "
        "motion, frame-by-frame animation, interactive widgets, or code-like behavior.\n"
        "- If the target renderer is concept_image or slide, prefer a clean static layout with "
        "large readable labels, reduced visual density, and one clear visual idea.\n"
        "- If the target renderer is concept_image or slide, do not use these words or ideas: "
        "animate, animation, animated, transition, move, motion, frame-by-frame, timeline, sequence, "
        "interactive widget, or step-by-step motion.\n"
        "- Return only the revised visual brief.",
        max_tokens=650,
        model=_refinement_model(provider),
    )
    if seg.modality in {Modality.CONCEPT_IMAGE, Modality.SLIDE} and _has_static_forbidden_terms(brief):
        brief = provider.chat(
            "Revise this visual brief so it is a static visual brief only.\n\n"
            f"Target renderer/modality: {seg.modality.value}\n"
            f"Segment narration to preserve: {seg.narration}\n\n"
            f"Current brief:\n{brief}\n\n"
            "Rules:\n"
            "- Preserve the required instructional concept from the narration.\n"
            "- Simplify or remove visual details that cause clutter, tiny text, cramped layout, "
            "or unreadability.\n"
            "- Use the visual as support for the narration, not a full transcript of the narration.\n"
            "- Describe a static layout only.\n"
            "- Do not use animation words such as animate, animation, animated, transition, move, "
            "motion, frame-by-frame, timeline, sequence, interactive widget, or step-by-step motion.\n"
            "- Return only the revised static visual brief.",
            max_tokens=500,
            model=_refinement_model(provider),
        )
    return brief


def _lesson_context(plan: LessonPlan) -> str:
    objectives = "\n".join(f"- {objective}" for objective in plan.objectives) or "- none"
    key_points = "\n".join(f"- {point}" for point in plan.key_learning_points) or "- none"
    segment_order = "\n".join(
        f"- {segment.id}: {segment.title} ({segment.modality.value})"
        for segment in plan.segments
    )
    return (
        "Lesson context:\n"
        f"Topic: {plan.topic}\n"
        f"Student persona: {plan.audience}\n"
        f"Learning goal: {plan.learning_goal or 'not provided'}\n"
        f"Bloom levels: {', '.join(plan.bloom_levels) or 'not provided'}\n"
        f"ICAP level: {plan.icap_level or 'not provided'}\n"
        f"Learning objectives:\n{objectives}\n"
        f"Key learning points:\n{key_points}\n"
        f"Segment order:\n{segment_order}"
    )


def _segment_context(
    plan: LessonPlan,
    seg: Segment,
    *,
    original_modality: Modality | None = None,
) -> str:
    index = next((i for i, segment in enumerate(plan.segments) if segment.id == seg.id), None)
    previous_segment = plan.segments[index - 1] if index is not None and index > 0 else None
    next_segment = (
        plan.segments[index + 1]
        if index is not None and index + 1 < len(plan.segments)
        else None
    )
    previous_text = (
        f"{previous_segment.id}: {previous_segment.title}"
        if previous_segment is not None
        else "none"
    )
    next_text = f"{next_segment.id}: {next_segment.title}" if next_segment is not None else "none"
    return (
        "Target segment:\n"
        f"ID: {seg.id}\n"
        f"Title: {seg.title}\n"
        f"Previous segment: {previous_text}\n"
        f"Next segment: {next_text}\n"
        f"Original modality: {(original_modality or seg.modality).value}\n"
        f"Current target modality: {seg.modality.value}\n"
        f"Target duration: {seg.target_seconds}\n"
        f"Rationale: {seg.rationale}\n"
        f"Narration: {seg.narration}\n"
        f"Current visual brief: {seg.visual_brief}"
    )


def _has_static_forbidden_terms(text: str) -> bool:
    lowered = text.casefold()
    forbidden = [
        r"\banimate\b",
        r"\banimation\b",
        r"\banimated\b",
        r"\btransition\b",
        r"\bmove\b",
        r"\bmotion\b",
        r"\bframe-by-frame\b",
        r"\btimeline\b",
        r"\binteractive widget\b",
        r"\bstep-by-step motion\b",
    ]
    import re

    return any(re.search(pattern, lowered) for pattern in forbidden)


def _refinement_model(provider: Provider) -> str | None:
    models = getattr(getattr(provider, "cfg", None), "models", None)
    return getattr(models, "refinement_text", None)
