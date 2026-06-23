from teachgen.eval.prompts import SECTION_INFERENCE_PROMPT, LECTURE_INFERENCE_PROMPT
from teachgen.eval.text_llm import TextLLM
from teachgen.eval.models import ChunkAnalysis, SectionInference, EvaluationRequest, LectureInference, SectionInferenceCollection


class SectionInferencer:
    def __init__(self, text_llm: TextLLM):
        self.text_llm = text_llm

    def infer(self, analysis: ChunkAnalysis) -> SectionInference:

        prompt = (
            f"{SECTION_INFERENCE_PROMPT}\n\n"
            f"ChunkAnalysis:\n{analysis.model_dump_json(indent=2)}"
        )

        return self.text_llm.analyze(prompt, SectionInference)


class LectureInferencer:
    def __init__(self, text_llm: TextLLM):
        self.text_llm = text_llm

    def infer(
        self,
        sections: list[SectionInference],
        request: EvaluationRequest,
    ) -> LectureInference:
        if not sections:
            raise ValueError("At least one section inference is required")

        ordered_sections = sorted(sections, key=lambda section: section.chunk_index)

        prompt = (
            f"{LECTURE_INFERENCE_PROMPT}\n\n"
            f"Optional metadata:\n{request.model_dump_json(indent=2)}\n\n"
            f"Ordered section inferences:\n"
            f"{SectionInferenceCollection(sections=ordered_sections).model_dump_json(indent=2)}"
        )

        return self.text_llm.analyze(prompt, LectureInference)
