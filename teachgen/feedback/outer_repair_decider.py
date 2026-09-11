from teachgen.eval.models import EvaluationResult
from teachgen.schema import OuterRepairDecision, PlanEvaluationResult, PlanMetricScore, ReviewResult

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

_SEVERITY_WEIGHT = {"minor": 1, "major": 3, "blocker": 5}


def _repair_priority(critiques) -> tuple[int, int, int]:
    """Rank one repair class by blocker/major urgency before finding count."""
    blockers = sum(item.severity == "blocker" for item in critiques)
    majors = sum(item.severity == "major" for item in critiques)
    weighted = sum(_SEVERITY_WEIGHT.get(item.severity, 1) for item in critiques)
    return blockers, majors, weighted


def _format_evidence_item(item) -> str:
    return (
        f"{item.start_time_seconds:.1f}-{item.end_time_seconds:.1f}s: "
        f"{item.description}"
    )


def decide_outer_repair(
    evaluation: EvaluationResult,
    threshold: int = 3,
    repair_mode: str = "auto",
    review: ReviewResult | None = None,
) -> OuterRepairDecision:
    if repair_mode not in {"auto", "plan_only", "asset_only"}:
        raise ValueError(f"unknown outer repair mode: {repair_mode}")

    if review is not None:
        plan_critiques = [item for item in review.critiques if item.repair_scope == "plan"]
        asset_critiques = [
            item for item in review.critiques if item.repair_scope in {"asset", "timing"}
        ]
        selected = []
        repair_type = "none"
        plan_allowed = repair_mode != "asset_only" and bool(plan_critiques)
        asset_allowed = repair_mode != "plan_only" and bool(asset_critiques)
        if plan_allowed and asset_allowed:
            plan_priority = _repair_priority(plan_critiques)
            asset_priority = _repair_priority(asset_critiques)
            if asset_priority > plan_priority:
                repair_type, selected = "asset", asset_critiques
            else:
                repair_type, selected = "plan", plan_critiques
        elif plan_allowed:
            repair_type, selected = "plan", plan_critiques
        elif asset_allowed:
            repair_type, selected = "asset", asset_critiques
        if repair_type == "none":
            return OuterRepairDecision(
                repair_type="none",
                reason="No actionable cause-classified repair candidates were found.",
            )
        metrics = list(dict.fromkeys(item.source_metric for item in selected if item.source_metric))
        segments = list(dict.fromkeys(item.segment_id for item in selected if item.segment_id))
        return OuterRepairDecision(
            repair_type=repair_type,
            reason=(
                f"{repair_type.title()} repair selected from the observed cause of "
                f"{len(selected)} actionable evaluator finding(s)."
            ),
            priority_metrics=metrics,
            affected_segments=segments,
            evidence=[item.detail or item.issue for item in selected],
        )

    weak_plan_scores = [
        score
        for score in evaluation.scores
        if score.metric in PLAN_LEVEL_METRICS and score.score <= threshold
    ]
    if repair_mode != "asset_only" and weak_plan_scores:
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

    if repair_mode == "plan_only":
        return OuterRepairDecision(
            repair_type="none",
            reason=(
                f"No plan-level metric was <= {threshold}; asset repairs are disabled "
                "because outer_repair_mode=plan_only."
            ),
        )

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
                rationale=f"Cause-routed plan repair for {score.metric}.",
                evidence=decision.evidence or evidence,
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
