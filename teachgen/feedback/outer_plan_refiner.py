from teachgen.schema import TeachingRequest, LessonPlan, OuterRepairDecision, PlanEvaluationResult, ReviewResult
from teachgen.eval.models import EvaluationResult
from teachgen.providers.base import Provider
from .outer_repair_decider import outer_decision_to_plan_evaluation, decide_outer_repair
from .lesson_plan_refiner import refine_plan



def refine_from_video_evaluation(
    provider: Provider,
    request: TeachingRequest,
    plan: LessonPlan,
    evaluation: EvaluationResult,
    *,
    threshold: int = 3,
    repair_mode: str = "auto",
    review: ReviewResult | None = None,
) -> tuple[LessonPlan, OuterRepairDecision, PlanEvaluationResult | None]:
    
    decision = decide_outer_repair(
        evaluation,
        threshold=threshold,
        repair_mode=repair_mode,
        review=review,
    )

    if decision.repair_type != "plan":
        return plan, decision, None
    
    plan_eval = outer_decision_to_plan_evaluation(decision, evaluation)

    affected = set(decision.affected_segments)
    global_structural = any(
        phrase in " ".join(decision.evidence).casefold()
        for phrase in ("whole plan", "overall lesson", "throughout the lesson", "global structure")
    )
    revised_plan = refine_plan(
        provider,
        request,
        plan,
        plan_eval,
        mode="outer",
        allowed_segment_ids=None if global_structural else affected,
    )
    revised_plan = preserve_outer_visual_contract(plan, revised_plan)

    return revised_plan, decision, plan_eval


def preserve_outer_visual_contract(
    original: LessonPlan,
    revised: LessonPlan,
) -> LessonPlan:
    """Keep plan-level repair from silently redesigning existing visuals."""
    original_by_id = {segment.id: segment for segment in original.segments}
    for segment in revised.segments:
        previous = original_by_id.get(segment.id)
        if previous is None:
            continue
        segment.modality = previous.modality
        segment.visual_brief = previous.visual_brief
    return revised
