"""Data contracts — the spine of the system.

Stages talk to each other only through these objects, never through each
other's implementation details. That decoupling is what makes the renderers
swappable and the feedback loop able to target individual segments.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Modality(str, Enum):
    """Which production path renders a segment's visual."""

    ANIMATION = "animation"            # code2video / Manim — demos, derivations, process
    SLIDE = "slide"                    # make_slide / pptx — definitions, summaries, lists
    CONCEPT_IMAGE = "concept_image"    # text-to-image — intuition, metaphor, one big idea

class PlanMetricScore(BaseModel):
    metric: str
    score: int
    rationale: str
    evidence: list[str] = Field(default_factory=list)


class PlanEvaluationResult(BaseModel):
    overall_score: float
    scores: list[PlanMetricScore]
    summary: str
    requires_revision: bool
    
class CourseSpec(BaseModel):
    topic: str
    learning_goal: str
    key_learning_points: list[str] = Field(default_factory=list)


class PedagogySpec(BaseModel):
    bloom_levels: list[str] = Field(default_factory=list)
    icap_level: str = ""


class TeachingRequest(BaseModel):
    request_id: str = ""
    course: CourseSpec
    student_persona: str
    pedagogy: PedagogySpec = Field(default_factory=PedagogySpec)

    @classmethod
    def from_topic_audience(cls, topic: str, audience: str) -> "TeachingRequest":
        return cls(
            course=CourseSpec(
                topic=topic,
                learning_goal=f"Teach the topic clearly: {topic}",
                key_learning_points=[],
            ),
            student_persona=audience,
        )
    
class OuterRepairDecision(BaseModel):
    repair_type: Literal["none", "asset", "plan"]
    reason: str
    priority_metrics: list[str] = Field(default_factory=list)
    affected_segments: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list) 

class Segment(BaseModel):
    id: str = Field(..., description="Stable id, e.g. 'seg1'")
    title: str
    narration: str = Field(..., description="Spoken script for this segment (plain text)")
    modality: Modality = Field(..., description="Which renderer produces the visual")
    visual_brief: str = Field(..., description="Instruction handed to the chosen renderer")
    rationale: str = Field("", description="Why the planner picked this modality")
    target_seconds: Optional[float] = Field(
        None, description="Planner's rough duration hint; animation renderer aims for this"
    )
    hints: dict = Field(default_factory=dict, description="Renderer-specific extras")


class LessonPlan(BaseModel):
    topic: str
    audience: str
    objectives: list[str]
    learning_goal: str = ""
    key_learning_points: list[str] = Field(default_factory=list)
    bloom_levels: list[str] = Field(default_factory=list)
    icap_level: str = ""
    segments: list[Segment]


class VisualAsset(BaseModel):
    """Normalized renderer output. Either a timed video clip or a static image."""

    segment_id: str
    kind: Literal["video", "image"]
    path: str
    duration: Optional[float] = Field(
        None, description="Set for video; None for image (driven by narration audio)"
    )
    intended_modality: Optional[Modality] = None
    rendered_modality: Optional[Modality] = None
    fallback_reason: Optional[str] = None
    validation_status: Optional[
        Literal["not_run", "passed", "passed_with_minor_issues", "failed"]
    ] = None


class AnimationRepairAction(BaseModel):
    """One bounded source-code edit emitted by the animation visual critic."""

    action: Literal[
        "replace_placement",
        "insert_cleanup",
        "replace_write",
        "set_z_index",
        "update_style",
    ]
    line_number: int = Field(ge=1)
    object_name: str = ""
    object_names: list[str] = Field(default_factory=list)
    method: Literal["place_at_grid", "place_in_area", "fade_out", "remove"] | None = None
    grid_position: str | None = None
    top_left: str | None = None
    bottom_right: str | None = None
    scale_factor: float | None = None
    z_index: int | None = None
    style_attribute: Literal["font_size", "color"] | None = None
    style_value: str | float | int | None = None


class AnimationCritique(BaseModel):
    has_issues: bool = False
    severity: Literal["minor", "major", "blocker"] = "minor"
    persistent: bool = False
    summary: str = ""
    repairs: list[AnimationRepairAction] = Field(default_factory=list)


class ConceptImageValidation(BaseModel):
    has_major_issues: bool = False
    severity: Literal["minor", "major", "blocker"] = "minor"
    issues: list[str] = Field(default_factory=list)
    summary: str = ""


class SlideSpec(BaseModel):
    """Deterministic, renderer-neutral content for one teaching slide."""

    title: str
    bullets: list[str] = Field(default_factory=list, max_length=5)
    layout: Literal["none", "pipeline", "comparison", "cells"] = "none"
    pipeline_nodes: list[str] = Field(default_factory=list, max_length=4)
    left_title: str = ""
    left_items: list[str] = Field(default_factory=list, max_length=4)
    right_title: str = ""
    right_items: list[str] = Field(default_factory=list, max_length=4)
    cells: list[str] = Field(default_factory=list, max_length=12)
    cells_label: str = ""
    caption: str = ""


class WordTiming(BaseModel):
    word: str
    start: float
    end: float


class NarrationAudio(BaseModel):
    segment_id: str
    path: str
    duration: float
    words: list[WordTiming] = Field(default_factory=list)


class Critique(BaseModel):
    """One issue raised by the MLLM reviewer watching the composited video."""

    segment_id: Optional[str] = Field(None, description="None = whole-video issue")
    severity: Literal["blocker", "major", "minor"]
    issue: str
    fix_action: Literal["change_modality", "rewrite_narration", "re_render", "adjust_timing"]
    detail: str = ""
    repair_scope: Literal["plan", "asset", "timing"] = "asset"
    cause: Literal["narration", "visual", "sequence", "rendering"] = "rendering"
    source_metric: str = ""


class ReviewResult(BaseModel):
    critiques: list[Critique] = Field(default_factory=list)
    overall_score: float = Field(0.0, description="0-10, reviewer's holistic rating")
    summary: str = ""

    @property
    def has_blocking_issues(self) -> bool:
        return any(c.severity in ("blocker", "major") for c in self.critiques)


# ---------------------------------------------------------------------------
# Nested feedback loop — outer review + inner refinement contracts
# ---------------------------------------------------------------------------

class ContentIssue(BaseModel):
    """A plan-level problem: narration or visual_brief needs rewriting."""

    segment_id: str
    field: Literal["narration", "visual_brief"]
    issue: str
    suggestion: str


class VisualIssue(BaseModel):
    """A rendering-quality problem: the approach is right but the output looks bad."""

    segment_id: str
    issue: str
    suggestion: str


class OuterReview(BaseModel):
    """Holistic evaluation of the composited video, with issues pre-classified."""

    overall_score: float = Field(..., description="0–10 holistic rating")
    content_issues: list[ContentIssue] = Field(default_factory=list)
    visual_issues: list[VisualIssue] = Field(default_factory=list)
    summary: str = ""

    @property
    def needs_plan_fix(self) -> bool:
        return bool(self.content_issues)

    @property
    def needs_visual_fix(self) -> bool:
        return bool(self.visual_issues)
