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
            seg.modality = _pick_alternative(seg.modality)
            seg.visual_brief = _rewrite_brief(provider, plan, seg, c)
            dirty_visual.add(seg.id)
        elif c.fix_action == "re_render":
            seg.visual_brief = _rewrite_brief(provider, plan, seg, c)
            dirty_visual.add(seg.id)
        elif c.fix_action == "adjust_timing":
            # Timing-only: nudge the target and let the compositor refit. Cheap path —
            # mark dirty only for animation, whose length is intrinsic.
            if seg.modality == Modality.ANIMATION:
                dirty_visual.add(seg.id)

    dirty_visual -= dirty_full
    return dirty_full, dirty_visual


def _pick_alternative(current: Modality) -> Modality:
    """Conservative fallback ladder when the reviewer says the approach is wrong."""
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
    )


def _rewrite_brief(provider: Provider, plan: LessonPlan, seg: Segment, c: Critique) -> str:
    return provider.chat(
        "Rewrite only the target segment visual brief to fix the critique.\n\n"
        f"{_lesson_context(plan)}\n\n"
        f"{_segment_context(plan, seg)}\n\n"
        "Critique to fix:\n"
        f"Issue: {c.issue}\n"
        f"Detail: {c.detail}\n\n"
        f"Target renderer/modality: {seg.modality.value}\n\n"
        "Non-negotiables:\n"
        "- Preserve all instructional content from the narration and current visual brief unless "
        "that exact element caused the defect.\n"
        "- Preserve required concepts, examples, comparisons, labels, equations, and terms.\n"
        "- Preserve the segment's role in the lesson sequence and its connection to nearby segments.\n"
        "- Do not add unrelated concepts or remove key learning points.\n"
        "- Fix the visual production problem by changing layout, sequencing, density, labels, "
        "or modality-specific rendering instructions.\n"
        "- If the target renderer is animation, keep the animation simple: few objects, large "
        "readable text, no cramped bullet lists, no overlapping labels, and clear step-by-step motion.\n"
        "- If the target renderer is concept_image or slide, prefer a clean static layout with "
        "large labels and one clear visual idea.\n"
        "- Return only the revised visual brief.",
        max_tokens=650,
    )


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


def _segment_context(plan: LessonPlan, seg: Segment) -> str:
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
        f"Current modality: {seg.modality.value}\n"
        f"Target duration: {seg.target_seconds}\n"
        f"Rationale: {seg.rationale}\n"
        f"Narration: {seg.narration}\n"
        f"Current visual brief: {seg.visual_brief}"
    )
