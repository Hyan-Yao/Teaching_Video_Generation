"""Top-level orchestration: Phase 1 (plan) -> Phase 2 (media + feedback loop).

This is the only place that knows the end-to-end flow. Each stage talks to the next
purely through schema objects, and per-segment work fans out across a thread pool.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Config
from teachgen.eval.models import EvaluationResult

from .feedback import eval_runner, evaluator_reviewer, evaluation_adapter
from .feedback import lesson_plan_refiner, plan_evaluator
from .feedback import (
    outer_plan_refiner,
    outer_repair_decider,
    outer_reviewer,
    plan_refiner,
    router,
    visual_refiner,
)
from .planner import content_writer, route
from .providers import get_provider
from .providers.base import Provider
from .mpcompat import VideoFileClip
from .renderers import get_renderer
from .renderers.base import RenderContext
from .schema import ContentIssue, LessonPlan, Modality, NarrationAudio, OuterReview, ReviewResult, Segment, VisualAsset, VisualIssue
from .audio import narrator
from .compositor import compositor


def generate(cfg: Config) -> dict:
    _prepare_run_directory(cfg)
    cfg.ensure_dirs()
    cfg.request_path.write_text(
        cfg.request.model_dump_json(indent=2),
        encoding="utf-8",
    )
    provider = get_provider(cfg)

    if cfg.resume and cfg.plan_path.exists():
        plan = LessonPlan.model_validate_json(cfg.plan_path.read_text(encoding="utf-8"))
        _log(f"Resuming with saved lesson plan -> {cfg.plan_path}")
    else:
        plan = phase1_plan(cfg, provider)
    result = phase2_produce(cfg, provider, plan)
    plan = LessonPlan.model_validate_json(cfg.plan_path.read_text(encoding="utf-8"))
    if cfg.run_evaluator_baseline:
        video_path = result["video_path"]
        last_evaluation_path = result.get("last_evaluation_path")
        last_evaluated_video_sha = result.get("last_evaluated_video_sha256")
        video_sha = _file_sha256(Path(video_path))
        if last_evaluation_path and last_evaluated_video_sha == video_sha:
            _log(
                "Reusing last evaluator result for baseline; "
                "final video matches the last evaluated draft."
            )
            evaluation_path = _copy_evaluation_outputs(
                Path(last_evaluation_path),
                cfg.evaluator_baseline_dir,
            )
        else:
            _log(f"Running evaluator baseline -> {cfg.evaluator_baseline_dir}")
            evaluation_path = eval_runner.run_lesson_evaluation(
                plan,
                video_path,
                cfg.evaluator_baseline_dir,
                chunk_seconds=cfg.evaluator_chunk_seconds,
                frame_interval_seconds=cfg.evaluator_frame_interval_seconds,
            )
        result["evaluation_path"] = str(evaluation_path)
    return result


def generate_from_plan(cfg: Config, plan: LessonPlan) -> dict:
    """Run media production from an existing lesson plan for controlled A/B tests."""
    _prepare_run_directory(cfg)
    cfg.ensure_dirs()
    cfg.request_path.write_text(
        cfg.request.model_dump_json(indent=2),
        encoding="utf-8",
    )
    cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    provider = get_provider(cfg)

    result = phase2_produce(cfg, provider, plan)
    if cfg.run_evaluator_baseline:
        video_path = result["video_path"]
        last_evaluation_path = result.get("last_evaluation_path")
        last_evaluated_video_sha = result.get("last_evaluated_video_sha256")
        video_sha = _file_sha256(Path(video_path))
        if last_evaluation_path and last_evaluated_video_sha == video_sha:
            _log(
                "Reusing last evaluator result for baseline; "
                "final video matches the last evaluated draft."
            )
            evaluation_path = _copy_evaluation_outputs(
                Path(last_evaluation_path),
                cfg.evaluator_baseline_dir,
            )
        else:
            _log(f"Running evaluator baseline -> {cfg.evaluator_baseline_dir}")
            evaluation_path = eval_runner.run_lesson_evaluation(
                plan,
                video_path,
                cfg.evaluator_baseline_dir,
                chunk_seconds=cfg.evaluator_chunk_seconds,
                frame_interval_seconds=cfg.evaluator_frame_interval_seconds,
            )
        result["evaluation_path"] = str(evaluation_path)
    return result


# ============================================================ PHASE 1 (text)
def phase1_plan(cfg: Config, provider: Provider) -> LessonPlan:
    _log("Phase 1: writing teaching content...")
    content = content_writer.write_content(provider, cfg.request)

    _log("Phase 1: routing segments to renderers...")
    plan = route.plan_lesson(provider, content, cfg.request)

    if cfg.plan_refinement_mode == "evaluator":
        plan = _refine_lesson_plan(cfg, provider, plan)

    cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    _log(f"Phase 1: lesson plan -> {cfg.plan_path}")
    for s in plan.segments:
        _log(f"   {s.id}  [{s.modality.value:<13}] {s.title}")
    return plan


def _refine_lesson_plan(cfg: Config, provider: Provider, plan: LessonPlan) -> LessonPlan:
    initial_path = cfg.run_dir / "lesson_plan_initial.json"
    initial_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    _log(f"Phase 1: initial lesson plan -> {initial_path}")

    for rnd in range(cfg.max_plan_rounds + 1):
        _log(f"Phase 1: evaluating lesson plan (round {rnd})...")
        evaluation = plan_evaluator.evaluate_plan(provider, cfg.request, plan)
        eval_path = cfg.run_dir / f"plan_eval_r{rnd}.json"
        eval_path.write_text(evaluation.model_dump_json(indent=2), encoding="utf-8")
        _log(
            f"   plan_score={evaluation.overall_score:.2f}  "
            f"requires_revision={evaluation.requires_revision}"
        )

        if not evaluation.requires_revision:
            break
        if rnd >= cfg.max_plan_rounds:
            _log("   max plan-refinement rounds reached; using latest plan.")
            break

        _log(f"Phase 1: refining lesson plan (round {rnd + 1})...")
        plan = lesson_plan_refiner.refine_plan(provider, cfg.request, plan, evaluation)
        refined_path = cfg.run_dir / f"lesson_plan_refined_r{rnd + 1}.json"
        refined_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        _log(f"   refined lesson plan -> {refined_path}")

    return plan


# ========================================================== PHASE 2 (media)
def phase2_produce(cfg: Config, provider: Provider, plan: LessonPlan) -> dict:
    """Nested feedback loop:

    Outer loop  (≤ max_outer_rounds, stops early when score ≥ score_threshold)
      ├─ Inner Loop 1 — Plan refinement   (narration / visual_brief edits)
      └─ Inner Loop 2 — Visual refinement (re-render broken segments)

    Caches are keyed by segment id; only dirty segments are re-produced each round.
    """
    if cfg.use_feedback and cfg.feedback_mode == "evaluator":
        return _phase2_evaluator_produce(cfg, provider, plan)

    audio_cache: dict[str, NarrationAudio] = {}
    visual_cache: dict[str, VisualAsset] = {}
    draft_path = None
    last_evaluation_path = None
    last_evaluated_video_sha = None

    for outer_rnd in range(cfg.max_outer_rounds + 1):
        # --- render all dirty segments ---
        dirty = {s.id for s in plan.segments if s.id not in visual_cache}
        if dirty:
            if outer_rnd > 0:
                _log(f"Outer round {outer_rnd}: re-producing {len(dirty)} segment(s)")
            _produce_assets(
                cfg,
                provider,
                plan,
                dirty,
                audio_cache,
                visual_cache,
                is_refinement_render=outer_rnd > 0,
                render_round=outer_rnd,
            )

        # --- composite ---
        feedback_disabled = not cfg.use_feedback or cfg.feedback_mode == "none"
        is_last = (outer_rnd == cfg.max_outer_rounds) or feedback_disabled
        draft_name = "final.mp4" if is_last else f"draft_r{outer_rnd}.mp4"
        draft_path = cfg.video_dir / draft_name
        _log(f"Compositing → {draft_path}")
        compositor.assemble(
            [visual_cache[s.id] for s in plan.segments],
            [audio_cache[s.id] for s in plan.segments],
            draft_path,
        )

        if feedback_disabled or is_last:
            break

        if cfg.feedback_mode == "evaluator":
            evaluation_dir = cfg.run_dir / f"evaluator_feedback_r{outer_rnd}"
            _log(f"Outer video evaluation (round {outer_rnd}) -> {evaluation_dir}")
            evaluation_path = eval_runner.run_lesson_evaluation(
                plan,
                draft_path,
                evaluation_dir,
                chunk_seconds=cfg.evaluator_chunk_seconds,
                frame_interval_seconds=cfg.evaluator_frame_interval_seconds,
            )
            last_evaluation_path = evaluation_path
            last_evaluated_video_sha = _file_sha256(draft_path)
            evaluation = EvaluationResult.model_validate_json(
                evaluation_path.read_text(encoding="utf-8")
            )

            evaluated_plan = plan.model_copy(deep=True)
            revised_plan, decision, plan_evaluation = (
                outer_plan_refiner.refine_from_video_evaluation(
                    provider,
                    cfg.request,
                    plan,
                    evaluation,
                    threshold=cfg.outer_plan_repair_threshold,
                    repair_mode=cfg.outer_repair_mode,
                )
            )
            (cfg.run_dir / f"outer_repair_decision_r{outer_rnd}.json").write_text(
                decision.model_dump_json(indent=2),
                encoding="utf-8",
            )

            if decision.repair_type == "asset":
                _log(
                    "Outer asset repair triggered: "
                    f"{', '.join(decision.priority_metrics)}"
                )
                review = evaluation_adapter.adapt_evaluation_to_review(
                    provider,
                    evaluation,
                    plan,
                    debug_dir=evaluation_dir,
                )
                review = _filter_asset_review_by_modality(cfg, plan, review)
                (cfg.run_dir / f"asset_review_r{outer_rnd}.json").write_text(
                    review.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                dirty_full, dirty_visual = router.apply_with_cache_hints(
                    provider,
                    plan,
                    review,
                )
                if not dirty_full and not dirty_visual:
                    _log("No actionable asset repairs; finalizing.")
                    draft_path = _finalize(cfg, draft_path)
                    break

                for sid in dirty_full:
                    audio_cache.pop(sid, None)
                    visual_cache.pop(sid, None)
                for sid in dirty_visual:
                    visual_cache.pop(sid, None)
                cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
                continue

            if decision.repair_type != "plan":
                _log(f"Outer repair decision: {decision.repair_type}; finalizing.")
                draft_path = _finalize(cfg, draft_path)
                break

            _log(
                "Outer plan repair triggered: "
                f"{', '.join(decision.priority_metrics)}"
            )
            if plan_evaluation is not None:
                (
                    cfg.run_dir / f"outer_plan_feedback_r{outer_rnd}.json"
                ).write_text(
                    plan_evaluation.model_dump_json(indent=2),
                    encoding="utf-8",
                )

            plan = revised_plan
            refined_path = cfg.run_dir / f"outer_lesson_plan_refined_r{outer_rnd + 1}.json"
            refined_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

            _log(f"Outer refined lesson plan -> {refined_path}")
            _log(f"Evaluating outer refined plan (round {outer_rnd + 1})...")
            after_eval = plan_evaluator.evaluate_plan(provider, cfg.request, plan)
            after_eval_path = cfg.run_dir / f"outer_plan_eval_after_r{outer_rnd + 1}.json"
            after_eval_path.write_text(
                after_eval.model_dump_json(indent=2),
                encoding="utf-8",
            )
            _log(
                f"   outer_plan_score={after_eval.overall_score:.2f}  "
                f"requires_revision={after_eval.requires_revision}"
            )

            dirty_full, dirty_visual = _plan_cache_changes(evaluated_plan, plan)

            # Plan and visual weaknesses can coexist. In auto mode, handle both
            # from this evaluation instead of allowing the plan decision to starve
            # the targeted asset repair path.
            if cfg.outer_repair_mode == "auto":
                asset_decision = outer_repair_decider.decide_outer_repair(
                    evaluation,
                    threshold=cfg.outer_plan_repair_threshold,
                    repair_mode="asset_only",
                )
                (
                    cfg.run_dir / f"outer_asset_repair_decision_r{outer_rnd}.json"
                ).write_text(
                    asset_decision.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                if asset_decision.repair_type == "asset":
                    _log(
                        "Outer asset repair also triggered: "
                        f"{', '.join(asset_decision.priority_metrics)}"
                    )
                    asset_metrics = set(asset_decision.priority_metrics)
                    asset_evaluation = evaluation.model_copy(
                        update={
                            "scores": [
                                score
                                for score in evaluation.scores
                                if score.metric in asset_metrics
                            ]
                        },
                        deep=True,
                    )
                    review = evaluation_adapter.adapt_evaluation_to_review(
                        provider,
                        asset_evaluation,
                        evaluated_plan,
                        debug_dir=evaluation_dir,
                    )
                    review = _filter_asset_review_by_modality(cfg, plan, review)
                    (cfg.run_dir / f"asset_review_r{outer_rnd}.json").write_text(
                        review.model_dump_json(indent=2),
                        encoding="utf-8",
                    )
                    asset_dirty_full, asset_dirty_visual = router.apply_with_cache_hints(
                        provider,
                        plan,
                        review,
                    )
                    dirty_full |= asset_dirty_full
                    dirty_visual |= asset_dirty_visual

            dirty_visual -= dirty_full
            if not dirty_full and not dirty_visual:
                _log("Plan/asset repair produced no media changes; finalizing.")
                draft_path = _finalize(cfg, draft_path)
                break

            _invalidate_caches(
                audio_cache,
                visual_cache,
                dirty_full=dirty_full,
                dirty_visual=dirty_visual,
            )
            cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            continue

        # --- outer review ---
        rev = _review_composite(cfg, provider, plan, draft_path, outer_rnd)
        _log(
            f"  score={rev.overall_score:.1f}  "
            f"content_issues={len(rev.content_issues)}  "
            f"visual_issues={len(rev.visual_issues)}"
        )
        (cfg.run_dir / f"review_r{outer_rnd}.json").write_text(
            rev.model_dump_json(indent=2), encoding="utf-8"
        )

        # early-stop when quality is good enough
        if rev.overall_score >= cfg.score_threshold:
            _log(f"Score {rev.overall_score:.1f} ≥ {cfg.score_threshold} — done.")
            draft_path = _finalize(cfg, draft_path)
            break

        if not rev.needs_plan_fix and not rev.needs_visual_fix:
            _log("No actionable issues; finalizing.")
            draft_path = _finalize(cfg, draft_path)
            break

        # --- Inner Loop 1: plan refinement (narration / visual_brief) ---
        if rev.needs_plan_fix:
            _log(f"  Inner Loop 1 — plan refinement ({len(rev.content_issues)} issues)")
            dirty_full, dirty_visual_only = plan_refiner.refine(
                provider, plan, rev.content_issues
            )
            for sid in dirty_full:          # narration changed → re-TTS + re-render
                audio_cache.pop(sid, None)
                visual_cache.pop(sid, None)
            for sid in dirty_visual_only:   # brief changed only → re-render only
                visual_cache.pop(sid, None)
            cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        # --- Inner Loop 2: visual refinement (re-render broken segments) ---
        if rev.needs_visual_fix:
            _log(f"  Inner Loop 2 — visual refinement ({len(rev.visual_issues)} issues)")
            dirty_visual = visual_refiner.refine(provider, plan, rev.visual_issues)
            for sid in dirty_visual:        # brief updated → re-render only
                visual_cache.pop(sid, None)

    return {
        "plan_path": str(cfg.plan_path),
        "video_path": str(draft_path),
        "last_evaluation_path": str(last_evaluation_path) if last_evaluation_path else None,
        "last_evaluated_video_sha256": last_evaluated_video_sha,
    }


def _phase2_evaluator_produce(cfg: Config, provider: Provider, plan: LessonPlan) -> dict:
    """Evaluator loop with cause routing, patience, and best-draft selection."""
    audio_cache, visual_cache = _load_resume_caches(cfg, plan) if cfg.resume else ({}, {})
    manifest_path = cfg.run_dir / "round_manifest.json"
    rounds: list[dict] = []
    if cfg.resume and manifest_path.exists():
        try:
            rounds = json.loads(manifest_path.read_text(encoding="utf-8")).get("rounds", [])
        except Exception:
            rounds = []
    start_round = (max((int(item["round"]) for item in rounds), default=-1) + 1)
    best = _best_saved_round(rounds)
    non_improving = 0
    pending_targets = _pending_repair_targets(rounds, start_round)

    for outer_rnd in range(start_round, cfg.max_outer_rounds + 1):
        render_debug_round = _fresh_render_debug_round(cfg, outer_rnd)
        dirty = {segment.id for segment in plan.segments if segment.id not in visual_cache}
        if dirty:
            _produce_assets(
                cfg,
                provider,
                plan,
                dirty,
                audio_cache,
                visual_cache,
                is_refinement_render=outer_rnd > 0,
                render_round=render_debug_round,
            )

        draft_path = cfg.video_dir / f"draft_r{outer_rnd}.mp4"
        _log(f"Compositing -> {draft_path}")
        compositor.assemble(
            [visual_cache[segment.id] for segment in plan.segments],
            [audio_cache[segment.id] for segment in plan.segments],
            draft_path,
        )
        plan_snapshot = cfg.run_dir / f"lesson_plan_r{outer_rnd}.json"
        plan_snapshot.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        evaluation_dir = cfg.run_dir / f"evaluator_feedback_r{outer_rnd}"
        evaluation_path = eval_runner.run_lesson_evaluation(
            plan,
            draft_path,
            evaluation_dir,
            chunk_seconds=cfg.evaluator_chunk_seconds,
            frame_interval_seconds=cfg.evaluator_frame_interval_seconds,
        )
        evaluation = EvaluationResult.model_validate_json(
            evaluation_path.read_text(encoding="utf-8")
        )
        review = None
        if outer_rnd < cfg.max_outer_rounds or pending_targets:
            review = evaluation_adapter.adapt_evaluation_to_review(
                provider, evaluation, plan, debug_dir=evaluation_dir
            )
        record = _round_record(
            outer_rnd,
            draft_path,
            plan_snapshot,
            evaluation_path,
            evaluation,
            plan,
            visual_cache,
        )
        if pending_targets:
            record["repair_verification"] = _verify_repair_targets(
                pending_targets,
                review or ReviewResult(),
                record["scores"],
            )
        record["render_debug_round"] = render_debug_round
        baseline = next((item for item in rounds if int(item.get("round", -1)) == 0), None)
        if baseline is None and outer_rnd == 0:
            baseline = record
        baseline_loc = (baseline or record)["scores"].get("Learning Objective Coverage", 0)
        record["duration_guard_passed"] = (
            outer_rnd == 0
            or record["duration_seconds"] <= (baseline or record)["duration_seconds"] * 1.25
            or record["scores"].get("Learning Objective Coverage", 0) > baseline_loc
        )
        rounds = [item for item in rounds if int(item.get("round", -1)) != outer_rnd]
        rounds.append(record)
        rounds.sort(key=lambda item: int(item["round"]))

        previous_best = best
        if best is None or _candidate_beats_best(record, best):
            best = record
            non_improving = 0
            record["selection_status"] = "best"
        else:
            non_improving += 1
            record["selection_status"] = "not_selected"
            record["selection_reason"] = _selection_rejection_reason(record, best)
        _write_round_manifest(manifest_path, rounds, best)

        if outer_rnd >= cfg.max_outer_rounds:
            break
        if previous_best is not None and non_improving >= cfg.refinement_patience:
            _log("Refinement stopped after a non-improving evaluated round.")
            break

        if review is None:
            review = evaluation_adapter.adapt_evaluation_to_review(
                provider, evaluation, plan, debug_dir=evaluation_dir
            )
        decision = outer_repair_decider.decide_outer_repair(
            evaluation,
            threshold=cfg.outer_plan_repair_threshold,
            repair_mode=cfg.outer_repair_mode,
            review=review,
        )
        (cfg.run_dir / f"outer_repair_decision_r{outer_rnd}.json").write_text(
            decision.model_dump_json(indent=2), encoding="utf-8"
        )
        pending_targets = []

        evaluated_plan = plan.model_copy(deep=True)
        if decision.repair_type == "plan":
            pending_targets = _repair_targets_for_decision(
                review,
                "plan",
                record["scores"],
                next_round=outer_rnd + 1,
            )
            revised_plan, _, plan_evaluation = outer_plan_refiner.refine_from_video_evaluation(
                provider,
                cfg.request,
                plan,
                evaluation,
                threshold=cfg.outer_plan_repair_threshold,
                repair_mode=cfg.outer_repair_mode,
                review=review,
            )
            if plan_evaluation is not None:
                (cfg.run_dir / f"outer_plan_feedback_r{outer_rnd}.json").write_text(
                    plan_evaluation.model_dump_json(indent=2), encoding="utf-8"
                )
            plan = revised_plan
            (cfg.run_dir / f"outer_lesson_plan_refined_r{outer_rnd + 1}.json").write_text(
                plan.model_dump_json(indent=2), encoding="utf-8"
            )
            dirty_full, dirty_visual = _plan_cache_changes(evaluated_plan, plan)
        elif decision.repair_type == "asset":
            selected_review = ReviewResult(
                critiques=[
                    item for item in review.critiques
                    if item.repair_scope in {"asset", "timing"}
                ],
                overall_score=review.overall_score,
                summary=review.summary,
            )
            selected_review = _filter_asset_review_by_modality(cfg, plan, selected_review)
            pending_targets = _repair_targets_for_decision(
                selected_review,
                "asset",
                record["scores"],
                next_round=outer_rnd + 1,
            )
            (cfg.run_dir / f"asset_review_r{outer_rnd}.json").write_text(
                selected_review.model_dump_json(indent=2), encoding="utf-8"
            )
            dirty_full, dirty_visual = router.apply_with_cache_hints(
                provider, plan, selected_review
            )
        else:
            _log("No actionable repair remains.")
            break

        record["repair_targets_for_next_round"] = pending_targets
        _write_round_manifest(manifest_path, rounds, best)
        dirty_visual -= dirty_full
        if not dirty_full and not dirty_visual:
            _log("Selected repair class produced no media changes.")
            break
        _invalidate_caches(
            audio_cache,
            visual_cache,
            dirty_full=dirty_full,
            dirty_visual=dirty_visual,
        )
        cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    if best is None:
        raise RuntimeError("evaluator refinement produced no evaluated draft")
    final = cfg.video_dir / "final.mp4"
    shutil.copy2(best["video_path"], final)
    shutil.copy2(best["plan_path"], cfg.plan_path)
    final_eval_path = _copy_evaluation_outputs(
        Path(best["evaluation_path"]), cfg.run_dir / "evaluator_final"
    )
    selection = {
        "selected_round": best["round"],
        "selected_video": best["video_path"],
        "final_video": str(final),
        "score": best["overall_score"],
        "reason": "Highest safe evaluated candidate under score and regression rules.",
        "criteria": {
            "minimum_overall_improvement": 0.125,
            "maximum_metric_drop": 1,
            "targeted_repair_verification": (
                "at least one targeted segment/metric finding resolved and no "
                "targeted metric declined"
            ),
            "tie_breakers": ["critical_metric_minimum", "shorter_duration", "earlier_round"],
        },
    }
    (cfg.run_dir / "selection.json").write_text(
        json.dumps(selection, indent=2), encoding="utf-8"
    )
    _write_round_manifest(manifest_path, rounds, best)
    return {
        "plan_path": str(cfg.plan_path),
        "video_path": str(final),
        "last_evaluation_path": str(final_eval_path),
        "last_evaluated_video_sha256": _file_sha256(final),
    }


def _round_record(
    round_index: int,
    video_path: Path,
    plan_path: Path,
    evaluation_path: Path,
    evaluation: EvaluationResult,
    plan: LessonPlan,
    visual_cache: dict[str, VisualAsset],
) -> dict:
    scores = {score.metric: score.score for score in evaluation.scores}
    critical = [
        scores[name] for name in (
            "Learning Objective Coverage",
            "Content Accuracy",
            "Visual Quality",
            "Multimedia Learning Design",
        ) if name in scores
    ]
    return {
        "round": round_index,
        "video_path": str(video_path),
        "video_sha256": _file_sha256(video_path),
        "duration_seconds": _video_duration_path(video_path),
        "plan_path": str(plan_path),
        "evaluation_path": str(evaluation_path),
        "overall_score": evaluation.overall_score,
        "scores": scores,
        "critical_metric_minimum": min(critical) if critical else 0,
        "intended_modalities": {segment.id: segment.modality.value for segment in plan.segments},
        "rendered_modalities": {
            segment_id: (asset.rendered_modality or asset.intended_modality).value
            if (asset.rendered_modality or asset.intended_modality) else None
            for segment_id, asset in visual_cache.items()
        },
    }


def _candidate_beats_best(candidate: dict, best: dict) -> bool:
    if not candidate.get("duration_guard_passed", True):
        return False
    verification = candidate.get("repair_verification")
    if verification and not verification.get("passed", False):
        return False
    score_gain = float(candidate["overall_score"]) - float(best["overall_score"])
    no_large_drop = all(
        candidate["scores"].get(metric, -999) >= score - 1
        for metric, score in best["scores"].items()
    )
    critical_metrics = {
        "Learning Objective Coverage",
        "Content Accuracy",
        "Visual Quality",
        "Multimedia Learning Design",
    }
    no_critical_drop = all(
        candidate["scores"].get(metric, -999) >= score
        for metric, score in best["scores"].items()
        if metric in critical_metrics
    )
    if score_gain >= 0.125 and no_large_drop and no_critical_drop:
        return True
    if abs(score_gain) < 1e-9 and no_large_drop and no_critical_drop:
        candidate_key = (
            candidate["critical_metric_minimum"],
            -candidate["duration_seconds"],
            -candidate["round"],
        )
        best_key = (
            best["critical_metric_minimum"],
            -best["duration_seconds"],
            -best["round"],
        )
        return candidate_key > best_key
    return False


def _selection_rejection_reason(candidate: dict, best: dict) -> str:
    if not candidate.get("duration_guard_passed", True):
        return "Rejected because duration grew by more than 25% without improving objective coverage."
    verification = candidate.get("repair_verification")
    if verification and not verification.get("passed", False):
        unresolved = verification.get("unresolved", [])
        targets = ", ".join(
            f"{item.get('segment_id')}/{item.get('source_metric')}" for item in unresolved
        )
        return (
            "Rejected because no targeted repair was verified as resolved"
            + (f": {targets}" if targets else ".")
        )
    gain = float(candidate["overall_score"]) - float(best["overall_score"])
    drops = [
        metric for metric, old_score in best["scores"].items()
        if candidate["scores"].get(metric, old_score) < old_score - 1
    ]
    if drops:
        return "Rejected because metric(s) dropped by more than one point: " + ", ".join(drops)
    critical_drops = [
        metric
        for metric in (
            "Learning Objective Coverage",
            "Content Accuracy",
            "Visual Quality",
            "Multimedia Learning Design",
        )
        if candidate["scores"].get(metric, -999) < best["scores"].get(metric, -999)
    ]
    if critical_drops:
        return "Rejected because critical metric(s) declined: " + ", ".join(critical_drops)
    return f"Overall improvement {gain:.3f} was below 0.125 and tie-breakers did not win."


def _best_saved_round(rounds: list[dict]) -> dict | None:
    best = None
    for item in sorted(rounds, key=lambda row: int(row["round"])):
        if best is None or _candidate_beats_best(item, best):
            best = item
    return best


def _repair_targets_for_decision(
    review: ReviewResult,
    repair_type: str,
    source_scores: dict[str, int],
    *,
    next_round: int,
) -> list[dict]:
    allowed_scopes = {"plan"} if repair_type == "plan" else {"asset", "timing"}
    if repair_type not in {"plan", "asset"}:
        return []
    targets = []
    seen = set()
    for critique in review.critiques:
        if critique.repair_scope not in allowed_scopes or critique.severity == "minor":
            continue
        key = (critique.segment_id, critique.source_metric)
        if not critique.segment_id or not critique.source_metric or key in seen:
            continue
        seen.add(key)
        targets.append(
            {
                "next_round": next_round,
                "segment_id": critique.segment_id,
                "source_metric": critique.source_metric,
                "source_score": source_scores.get(critique.source_metric),
                "issue": critique.issue,
            }
        )
    return targets


def _pending_repair_targets(rounds: list[dict], round_index: int) -> list[dict]:
    for record in reversed(sorted(rounds, key=lambda item: int(item.get("round", -1)))):
        targets = record.get("repair_targets_for_next_round", [])
        if targets and all(int(item.get("next_round", -1)) == round_index for item in targets):
            return targets
    return []


def _verify_repair_targets(
    targets: list[dict],
    review: ReviewResult,
    current_scores: dict[str, int],
) -> dict:
    current_pairs = {
        (critique.segment_id, critique.source_metric)
        for critique in review.critiques
        if critique.severity in {"major", "blocker"}
    }
    resolved = [
        target
        for target in targets
        if (target.get("segment_id"), target.get("source_metric")) not in current_pairs
    ]
    unresolved = [target for target in targets if target not in resolved]
    target_scores_not_worse = all(
        target.get("source_score") is None
        or current_scores.get(target.get("source_metric"), -999) >= target["source_score"]
        for target in targets
    )
    return {
        "passed": bool(resolved) and target_scores_not_worse,
        "resolved_count": len(resolved),
        "target_count": len(targets),
        "target_scores_not_worse": target_scores_not_worse,
        "resolved": resolved,
        "unresolved": unresolved,
    }


def _write_round_manifest(path: Path, rounds: list[dict], best: dict | None) -> None:
    path.write_text(
        json.dumps(
            {"rounds": rounds, "current_best_round": best["round"] if best else None},
            indent=2,
        ),
        encoding="utf-8",
    )


def _video_duration_path(path: Path) -> float:
    clip = VideoFileClip(str(path))
    try:
        return float(clip.duration or 0.0)
    finally:
        clip.close()


def _fresh_render_debug_round(cfg: Config, outer_round: int) -> int:
    if not cfg.resume:
        return outer_round
    used: list[int] = []
    for path in cfg.run_dir.glob("**/round_*"):
        if not path.is_dir():
            continue
        try:
            used.append(int(path.name.removeprefix("round_")))
        except ValueError:
            continue
    return max([outer_round - 1, *used]) + 1


def _review_composite(
    cfg: Config,
    provider: Provider,
    plan: LessonPlan,
    draft_path,
    outer_rnd: int,
) -> OuterReview:
    if cfg.feedback_mode == "evaluator":
        _log(f"Outer review with evaluator (round {outer_rnd})...")
        review = evaluator_reviewer.review(
            provider, plan, draft_path, cfg, round_index=outer_rnd
        )
        return _review_result_to_outer_review(review)

    _log(f"Outer review (round {outer_rnd})...")
    return outer_reviewer.review(provider, plan, draft_path)


def _review_result_to_outer_review(review: ReviewResult) -> OuterReview:
    """Bridge the previous evaluator adapter into main's new nested refiner schema."""
    content_issues: list[ContentIssue] = []
    visual_issues: list[VisualIssue] = []

    for critique in review.critiques:
        if not critique.segment_id:
            continue

        suggestion = critique.detail or critique.issue
        if critique.fix_action in {"re_render", "adjust_timing"}:
            visual_issues.append(
                VisualIssue(
                    segment_id=critique.segment_id,
                    issue=critique.issue,
                    suggestion=suggestion,
                )
            )
        else:
            field = "narration" if critique.fix_action == "rewrite_narration" else "visual_brief"
            content_issues.append(
                ContentIssue(
                    segment_id=critique.segment_id,
                    field=field,
                    issue=critique.issue,
                    suggestion=suggestion,
                )
            )

    return OuterReview(
        overall_score=review.overall_score,
        content_issues=content_issues,
        visual_issues=visual_issues,
        summary=review.summary,
    )


