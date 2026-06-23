"""Evaluator-driven reviewer that returns the router's existing ReviewResult."""

from __future__ import annotations

from pathlib import Path

from teachgen.eval.models import EvaluationResult

from ..config import Config
from ..providers.base import Provider
from ..schema import LessonPlan, ReviewResult
from .eval_runner import run_lesson_evaluation
from .evaluation_adapter import adapt_evaluation_to_review


def review(
    provider: Provider,
    plan: LessonPlan,
    video_path: Path,
    cfg: Config,
    *,
    round_index: int = 0,
) -> ReviewResult:
    """Run the evaluator and adapt its findings into segment-level critiques."""
    output_dir = cfg.run_dir / f"evaluator_feedback_r{round_index}"
    result_path = run_lesson_evaluation(
        plan,
        video_path,
        output_dir,
        chunk_seconds=cfg.evaluator_chunk_seconds,
    )
    result = EvaluationResult.model_validate_json(
        result_path.read_text(encoding="utf-8")
    )
    return adapt_evaluation_to_review(provider, result, plan)
