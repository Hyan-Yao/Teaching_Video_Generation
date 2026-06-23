from pathlib import Path

from teachgen.eval.models import (
    ContentChunkAnalysis,
    EvidenceItem,
    PedagogyChunkAnalysis,
    ChunkAnalysis,
    VisualMultimediaChunkAnalysis,
)
from teachgen.eval.video_llm import VideoLLM
from teachgen.eval.video import VideoChunk
from teachgen.eval.prompts import CONTENT_EXTRACTOR_PROMPT, VISUAL_MULTIMEDIA_EXTRACTOR_PROMPT, PEDAGOGY_EXTRACTOR_PROMPT


def _chunk_instruction(chunk: VideoChunk) -> str:
    return (
        f"Use chunk_index={chunk.index}. "
        "The supplied video file is this chunk only. "
        f"The valid timestamp range is 0 to {chunk.end_time_seconds} seconds, "
        "relative to the start of this chunk. "
        "Do not report timestamps less than 0 or greater than "
        f"{chunk.end_time_seconds}."
    )


def _iter_evidence_items(value):
    if isinstance(value, EvidenceItem):
        yield value
        return

    if isinstance(value, list):
        for item in value:
            yield from _iter_evidence_items(item)
        return

    if hasattr(value, "model_dump"):
        for item in value.model_dump().values():
            yield from _iter_evidence_items(item)


def _validate_evidence_timestamps(analysis, chunk: VideoChunk, label: str) -> None:
    for evidence in _iter_evidence_items(analysis):
        if evidence.start_time_seconds < 0 or evidence.end_time_seconds < 0:
            raise ValueError(f"{label} extractor returned negative timestamp: {evidence}")

        if evidence.start_time_seconds > chunk.end_time_seconds:
            raise ValueError(f"{label} extractor returned out-of-range timestamp: {evidence}")

        if evidence.end_time_seconds > chunk.end_time_seconds:
            raise ValueError(f"{label} extractor returned out-of-range timestamp: {evidence}")


class ContentExtractor:
    def __init__(self, video_llm: VideoLLM):
        self.video_llm = video_llm

    def analyze(self, video_path: str | Path, chunk: VideoChunk,) -> ContentChunkAnalysis:
        prompt = (
            f"{CONTENT_EXTRACTOR_PROMPT}\n"
            f"{_chunk_instruction(chunk)}"
        )
        return self.video_llm.analyze(video_path, prompt, ContentChunkAnalysis)


class VisualMultimediaExtractor:
    def __init__(self, video_llm: VideoLLM):
        self.video_llm = video_llm

    def analyze(self, video_path: str | Path, chunk: VideoChunk) -> VisualMultimediaChunkAnalysis:
        prompt = (
            f"{VISUAL_MULTIMEDIA_EXTRACTOR_PROMPT}\n"
            f"{_chunk_instruction(chunk)}"
        )

        return self.video_llm.analyze(video_path, prompt, VisualMultimediaChunkAnalysis)
    

class PedagogyExtractor:
    def __init__(self, video_llm: VideoLLM):
        self.video_llm = video_llm

    def analyze(self, video_path: str | Path, chunk: VideoChunk) -> PedagogyChunkAnalysis:
        prompt = (
            f"{PEDAGOGY_EXTRACTOR_PROMPT}\n"
            f"{_chunk_instruction(chunk)}"
        )

        return self.video_llm.analyze(video_path, prompt, PedagogyChunkAnalysis)
    

class ChunkAnalyzer:
    def __init__(self, 
                 content_extractor: ContentExtractor, 
                 visual_extractor: VisualMultimediaExtractor, 
                 pedagogy_extractor: PedagogyExtractor):
        
        self.content_extractor = content_extractor
        self.visual_extractor = visual_extractor
        self.pedagogy_extractor = pedagogy_extractor

    def analyze(
            self,
            video_path: str | Path,
            chunk: VideoChunk,
        ) -> ChunkAnalysis:
            
            content = self.content_extractor.analyze(video_path, chunk)
            
            if content.chunk_index != chunk.index:
                raise ValueError("Content extractor returned incorrect chunk index")
            _validate_evidence_timestamps(content, chunk, "Content")
            
            visual = self.visual_extractor.analyze(video_path, chunk)
            if visual.chunk_index != chunk.index:
                raise ValueError("Visual extractor returned incorrect chunk index")
            _validate_evidence_timestamps(visual, chunk, "Visual")

            pedagogy = self.pedagogy_extractor.analyze(video_path, chunk)
            if pedagogy.chunk_index != chunk.index:
                raise ValueError("Pedagogy extractor returned incorrect chunk index")
            _validate_evidence_timestamps(pedagogy, chunk, "Pedagogy")

            return ChunkAnalysis(
                chunk_index=chunk.index,
                start_time_seconds=chunk.start_time_seconds,
                end_time_seconds = chunk.end_time_seconds,
                content = content,
                visual_multimedia= visual,
                pedagogy= pedagogy,
            )
