import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from code2video.scope_refine import GridCodeModifier
from teachgen.feedback.evaluation_adapter import (
    _RepairCandidate,
    _RepairPlan,
    _SegmentInterval,
    _apply_animation_visual_repair_policy,
    _normalize_repair_causes,
)
from teachgen.feedback.router import _pick_alternative
from teachgen.feedback.lesson_plan_refiner import _validate_refinement
from teachgen.feedback.outer_repair_decider import decide_outer_repair
from teachgen.pipeline import (
    _candidate_beats_best,
    _prepare_run_directory,
    _render_segment,
    _verify_repair_targets,
)
from teachgen.renderers.animation import _extract_stable_video_frames, _normalize_animation_critique
from teachgen.renderers.base import RenderContext
from teachgen.renderers.concept_image import ConceptImageRenderer
from teachgen.renderers.slide import _draw_slide
from teachgen.schema import (
    CourseSpec,
    LessonPlan,
    Modality,
    NarrationAudio,
    PedagogySpec,
    Segment,
    SlideSpec,
    TeachingRequest,
    Critique,
    ReviewResult,
    VisualAsset,
)


def _segment(segment_id="seg1", narration="A concise explanation.", modality=Modality.ANIMATION):
    return Segment(
        id=segment_id,
        title=segment_id,
        narration=narration,
        modality=modality,
        visual_brief="Show the exact concept clearly.",
        target_seconds=10,
    )


def _plan(*segments):
    return LessonPlan(
        topic="Binary",
        audience="Beginners",
        objectives=["Convert a value."],
        learning_goal="Understand conversion.",
        key_learning_points=["Exact mappings"],
        segments=list(segments),
    )


class _ConceptProvider:
    def __init__(self, validations):
        self.validations = list(validations)
        self.image_calls = 0

    def chat(self, *_args, **_kwargs):
        return "One large exact diagram with generous whitespace."

    def image(self, *_args, **_kwargs):
        self.image_calls += 1
        return b"\x89PNG\r\n\x1a\nmock"

    def vision(self, *_args, **_kwargs):
        return json.dumps(self.validations.pop(0))