def _filter_asset_review_by_modality(
    cfg: Config,
    plan: LessonPlan,
    review: ReviewResult,
) -> ReviewResult:
    if cfg.asset_repair_modalities == "all":
        return review
    if cfg.asset_repair_modalities != "animation":
        raise ValueError(f"unknown asset repair modality filter: {cfg.asset_repair_modalities}")

    animation_ids = {
        segment.id for segment in plan.segments if segment.modality == Modality.ANIMATION
    }
    kept = [
        critique for critique in review.critiques
        if critique.segment_id in animation_ids
    ]
    if len(kept) == len(review.critiques):
        return review
    return ReviewResult(
        critiques=kept,
        overall_score=review.overall_score,
        summary=(
            f"{review.summary} Filtered asset repair to animation segments only; "
            f"kept {len(kept)} of {len(review.critiques)} repair critique(s)."
        ).strip(),
    )


def _plan_cache_changes(
    before: LessonPlan,
    after: LessonPlan,
) -> tuple[set[str], set[str]]:
    """Return surgical cache invalidations for a lesson-plan revision."""
    before_by_id = {segment.id: segment for segment in before.segments}
    dirty_full: set[str] = set()
    dirty_visual: set[str] = set()

    for segment in after.segments:
        previous = before_by_id.get(segment.id)
        if previous is None or segment.narration != previous.narration:
            dirty_full.add(segment.id)
            continue

        visual_fields_changed = any(
            (
                segment.title != previous.title,
                segment.modality != previous.modality,
                segment.visual_brief != previous.visual_brief,
                segment.target_seconds != previous.target_seconds,
                segment.hints != previous.hints,
            )
        )
        if visual_fields_changed:
            dirty_visual.add(segment.id)

    dirty_visual -= dirty_full
    return dirty_full, dirty_visual


