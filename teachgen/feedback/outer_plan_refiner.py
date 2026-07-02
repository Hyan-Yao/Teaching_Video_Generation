from teachgen.schema import TeachingRequest, LessonPlan, OuterRepairDecision, PlanEvaluationResult
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
) -> tuple[LessonPlan, OuterRepairDecision, PlanEvaluationResult | None]:
    
    decision = decide_outer_repair(evaluation, threshold=threshold)

    if decision.repair_type != "plan":
        return plan, decision, None
    
    plan_eval = outer_decision_to_plan_evaluation(decision, evaluation)

    revised_plan = refine_plan(
        provider,
        request,
        plan,
        plan_eval
    )

    return revised_plan, decision, plan_eval
