"""Single source of configuration.

Everything funnels through here: the API key comes from the environment, model
names have sane defaults, and all paths hang off one run directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from .schema import TeachingRequest


@dataclass
class ModelConfig:
    """Which concrete models the default OpenAI provider should use."""

    text: str = "gpt-5.6-sol"             # planning, content writing, routing
    refinement_text: str = "gpt-5.6-sol"  # plan/repair/refinement LLM calls only
    vision: str = "gpt-5.6-sol"           # MLLM reviewer (reads sampled video frames)
    visual_text: str = "gpt-5.6-sol"      # slide/image prompts + first-pass animation code
    animation_code: str = "gpt-5.6-sol"   # Code2Video Manim code + visual repair
    tts: str = "gpt-4o-mini-tts"    # narration synthesis
    transcribe: str = "whisper-1"   # word-level timestamps for A/V alignment
    image: str = "gpt-image-2"      # concept_image renderer


@dataclass
class Config:
    """Top-level run configuration. Construct via `Config.from_env(request=...)`."""

    topic: str
    request: TeachingRequest
    audience: str = "general learners"
    provider: str = "openai"        # OpenAI is the only supported backend.
    api_key: str = ""
    models: ModelConfig = field(default_factory=ModelConfig)

    # Feedback loop
    plan_refinement_mode: str = "none"  # "none" | "evaluator"
    max_plan_rounds: int = 1            # inner plan-refinement cap
    use_feedback: bool = True
    feedback_mode: str = "original"  # "original" | "evaluator" | "none"
    max_outer_rounds: int = 3       # outer loop cap
    score_threshold: float = 8.0   # stop early when overall_score >= this
    outer_plan_repair_threshold: int = 3
    outer_repair_mode: str = "auto"  # "auto" | "plan_only" | "asset_only"

    # Optional post-run evaluator output
    run_evaluator_baseline: bool = False
    evaluator_chunk_seconds: float = 120
    evaluator_frame_interval_seconds: float = 2

    # Execution
    parallel: bool = True
    max_workers: int = 6
    animation_mode: str = "basic"  # "basic" | "code2video_critic"
    animation_feedback_rounds: int = 1
    animation_repair_policy: str = "critic_first"  # "critic_first" | "fallback_first"
    asset_repair_modalities: str = "all"  # "all" | "animation"
    concept_image_validation_retries: int = 1
    refinement_patience: int = 1
    resume: bool = False

    # Paths
    run_dir: Path = Path("runs")

    # Where the existing repos live (we adapt, not fork, them)
    repo_root: Path = Path(__file__).resolve().parent.parent

    @classmethod
    def from_env(cls, request: TeachingRequest, **overrides) -> "Config":
        topic = request.course.topic
        audience = request.student_persona
        provider = overrides.get("provider", "openai")
        env_name = "OPENAI_API_KEY"
        api_key = os.environ.get(env_name, "")
        if not api_key and provider == "openai":
            raise SystemExit(
                f"{env_name} is not set. Export it first:\n"
                f"    export {env_name}=sk-..."
            )
        cfg = cls(
            topic=topic,
            audience=audience,
            request=request,
            api_key=api_key,
            **overrides,
        )
        cfg.run_dir = Path(cfg.run_dir) / _safe_slug(topic)
        return cfg

    # --- derived paths (created lazily by the pipeline) ---
    @property
    def plan_path(self) -> Path:
        return self.run_dir / "lesson_plan.json"

    @property
    def request_path(self) -> Path:
        return self.run_dir / "request.json"

    @property
    def assets_dir(self) -> Path:
        return self.run_dir / "assets"      # per-segment visuals

    @property
    def audio_dir(self) -> Path:
        return self.run_dir / "audio"       # per-segment narration

    @property
    def video_dir(self) -> Path:
        return self.run_dir / "video"       # draft + final composites

    @property
    def evaluator_baseline_dir(self) -> Path:
        return self.run_dir / "evaluator_baseline"

    def ensure_dirs(self) -> None:
        for d in (self.run_dir, self.assets_dir, self.audio_dir, self.video_dir):
            d.mkdir(parents=True, exist_ok=True)


def _safe_slug(text: str, maxlen: int = 60) -> str:
    keep = [c if c.isalnum() else "-" for c in text.strip().lower()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:maxlen] or "untitled"
