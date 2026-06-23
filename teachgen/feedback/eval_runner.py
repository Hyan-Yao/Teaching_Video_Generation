from __future__ import annotations
from pathlib import Path
from teachgen.eval.models import EvaluationRequest
from ..schema import LessonPlan


def build_eval_request(plan: LessonPlan, video_path: Path | str) -> EvaluationRequest:
    """Convert a generated lesson plan and video path into evaluator metadata."""
    return EvaluationRequest(
        video_path=str(video_path),
        course_requirement=_format_course_requirement(plan),
        learning_objectives=plan.objectives,
        student_persona=plan.audience,
        intended_bloom=None,
    )


def _format_course_requirement(plan: LessonPlan) -> str:
    lines = [
        f"Topic: {plan.topic}",
        f"Audience: {plan.audience}",
        "",
        "Learning objectives:",
    ]
    lines.extend(f"- {objective}" for objective in plan.objectives)
    lines.extend(["", "Expected lesson structure:"])

    for index, segment in enumerate(plan.segments, start=1):
        lines.extend(
            [
                f"{index}. {segment.id}: {segment.title}",
                f"   Modality: {segment.modality.value}",
                f"   Narration: {segment.narration}",
                f"   Visual brief: {segment.visual_brief}",
            ]
        )
        if segment.rationale:
            lines.append(f"   Rationale: {segment.rationale}")
        if segment.target_seconds is not None:
            lines.append(f"   Target duration: {segment.target_seconds:.1f} seconds")

    return "\n".join(lines)


def run_lesson_evaluation(
    plan: LessonPlan,
    video_path: Path | str,
    output_dir: Path,
    chunk_seconds: float = 900,
) -> Path:
    from teachgen.eval.run_evaluation import run_evaluation

    request = build_eval_request(plan, video_path)
    return run_evaluation(
        request=request,
        output_dir=output_dir,
        chunk_seconds=chunk_seconds,
    )
