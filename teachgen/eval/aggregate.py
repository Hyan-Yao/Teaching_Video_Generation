from teachgen.eval.models import EvaluationRequest, EvaluationResult, GraderOutput, LectureInference


EXPECTED_METRICS = {
    "Learning Objective Coverage",
    "Content Accuracy",
    "Visual Quality",
    "Multimedia Learning Design",
    "Logic",
    "Learning Adaptation",
    "Bloom Alignment",
    "ICAP Alignment",
}


def aggregate_evaluation(request: EvaluationRequest, 
                         lecture_inference: LectureInference, 
                         grader_outputs: list[GraderOutput]) -> EvaluationResult:
    scores = [score for grader_output in grader_outputs for score in grader_output.scores]

    if not grader_outputs:
        raise ValueError("At least one grader output is required")
    
    metric_names = [score.metric for score in scores]
    metric_name_set = set(metric_names)

    missing_metrics = EXPECTED_METRICS - metric_name_set
    unexpected_metrics = metric_name_set - EXPECTED_METRICS
    duplicate_metrics = { 
        metric
        for metric in metric_names
        if metric_names.count(metric) > 1
    }

    if missing_metrics:
        raise ValueError(f"Missing rubric metrics: {sorted(missing_metrics)}")

    if unexpected_metrics:
        raise ValueError(f"Unexpected rubric metrics: {sorted(unexpected_metrics)}")

    if duplicate_metrics:
        raise ValueError(f"Duplicate rubric metrics: {sorted(duplicate_metrics)}")

    overall_score = sum([score.score for score in scores]) / len(scores)

    summary_lines = [
    f"{grader_output.grader_name}: {grader_output.overall_comments}"
    for grader_output in grader_outputs
    ]
    summary = "\n".join(summary_lines)

    return EvaluationResult(
        request=request,
        lecture_inference=lecture_inference,
        scores=scores,
        overall_score=overall_score,
        summary=summary
    )
