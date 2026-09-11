"""`animation` renderer — drives code2video (code2video/agent.py) at single-segment grain.

teachgen owns the outline, so we DO NOT call agent.GENERATE_VIDEO() (its top-level
multi-section orchestration). Instead, per segment, we:

  1. Convert the segment into code2video's `Section` shape (short on-screen lecture
     lines, each paired with an animation description) via the Provider.
  2. Build a code2video RunConfig. Both paths use TeachGen's OpenAI Provider;
     critic mode adds post-render visual critique and code repair.
  3. Run generate_section_code() then render_section(), which renders Manim and runs
     the self-repair loop, landing an .mp4 in agent.section_videos[seg.id].
  4. Copy that clip into teachgen's assets dir and return it as a VisualAsset(video).

If Manim isn't installed or the render ultimately fails, this raises — and the
pipeline transparently falls back to a slide for that segment.
"""

from __future__ import annotations

import shutil
import sys
import importlib.util
import json
from pathlib import Path

import cv2
from pydantic import BaseModel, Field, model_validator

from ..schema import AnimationCritique, Modality, Segment, VisualAsset
from .base import RenderContext

# Code2Video renders at -ql (854x480 @ 15fps); the compositor upscales to 1080p.

STORYBOARD_SYSTEM = """\
You convert one teaching segment into a Manim storyboard for a 2D animation.
Produce SHORT on-screen lecture lines (each <= 8 words) and, for EACH line, one
concrete animation description of what should appear/move on the right side of the
screen to illustrate it. Keep it to 2-5 lines. The two lists MUST be the same
length and aligned by index. Also return matching step_start_seconds and
step_end_seconds lists based on the supplied synthesized-audio word timestamps.
All four lists MUST have the same length.

Use the full lesson/request context to choose what the animation must preserve, but
make the actual animation simple and grid-friendly. Describe only simple 2D vector
graphics (shapes, arrows, labels, graphs) — no 3D, no external images, no dense
tables, and no full transcripts. Prefer one clear mechanism, comparison, or flow.

If narration asks the learner to pause, calculate, predict, choose, or answer and
then supplies the answer later, create separate prompt and reveal storyboard steps.
The prompt step may show only the information needed to solve the task. It must not
contain the answer, completed calculation, highlighted result, or solution state.
The reveal step must begin when the answer is spoken according to the supplied word
timestamps. Never expose a later answer in an earlier storyboard step.
"""


class _AnimSpec(BaseModel):
    lecture_lines: list[str] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="2-5 short on-screen lines",
    )
    animations: list[str] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="One animation description per line",
    )
    step_start_seconds: list[float] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="Narration time when each visual step begins",
    )
    step_end_seconds: list[float] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="Narration time when each visual step ends",
    )

    @model_validator(mode="after")
    def _aligned_lists(self):
        lengths = {
            len(self.lecture_lines),
            len(self.animations),
            len(self.step_start_seconds),
            len(self.step_end_seconds),
        }
        if len(lengths) != 1:
            raise ValueError("storyboard lines, animations, and timing lists must align")
        return self


