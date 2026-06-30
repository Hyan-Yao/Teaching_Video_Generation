"""Single source of configuration.

Everything funnels through here: the API key comes from the environment, model
names have sane defaults, and all paths hang off one run directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelConfig:
    """Which concrete models the default OpenRouter provider should use."""

    text: str = "openai/gpt-4o"                # planning, content writing, routing
    vision: str = "openai/gpt-4o"              # MLLM reviewer (reads sampled frames)
    tts: str = "x-ai/grok-voice-tts-1.0"       # narration synthesis
    transcribe: str = ""                       # only used by the optional OpenAI provider
    image: str = "openai/gpt-image-1"          # concept_image renderer


@dataclass
class Config:
    """Top-level run configuration. Construct via `Config.from_env(topic=...)`."""

    topic: str
    audience: str = "general learners"
    provider: str = "openrouter"    # "openrouter" (default) | "openai" | "gemini"
    api_key: str = ""

    models: ModelConfig = field(default_factory=ModelConfig)

    # Feedback loop
    use_feedback: bool = True
    feedback_mode: str = "original"  # "original" | "evaluator" | "none"
    max_feedback_rounds: int = 2

    # Optional post-run evaluator output
    run_evaluator_baseline: bool = False
    evaluator_chunk_seconds: float = 900

    # Execution
    parallel: bool = True
    max_workers: int = 6

    # Paths
    run_dir: Path = Path("runs")

    # Where the existing repos live (we adapt, not fork, them)
    repo_root: Path = Path(__file__).resolve().parent.parent

    @classmethod
    def from_env(cls, topic: str, **overrides) -> "Config":
        provider = overrides.get("provider", "openrouter")
        env_name = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
        api_key = os.environ.get(env_name, "")
        if not api_key and provider in {"openrouter", "openai"}:
            example = "sk-or-..." if provider == "openrouter" else "sk-..."
            raise SystemExit(
                f"{env_name} is not set. Export it first:\n"
                f"    export {env_name}={example}"
            )
        cfg = cls(topic=topic, api_key=api_key, **overrides)
        cfg.run_dir = Path(cfg.run_dir) / _safe_slug(topic)
        return cfg

    # --- derived paths (created lazily by the pipeline) ---
    @property
    def plan_path(self) -> Path:
        return self.run_dir / "lesson_plan.json"

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
