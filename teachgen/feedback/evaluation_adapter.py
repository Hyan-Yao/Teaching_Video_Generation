"""Convert evaluator output into the existing feedback router schema."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from teachgen.eval.models import EvaluationResult, RubricScore

from ..providers.base import Provider
from ..schema import Critique, LessonPlan, ReviewResult


class _SegmentInterval(BaseModel):
    segment_id: str
    start_time_seconds: float
    end_time_seconds: float


class _RepairCandidate(BaseModel):
    timestamp_seconds: float = Field(ge=0)
    severity: Literal["blocker", "major", "minor"]
    issue: str
    fix_action: Literal["replan", "rewrite_narration", "re_render", "adjust_timing"]
    detail: str = ""
    source_metric: str


class _RepairPlan(BaseModel):
    candidates: list[_RepairCandidate] = Field(default_factory=list)
    summary: str = ""


SYSTEM = """\
You convert instructional-video evaluator findings into repair requests for an
existing segment-level video regeneration router.

You are not grading the video. The evaluator already did that.

Only create repair candidates for problems that are:
1. supported by timestamped evidence,
2. important enough to change the video,
3. likely repairable by one existing router action.

Available router actions:
- re_render: visual is broken, unreadable, ugly, malformed, or technically defective.
- rewrite_narration: narration/content is inaccurate, unclear, mismatched, or pedagogically weak.
- replan: the segment's visual modality or visual approach is wrong.
- adjust_timing: pacing, duration, or audio-visual synchronization is wrong.

For scores 1-2, usually create repair candidates unless the evidence is not
actionable. For score 3, be selective: create a candidate only for clear,
repairable negative evidence. Do not create candidates from positive evidence.

Use timestamp_seconds from the evidence item that best localizes the problem.
Do not guess segment ids.
"""


def adapt_evaluation_to_review(
    provider: Provider,
    result: EvaluationResult,
    plan: LessonPlan,
    *,
    debug_dir: Path | None = None,
) -> ReviewResult:
    """Ask an LLM to choose repairable findings, then map timestamps to segments."""
    repair_plan = _plan_repairs(provider, result, debug_dir=debug_dir)
    timeline = build_segment_timeline(plan, _video_duration(result))

    critiques: list[Critique] = []
    for candidate in repair_plan.candidates:
        segment_id = segment_for_timestamp(timeline, candidate.timestamp_seconds)
        critiques.append(
            Critique(
                segment_id=segment_id,
                severity=candidate.severity,
                issue=candidate.issue,
                fix_action=candidate.fix_action,
                detail=_format_detail(candidate),
            )
        )

    return ReviewResult(
        critiques=critiques,
        overall_score=result.overall_score * 2,
        summary=repair_plan.summary or result.summary,
    )


def build_segment_timeline(
    plan: LessonPlan,
    video_duration: float | None,
) -> list[_SegmentInterval]:
    """Build approximate segment intervals from target durations, scaled to video."""
    if not plan.segments:
        return []

    weights = [
        segment.target_seconds if segment.target_seconds and segment.target_seconds > 0 else 1.0
        for segment in plan.segments
    ]
    total_weight = sum(weights) or float(len(plan.segments))
    total_duration = video_duration if video_duration and video_duration > 0 else total_weight

    timeline: list[_SegmentInterval] = []
    cursor = 0.0
    for segment, weight in zip(plan.segments, weights):
        duration = total_duration * (weight / total_weight)
        end = cursor + duration
        timeline.append(
            _SegmentInterval(
                segment_id=segment.id,
                start_time_seconds=cursor,
                end_time_seconds=end,
            )
        )
        cursor = end
    return timeline


def segment_for_timestamp(
    timeline: list[_SegmentInterval],
    timestamp_seconds: float,
) -> str | None:
    if not timeline:
        return None

    for interval in timeline:
        if interval.start_time_seconds <= timestamp_seconds < interval.end_time_seconds:
            return interval.segment_id

    if timestamp_seconds < timeline[0].start_time_seconds:
        return timeline[0].segment_id
    return timeline[-1].segment_id


def _plan_repairs(
    provider: Provider,
    result: EvaluationResult,
    *,
    debug_dir: Path | None = None,
) -> _RepairPlan:
    prompt = (
        "Evaluator scores and evidence:\n\n"
        f"{_format_scores(result.scores)}\n\n"
        "Return only repair candidates the current router can act on."
    )
    repair_plan = provider.chat_json(prompt, _RepairPlan, system=SYSTEM, max_tokens=2500)
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "repair_planner_system.txt").write_text(SYSTEM, encoding="utf-8")
        (debug_dir / "repair_planner_prompt.txt").write_text(prompt, encoding="utf-8")
        (debug_dir / "repair_plan.json").write_text(
            repair_plan.model_dump_json(indent=2), encoding="utf-8"
        )
    return repair_plan


def _format_scores(scores: list[RubricScore]) -> str:
    blocks: list[str] = []
    for score in scores:
        if score.score > 3:
            continue
        blocks.append(
            "\n".join(
                [
                    f"Metric: {score.metric}",
                    f"Score: {score.score}/5",
                    f"Rationale: {score.rationale}",
                    "Supporting evidence:",
                    *_format_evidence(score.supporting_evidence),
                    "Conflicting evidence:",
                    *_format_evidence(score.conflicting_evidence),
                ]
            )
        )
    return "\n\n---\n\n".join(blocks) or "No metrics scored 3 or below."


def _format_evidence(evidence) -> list[str]:
    if not evidence:
        return ["- none"]
    return [
        (
            f"- [{item.start_time_seconds:.1f}-{item.end_time_seconds:.1f}] "
            f"{item.description} (confidence={item.confidence:.2f})"
        )
        for item in evidence
    ]


def _format_detail(candidate: _RepairCandidate) -> str:
    return (
        f"Evaluator metric: {candidate.source_metric}. "
        f"Timestamp: {candidate.timestamp_seconds:.1f}s. {candidate.detail}"
    ).strip()


def _video_duration(result: EvaluationResult) -> float | None:
    try:
        from teachgen.eval.video import get_video_duration

        return get_video_duration(result.request.video_path)
    except Exception:
        return None
