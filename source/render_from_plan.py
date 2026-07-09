from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from teachgen.config import Config
from teachgen.feedback import eval_runner
from teachgen.pipeline import phase2_produce
from teachgen.providers import get_provider
from teachgen.schema import LessonPlan, TeachingRequest


def main() -> None:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Temporary helper: render/evaluate from an existing LessonPlan JSON."
    )
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--eval-baseline", action="store_true")
    parser.add_argument("--eval-chunk-seconds", type=float, default=900)
    parser.add_argument("--no-parallel", action="store_true")
    parser.add_argument("--max-workers", type=int, default=6)
    args = parser.parse_args()

    request = TeachingRequest.model_validate_json(
        Path(args.request_json).read_text(encoding="utf-8")
    )
    plan = LessonPlan.model_validate_json(Path(args.plan_json).read_text(encoding="utf-8"))

    cfg = Config.from_env(
        request=request,
        run_dir=args.run_dir,
        feedback_mode="none",
        use_feedback=False,
        max_outer_rounds=0,
        run_evaluator_baseline=args.eval_baseline,
        evaluator_chunk_seconds=args.eval_chunk_seconds,
        parallel=not args.no_parallel,
        max_workers=args.max_workers,
    )
    cfg.ensure_dirs()
    cfg.request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    provider = get_provider(cfg)
    result = phase2_produce(cfg, provider, plan)

    if args.eval_baseline:
        evaluation_path = eval_runner.run_lesson_evaluation(
            plan,
            result["video_path"],
            cfg.evaluator_baseline_dir,
            chunk_seconds=args.eval_chunk_seconds,
        )
        result["evaluation_path"] = str(evaluation_path)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
