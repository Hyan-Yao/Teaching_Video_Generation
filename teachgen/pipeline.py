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
from .feedback import outer_plan_refiner, outer_reviewer, plan_refiner, router, visual_refiner
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
    cfg.ensure_dirs()
    cfg.request_path.write_text(
        cfg.request.model_dump_json(indent=2),
        encoding="utf-8",
    )
    provider = get_provider(cfg)

    plan = phase1_plan(cfg, provider)
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
            _produce_assets(cfg, provider, plan, dirty, audio_cache, visual_cache)

        # --- composite ---
        is_last = (outer_rnd == cfg.max_outer_rounds)
        draft_name = "final.mp4" if is_last else f"draft_r{outer_rnd}.mp4"
        draft_path = cfg.video_dir / draft_name
        _log(f"Compositing → {draft_path}")
        compositor.assemble(
            [visual_cache[s.id] for s in plan.segments],
            [audio_cache[s.id] for s in plan.segments],
            draft_path,
        )

        if not cfg.use_feedback or cfg.feedback_mode == "none" or is_last:
            break

        if cfg.feedback_mode == "evaluator":
            evaluation_dir = cfg.run_dir / f"evaluator_feedback_r{outer_rnd}"
            _log(f"Outer video evaluation (round {outer_rnd}) -> {evaluation_dir}")
            evaluation_path = eval_runner.run_lesson_evaluation(
                plan,
                draft_path,
                evaluation_dir,
                chunk_seconds=cfg.evaluator_chunk_seconds,
            )
            last_evaluation_path = evaluation_path
            last_evaluated_video_sha = _file_sha256(draft_path)
            evaluation = EvaluationResult.model_validate_json(
                evaluation_path.read_text(encoding="utf-8")
            )

            revised_plan, decision, plan_evaluation = (
                outer_plan_refiner.refine_from_video_evaluation(
                    provider,
                    cfg.request,
                    plan,
                    evaluation,
                    threshold=cfg.outer_plan_repair_threshold,
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

            audio_cache.clear()
            visual_cache.clear()
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


def _produce_assets(cfg, provider, plan, dirty, audio_cache, visual_cache):
    """Narrate + render every dirty segment, in parallel."""
    todo = [s for s in plan.segments if s.id in dirty]
    if not todo:
        return

    def work(seg: Segment):
        audio = narrator.narrate(provider, seg, cfg.audio_dir)
        visual = _render_segment(cfg, provider, plan, seg, audio)
        return seg.id, audio, visual

    if cfg.parallel:
        with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
            results = list(ex.map(work, todo))
    else:
        results = [work(s) for s in todo]

    for sid, audio, visual in results:
        audio_cache[sid] = audio
        visual_cache[sid] = visual


def _render_segment(cfg, provider, plan: LessonPlan, seg: Segment, audio: NarrationAudio) -> VisualAsset:
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
        plan=plan,
    )
    chain = [seg.modality]
    for m in (Modality.CONCEPT_IMAGE, Modality.SLIDE):
        if m not in chain:
            chain.append(m)

    last_err: Exception | None = None
    for i, modality in enumerate(chain):
        try:
            asset = get_renderer(modality).render(seg, ctx)
            if modality == Modality.ANIMATION:
                unhealthy_reason = _animation_asset_unhealthy(asset, audio)
                if unhealthy_reason:
                    raise RuntimeError(unhealthy_reason)
            if i > 0:
                _log(f"   {seg.id}: {seg.modality.value} failed; fell back to {modality.value}")
                seg.modality = modality
            return asset
        except Exception as e:  # NotImplementedError included
            last_err = e
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