class AnimationRenderer:
    modality = Modality.ANIMATION

    def render(self, seg: Segment, ctx: RenderContext) -> VisualAsset:
        agent_mod, base_class = _load_code2video(ctx.cfg.repo_root)

        spec = self._storyboard(ctx, seg)
        target_seconds = ctx.audio_seconds or seg.target_seconds or 12
        section = agent_mod.Section(
            id=seg.id,
            title=seg.title,
            lecture_lines=spec.lecture_lines,
            animations=spec.animations,
            target_seconds=target_seconds,
            step_timings=_normalize_step_timings(spec, target_seconds),
        )

        use_critic = ctx.cfg.animation_mode == "code2video_critic"
        cfg = agent_mod.RunConfig(
            api=_openai_code2video_api(ctx) if use_critic else _provider_api(ctx),
            critic_api=_openai_code2video_api(ctx) if use_critic else None,
            critic_vision_api=_openai_visual_critic_api(ctx) if use_critic else None,
            use_feedback=use_critic,
            use_assets=False,
            feedback_rounds=max(0, ctx.cfg.animation_feedback_rounds),
            max_code_token_length=10000,
            max_regenerate_tries=2,
            max_fix_bug_tries=3,
            max_feedback_gen_code_tries=1,
            max_mllm_fix_bugs_tries=2,
        )

        # code2video hard-codes a "CASES" layout and resolves json_files relative to it.
        folder = ctx.cfg.repo_root / "code2video" / "CASES" / f"tg_{ctx.cfg.run_dir.name}"
        agent = agent_mod.TeachingVideoAgent(
            idx=0, knowledge_point=seg.title, folder=folder, cfg=cfg
        )

        # Force fresh code each round (code2video reuses an existing <id>.py otherwise).
        code_file = agent.output_dir / f"{seg.id}.py"
        if code_file.exists():
            code_file.unlink()

        debug_dir = (
            ctx.cfg.run_dir
            / "animation_debug"
            / seg.id
            / f"round_{ctx.render_round}"
        )
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "storyboard.json").write_text(
            spec.model_dump_json(indent=2),
            encoding="utf-8",
        )

        agent.generate_section_code(section, attempt=1)
        if code_file.exists():
            shutil.copy(code_file, debug_dir / "code_initial.py")

        ok = agent.render_section(section)
        mp4 = agent.section_videos.get(seg.id)
        if code_file.exists():
            shutil.copy(
                code_file,
                debug_dir / ("code_final.py" if ok else "code_rejected.py"),
            )
        _write_feedback_debug(agent, debug_dir)
        _copy_critic_versions(agent, debug_dir, seg.id)
        if not ok or not mp4 or not Path(mp4).exists():
            raise RuntimeError(f"code2video failed to render {seg.id}")

        out = ctx.out_dir / f"{seg.id}.mp4"
        shutil.copy(mp4, out)
        (debug_dir / "render_result.json").write_text(
            json.dumps(
                {
                    "animation_mode": ctx.cfg.animation_mode,
                    "source_mp4": str(mp4),
                    "copied_mp4": str(out),
                    "duration_seconds": _duration(out),
                    "step_timings": section.step_timings,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return VisualAsset(
            segment_id=seg.id,
            kind="video",
            path=str(out),
            duration=_duration(out),
            intended_modality=seg.modality,
            rendered_modality=Modality.ANIMATION,
            validation_status="passed",
        )

    def _storyboard(self, ctx: RenderContext, seg: Segment) -> _AnimSpec:
        plan = ctx.plan
        request = ctx.cfg.request
        target_seconds = ctx.audio_seconds or seg.target_seconds or 12
        timed_words = _format_word_timings(ctx.word_timings)
        neighbors = _neighbor_context(plan, seg.id) if plan else "Unavailable"
        objectives = "\n".join(f"- {obj}" for obj in (plan.objectives if plan else []))
        key_points = "\n".join(f"- {kp}" for kp in request.course.key_learning_points)
        prompt = (
            "Structured request context:\n"
            f"Topic: {request.course.topic}\n"
            f"Learning goal: {request.course.learning_goal}\n"
            f"Key learning points:\n{key_points}\n"
            f"Student persona: {request.student_persona}\n"
            f"Bloom levels: {', '.join(request.pedagogy.bloom_levels)}\n"
            f"ICAP level: {request.pedagogy.icap_level}\n\n"
            "Lesson context:\n"
            f"Objectives:\n{objectives or '- Unavailable'}\n"
            f"Neighboring segments: {neighbors}\n\n"
            "Target segment:\n"
            f"Segment id: {seg.id}\n"
            f"Title: {seg.title}\n"
            f"Narration: {seg.narration}\n"
            f"Visual brief: {seg.visual_brief}\n"
            f"Rationale: {seg.rationale}\n"
            f"Target/audio duration: ~{target_seconds:.0f}s\n\n"
            "Actual narration word timings from the synthesized audio:\n"
            f"{timed_words or '[Word timings unavailable; estimate from the total duration.]'}\n\n"
            "Produce aligned lecture_lines and animations. The animation should support "
            "the narration at a glance; the narration is the source of full detail. "
            "Use 2-5 visual steps only, in the same order the narration explains them. "
            "For every visual step, return step_start_seconds and step_end_seconds that "
            "match when the corresponding idea is actually spoken in the timestamped "
            "audio. The four lists must have the same length. Start the first step at "
            "0 seconds, keep timings ordered and non-overlapping, and end the final "
            f"step at about {target_seconds:.2f} seconds. "
            "If the narration asks the learner to pause, calculate, predict, choose, "
            "or answer before giving a solution, allocate one answer-free prompt step "
            "and a later reveal step. Use the word timings to begin the reveal only "
            "when the answer is spoken. "
            "Do not add extra examples or labels that are not spoken in this segment. "
            "Avoid crowded text and choose visuals that fit safely in Code2Video's "
            "right-side grid."
        )
        return ctx.provider.chat_json(
            prompt,
            _AnimSpec,
            system=STORYBOARD_SYSTEM,
            max_tokens=1500,
            model=ctx.cfg.models.visual_text,
        )


# --------------------------------------------------------------------- helpers
def _provider_api(ctx: RenderContext, *, model: str | None = None):
    """A code2video-compatible `api` callable backed by teachgen's Provider.

    code2video calls `response, usage = api(prompt, max_tokens=...)` and reads
    `response.choices[0].message.content`. We mimic just that shape.
    """
    provider = ctx.provider

    class _Resp:
        def __init__(self, content):
            self.choices = [type("C", (), {"message": type("M", (), {"content": content})})]

    def api(prompt, max_tokens=8000, **_):
        text = provider.chat(
            prompt,
            max_tokens=min(max_tokens, 8000),
            model=model or ctx.cfg.models.visual_text,
        )
        return _Resp(text), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    return api


def _openai_code2video_api(ctx: RenderContext):
    """Code2Video-compatible OpenAI callable for animation code and repair."""
    return _provider_api(ctx, model=ctx.cfg.models.animation_code)


def _openai_visual_critic_api(ctx: RenderContext):
    """Code2Video critic callable backed by GPT-5 image input."""
    model = ctx.cfg.models.animation_code

    class _Resp:
        def __init__(self, content, sampled_timestamps=None):
            self.choices = [type("C", (), {"message": type("M", (), {"content": content})})]
            self.sampled_timestamps = sampled_timestamps or []

    def critic(prompt, video_path, image_path, section=None, max_tokens=4000, **_):
        frames, timestamps = _extract_stable_video_frames(video_path, section)
        timestamp_note = ", ".join(f"frame {i + 1}={value:.2f}s" for i, value in enumerate(timestamps))
        prompt = (
            f"{prompt}\n\nStable sample timestamps in image order: {timestamp_note}. "
            "The final image is the grid reference, not a video frame."
        )
        images = [*frames, _read_image(image_path)]
        content_text = ctx.provider.vision(
            prompt,
            images,
            max_tokens=min(max_tokens, 4000),
            model=model,
        )
        if not content_text:
            raise RuntimeError("OpenAI animation critic returned no content")
        content_text = _normalize_animation_critique(content_text)
        return _Resp(content_text, timestamps)

    return critic


def _normalize_animation_critique(raw: str) -> str:
    """Validate the visual critic's bounded action schema before code touches it."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    payload = json.loads(text)
    layout = payload.get("layout", payload)
    critique = AnimationCritique.model_validate(
        {
            "has_issues": layout.get("has_issues", False),
            "severity": layout.get("severity", "minor"),
            "persistent": layout.get("persistent", False),
            "summary": layout.get("summary", ""),
            "repairs": layout.get("improvements", []),
        }
    )
    return json.dumps(
        {
            "layout": {
                "has_issues": critique.has_issues,
                "severity": critique.severity,
                "persistent": critique.persistent,
                "summary": critique.summary,
                "improvements": [item.model_dump() for item in critique.repairs],
            }
        },
        ensure_ascii=False,
    )


def _extract_stable_video_frames(video_path: str, section=None) -> tuple[list[bytes], list[float]]:
    """Sample consecutive low-motion states near each storyboard-step end."""
    cap = cv2.VideoCapture(video_path)
    total = max(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 1)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 15.0)
    duration = total / fps
    timings = getattr(section, "step_timings", None) or []
    timestamps: list[float] = []
    if timings:
        for timing in timings:
            start = max(0.0, float(timing.get("start_seconds", 0.0)))
            end = min(duration, float(timing.get("end_seconds", duration)))
            if end <= start:
                continue
            stable_pair = _stable_pair_near_step_end(cap, start, end, fps)
            if stable_pair:
                timestamps.extend(stable_pair)
            else:
                # Retain deterministic late-step coverage when generated code never
                # settles, allowing the critic to diagnose continuous motion.
                timestamps.extend((start + (end - start) * 0.82, start + (end - start) * 0.94))
    else:
        timestamps = [duration * frac for frac in (0.2, 0.4, 0.6, 0.8, 0.96)]

    unique_timestamps: list[float] = []
    for value in timestamps:
        value = max(0.0, min(value, max(0.0, duration - 1 / fps)))
        if not unique_timestamps or abs(value - unique_timestamps[-1]) >= 0.05:
            unique_timestamps.append(value)

    frames: list[bytes] = []
    kept_timestamps: list[float] = []
    for timestamp in unique_timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = cap.read()
        if ok:
            _, buf = cv2.imencode(".jpg", frame)
            frames.append(buf.tobytes())
            kept_timestamps.append(timestamp)
    cap.release()
    return frames, kept_timestamps


def _stable_pair_near_step_end(
    cap: cv2.VideoCapture,
    start: float,
    end: float,
    fps: float,
) -> tuple[float, float] | None:
    """Find two frames inside a >=0.5s low-motion plateau late in one step."""
    window_start = start + (end - start) * 0.5
    probe_step = min(0.25, max(0.12, 2.0 / max(fps, 1.0)))
    times: list[float] = []
    value = window_start
    while value < end - (1.0 / max(fps, 1.0)):
        times.append(value)
        value += probe_step
    if len(times) < 3:
        return None

    thumbnails: list = []
    valid_times: list[float] = []
    for timestamp in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        thumbnails.append(cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA))
        valid_times.append(timestamp)
    if len(thumbnails) < 3:
        return None

    stable_pairs = [
        float(cv2.absdiff(left, right).mean()) <= 0.03
        for left, right in zip(thumbnails, thumbnails[1:])
    ]
    runs: list[tuple[int, int]] = []
    run_start = None
    for index, stable in enumerate([*stable_pairs, False]):
        if stable and run_start is None:
            run_start = index
        elif not stable and run_start is not None:
            runs.append((run_start, index))
            run_start = None

    minimum_pairs = max(2, int(round(0.5 / probe_step)))
    eligible = [run for run in runs if run[1] - run[0] >= minimum_pairs]
    if not eligible:
        return None
    run_start, run_end = max(eligible, key=lambda run: (run[1], run[1] - run[0]))
    first_index = run_start + max(1, (run_end - run_start) // 2)
    second_index = run_end
    return valid_times[first_index], valid_times[second_index]


def _format_word_timings(words) -> str:
    if not words:
        return ""
    return " ".join(
        f"[{float(word.start):.2f}-{float(word.end):.2f}] {word.word}"
        for word in words
        if str(word.word).strip()
    )


def _normalize_step_timings(spec: _AnimSpec, target_seconds: float) -> list[dict]:
    """Clamp model-selected narration windows into a complete monotonic timeline."""
    target = max(float(target_seconds), 0.5)
    count = len(spec.lecture_lines)
    starts = [float(value) for value in spec.step_start_seconds]
    ends = [float(value) for value in spec.step_end_seconds]
    boundaries = [0.0]

    for index in range(1, count):
        proposed = (ends[index - 1] + starts[index]) / 2
        minimum = boundaries[-1] + 0.25
        maximum = target - (count - index) * 0.25
        boundaries.append(min(max(proposed, minimum), maximum))
    boundaries.append(target)

    return [
        {
            "start_seconds": round(boundaries[index], 3),
            "end_seconds": round(boundaries[index + 1], 3),
            "duration_seconds": round(boundaries[index + 1] - boundaries[index], 3),
        }
        for index in range(count)
    ]


def _read_image(image_path) -> bytes:
    with open(image_path, "rb") as f:
        return f.read()


def _neighbor_context(plan, segment_id: str) -> str:
    segments = list(plan.segments)
    for idx, item in enumerate(segments):
        if item.id == segment_id:
            prev_title = segments[idx - 1].title if idx > 0 else "None"
            next_title = segments[idx + 1].title if idx + 1 < len(segments) else "None"
            return f"previous={prev_title}; current={item.title}; next={next_title}"
    return "Unavailable"


def _write_feedback_debug(agent, debug_dir: Path) -> None:
    rows = []
    for key, feedback in getattr(agent, "video_feedbacks", {}).items():
        rows.append(
            {
                "key": key,
                "section_id": feedback.section_id,
                "video_path": feedback.video_path,
                "has_issues": feedback.has_issues,
                "severity": feedback.severity,
                "persistent": feedback.persistent,
                "sampled_timestamps": feedback.sampled_timestamps,
                "rejection_reason": feedback.rejection_reason,
                "suggested_improvements": feedback.suggested_improvements,
                "raw_response": feedback.raw_response,
            }
        )
    if rows:
        (debug_dir / "critic_feedback.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _copy_critic_versions(agent, debug_dir: Path, segment_id: str) -> None:
    versions_dir = Path(agent.output_dir) / "critic_versions"
    if not versions_dir.is_dir():
        return
    for source in versions_dir.glob(f"{segment_id}_*.mp4"):
        shutil.copy2(source, debug_dir / source.name)


def _load_code2video(repo_root: Path):
    """Lazy-import code2video/agent.py (pulls Manim). repo_root and code2video/ must import."""
    code2video_dir = repo_root / "code2video"
    for p in (str(code2video_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)

    agent_path = code2video_dir / "agent.py"
    spec = importlib.util.spec_from_file_location("teachgen_code2video_agent", agent_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load code2video agent from {agent_path}")
    agent = importlib.util.module_from_spec(spec)
    sys.modules["teachgen_code2video_agent"] = agent
    spec.loader.exec_module(agent)

    from prompts import base_class  # noqa: E402  (repo_root/prompts)

    return agent, base_class


def _duration(path: Path) -> float:
    try:
        from ..mpcompat import VideoFileClip

        clip = VideoFileClip(str(path))
        d = float(clip.duration)
        clip.close()
        return d
    except Exception:
        return 0.0
