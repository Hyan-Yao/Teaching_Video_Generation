from __future__ import annotations

import re

from teachgen.feedback.plan_prompts import PLAN_REFINER_SYSTEM, PLAN_REFINER_TEMPLATE
from teachgen.schema import LessonPlan, PlanEvaluationResult, TeachingRequest


def _refinement_model(provider) -> str | None:
    models = getattr(getattr(provider, "cfg", None), "models", None)
    return getattr(models, "refinement_text", None)


def refine_plan(
    provider,
    request: TeachingRequest,
    plan: LessonPlan,
    evaluation: PlanEvaluationResult,
    *,
    mode: str = "inner",
    allowed_segment_ids: set[str] | None = None,
) -> LessonPlan:
    if allowed_segment_ids is None:
        allowed_segment_ids = {segment.id for segment in plan.segments}
    timing_split_allowed = _timing_split_is_explicit(evaluation)
    constraint_text = (
        f"Refinement mode: {mode}.\n"
        f"Segments explicitly affected by evidence: {', '.join(sorted(allowed_segment_ids))}.\n"
        f"Maximum total narration growth: {'15%' if mode == 'outer' else '20%'}.\n"
        f"Maximum added segments: {'1 only for an explicit prompt/reveal timing split' if mode == 'outer' else '1'}.\n"
        f"Prompt/reveal split allowed: {timing_split_allowed}.\n"
        f"Prompt/reveal split required in this repair: {mode == 'outer' and timing_split_allowed}."
    )
    prompt = PLAN_REFINER_TEMPLATE.format(
        request_json=request.model_dump_json(indent=2),
        plan_json=plan.model_dump_json(indent=2),
        evaluation_json=evaluation.model_dump_json(indent=2),
        constraints=constraint_text,
    )
    retry_feedback = ""
    for _attempt in range(2):
        candidate = provider.chat_json(
            prompt + retry_feedback,
            LessonPlan,
            system=PLAN_REFINER_SYSTEM,
            max_tokens=6000,
            temperature=0,
            seed=12345,
            model=_refinement_model(provider),
        )
        violations = _validate_refinement(
            plan,
            candidate,
            mode=mode,
            allowed_segment_ids=allowed_segment_ids,
            timing_split_allowed=timing_split_allowed,
        )
        if not violations:
            _recalculate_changed_durations(plan, candidate)
            return candidate
        retry_feedback = (
            "\n\nYour proposed plan violated these hard constraints:\n- "
            + "\n- ".join(violations)
            + "\nReturn a corrected complete plan."
        )
    return plan


def _validate_refinement(
    before: LessonPlan,
    after: LessonPlan,
    *,
    mode: str,
    allowed_segment_ids: set[str],
    timing_split_allowed: bool,
) -> list[str]:
    violations: list[str] = []
    before_ids = [segment.id for segment in before.segments]
    after_ids = [segment.id for segment in after.segments]
    before_by_id = {segment.id: segment for segment in before.segments}
    after_by_id = {segment.id: segment for segment in after.segments}
    max_growth = 0.15 if mode == "outer" else 0.20
    before_words = sum(len(segment.narration.split()) for segment in before.segments)
    after_words = sum(len(segment.narration.split()) for segment in after.segments)
    if after_words > max(1, int(before_words * (1 + max_growth))):
        violations.append(
            f"total narration grew from {before_words} to {after_words} words"
        )

    added_ids = [segment_id for segment_id in after_ids if segment_id not in before_by_id]
    if len(set(after_ids)) != len(after_ids):
        violations.append("segment IDs are not unique")
    if any(not re.fullmatch(r"seg[0-9]+", segment_id) for segment_id in added_ids):
        violations.append("new segment IDs must use the stable segN format")
    if len(added_ids) > 1:
        violations.append("more than one segment was added")
    if mode == "outer" and added_ids and not timing_split_allowed:
        violations.append("a segment was added without explicit premature-reveal evidence")
    if mode == "outer" and timing_split_allowed and not added_ids:
        violations.append(
            "explicit premature-reveal evidence requires one real prompt/reveal segment split"
        )
    preserved_order = [segment_id for segment_id in after_ids if segment_id in before_by_id]
    if preserved_order != before_ids:
        violations.append("existing segment IDs were removed or reordered")

    if mode == "outer" and timing_split_allowed and added_ids:
        added_index = after_ids.index(added_ids[0])
        preceding_id = after_ids[added_index - 1] if added_index > 0 else None
        if preceding_id not in allowed_segment_ids:
            violations.append(
                "the reveal segment must immediately follow an explicitly affected prompt segment"
            )

    for segment_id in before_ids:
        old = before_by_id[segment_id]
        new = after_by_id.get(segment_id)
        if new is None:
            continue
        if mode == "outer" and segment_id not in allowed_segment_ids and new != old:
            violations.append(f"unaffected segment {segment_id} was edited")
        if mode == "outer" and new.modality != old.modality:
            violations.append(f"plan repair changed modality for {segment_id}")
        allow_prompt_visual_change = (
            timing_split_allowed and bool(added_ids) and segment_id in allowed_segment_ids
        )
        if mode == "outer" and new.visual_brief != old.visual_brief and not allow_prompt_visual_change:
            violations.append(f"plan repair changed visual contract for {segment_id}")
        if mode == "outer" and allow_prompt_visual_change and new.visual_brief == old.visual_brief:
            violations.append(
                f"prompt segment {segment_id} kept its answer-revealing visual brief"
            )
        if _has_unfulfilled_promise(new.narration):
            violations.append(f"{segment_id} promises content without delivering it")
    return violations


def _timing_split_is_explicit(evaluation: PlanEvaluationResult) -> bool:
    text = " ".join(
        [evaluation.summary]
        + [score.rationale for score in evaluation.scores]
        + [item for score in evaluation.scores for item in score.evidence]
    ).casefold()
    return any(
        phrase in text
        for phrase in ("premature answer", "answer exposure", "revealed too early", "prompt/reveal")
    )


def _has_unfulfilled_promise(narration: str) -> bool:
    pattern = re.compile(
        r"\b(?:we will|we'll|let(?:'s| us))\s+(?:explain|demonstrate|explore|calculate|show|analy[sz]e)\b",
        re.I,
    )
    for match in pattern.finditer(narration):
        if len(narration[match.end():].split()) < 8:
            return True
    return False


def _recalculate_changed_durations(before: LessonPlan, after: LessonPlan) -> None:
    before_by_id = {segment.id: segment for segment in before.segments}
    for segment in after.segments:
        previous = before_by_id.get(segment.id)
        if previous is None or segment.narration != previous.narration:
            segment.target_seconds = round(max(1.0, len(segment.narration.split()) / 2.5), 1)
