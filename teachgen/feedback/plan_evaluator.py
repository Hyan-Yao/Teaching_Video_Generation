from __future__ import annotations

from teachgen.schema import LessonPlan, PlanEvaluationResult, TeachingRequest
from teachgen.feedback.plan_prompts import PLAN_EVALUATOR_SYSTEM, PLAN_EVALUATOR_TEMPLATE



PLAN_METRICS = [
    "Learning Objective Coverage",
    "Content Accuracy",
    "Multimedia Learning Design",
    "Logic",
    "Learning Adaptation",
    "Bloom Alignment",
    "ICAP Alignment",
]



def evaluate_plan(provider, request: TeachingRequest, plan: LessonPlan) -> PlanEvaluationResult:

    metrics = "\n".join(f"- {metric}" for metric in PLAN_METRICS)
    prompt = PLAN_EVALUATOR_TEMPLATE.format(
            request_json=request.model_dump_json(indent=2),
            plan_json=plan.model_dump_json(indent=2),
            metrics=metrics,
        )

    result = provider.chat_json(
        prompt, 
        PlanEvaluationResult,
        system=PLAN_EVALUATOR_SYSTEM,
        max_tokens = 4000,
        temperature=0,
        seed=12345,
    )

    scores = [score.score for score in result.scores]
    overall_score = sum(scores) / len(scores) if scores else 0.0
    requires_revision = any(score <= 3 for score in scores)

    return result.model_copy(
        update = {
            "overall_score": overall_score,
            "requires_revision": requires_revision
        }
    )
