"""Top-level orchestration: Phase 1 (plan) -> Phase 2 (media + feedback loop).

This is the only place that knows the end-to-end flow. Each stage talks to the next
purely through schema objects, and per-segment work fans out across a thread pool.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from .config import Config
from .feedback import eval_runner, evaluator_reviewer, reviewer, router
from .planner import content_writer, route
from .providers import get_provider
from .providers.base import Provider
from .renderers import get_renderer
from .renderers.base import RenderContext
from .schema import LessonPlan, Modality, NarrationAudio, Segment, VisualAsset
from .audio import narrator
from .compositor import compositor


def generate(cfg: Config) -> dict:
    cfg.ensure_dirs()
    provider = get_provider(cfg)

    plan = phase1_plan(cfg, provider)
    result = phase2_produce(cfg, provider, plan)
    if cfg.run_evaluator_baseline:
        video_path = result["video_path"]
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
    content = content_writer.write_content(provider, cfg.topic, cfg.audience)

    _log("Phase 1: routing segments to renderers...")
    plan = route.plan_lesson(provider, content)

    cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    _log(f"Phase 1: lesson plan -> {cfg.plan_path}")
    for s in plan.segments:
        _log(f"   {s.id}  [{s.modality.value:<13}] {s.title}")
    return plan


# ========================================================== PHASE 2 (media)
def phase2_produce(cfg: Config, provider: Provider, plan: LessonPlan) -> dict:
    # Caches keyed by segment id so feedback rounds only redo what changed.
    audio_cache: dict[str, NarrationAudio] = {}
    visual_cache: dict[str, VisualAsset] = {}

    draft_path = None
    for rnd in range(cfg.max_feedback_rounds + 1):
        dirty = {s.id for s in plan.segments if s.id not in visual_cache}
        if rnd > 0:
            _log(f"Feedback round {rnd}: re-doing {len(dirty)} segment(s)")

        _produce_assets(cfg, provider, plan, dirty, audio_cache, visual_cache)

        audios = [audio_cache[s.id] for s in plan.segments]
        visuals = [visual_cache[s.id] for s in plan.segments]

        draft_path = cfg.video_dir / ("final.mp4" if rnd == cfg.max_feedback_rounds else f"draft_r{rnd}.mp4")
        _log(f"Compositing -> {draft_path}")
        compositor.assemble(visuals, audios, draft_path)

        if not cfg.use_feedback or cfg.feedback_mode == "none" or rnd == cfg.max_feedback_rounds:
            break

        if cfg.feedback_mode == "evaluator":
            _log("Reviewing composite with evaluator...")
            rev = evaluator_reviewer.review(provider, plan, draft_path, cfg, round_index=rnd)
        else:
            _log("Reviewing composite with MLLM...")
            rev = reviewer.review(provider, plan, draft_path)
        _log(f"   score={rev.overall_score:.1f}  critiques={len(rev.critiques)}")
        (cfg.run_dir / f"review_r{rnd}.json").write_text(
            rev.model_dump_json(indent=2), encoding="utf-8"
        )
        if not rev.has_blocking_issues:
            _log("No blocking issues; finalizing.")
            draft_path = _finalize(cfg, draft_path)
            break

        dirty_now = router.apply(provider, plan, rev)
        for sid in dirty_now:  # invalidate caches for changed segments
            audio_cache.pop(sid, None)
            visual_cache.pop(sid, None)
        cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    return {"plan_path": str(cfg.plan_path), "video_path": str(draft_path)}


def _produce_assets(cfg, provider, plan, dirty, audio_cache, visual_cache):
    """Narrate + render every dirty segment, in parallel."""
    todo = [s for s in plan.segments if s.id in dirty]
    if not todo:
        return

    def work(seg: Segment):
        audio = narrator.narrate(provider, seg, cfg.audio_dir)
        visual = _render_segment(cfg, provider, seg, audio)
        return seg.id, audio, visual

    if cfg.parallel:
        with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
            results = list(ex.map(work, todo))
    else:
        results = [work(s) for s in todo]

    for sid, audio, visual in results:
        audio_cache[sid] = audio
        visual_cache[sid] = visual


def _render_segment(cfg, provider, seg: Segment, audio: NarrationAudio) -> VisualAsset:
    """Dispatch to the planned renderer; degrade gracefully on failure.

    Fallback order is planned -> concept_image -> slide. concept_image comes first so
    that a failed animation does NOT introduce a stray slide on a non-recap segment
    (slides are reserved for the final summary). Slide is the last-resort emergency.
    """
    ctx = RenderContext(
        cfg=cfg, provider=provider, out_dir=cfg.assets_dir, audio_seconds=audio.duration
    )
    chain = [seg.modality]
    for m in (Modality.CONCEPT_IMAGE, Modality.SLIDE):
        if m not in chain:
            chain.append(m)

    last_err: Exception | None = None
    for i, modality in enumerate(chain):
        try:
            asset = get_renderer(modality).render(seg, ctx)
            if i > 0:
                _log(f"   {seg.id}: {seg.modality.value} failed; fell back to {modality.value}")
                seg.modality = modality
            return asset
        except Exception as e:  # NotImplementedError included
            last_err = e
    raise last_err  # all renderers failed for this segment


def _finalize(cfg: Config, draft_path):
    final = cfg.video_dir / "final.mp4"
    if str(draft_path) != str(final):
        import shutil

        shutil.copy(draft_path, final)
    return final


def _log(msg: str) -> None:
    print(f"[teachgen] {msg}", flush=True)
