"""One-key, structured-request entry point.

    export OPENAI_API_KEY=sk-...
    python -m teachgen --request-json examples/regression_request.json

Options let you stop after Phase 1 (to review the plan), tune the feedback loop, or
override OpenAI models for an individual run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .config import Config
from .pipeline import generate, generate_from_plan, phase1_plan
from .providers import get_provider
from .schema import LessonPlan, TeachingRequest


def main() -> None:
    ap = argparse.ArgumentParser(prog="teachgen", description=__doc__)
    ap.add_argument("--request-json", required=True, help="path to the structured teaching request JSON")
    ap.add_argument(
        "--plan-json",
        help="optional existing lesson plan JSON; skips Phase 1 and renders/refines from this plan",
    )
    ap.add_argument("--text-model", help="override the text/planning/routing model")
    ap.add_argument(
        "--refinement-text-model",
        help="override the plan/repair/refinement text model",
    )
    ap.add_argument("--vision-model", help="override the vision/reviewer model")
    ap.add_argument("--visual-text-model", help="override the visual helper/code animation model")
    ap.add_argument(
        "--animation-code-model",
        help="override the OpenAI model used for Code2Video Manim code/refinement",
    )
    ap.add_argument("--tts-model", help="override the TTS model")
    ap.add_argument("--image-model", help="override the image model")
    ap.add_argument(
        "--plan-refinement-mode",
        choices=["none", "evaluator"],
        default="none",
        help="which inner plan refiner to use before video generation",
    )
    ap.add_argument("--max-plan-rounds", type=int, default=1, help="max inner plan-refinement rounds")
    ap.add_argument("--no-feedback", action="store_true", help="skip the MLLM review loop")
    ap.add_argument(
        "--feedback-mode",
        choices=["original", "evaluator", "none"],
        default="original",
        help="which outer reviewer to use during refinement",
    )
    ap.add_argument("--max-rounds", type=int, default=3, help="max outer feedback rounds")
    ap.add_argument("--score-threshold", type=float, default=8.0,
                    help="stop early when overall score >= this (0-10)")
    ap.add_argument(
        "--outer-plan-repair-threshold",
        type=int,
        default=3,
        help="trigger outer plan repair when a plan-level video metric is <= this",
    )
    ap.add_argument(
        "--outer-repair-mode",
        choices=["auto", "plan_only", "asset_only"],
        default="auto",
        help="limit evaluator-driven outer repairs; asset_only is useful for visual-refiner demos",
    )
    ap.add_argument(
        "--eval-baseline",
        action="store_true",
        help="run the evaluator on the produced video and save results under evaluator_baseline",
    )
    ap.add_argument(
        "--eval-chunk-seconds",
        type=float,
        default=120,
        help="chunk size used by the evaluator",
    )
    ap.add_argument(
        "--eval-frame-interval-seconds",
        type=float,
        default=2,
        help="seconds between frames sampled by the OpenAI evaluator",
    )
    ap.add_argument("--no-parallel", action="store_true")
    ap.add_argument("--max-workers", type=int, default=6)
    ap.add_argument(
        "--animation-mode",
        choices=["basic", "code2video_critic"],
        default="basic",
        help="basic uses the current one-pass animation path; code2video_critic enables Code2Video's grid visual critic loop",
    )
    ap.add_argument(
        "--animation-feedback-rounds",
        type=int,
        default=1,
        help="number of Code2Video visual critic repair rounds per animation segment",
    )
    ap.add_argument(
        "--animation-repair-policy",
        choices=["critic_first", "fallback_first"],
        default="critic_first",
        help="critic_first retries bad animations with the Code2Video critic once; fallback_first immediately changes bad animations to concept_image",
    )
    ap.add_argument(
        "--asset-repair-modalities",
        choices=["all", "animation"],
        default="all",
        help="limit evaluator-driven asset repair to all visual segments or animation-only segments",
    )
    ap.add_argument(
        "--concept-image-validation-retries",
        type=int,
        default=1,
        help="major-error regeneration attempts before concept images fall back to slides",
    )
    ap.add_argument(
        "--refinement-patience",
        type=int,
        default=1,
        help="stop after this many consecutive evaluated rounds fail to improve",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help="continue an interrupted nonempty run directory instead of refusing it",
    )
    ap.add_argument("--run-dir", default="runs")
    ap.add_argument(
        "--plan-only",
        action="store_true",
        help="run Phase 1 only and print the lesson plan, then stop",
    )
    args = ap.parse_args()
    feedback_mode = "none" if args.no_feedback else args.feedback_mode
    request_path = Path(args.request_json)
    request = TeachingRequest.model_validate_json(request_path.read_text(encoding="utf-8"))

    cfg = Config.from_env(
        request=request,
        plan_refinement_mode=args.plan_refinement_mode,
        max_plan_rounds=args.max_plan_rounds,
        use_feedback=feedback_mode != "none",
        feedback_mode=feedback_mode,
        max_outer_rounds=args.max_rounds,
        score_threshold=args.score_threshold,
        outer_plan_repair_threshold=args.outer_plan_repair_threshold,
        outer_repair_mode=args.outer_repair_mode,
        run_evaluator_baseline=args.eval_baseline,
        evaluator_chunk_seconds=args.eval_chunk_seconds,
        evaluator_frame_interval_seconds=args.eval_frame_interval_seconds,
        parallel=not args.no_parallel,
        max_workers=args.max_workers,
        animation_mode=args.animation_mode,
        animation_feedback_rounds=args.animation_feedback_rounds,
        animation_repair_policy=args.animation_repair_policy,
        asset_repair_modalities=args.asset_repair_modalities,
        concept_image_validation_retries=max(0, args.concept_image_validation_retries),
        refinement_patience=max(1, args.refinement_patience),
        resume=args.resume,
        run_dir=args.run_dir,
    )
    if args.text_model:
        cfg.models.text = args.text_model
    if args.refinement_text_model:
        cfg.models.refinement_text = args.refinement_text_model
    if args.vision_model:
        cfg.models.vision = args.vision_model
    if args.visual_text_model:
        cfg.models.visual_text = args.visual_text_model
    if args.animation_code_model:
        cfg.models.animation_code = args.animation_code_model
    if args.tts_model:
        cfg.models.tts = args.tts_model
    if args.image_model:
        cfg.models.image = args.image_model

    if args.plan_only:
        cfg.ensure_dirs()
        plan = phase1_plan(cfg, get_provider(cfg))
        print(json.dumps(json.loads(plan.model_dump_json()), indent=2, ensure_ascii=False))
        return

    if args.plan_json:
        plan_path = Path(args.plan_json)
        plan = LessonPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        result = generate_from_plan(cfg, plan)
    else:
        result = generate(cfg)
    print("\n=== Done ===")
    print("Lesson plan :", result["plan_path"])
    print("Final video :", result["video_path"])
    if result.get("evaluation_path"):
        print("Evaluation :", result["evaluation_path"])


if __name__ == "__main__":
    main()
