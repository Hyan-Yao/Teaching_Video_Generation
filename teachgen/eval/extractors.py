from pathlib import Path

from pydantic import BaseModel

from teachgen.eval.models import ChunkAnalysis, EvidenceItem
from teachgen.eval.prompts import (
    CONTENT_EXTRACTOR_PROMPT,
    PEDAGOGY_EXTRACTOR_PROMPT,
    VISUAL_MULTIMEDIA_EXTRACTOR_PROMPT,
)
from teachgen.eval.video import VideoChunk
from teachgen.eval.video_llm import VideoLLM


COMBINED_EXTRACTOR_PROMPT = """\
Analyze this instructional-video chunk using the timestamped transcript and frames.
Return one ChunkAnalysis object containing nested content, visual_multimedia, and
pedagogy analyses. Apply all three evidence-extraction instructions below. They
remain factual-extraction tasks: do not assign rubric scores or write a global
quality judgment. All evidence timestamps are local to this chunk.

CONTENT EXTRACTION INSTRUCTIONS:
{content}

VISUAL/MULTIMEDIA EXTRACTION INSTRUCTIONS:
{visual}

PEDAGOGY EXTRACTION INSTRUCTIONS:
{pedagogy}
""".format(
    content=CONTENT_EXTRACTOR_PROMPT,
    visual=VISUAL_MULTIMEDIA_EXTRACTOR_PROMPT,
    pedagogy=PEDAGOGY_EXTRACTOR_PROMPT,
)


def _chunk_instruction(chunk: VideoChunk) -> str:
    return (
        f"Use chunk_index={chunk.index}. "
        "The supplied transcript and frames are this chunk only. "
        f"The valid timestamp range is 0 to {chunk.end_time_seconds} seconds, "
        "relative to the start of this chunk. "
        "Set the top-level and every nested analysis chunk_index to this value. "
        "Set each analysis start_time_seconds to 0 and end_time_seconds to the "
        "chunk end time. Do not report timestamps outside the valid range."
    )


def _iter_evidence_items(value):
    if isinstance(value, EvidenceItem):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_evidence_items(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_evidence_items(item)
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            item = getattr(value, field_name)
            yield from _iter_evidence_items(item)


def _validate_evidence_timestamps(analysis, chunk: VideoChunk, label: str) -> None:
    for evidence in _iter_evidence_items(analysis):
        if evidence.start_time_seconds < 0 or evidence.end_time_seconds < 0:
            raise ValueError(f"{label} extractor returned negative timestamp: {evidence}")
        if evidence.start_time_seconds > chunk.end_time_seconds:
            raise ValueError(f"{label} extractor returned out-of-range timestamp: {evidence}")
        if evidence.end_time_seconds > chunk.end_time_seconds:
            raise ValueError(f"{label} extractor returned out-of-range timestamp: {evidence}")
        if evidence.end_time_seconds < evidence.start_time_seconds:
            raise ValueError(f"{label} extractor returned inverted timestamp: {evidence}")


def shift_chunk_timestamps(analysis: ChunkAnalysis, offset_seconds: float) -> ChunkAnalysis:
    """Convert local extraction timestamps to full-video time for repair routing."""
    if offset_seconds == 0:
        return analysis

    analysis.start_time_seconds += offset_seconds
    analysis.end_time_seconds += offset_seconds
    for nested in (analysis.content, analysis.visual_multimedia, analysis.pedagogy):
        nested.start_time_seconds += offset_seconds
        nested.end_time_seconds += offset_seconds
        for evidence in _iter_evidence_items(nested):
            evidence.start_time_seconds += offset_seconds
            evidence.end_time_seconds += offset_seconds
    return analysis


class ChunkAnalyzer:
    """One GPT-5 frame/audio call per chunk, preserving the old result schema."""

    def __init__(self, video_llm: VideoLLM):
        self.video_llm = video_llm

    def analyze(
        self,
        video_path: str | Path,
        chunk: VideoChunk,
        *,
        frame_interval_seconds: float,
        debug_dir: Path,
        authoritative_narration: str | None = None,
    ) -> ChunkAnalysis:
        reference = ""
        if authoritative_narration:
            reference = (
                "\n\nAUTHORITATIVE SOURCE NARRATION FOR SYMBOL VERIFICATION ONLY:\n"
                f"{authoritative_narration}\n\n"
                "Use this source only to verify fragile exact strings such as binary "
                "digits, equations, operators, variable names, acronyms, and code tokens. "
                "Whisper may collapse repeated symbols. Do not treat this source as proof "
                "that content was audibly delivered, visually shown, or aligned at a "
                "particular timestamp."
            )
        analysis = self.video_llm.analyze(
            video_path,
            f"{COMBINED_EXTRACTOR_PROMPT}\n\n{_chunk_instruction(chunk)}{reference}",
            ChunkAnalysis,
            chunk=chunk,
            frame_interval_seconds=frame_interval_seconds,
            debug_dir=debug_dir,
        )
        if analysis.chunk_index != chunk.index:
            raise ValueError("Combined extractor returned incorrect chunk index")
        for label, nested in (
            ("Content", analysis.content),
            ("Visual", analysis.visual_multimedia),
            ("Pedagogy", analysis.pedagogy),
        ):
            if nested.chunk_index != chunk.index:
                raise ValueError(f"{label} extractor returned incorrect chunk index")
            _validate_evidence_timestamps(nested, chunk, label)
        return analysis
