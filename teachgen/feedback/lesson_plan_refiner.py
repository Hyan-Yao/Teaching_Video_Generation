from __future__ import annotations

from teachgen.feedback.plan_prompts import PLAN_REFINER_SYSTEM, PLAN_REFINER_TEMPLATE
from teachgen.schema import LessonPlan, PlanEvaluationResult, TeachingRequest


def refine_plan(
    provider,
    request: TeachingRequest,
    plan: LessonPlan,
    evaluation: PlanEvaluationResult,
) -> LessonPlan:
    prompt = PLAN_REFINER_TEMPLATE.format(
        request_json=request.model_dump_json(indent=2),
        plan_json=plan.model_dump_json(indent=2),
        evaluation_json=evaluation.model_dump_json(indent=2),
    )

    return provider.chat_json(
        prompt,
        LessonPlan,
        system=PLAN_REFINER_SYSTEM,
        max_tokens=6000,
        temperature=0,
        seed=12345,
    )