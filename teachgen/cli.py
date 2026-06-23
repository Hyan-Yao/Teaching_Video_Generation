"""One-key, one-topic entry point.

    export OPENAI_API_KEY=sk-...
    python -m teachgen --topic "How the Fourier transform works"

Options let you stop after Phase 1 (to review the plan), tune the feedback loop, or
swap the backend provider.
"""

from __future__ import annotations

import argparse
import json

from .config import Config
from .pipeline import generate, phase1_plan
from .providers import get_provider


def main() -> None:
    ap = argparse.ArgumentParser(prog="teachgen", description=__doc__)
    ap.add_argument("--topic", required=True, help="the lesson topic")
    ap.add_argument("--audience", default="general learners")
    ap.add_argument("--provider", default="openai", choices=["openai", "gemini"])
    ap.add_argument("--no-feedback", action="store_true", help="skip the MLLM review loop")
    ap.add_argument(
        "--feedback-mode",
        choices=["original", "evaluator", "none"],
        default="original",
        help="which feedback reviewer to use during refinement",
    )
    ap.add_argument("--max-rounds", type=int, default=2, help="max feedback rounds")
    ap.add_argument(
        "--eval-baseline",
        action="store_true",
        help="run the evaluator on the produced video and save results under evaluator_baseline",
    )
    ap.add_argument(
        "--eval-chunk-seconds",
        type=float,
        default=900,
        help="chunk size used by the evaluator",
    )
    ap.add_argument("--no-parallel", action="store_true")
    ap.add_argument("--max-workers", type=int, default=6)
    ap.add_argument("--run-dir", default="runs")
    ap.add_argument(
        "--plan-only",
        action="store_true",
        help="run Phase 1 only and print the lesson plan, then stop",
    )
    args = ap.parse_args()
    feedback_mode = "none" if args.no_feedback else args.feedback_mode

    cfg = Config.from_env(
        topic=args.topic,
        audience=args.audience,
        provider=args.provider,
        use_feedback=feedback_mode != "none",
        feedback_mode=feedback_mode,
        max_feedback_rounds=args.max_rounds,
        run_evaluator_baseline=args.eval_baseline,
        evaluator_chunk_seconds=args.eval_chunk_seconds,
        parallel=not args.no_parallel,
        max_workers=args.max_workers,
        run_dir=args.run_dir,
    )

    if args.plan_only:
        cfg.ensure_dirs()
        plan = phase1_plan(cfg, get_provider(cfg))
        print(json.dumps(json.loads(plan.model_dump_json()), indent=2, ensure_ascii=False))
        return

    result = generate(cfg)
    print("\n=== Done ===")
    print("Lesson plan :", result["plan_path"])
    print("Final video :", result["video_path"])
    if result.get("evaluation_path"):
        print("Evaluation :", result["evaluation_path"])


if __name__ == "__main__":
    main()