def _invalidate_caches(
    audio_cache: dict[str, NarrationAudio],
    visual_cache: dict[str, VisualAsset],
    *,
    dirty_full: set[str],
    dirty_visual: set[str],
) -> None:
    for segment_id in dirty_full:
        audio_cache.pop(segment_id, None)
        visual_cache.pop(segment_id, None)
    for segment_id in dirty_visual:
        visual_cache.pop(segment_id, None)


def _produce_assets(
    cfg,
    provider,
    plan,
    dirty,
    audio_cache,
    visual_cache,
    *,
    is_refinement_render: bool = False,
    render_round: int = 0,
):
    """Narrate + render every dirty segment, in parallel."""
    todo = [s for s in plan.segments if s.id in dirty]
    if not todo:
        return

    def work(seg: Segment):
        audio = audio_cache.get(seg.id)
        if audio is None:
            audio = narrator.narrate(provider, seg, cfg.audio_dir)
        visual = _render_segment(
            cfg,
            provider,
            plan,
            seg,
            audio,
            is_refinement_render=is_refinement_render,
            render_round=render_round,
        )
        return seg.id, audio, visual

    if cfg.parallel:
        with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
            results = list(ex.map(work, todo))
    else:
        results = [work(s) for s in todo]

    for sid, audio, visual in results:
        audio_cache[sid] = audio
        visual_cache[sid] = visual
        segment = next(item for item in plan.segments if item.id == sid)
        audio_payload = audio.model_dump()
        audio_payload["narration_sha256"] = _text_sha256(segment.narration)
        (cfg.audio_dir / f"{sid}.audio.json").write_text(
            json.dumps(audio_payload, indent=2), encoding="utf-8"
        )
        asset_payload = visual.model_dump(mode="json")
        asset_payload["segment_signature"] = _segment_signature(segment)
        (cfg.assets_dir / f"{sid}.asset.json").write_text(
            json.dumps(asset_payload, indent=2), encoding="utf-8"
        )


