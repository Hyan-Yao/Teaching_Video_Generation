"""Convert evaluator output into the existing feedback router schema."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from teachgen.eval.models import EvaluationResult, RubricScore

from ..providers.base import Provider
from ..schema import Critique, LessonPlan, Modality, ReviewResult


class _SegmentInterval(BaseModel):
    segment_id: str
    start_time_seconds: float
    end_time_seconds: float


class _RepairCandidate(BaseModel):
    timestamp_seconds: float = Field(ge=0)
    segment_id: str | None = None
    severity: Literal["blocker", "major", "minor"]
    issue: str
    fix_action: Literal["change_modality", "rewrite_narration", "re_render", "adjust_timing"]
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

Preserve the lesson plan's instructional meaning. Required content comes from
the request, objectives, key learning points, target segment narration, and
rationale. The current visual brief is implementation guidance, not a contract:
if the evaluator evidence shows visual clutter, tiny text, dense tables, cramped
labels, or unreadable details, the repair may ask the router to simplify or
replace those visual details while keeping the required concept intact.

A repair candidate should identify what went wrong in production, what concept
the segment still needs to teach, and what kind of visual redesign would better
support the narration.

Available router actions:
- re_render: visual is broken, unreadable, ugly, malformed, or technically defective,
  but the current modality is still appropriate and the issue is simple.
- rewrite_narration: narration/content is inaccurate, unclear, mismatched, or pedagogically weak.
- change_modality: the segment's visual modality or visual approach is wrong.
- adjust_timing: pacing, duration, or audio-visual synchronization is wrong.

For broken, messy, unreadable, cramped, mistimed, or narration-mismatched
animations, prefer change_modality instead of asking for a more complex
animation. The next modality will be concept_image, and render-time fallback can
still degrade to slide if needed.

For scores 1-2, usually create repair candidates unless the evidence is not
actionable. For score 3, be selective: create a candidate only for clear,
repairable negative evidence. Do not create candidates from positive evidence.

Use timestamp_seconds from the evidence item that best localizes the problem.
If the evidence or lesson context clearly identifies a segment, include segment_id.
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
    repair_plan = _plan_repairs(provider, result, plan, debug_dir=debug_dir)
    timeline = build_segment_timeline(plan, _video_duration(result), debug_dir=debug_dir)
    if debug_dir is not None:
        (debug_dir / "resolved_segment_timeline.json").write_text(
            json.dumps([interval.model_dump() for interval in timeline], indent=2),
            encoding="utf-8",
        )
    _force_animation_visual_fallbacks(repair_plan, timeline, plan)
    if debug_dir is not None:
        (debug_dir / "repair_plan.json").write_text(
            repair_plan.model_dump_json(indent=2), encoding="utf-8"
        )

    critiques: list[Critique] = []
    for candidate in repair_plan.candidates:
        segment_id = resolve_candidate_segment(plan, timeline, candidate)
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
    *,
    debug_dir: Path | None = None,
) -> list[_SegmentInterval]:
    """Build segment intervals, preferring actual rendered audio durations."""
    if not plan.segments:
        return []

    actual_weights = _audio_segment_durations(plan, debug_dir)
    if actual_weights:
        return _timeline_from_weights(plan, actual_weights)

    rendered_weights = _visual_segment_durations(plan, debug_dir)
    if rendered_weights:
        return _timeline_from_weights(plan, rendered_weights)

    weights = [
        segment.target_seconds if segment.target_seconds and segment.target_seconds > 0 else 1.0
        for segment in plan.segments
    ]
    total_weight = sum(weights) or float(len(plan.segments))
    total_duration = video_duration if video_duration and video_duration > 0 else total_weight

    return _timeline_from_weights(plan, weights, total_duration=total_duration)


def _timeline_from_weights(
    plan: LessonPlan,
    weights: list[float],
    *,
    total_duration: float | None = None,
) -> list[_SegmentInterval]:
    total_weight = sum(weights) or float(len(plan.segments))
    if total_duration is None or total_duration <= 0:
        total_duration = total_weight

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


def _audio_segment_durations(plan: LessonPlan, debug_dir: Path | None) -> list[float] | None:
    if debug_dir is None:
        return None
    audio_dir = debug_dir.parent / "audio"
    durations: list[float] = []
    for segment in plan.segments:
        audio_path = audio_dir / f"{segment.id}.mp3"
        if not audio_path.exists():
            return None
        duration = _media_duration(audio_path)
        if duration is None or duration <= 0:
            return None
        durations.append(duration)
    return durations


def _visual_segment_durations(plan: LessonPlan, debug_dir: Path | None) -> list[float] | None:
    if debug_dir is None:
        return None
    assets_dir = debug_dir.parent / "assets"
    durations: list[float] = []
    for segment in plan.segments:
        duration = None
        for suffix in (".mp4", ".png", ".jpg", ".jpeg"):
            asset_path = assets_dir / f"{segment.id}{suffix}"
            if asset_path.exists():
                duration = _media_duration(asset_path)
                break
        if duration is None or duration <= 0:
            return None
        durations.append(duration)
    return durations


def _media_duration(path: Path) -> float | None:
    try:
        from teachgen.mpcompat import AudioFileClip, ImageClip, VideoFileClip

        if path.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}:
            clip = AudioFileClip(str(path))
        elif path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            return None
        else:
            clip = VideoFileClip(str(path))
        try:
            return float(clip.duration or 0.0)
        finally:
            clip.close()
    except Exception:
        return None


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


def resolve_candidate_segment(
    plan: LessonPlan,
    timeline: list[_SegmentInterval],
    candidate: _RepairCandidate,
) -> str | None:
    valid_ids = {segment.id for segment in plan.segments}
    timestamp_segment = segment_for_timestamp(timeline, candidate.timestamp_seconds)
    explicit_segment = candidate.segment_id if candidate.segment_id in valid_ids else None
    mentioned_segment = _mentioned_segment_id(candidate, valid_ids)
    semantic_segment = _semantic_segment_id(plan, candidate)

    if mentioned_segment and mentioned_segment != timestamp_segment:
        return mentioned_segment
    if explicit_segment and explicit_segment != timestamp_segment:
        return explicit_segment
    if semantic_segment and semantic_segment != timestamp_segment:
        return semantic_segment
    return explicit_segment or mentioned_segment or semantic_segment or timestamp_segment


def _mentioned_segment_id(candidate: _RepairCandidate, valid_ids: set[str]) -> str | None:
    text = " ".join(
        part
        for part in [
            candidate.segment_id or "",
            candidate.issue,
            candidate.detail,
        ]
        if part
    )
    matches: list[str] = []
    for match in re.finditer(r"\bseg(?:ment)?\s*([0-9]+)\b", text, flags=re.I):
        segment_id = f"seg{match.group(1)}"
        if segment_id in valid_ids:
            matches.append(segment_id)
    for match in re.finditer(r"\bSegment\s+([0-9]+)\b", text):
        segment_id = f"seg{match.group(1)}"
        if segment_id in valid_ids:
            matches.append(segment_id)
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


def _semantic_segment_id(plan: LessonPlan, candidate: _RepairCandidate) -> str | None:
    text = _normalize_text(" ".join([candidate.issue, candidate.detail]))
    if not text:
        return None

    for segment in plan.segments:
        title = _normalize_text(segment.title)
        if title and title in text:
            return segment.id

    query_tokens = _significant_tokens(text)
    if len(query_tokens) < 2:
        return None

    scores: list[tuple[int, str]] = []
    for segment in plan.segments:
        segment_text = _normalize_text(
            " ".join(
                [
                    segment.title,
                    segment.narration,
                    segment.visual_brief,
                    segment.rationale,
                ]
            )
        )
        segment_tokens = _significant_tokens(segment_text)
        scores.append((len(query_tokens & segment_tokens), segment.id))

    scores.sort(reverse=True)
    if not scores or scores[0][0] < 2:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 2:
        return None
    return scores[0][1]


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _significant_tokens(text: str) -> set[str]:
    stopwords = {
        "about",
        "across",
        "after",
        "also",
        "because",
        "before",
        "being",
        "clear",
        "could",
        "during",
        "ensure",
        "every",
        "from",
        "hard",
        "into",
        "large",
        "lesson",
        "maintain",
        "making",
        "segment",
        "small",
        "that",
        "their",
        "there",
        "these",
        "this",
        "through",
        "using",
        "video",
        "visual",
        "while",
        "with",
    }
    return {
        token
        for token in text.split()
        if len(token) > 4 and token not in stopwords and not token.isdigit()
    }


def _plan_repairs(
    provider: Provider,
    result: EvaluationResult,
    plan: LessonPlan,
    *,
    debug_dir: Path | None = None,
) -> _RepairPlan:
    prompt = (
        "Lesson plan context that must be preserved:\n\n"
        f"{_format_plan_context(plan)}\n\n"
        "Evaluator scores and evidence:\n\n"
        f"{_format_scores(result.scores)}\n\n"
        "Return only repair candidates the current router can act on. "
        "Each candidate detail should explain the defect to fix, the required "
        "instructional concept to preserve from the narration/request, and how "
        "the visual can be simplified if the old visual brief caused clutter. "
        "Do not require preserving every visual label, table cell, code snippet, "
        "filename, email body, or bullet from the old visual brief unless it is "
        "central to the target segment's narration. For major/blocker animation "
        "rendering defects, prefer change_modality over re_render so the segment "
        "can be rebuilt as a simpler concept image."
    )
    repair_plan = provider.chat_json(
        prompt,
        _RepairPlan,
        system=SYSTEM,
        max_tokens=2500,
        model=_refinement_model(provider),
    )
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "repair_planner_system.txt").write_text(SYSTEM, encoding="utf-8")
        (debug_dir / "repair_planner_prompt.txt").write_text(prompt, encoding="utf-8")
        (debug_dir / "repair_plan_raw.json").write_text(
            repair_plan.model_dump_json(indent=2), encoding="utf-8"
        )
    return repair_plan


def _force_animation_visual_fallbacks(
    repair_plan: _RepairPlan,
    timeline: list[_SegmentInterval],
    plan: LessonPlan,
) -> None:
    """Force major/blocker visual repairs on animations to change modality."""
    by_id = {segment.id: segment for segment in plan.segments}
    visual_metrics = {
        "visual quality",
        "visual_quality",
        "multimedia learning design",
        "multimedia_learning_design",
    }
    fallback_severities = {"major", "blocker"}

    for candidate in repair_plan.candidates:
        if candidate.source_metric.strip().casefold() not in visual_metrics:
            continue
        if candidate.severity not in fallback_severities:
            continue

        segment_id = resolve_candidate_segment(plan, timeline, candidate)
        segment = by_id.get(segment_id) if segment_id else None
        if segment is None or segment.modality != Modality.ANIMATION:
            continue

        if candidate.fix_action != "change_modality":
            candidate.detail = (
                f"{candidate.detail} "
                "Deterministic policy override: major/blocker visual issue on "
                "an animation segment, so fallback to concept_image instead of "
                "retrying animation."
            ).strip()
        candidate.fix_action = "change_modality"


def _format_plan_context(plan: LessonPlan) -> str:
    lines = [
        f"Topic: {plan.topic}",
        f"Audience/persona: {plan.audience}",
        f"Learning goal: {plan.learning_goal or 'not provided'}",
        "Learning objectives:",
        *[f"- {objective}" for objective in plan.objectives],
        "Key learning points:",
        *[f"- {point}" for point in plan.key_learning_points],
        f"Bloom levels: {', '.join(plan.bloom_levels) or 'not provided'}",
        f"ICAP level: {plan.icap_level or 'not provided'}",
        "",
        "Segment timeline and required content:",
    ]
    for segment in plan.segments:
        lines.extend(
            [
                (
                    f"- {segment.id}: {segment.title} "
                    f"({segment.modality.value}, target {segment.target_seconds}s)"
                ),
                f"  Narration: {segment.narration}",
                f"  Visual brief: {segment.visual_brief}",
                f"  Rationale: {segment.rationale}",
            ]
        )
    return "\n".join(lines)


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


def _refinement_model(provider: Provider) -> str | None:
    models = getattr(getattr(provider, "cfg", None), "models", None)
    return getattr(models, "refinement_text", None)