class ReliabilityControlTests(unittest.TestCase):
    def test_animation_critic_requires_structured_local_actions(self):
        valid = json.dumps(
            {
                "layout": {
                    "has_issues": True,
                    "severity": "major",
                    "persistent": True,
                    "summary": "persistent overlap",
                    "improvements": [
                        {
                            "action": "replace_write",
                            "line_number": 12,
                            "object_name": "label",
                        }
                    ],
                }
            }
        )
        normalized = json.loads(_normalize_animation_critique(valid))
        self.assertEqual(normalized["layout"]["improvements"][0]["action"], "replace_write")
        with self.assertRaises(Exception):
            _normalize_animation_critique(
                json.dumps(
                    {
                        "layout": {
                            "has_issues": True,
                            "severity": "major",
                            "persistent": True,
                            "improvements": [{"solution": "rewrite everything"}],
                        }
                    }
                )
            )

    def test_structured_grid_actions_apply_only_local_edits(self):
        code = "\n".join(
            [
                "class Demo:",
                "    def construct(self):",
                "        self.place_at_grid(label, 'A1', scale_factor=1)",
                "        self.play(Write(value))",
                "        next_value = Text('next')",
            ]
        )
        actions = [
            {
                "action": "replace_placement",
                "line_number": 3,
                "object_name": "label",
                "method": "place_at_grid",
                "grid_position": "C3",
                "scale_factor": 0.7,
            },
            {"action": "replace_write", "line_number": 4, "object_name": "value"},
            {
                "action": "insert_cleanup",
                "line_number": 5,
                "method": "fade_out",
                "object_names": ["label", "value"],
            },
        ]
        modified = GridCodeModifier(code).parse_feedback_and_modify(actions)
        self.assertIn("self.place_at_grid(label, 'C3', scale_factor=0.7)", modified)
        self.assertIn("self.play(FadeIn(value))", modified)
        self.assertIn("self.play(FadeOut(label), FadeOut(value))", modified)

        styled_code = "\n".join(
            [
                "class Demo:",
                "    def construct(self):",
                "        label = Text('A', font_size=24, color='#FFFFFF')",
            ]
        )
        restyled = GridCodeModifier(styled_code).parse_feedback_and_modify(
            [
                {
                    "action": "update_style",
                    "line_number": 3,
                    "object_name": "label",
                    "style_attribute": "font_size",
                    "style_value": 36,
                }
            ]
        )
        layered = GridCodeModifier(restyled).parse_feedback_and_modify(
            [
                {
                    "action": "set_z_index",
                    "line_number": 3,
                    "object_name": "label",
                    "z_index": 4,
                }
            ]
        )
        self.assertIn("font_size=36", layered)
        self.assertIn("label.set_z_index(4)", layered)

    def test_stable_sampling_uses_two_samples_near_each_step_end(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clip.mp4"
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48)
            )
            for index in range(100):
                writer.write(np.full((48, 64, 3), index, dtype=np.uint8))
            writer.release()
            section = SimpleNamespace(
                step_timings=[
                    {"start_seconds": 0, "end_seconds": 5},
                    {"start_seconds": 5, "end_seconds": 10},
                ]
            )
            frames, timestamps = _extract_stable_video_frames(str(path), section)
        self.assertEqual(len(frames), 4)
        self.assertAlmostEqual(timestamps[0], 4.1, places=1)
        self.assertAlmostEqual(timestamps[-1], 9.7, places=1)

    def test_stable_sampling_prefers_a_consecutive_low_motion_plateau(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settled.mp4"
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48)
            )
            for index in range(100):
                within_step = index % 50
                value = within_step * 8 if within_step < 20 else 160
                writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
            writer.release()
            section = SimpleNamespace(
                step_timings=[
                    {"start_seconds": 0, "end_seconds": 5},
                    {"start_seconds": 5, "end_seconds": 10},
                ]
            )
            frames, timestamps = _extract_stable_video_frames(str(path), section)
        self.assertEqual(len(frames), 4)
        self.assertGreater(timestamps[0], 3.0)
        self.assertGreater(timestamps[2], 8.0)

    def test_concept_image_retries_once_after_major_validation(self):
        validations = [
            {"has_major_issues": True, "severity": "major", "issues": ["wrong label"]},
            {"has_major_issues": False, "severity": "minor", "issues": []},
        ]
        provider = _ConceptProvider(validations)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            request = TeachingRequest(
                course=CourseSpec(topic="Binary", learning_goal="Learn", key_learning_points=[]),
                student_persona="Beginner",
                pedagogy=PedagogySpec(),
            )
            cfg = SimpleNamespace(
                run_dir=root,
                audience="Beginner",
                request=request,
                concept_image_validation_retries=1,
                models=SimpleNamespace(visual_text="gpt", vision="gpt"),
            )
            ctx = RenderContext(cfg=cfg, provider=provider, out_dir=root, plan=_plan(_segment()), render_round=0)
            asset = ConceptImageRenderer().render(_segment(modality=Modality.CONCEPT_IMAGE), ctx)
        self.assertEqual(provider.image_calls, 2)
        self.assertEqual(asset.validation_status, "passed")

    def test_visual_content_accuracy_problem_routes_to_asset(self):
        repair_plan = _RepairPlan(
            candidates=[
                _RepairCandidate(
                    timestamp_seconds=2,
                    segment_id="seg1",
                    severity="major",
                    issue="The rendered label states the wrong value.",
                    fix_action="rewrite_narration",
                    source_metric="Content Accuracy",
                    repair_scope="plan",
                    cause="visual",
                )
            ]
        )
        plan = _plan(_segment())
        timeline = [_SegmentInterval(segment_id="seg1", start_time_seconds=0, end_time_seconds=10)]
        _normalize_repair_causes(repair_plan, timeline, plan)
        candidate = repair_plan.candidates[0]
        self.assertEqual(candidate.repair_scope, "asset")
        self.assertEqual(candidate.fix_action, "re_render")

        review = ReviewResult(
            critiques=[
                Critique(
                    segment_id="seg1",
                    severity="major",
                    issue="Wrong visible value",
                    fix_action="re_render",
                    repair_scope="asset",
                    cause="visual",
                    source_metric="Content Accuracy",
                )
            ]
        )
        decision = decide_outer_repair(
            SimpleNamespace(scores=[]), repair_mode="auto", review=review
        )
        self.assertEqual(decision.repair_type, "asset")

    def test_unconfirmed_animation_defect_does_not_trigger_regeneration(self):
        plan = _plan(_segment())
        repair_plan = _RepairPlan(
            candidates=[
                _RepairCandidate(
                    timestamp_seconds=2,
                    segment_id="seg1",
                    severity="major",
                    issue="Possible overlap in one transition frame.",
                    fix_action="re_render",
                    source_metric="Visual Quality",
                    repair_scope="asset",
                    cause="rendering",
                    persistent_across_stable_frames=False,
                )
            ]
        )
        timeline = [_SegmentInterval(segment_id="seg1", start_time_seconds=0, end_time_seconds=10)]
        _apply_animation_visual_repair_policy(object(), repair_plan, timeline, plan)
        self.assertEqual(repair_plan.candidates[0].severity, "minor")

    def test_useful_animation_is_repaired_without_modality_fallback(self):
        plan = _plan(_segment())
        repair_plan = _RepairPlan(
            candidates=[
                _RepairCandidate(
                    timestamp_seconds=2,
                    segment_id="seg1",
                    severity="major",
                    issue="Persistent settled-state overlap.",
                    fix_action="change_modality",
                    source_metric="Visual Quality",
                    repair_scope="asset",
                    cause="rendering",
                    persistent_across_stable_frames=True,
                    animation_still_instructionally_useful=True,
                )
            ]
        )
        timeline = [_SegmentInterval(segment_id="seg1", start_time_seconds=0, end_time_seconds=10)]
        _apply_animation_visual_repair_policy(object(), repair_plan, timeline, plan)
        self.assertEqual(repair_plan.candidates[0].fix_action, "re_render")

    def test_static_timing_repair_moves_to_animation(self):
        critique = Critique(
            segment_id="seg1",
            severity="major",
            issue="Answer never reveals.",
            fix_action="change_modality",
            repair_scope="timing",
            cause="rendering",
            source_metric="Multimedia Learning Design",
        )
        self.assertEqual(_pick_alternative(Modality.CONCEPT_IMAGE, critique), Modality.ANIMATION)

    def test_outer_plan_validation_rejects_unrelated_edits_and_growth(self):
        before = _plan(_segment("seg1"), _segment("seg2"))
        after = before.model_copy(deep=True)
        after.segments[1].narration = "unrelated " * 30
        violations = _validate_refinement(
            before,
            after,
            mode="outer",
            allowed_segment_ids={"seg1"},
            timing_split_allowed=False,
        )
        self.assertTrue(any("unaffected segment seg2" in item for item in violations))
        self.assertTrue(any("total narration grew" in item for item in violations))

    def test_outer_timing_repair_requires_a_real_prompt_reveal_split(self):
        before = _plan(
            _segment(
                "seg1",
                narration="Calculate ten now. Pause. The answer is ten.",
                modality=Modality.SLIDE,
            ),
            _segment("seg2", narration="Close the lesson.", modality=Modality.SLIDE),
        )
        unchanged = before.model_copy(deep=True)
        violations = _validate_refinement(
            before,
            unchanged,
            mode="outer",
            allowed_segment_ids={"seg1"},
            timing_split_allowed=True,
        )
        self.assertTrue(any("requires one real prompt/reveal" in item for item in violations))

        revised = before.model_copy(deep=True)
        revised.segments[0].narration = "Calculate ten now. Pause."
        revised.segments[0].visual_brief = "Show only the unanswered calculation."
        reveal = _segment(
            "seg3",
            narration="The answer is ten.",
            modality=Modality.SLIDE,
        )
        reveal.visual_brief = "Reveal the completed answer: ten."
        revised.segments.insert(1, reveal)
        self.assertEqual(
            _validate_refinement(
                before,
                revised,
                mode="outer",
                allowed_segment_ids={"seg1"},
                timing_split_allowed=True,
            ),
            [],
        )

    def test_more_urgent_asset_findings_are_repaired_before_one_plan_finding(self):
        review = ReviewResult(
            critiques=[
                Critique(
                    segment_id="seg1",
                    severity="major",
                    issue="Answer appears too early.",
                    fix_action="rewrite_narration",
                    repair_scope="plan",
                    cause="sequence",
                    source_metric="ICAP Alignment",
                ),
                Critique(
                    segment_id="seg2",
                    severity="major",
                    issue="Persistent unreadable labels.",
                    fix_action="re_render",
                    repair_scope="asset",
                    cause="rendering",
                    source_metric="Visual Quality",
                ),
                Critique(
                    segment_id="seg3",
                    severity="major",
                    issue="Persistent overlap.",
                    fix_action="re_render",
                    repair_scope="asset",
                    cause="rendering",
                    source_metric="Visual Quality",
                ),
            ]
        )
        decision = decide_outer_repair(
            SimpleNamespace(scores=[]), repair_mode="auto", review=review
        )
        self.assertEqual(decision.repair_type, "asset")

    def test_best_draft_rejects_small_gain_and_large_metric_drop(self):
        best = {
            "overall_score": 4.0,
            "scores": {"Visual Quality": 5, "Logic": 4},
            "critical_metric_minimum": 4,
            "duration_seconds": 100,
            "round": 0,
        }
        small_gain = {
            **best,
            "overall_score": 4.1,
            "round": 1,
            "duration_guard_passed": True,
        }
        regression = {
            **best,
            "overall_score": 4.25,
            "scores": {"Visual Quality": 3, "Logic": 5},
            "round": 1,
            "duration_guard_passed": True,
        }
        self.assertFalse(_candidate_beats_best(small_gain, best))
        self.assertFalse(_candidate_beats_best(regression, best))

        tied_but_shorter = {
            **best,
            "duration_seconds": 90,
            "round": 1,
            "duration_guard_passed": True,
        }
        self.assertTrue(_candidate_beats_best(tied_but_shorter, best))

    def test_best_draft_requires_targeted_repair_verification(self):
        best = {
            "overall_score": 4.0,
            "scores": {"Visual Quality": 3, "Logic": 4},
            "critical_metric_minimum": 3,
            "duration_seconds": 100,
            "round": 0,
        }
        candidate = {
            **best,
            "overall_score": 4.25,
            "scores": {"Visual Quality": 3, "Logic": 5},
            "round": 1,
            "duration_guard_passed": True,
            "repair_verification": {"passed": False},
        }
        self.assertFalse(_candidate_beats_best(candidate, best))

        targets = [
            {
                "segment_id": "seg1",
                "source_metric": "Visual Quality",
                "source_score": 3,
                "issue": "Overlap",
            }
        ]
        unresolved_review = ReviewResult(
            critiques=[
                Critique(
                    segment_id="seg1",
                    severity="major",
                    issue="Overlap remains",
                    fix_action="re_render",
                    repair_scope="asset",
                    cause="rendering",
                    source_metric="Visual Quality",
                )
            ]
        )
        self.assertFalse(
            _verify_repair_targets(targets, unresolved_review, {"Visual Quality": 3})["passed"]
        )
        self.assertTrue(
            _verify_repair_targets(targets, ReviewResult(), {"Visual Quality": 4})["passed"]
        )

    def test_fallback_keeps_intended_modality_on_plan(self):
        segment = _segment()
        plan = _plan(segment)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cfg = SimpleNamespace(assets_dir=root, run_dir=root)
            audio = NarrationAudio(segment_id="seg1", path="unused", duration=10)

            class _Renderer:
                def __init__(self, modality):
                    self.modality = modality

                def render(self, seg, _ctx):
                    if self.modality == Modality.ANIMATION:
                        raise RuntimeError("bad animation")
                    path = root / "seg1.png"
                    path.write_bytes(b"png")
                    return VisualAsset(segment_id=seg.id, kind="image", path=str(path))

            with patch("teachgen.pipeline.get_renderer", side_effect=lambda mode: _Renderer(mode)):
                asset = _render_segment(cfg, object(), plan, segment, audio)
        self.assertEqual(segment.modality, Modality.ANIMATION)
        self.assertEqual(asset.rendered_modality, Modality.CONCEPT_IMAGE)
        self.assertIn("bad animation", asset.fallback_reason)

    def test_deterministic_cells_slide_renders_exact_values(self):
        spec = SlideSpec(
            title="One byte",
            bullets=["Eight exact bits"],
            layout="cells",
            cells=list("01000001"),
            cells_label="A = 65",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "slide.png"
            _draw_slide(spec, path)
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 1000)

    def test_nonempty_run_directory_requires_resume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir)
            (path / "partial.txt").write_text("partial", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                _prepare_run_directory(SimpleNamespace(run_dir=path, resume=False))
            _prepare_run_directory(SimpleNamespace(run_dir=path, resume=True))


if __name__ == "__main__":
    unittest.main()