def _render_segment(
    cfg,
    provider,
    plan: LessonPlan,
    seg: Segment,
    audio: NarrationAudio,
    *,
    is_refinement_render: bool = False,
    render_round: int = 0,
) -> VisualAsset:
    """Dispatch to the planned renderer; degrade gracefully on failure.

    Fallback order is planned -> concept_image -> slide. concept_image comes first so
    that a failed animation does NOT introduce a stray slide on a non-recap segment
    (slides are reserved for the final summary). Slide is the last-resort emergency.
    """
    ctx = RenderContext(
        cfg=cfg,
        provider=provider,
        out_dir=cfg.assets_dir,
        audio_seconds=audio.duration,
        word_timings=audio.words,
        plan=plan,
        is_refinement_render=is_refinement_render,
        render_round=render_round,
    )
    if seg.modality == Modality.ANIMATION:
        chain = [Modality.ANIMATION, Modality.CONCEPT_IMAGE, Modality.SLIDE]
    elif seg.modality == Modality.CONCEPT_IMAGE:
        chain = [Modality.CONCEPT_IMAGE, Modality.SLIDE]
    else:
        chain = [Modality.SLIDE]

    last_err: Exception | None = None
    failures: list[str] = []
    for i, modality in enumerate(chain):
        try:
            asset = get_renderer(modality).render(seg, ctx)
            if modality == Modality.ANIMATION:
                unhealthy_reason = _animation_asset_unhealthy(asset, audio)
                if unhealthy_reason:
                    raise RuntimeError(unhealthy_reason)
            if i > 0:
                _log(f"   {seg.id}: {seg.modality.value} failed; fell back to {modality.value}")
            asset.intended_modality = seg.modality
            asset.rendered_modality = modality
            asset.fallback_reason = "; ".join(failures) or None
            asset_path = cfg.assets_dir / f"{seg.id}.asset.json"
            asset_path.write_text(asset.model_dump_json(indent=2), encoding="utf-8")
            return asset
        except Exception as e:  # NotImplementedError included
            last_err = e
            failures.append(f"{modality.value}: {type(e).__name__}: {e}")
            _log(f"   {seg.id}: {modality.value} failed: {type(e).__name__}: {e}")
    raise last_err  # all renderers failed for this segment


