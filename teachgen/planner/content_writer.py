"""Topic -> teaching content (objectives + per-segment narration). Pure text."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..providers.base import Provider
from ..schema import TeachingRequest

SYSTEM = """\
You are an expert curriculum designer and lecturer. Given a structured teaching request,
you produce the SPOKEN CONTENT of a short teaching video: a tight set of learning
objectives, then an ordered list of segments. Each segment is one coherent beat of
the lecture with a title and the exact narration a teacher would say aloud.

Rules:
- Treat the topic, learning goal, key learning points, student persona, Bloom levels,
  and ICAP level as required design constraints.
- Cover every key learning point unless it is redundant with another point.
- Match the depth, pacing, examples, and prerequisite scaffolding to the student persona.
- Align the spoken lesson with the requested Bloom levels and ICAP level.
- 4 to 8 segments. Each narration is 2-5 sentences, conversational, no markdown.
- Build understanding progressively: hook -> intuition -> mechanism -> example -> recap.
- Write only what is SPOKEN. Do not describe visuals here; that comes later.
"""


class _DraftSegment(BaseModel):
    title: str
    narration: str = Field(..., description="What the teacher says aloud, 2-5 sentences")


class TeachingContent(BaseModel):
    topic: str
    audience: str
    objectives: list[str] = Field(..., description="3-5 concrete learning outcomes")
    segments: list[_DraftSegment]


def write_content(provider: Provider, request: TeachingRequest) -> TeachingContent:
    course = request.course
    pedagogy = request.pedagogy
    prompt = (
        f"Topic: {course.topic}\n\n"
        f"Learning goal:\n{course.learning_goal}\n\n"
        "Key learning points:\n"
        + "\n".join(f"- {point}" for point in course.key_learning_points)
        + "\n\n"
        f"Student persona:\n{request.student_persona}\n\n"
        f"Bloom levels: {', '.join(pedagogy.bloom_levels) or 'not specified'}\n"
        f"ICAP level: {pedagogy.icap_level or 'not specified'}\n\n"
        "Write the learning objectives and the ordered spoken segments now."
    )
    content = provider.chat_json(prompt, TeachingContent, system=SYSTEM, max_tokens=4000)
    # Trust the topic/audience we passed in over whatever the model echoes back.
    content.topic = course.topic
    content.audience = request.student_persona
    return content
