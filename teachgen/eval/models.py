from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class EvaluatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationRequest(EvaluatorModel):
    video_path: str
    course_requirement: str | None = None
    learning_objectives: list[str] | None = None
    student_persona: str | None = None
    intended_bloom: str | None = None


class EvidenceItem(EvaluatorModel):
    start_time_seconds: float = Field(ge=0)
    end_time_seconds: float = Field(ge=0)
    description: str
    confidence: float = Field(ge=0, le=1)


class ContentChunkAnalysis(EvaluatorModel):
    chunk_index: int = Field(ge=0)
    start_time_seconds: float = Field(ge=0)
    end_time_seconds: float = Field(ge=0)
    topics: list[EvidenceItem]
    claims: list[EvidenceItem]
    definitions: list[EvidenceItem]
    examples: list[EvidenceItem]
    possible_accuracy_issues: list[EvidenceItem]


class ContentAnalysisCollection(EvaluatorModel):
    chunks: list[ContentChunkAnalysis]


class VisualMultimediaChunkAnalysis(EvaluatorModel):
    chunk_index: int = Field(ge=0)
    start_time_seconds: float = Field(ge=0)
    end_time_seconds: float = Field(ge=0)
    visual_elements: list[EvidenceItem]
    visual_defects: list[EvidenceItem]
    audio_visual_alignment: list[EvidenceItem]
    effective_visual_support: list[EvidenceItem]
    missed_visual_opportunities: list[EvidenceItem]


class VisualMultimediaAnalysisCollection(EvaluatorModel):
    chunks: list[VisualMultimediaChunkAnalysis]


class PedagogyChunkAnalysis(EvaluatorModel):
    chunk_index: int = Field(ge=0)
    start_time_seconds: float = Field(ge=0)
    end_time_seconds: float = Field(ge=0)
    scaffolding_events: list[EvidenceItem]
    transitions: list[EvidenceItem]
    questions: list[EvidenceItem]
    learner_activities: list[EvidenceItem]
    summaries_and_reviews: list[EvidenceItem]
    prerequisite_assumptions: list[EvidenceItem]
    announced_cognitive_goals: list[EvidenceItem]
    bloom_signals: list[EvidenceItem]
    icap_signals: list[EvidenceItem]


class PedagogyAnalysisCollection(EvaluatorModel):
    chunks: list[PedagogyChunkAnalysis]


class ChunkAnalysis(EvaluatorModel):
    chunk_index: int = Field(ge=0)
    start_time_seconds: float = Field(ge=0)
    end_time_seconds: float = Field(ge=0)
    content: ContentChunkAnalysis
    visual_multimedia: VisualMultimediaChunkAnalysis
    pedagogy: PedagogyChunkAnalysis


class InferenceItem(EvaluatorModel):
    conclusion: str
    source: Literal["provided", "inferred", "mixed"]
    supporting_evidence: list[EvidenceItem]
    confidence: float = Field(ge=0, le=1)


ConceptDepth = Literal[
    "mention",
    "brief_explanation",
    "detailed_explanation",
    "demonstration",
    "application",
]


class ObservedConcept(EvaluatorModel):
    concept: str
    observed_depth: ConceptDepth
    supporting_evidence: list[EvidenceItem]
    confidence: float = Field(ge=0, le=1)


class ExpectedConcept(EvaluatorModel):
    concept: str
    importance: Literal["core", "required_prerequisite", "supporting"]
    expected_depth: ConceptDepth
    rationale: str
    source: Literal["provided", "inferred", "mixed"]
    confidence: float = Field(ge=0, le=1)


class SectionInference(EvaluatorModel):
    chunk_index: int = Field(ge=0)
    start_time_seconds: float = Field(ge=0)
    end_time_seconds: float = Field(ge=0)
    section_summary: str
    observed_concepts: list[ObservedConcept]
    inferred_objectives: list[InferenceItem]
    required_prerequisites: list[InferenceItem]
    bloom_levels_supported: list[InferenceItem]
    icap_levels_supported: list[InferenceItem]
    strengths: list[InferenceItem]
    concerns: list[InferenceItem]


class LectureInference(EvaluatorModel):
    lecture_summary: str
    inferred_scope: InferenceItem
    learning_objectives: list[InferenceItem]
    observed_concepts: list[ObservedConcept]
    expected_concepts: list[ExpectedConcept]
    assumed_learner_background: list[InferenceItem]
    intended_bloom_level: InferenceItem
    expected_icap_level: InferenceItem
    instructional_structure: list[InferenceItem]
    overall_strengths: list[InferenceItem]
    overall_concerns: list[InferenceItem]

class SectionInferenceCollection(EvaluatorModel):
    sections: list[SectionInference]


class RubricScore(EvaluatorModel):
    metric: str
    score: int = Field(ge=1, le=5)
    rationale: str
    supporting_evidence: list[EvidenceItem]
    conflicting_evidence: list[EvidenceItem]
    confidence: float = Field(ge=0, le=1)
    based_on_inferred_context: bool


class GraderOutput(EvaluatorModel):
    grader_name: str
    scores: list[RubricScore]
    overall_comments: str


class EvaluationResult(EvaluatorModel):
    request: EvaluationRequest
    lecture_inference: LectureInference
    scores: list[RubricScore]
    overall_score: float = Field(ge=1, le=5)
    summary: str