def _animation_asset_unhealthy(asset: VisualAsset, audio: NarrationAudio) -> str | None:
    """Reject animation MP4s likely to hang or smear during composition/evaluation.

    code2video can sometimes produce an MP4 that opens successfully but contains far
    fewer readable frames than its reported/needed duration. MoviePy then repeatedly
    freezes the final valid frame while writing evaluator chunks. For evaluator runs,
    a static concept image is better than a broken animation clip.
    """
    if asset.kind != "video":
        return "animation renderer did not return a video asset"

    path = Path(asset.path)
    if not path.is_file() or path.stat().st_size == 0:
        return f"animation asset missing or empty: {path}"

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            clip = VideoFileClip(str(path))
            try:
                duration = float(clip.duration or 0.0)
                if duration <= 0:
                    return f"animation asset has invalid duration: {path}"

                probe_t = max(0.0, min(duration - 0.05, duration * 0.95))
                if probe_t > 0:
                    clip.get_frame(probe_t)

                warning_text = "\n".join(str(w.message) for w in caught)
                if "bytes wanted but 0 bytes read" in warning_text:
                    return f"animation asset has unreadable frames: {path}"

                shortfall = float(audio.duration or 0.0) - duration
                allowed_shortfall = max(2.0, float(audio.duration or 0.0) * 0.20)
                if shortfall > allowed_shortfall:
                    return (
                        "animation asset is much shorter than narration "
                        f"({duration:.1f}s video vs {audio.duration:.1f}s audio)"
                    )
            finally:
                clip.close()
    except Exception as e:
        return f"animation asset failed health check: {type(e).__name__}: {e}"

    return None


