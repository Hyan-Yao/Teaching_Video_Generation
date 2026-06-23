"""MLLM reviewer — watches the composited video and returns structured critiques.

OpenAI can't ingest mp4 directly, so we sample frames uniformly and hand them to the
vision model alongside the lesson plan (titles + narration). The reviewer judges
pacing, on-screen/spoken alignment, legibility, and modality fit, and tags each issue
with a `fix_action` the router knows how to apply.
"""

from __future__ import annotations

from pathlib import Path

from ..providers.base import Provider
from ..schema import LessonPlan, ReviewResult

SYSTEM = """\
You are a meticulous teaching-video reviewer. You are shown frames sampled in order
from a generated lesson video, plus the lesson plan (each segment's title, narration,
and which renderer produced it). Judge:
- Clarity & legibility of on-screen visuals.
- Whether the visual matches what is being said (and the right modality was chosen).
- Pacing and flow across segments.
- Factual/teaching quality.

Return critiques. For each, set fix_action to exactly one of:
- "replan": the wrong modality was chosen for a segment (visual approach is wrong).
- "rewrite_narration": the script is unclear, wrong, or mismatched to the visual.
- "re_render": the visual is broken/ugly/illegible but the approach is right.
- "adjust_timing": only pacing/duration is off.
Set segment_id to the offending segment (e.g. "seg3"), or null for whole-video issues.
Use severity "blocker" only for genuinely broken output. Also give an overall_score 0-10.
"""


def review(
    provider: Provider, plan: LessonPlan, video_path: Path, *, num_frames: int = 12
) -> ReviewResult:
    frames = _sample_frames(video_path, num_frames)
    plan_blob = "\n".join(
        f"{s.id} [{s.modality.value}] {s.title}: {s.narration}" for s in plan.segments
    )
    prompt = (
        f"Topic: {plan.topic} (audience: {plan.audience})\n\n"
        f"Lesson plan:\n{plan_blob}\n\n"
        f"{len(frames)} frames follow, sampled in chronological order. Review the video."
    )
    # Two steps keep the Provider Protocol minimal: the vision model writes the
    # critique as prose, then chat_json structures it into ReviewResult.
    notes = provider.vision(prompt, frames, system=SYSTEM, max_tokens=2000)
    return provider.chat_json(
        f"Convert this review into the structured schema:\n\n{notes}",
        ReviewResult,
        system="You convert free-form review notes into the ReviewResult schema verbatim.",
        max_tokens=2000,
    )


def _sample_frames(video_path: Path, n: int) -> list[bytes]:
    """Grab n evenly spaced frames from the video as PNG bytes."""
    from ..mpcompat import VideoFileClip

    clip = VideoFileClip(str(video_path))
    try:
        from io import BytesIO

        from PIL import Image

        dur = clip.duration
        out: list[bytes] = []
        for i in range(n):
            t = dur * (i + 0.5) / n
            frame = clip.get_frame(t)  # HxWx3 ndarray
            buf = BytesIO()
            Image.fromarray(frame).save(buf, format="PNG")
            out.append(buf.getvalue())
        return out
    finally:
        clip.close()
