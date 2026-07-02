from teachgen.eval.models import EvaluationResult
from teachgen.schema import OuterRepairDecision, PlanEvaluationResult, PlanMetricScore

PLAN_LEVEL_METRICS = {
    "Learning Objective Coverage",
    "Content Accuracy",
    "Logic",
    "Learning Adaptation",
    "Bloom Alignment",
    "ICAP Alignment",
}

ASSET_LEVEL_METRICS = {
    "Visual Quality",
    "Multimedia Learning Design",
}


def _format_evidence_item(item) -> str:
    return (
        f"{item.start_time_seconds:.1f}-{item.end_time_seconds:.1f}s: "
        f"{item.description}"
    )


def decide_outer_repair(evaluation: EvaluationResult, threshold: int = 3) -> OuterRepairDecision:
    weak_plan_scores = [
        score
        for score in evaluation.scores
        if score.metric in PLAN_LEVEL_METRICS and score.score <= threshold
    ]
    if weak_plan_scores:
        priority_metrics = [score.metric for score in weak_plan_scores]

        evidence = []
        for score in weak_plan_scores:
            evidence.append(f"{score.metric} scored {score.score}: {score.rationale}")

            for item in score.supporting_evidence:
                evidence.append(f"{score.metric} supporting evidence: {_format_evidence_item(item)}")

            for item in score.conflicting_evidence:
                evidence.append(f"{score.metric} conflicting evidence: {_format_evidence_item(item)}")

        return OuterRepairDecision(
            repair_type="plan",
            reason=(
                f"Plan-level repair triggered because these metrics were <= "
                f"{threshold}: {', '.join(priority_metrics)}."
            ),
            priority_metrics=priority_metrics,
            evidence=evidence,
        )

    weak_asset_scores = [
        score
        for score in evaluation.scores
        if score.metric in ASSET_LEVEL_METRICS and score.score <= threshold
    ]

    if not weak_asset_scores:
        return OuterRepairDecision(
            repair_type="none",
            reason=f"No plan-level or asset-level metric was <= {threshold}.",
        )

    priority_metrics = [score.metric for score in weak_asset_scores]

    evidence = []
    for score in weak_asset_scores:
        evidence.append(f"{score.metric} scored {score.score}: {score.rationale}")

        for item in score.supporting_evidence:
            evidence.append(f"{score.metric} supporting evidence: {_format_evidence_item(item)}")

        for item in score.conflicting_evidence:
            evidence.append(f"{score.metric} conflicting evidence: {_format_evidence_item(item)}")

    return OuterRepairDecision(
        repair_type="asset",
        reason=(
            f"Asset-level repair triggered because these metrics were <= "
            f"{threshold}: {', '.join(priority_metrics)}."
        ),
        priority_metrics=priority_metrics,
        evidence=evidence,
    )


def outer_decision_to_plan_evaluation(
    decision: OuterRepairDecision,
    evaluation: EvaluationResult,
) -> PlanEvaluationResult:
    if decision.repair_type != "plan":
        return PlanEvaluationResult(
            overall_score=evaluation.overall_score,
            scores=[],
            summary=decision.reason,
            requires_revision=False,
        )

    priority_metrics = set(decision.priority_metrics)
    selected_scores = [
        score for score in evaluation.scores if score.metric in priority_metrics
    ]

    plan_scores = []
    for score in selected_scores:
        evidence = [f"Video evaluator rationale: {score.rationale}"]

        for item in score.supporting_evidence:
            evidence.append(
                f"Supporting video evidence: {_format_evidence_item(item)}"
            )

        for item in score.conflicting_evidence:
            evidence.append(
                f"Conflicting video evidence: {_format_evidence_item(item)}"
            )

        plan_scores.append(
            PlanMetricScore(
                metric=score.metric,
                score=score.score,
                rationale=score.rationale,
                evidence=evidence,
            )
        )

    overall_score = (
        sum(score.score for score in plan_scores) / len(plan_scores)
        if plan_scores
        else evaluation.overall_score
    )

    return PlanEvaluationResult(
        overall_score=overall_score,
        scores=plan_scores,
        summary=decision.reason,
        requires_revision=bool(plan_scores),
    )
