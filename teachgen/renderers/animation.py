"""`animation` renderer — drives code2video (code2video/agent.py) at single-segment grain.

teachgen owns the outline, so we DO NOT call agent.GENERATE_VIDEO() (its top-level
multi-section orchestration). Instead, per segment, we:

  1. Convert the segment into code2video's `Section` shape (short on-screen lecture
     lines, each paired with an animation description) via the Provider.
  2. Build a code2video RunConfig whose `api` callable is either a shim over our
     Provider (basic mode) or an OpenRouter Claude shim (critic mode). The basic
     path keeps Code2Video's visual feedback disabled. The critic path enables
     Code2Video's grid-based visual feedback loop while keeping external assets off.
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
import os
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

from ..schema import Modality, Segment, VisualAsset
from .base import RenderContext

# Code2Video renders at -ql (854x480 @ 15fps); the compositor upscales to 1080p.

STORYBOARD_SYSTEM = """\
You convert one teaching segment into a Manim storyboard for a 2D animation.
Produce SHORT on-screen lecture lines (each <= 8 words) and, for EACH line, one
concrete animation description of what should appear/move on the right side of the
screen to illustrate it. Keep it to 2-5 lines. The two lists MUST be the same
length and aligned by index.

Use the full lesson/request context to choose what the animation must preserve, but
make the actual animation simple and grid-friendly. Describe only simple 2D vector
graphics (shapes, arrows, labels, graphs) — no 3D, no external images, no dense
tables, and no full transcripts. Prefer one clear mechanism, comparison, or flow.
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
        )

        use_critic = ctx.cfg.animation_mode == "code2video_critic"
        cfg = agent_mod.RunConfig(
            api=_openrouter_code2video_api(ctx) if use_critic else _provider_api(ctx),
            use_feedback=use_critic,
            use_assets=False,
            feedback_rounds=max(0, ctx.cfg.animation_feedback_rounds),
            max_code_token_length=10000,
            max_regenerate_tries=2,
            max_fix_bug_tries=3,
            max_feedback_gen_code_tries=2,
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

        debug_dir = ctx.cfg.run_dir / "animation_debug" / seg.id
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
        if not ok or not mp4 or not Path(mp4).exists():
            raise RuntimeError(f"code2video failed to render {seg.id}")

        if code_file.exists():
            shutil.copy(code_file, debug_dir / "code_final.py")
        _write_feedback_debug(agent, debug_dir)

        out = ctx.out_dir / f"{seg.id}.mp4"
        shutil.copy(mp4, out)
        (debug_dir / "render_result.json").write_text(
            json.dumps(
                {
                    "animation_mode": ctx.cfg.animation_mode,
                    "source_mp4": str(mp4),
                    "copied_mp4": str(out),
                    "duration_seconds": _duration(out),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return VisualAsset(
            segment_id=seg.id, kind="video", path=str(out), duration=_duration(out)
        )

    def _storyboard(self, ctx: RenderContext, seg: Segment) -> _AnimSpec:
        plan = ctx.plan
        request = ctx.cfg.request
        target_seconds = ctx.audio_seconds or seg.target_seconds or 12
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
            "Produce aligned lecture_lines and animations. The animation should support "
            "the narration at a glance; the narration is the source of full detail. "
            "Use 2-5 visual steps only, in the same order the narration explains them. "
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
def _provider_api(ctx: RenderContext):
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
            model=ctx.cfg.models.visual_text,
        )
        return _Resp(text), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    return api


def _openrouter_code2video_api(ctx: RenderContext):
    """Code2Video-compatible API callable backed by OpenRouter for Manim code."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is required for --animation-mode code2video_critic"
        )

    model = ctx.cfg.models.animation_code

    class _Resp:
        def __init__(self, content):
            self.choices = [type("C", (), {"message": type("M", (), {"content": content})})]

    def api(prompt, max_tokens=8000, **_):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": min(max_tokens, 10000),
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Teaching_Video_Generation",
                "X-Title": "Teaching Video Generation",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter animation code call failed: {e.code} {detail}") from e

        body = json.loads(raw)
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not content:
            raise RuntimeError(f"OpenRouter animation code call returned no content: {raw[:500]}")
        usage = body.get("usage") or {}
        return _Resp(content), {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    return api


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
                "suggested_improvements": feedback.suggested_improvements,
                "raw_response": feedback.raw_response,
            }
        )
    if rows:
        (debug_dir / "critic_feedback.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


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