def _finalize(cfg: Config, draft_path):
    final = cfg.video_dir / "final.mp4"
    if str(draft_path) != str(final):
        shutil.copy(draft_path, final)
    return final


def _prepare_run_directory(cfg: Config) -> None:
    if not cfg.run_dir.exists():
        return
    contents = [path for path in cfg.run_dir.iterdir() if path.name != ".DS_Store"]
    if contents and not cfg.resume:
        raise FileExistsError(
            f"Run directory is not empty: {cfg.run_dir}. Choose a new --run-dir "
            "or pass --resume to continue the interrupted run."
        )


def _load_resume_caches(
    cfg: Config,
    plan: LessonPlan,
) -> tuple[dict[str, NarrationAudio], dict[str, VisualAsset]]:
    audio_cache: dict[str, NarrationAudio] = {}
    visual_cache: dict[str, VisualAsset] = {}
    for segment in plan.segments:
        audio_meta = cfg.audio_dir / f"{segment.id}.audio.json"
        if audio_meta.exists():
            try:
                payload = json.loads(audio_meta.read_text(encoding="utf-8"))
                if payload.pop("narration_sha256", None) == _text_sha256(segment.narration):
                    audio = NarrationAudio.model_validate(payload)
                    if Path(audio.path).is_file():
                        audio_cache[segment.id] = audio
            except Exception:
                pass
        asset_meta = cfg.assets_dir / f"{segment.id}.asset.json"
        if asset_meta.exists():
            try:
                payload = json.loads(asset_meta.read_text(encoding="utf-8"))
                if payload.pop("segment_signature", None) == _segment_signature(segment):
                    asset = VisualAsset.model_validate(payload)
                    if Path(asset.path).is_file():
                        visual_cache[segment.id] = asset
            except Exception:
                pass
    _log(
        f"Resume cache: {len(audio_cache)}/{len(plan.segments)} audio and "
        f"{len(visual_cache)}/{len(plan.segments)} visual assets are reusable."
    )
    return audio_cache, visual_cache


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _segment_signature(segment: Segment) -> str:
    return _text_sha256(segment.model_dump_json())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_evaluation_outputs(source_evaluation_path: Path, target_dir: Path) -> Path:
    source_dir = source_evaluation_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        target = target_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    return target_dir / source_evaluation_path.name


def _log(msg: str) -> None:
    print(f"[teachgen] {msg}", flush=True)
