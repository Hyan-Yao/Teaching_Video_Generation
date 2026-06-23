from teachgen.eval.models import (
    ContentAnalysisCollection,
    ContentChunkAnalysis,
    EvaluationRequest,
    GraderOutput,
    LectureInference,
    PedagogyAnalysisCollection,
    PedagogyChunkAnalysis,
    SectionInference,
    SectionInferenceCollection,
    VisualMultimediaAnalysisCollection,
    VisualMultimediaChunkAnalysis,
)
from teachgen.eval.prompts import (
    CONTENT_GRADER_PROMPT,
    PEDAGOGY_GRADER_PROMPT,
    PRESENTATION_GRADER_PROMPT,
)
from teachgen.eval.text_llm import TextLLM


class ContentGrader:
    def __init__(self, text_llm: TextLLM):
        self.text_llm = text_llm

    def grade(
        self,
        request: EvaluationRequest,
        lecture: LectureInference,
        sections: list[SectionInference],
        content_chunks: list[ContentChunkAnalysis],
    ) -> GraderOutput:
        if not sections:
            raise ValueError("At least one section inference is required")

        if not content_chunks:
            raise ValueError("At least one content chunk analysis is required")

        prompt = (
            f"{CONTENT_GRADER_PROMPT}\n\n"
            f"Evaluation request:\n{request.model_dump_json(indent=2)}\n\n"
            f"Lecture inference:\n{lecture.model_dump_json(indent=2)}\n\n"
            f"Section inferences:\n"
            f"{SectionInferenceCollection(sections=sections).model_dump_json(indent=2)}\n\n"
            f"Raw content evidence:\n"
            f"{ContentAnalysisCollection(chunks=content_chunks).model_dump_json(indent=2)}"
        )

        return self.text_llm.analyze(prompt, GraderOutput)


class PresentationGrader:
    def __init__(self, text_llm: TextLLM):
        self.text_llm = text_llm

    def grade(
        self,
        lecture: LectureInference,
        sections: list[SectionInference],
        visual_chunks: list[VisualMultimediaChunkAnalysis],
        pedagogy_chunks: list[PedagogyChunkAnalysis],
    ) -> GraderOutput:
        if not sections:
            raise ValueError("At least one section inference is required")

        if not visual_chunks:
            raise ValueError("At least one visual multimedia analysis is required")

        if not pedagogy_chunks:
            raise ValueError("At least one pedagogy analysis is required")

        prompt = (
            f"{PRESENTATION_GRADER_PROMPT}\n\n"
            f"Lecture inference:\n{lecture.model_dump_json(indent=2)}\n\n"
            f"Section inferences:\n"
            f"{SectionInferenceCollection(sections=sections).model_dump_json(indent=2)}\n\n"
            f"Raw visual and multimedia evidence:\n"
            f"{VisualMultimediaAnalysisCollection(chunks=visual_chunks).model_dump_json(indent=2)}\n\n"
            f"Raw pedagogy and transition evidence:\n"
            f"{PedagogyAnalysisCollection(chunks=pedagogy_chunks).model_dump_json(indent=2)}"
        )

        return self.text_llm.analyze(prompt, GraderOutput)


class PedagogyGrader:
    def __init__(self, text_llm: TextLLM):
        self.text_llm = text_llm

    def grade(
        self,
        request: EvaluationRequest,
        lecture: LectureInference,
        sections: list[SectionInference],
        pedagogy_chunks: list[PedagogyChunkAnalysis],
    ) -> GraderOutput:
        if not sections:
            raise ValueError("At least one section inference is required")

        if not pedagogy_chunks:
            raise ValueError("At least one pedagogy analysis is required")

        prompt = (
            f"{PEDAGOGY_GRADER_PROMPT}\n\n"
            f"Evaluation request:\n{request.model_dump_json(indent=2)}\n\n"
            f"Lecture inference:\n{lecture.model_dump_json(indent=2)}\n\n"
            f"Section inferences:\n"
            f"{SectionInferenceCollection(sections=sections).model_dump_json(indent=2)}\n\n"
            f"Raw pedagogy evidence:\n"
            f"{PedagogyAnalysisCollection(chunks=pedagogy_chunks).model_dump_json(indent=2)}"
        )

        return self.text_llm.analyze(prompt, GraderOutput)
