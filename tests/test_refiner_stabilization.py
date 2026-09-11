import unittest

from code2video.scope_refine import GridCodeModifier
from teachgen.eval.models import EvaluationRequest
from teachgen.eval.run_evaluation import _authoritative_narration
from teachgen.feedback.evaluation_adapter import (
    _RepairCandidate,
    _RepairPlan,
    _enforce_asset_repair_scope,
)
from teachgen.feedback.outer_plan_refiner import preserve_outer_visual_contract
from teachgen.pipeline import _plan_cache_changes
from teachgen.renderers.animation import _AnimSpec, _normalize_step_timings
from teachgen.schema import LessonPlan, Modality, Segment


def _segment(
    segment_id: str,
    *,
    narration: str = "Original narration.",
    modality: Modality = Modality.ANIMATION,
    visual_brief: str = "Original visual.",
) -> Segment:
    return Segment(
        id=segment_id,
        title=f"Title {segment_id}",
        narration=narration,
        modality=modality,
        visual_brief=visual_brief,
        target_seconds=10,
    )


def _plan(*segments: Segment) -> LessonPlan:
    return LessonPlan(
        topic="Binary numbers",
        audience="Introductory learners",
        objectives=["Convert a decimal number to binary."],
        segments=list(segments),
    )


class RefinerStabilizationTests(unittest.TestCase):
    def test_outer_plan_repair_preserves_existing_visual_contract(self):
        original = _plan(_segment("seg1"))
        revised = _plan(
            _segment(
                "seg1",
                narration="A more concrete worked example.",
                modality=Modality.CONCEPT_IMAGE,
                visual_brief="A completely different visual.",
            )
        )

        result = preserve_outer_visual_contract(original, revised)

        self.assertEqual(result.segments[0].narration, "A more concrete worked example.")
        self.assertEqual(result.segments[0].modality, Modality.ANIMATION)
        self.assertEqual(result.segments[0].visual_brief, "Original visual.")

    def test_plan_cache_changes_only_invalidate_changed_segments(self):
        original = _plan(_segment("seg1"), _segment("seg2"))
        revised = original.model_copy(deep=True)
        revised.segments[1].narration = "Only segment two changed."

        dirty_full, dirty_visual = _plan_cache_changes(original, revised)

        self.assertEqual(dirty_full, {"seg2"})
        self.assertEqual(dirty_visual, set())

    def test_visual_only_plan_change_keeps_audio_cache_valid(self):
        original = _plan(_segment("seg1"))
        revised = original.model_copy(deep=True)
        revised.segments[0].visual_brief = "A cleaner visual."

        dirty_full, dirty_visual = _plan_cache_changes(original, revised)

        self.assertEqual(dirty_full, set())
        self.assertEqual(dirty_visual, {"seg1"})

    def test_animation_timing_windows_are_monotonic_and_cover_audio(self):
        spec = _AnimSpec(
            lecture_lines=["First idea", "Second idea", "Third idea"],
            animations=["Show first", "Show second", "Show third"],
            step_start_seconds=[0, 4.0, 8.5],
            step_end_seconds=[3.5, 8.0, 12.0],
        )

        timings = _normalize_step_timings(spec, 12)

        self.assertEqual(timings[0]["start_seconds"], 0)
        self.assertEqual(timings[-1]["end_seconds"], 12)
        self.assertEqual(timings[0]["end_seconds"], timings[1]["start_seconds"])
        self.assertEqual(timings[1]["end_seconds"], timings[2]["start_seconds"])

    def test_cleanup_feedback_is_inserted_without_replacing_instructional_code(self):
        code = "\n".join(
            [
                "class Demo:",
                "    def construct(self):",
                "        old_label = Text('old')",
                "        new_label = Text('new')",
            ]
        )
        feedback = [
            "[LAYOUT] Problem: stale label; "
            "Solution: Line 4: self.play(FadeOut(old_label))"
        ]

        modified = GridCodeModifier(code).parse_feedback_and_modify(feedback)

        self.assertIn("        self.play(FadeOut(old_label))\n        new_label", modified)

    def test_source_narration_is_extracted_for_symbol_verification(self):
        request = EvaluationRequest(
            video_path="video.mp4",
            course_requirement=(
                "1. seg1: ASCII\n"
                "   Narration: A is 01000001.\n"
                "2. seg2: Next\n"
                "   Narration: B is 01000010."
            ),
        )

        self.assertEqual(
            _authoritative_narration(request),
            "A is 01000001.\nB is 01000010.",
        )

    def test_visual_metric_repair_cannot_rewrite_narration(self):
        repair_plan = _RepairPlan(
            candidates=[
                _RepairCandidate(
                    timestamp_seconds=10,
                    segment_id="seg1",
                    severity="major",
                    issue="Narration and visible diagram do not match.",
                    fix_action="rewrite_narration",
                    source_metric="Multimedia Learning Design",
                )
            ]
        )

        _enforce_asset_repair_scope(repair_plan)

        self.assertEqual(repair_plan.candidates[0].fix_action, "re_render")
        self.assertIn("preserve narration", repair_plan.candidates[0].detail)


if __name__ == "__main__":
    unittest.main()
