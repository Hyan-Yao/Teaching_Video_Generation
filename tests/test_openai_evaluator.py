import tempfile
import unittest
from pathlib import Path

from teachgen.eval.extractors import ChunkAnalyzer, shift_chunk_timestamps
from teachgen.eval.models import ChunkAnalysis, EvidenceItem
from teachgen.eval.video import VideoChunk
from teachgen.eval.video_llm import (
    _format_transcript,
    _sample_timestamps,
    _select_low_motion_timestamps,
)
from teachgen.providers.openai_provider import _image_mime_type


def _analysis(index: int, duration: float) -> ChunkAnalysis:
    nested = {
        "chunk_index": index,
        "start_time_seconds": 0,
        "end_time_seconds": duration,
    }
    return ChunkAnalysis.model_validate(
        {
            "chunk_index": index,
            "start_time_seconds": 0,
            "end_time_seconds": duration,
            "content": {
                **nested,
                "topics": [],
                "claims": [],
                "definitions": [],
                "examples": [],
                "possible_accuracy_issues": [],
            },
            "visual_multimedia": {
                **nested,
                "visual_elements": [],
                "visual_defects": [],
                "audio_visual_alignment": [],
                "effective_visual_support": [],
                "missed_visual_opportunities": [],
            },
            "pedagogy": {
                **nested,
                "scaffolding_events": [],
                "transitions": [],
                "questions": [],
                "learner_activities": [],
                "summaries_and_reviews": [],
                "prerequisite_assumptions": [],
                "announced_cognitive_goals": [],
                "bloom_signals": [],
                "icap_signals": [],
            },
        }
    )


class _FakeVideoLLM:
    def analyze(self, _video_path, prompt, output_model, **kwargs):
        assert output_model is ChunkAnalysis
        assert "CONTENT EXTRACTION INSTRUCTIONS" in prompt
        assert kwargs["frame_interval_seconds"] == 2
        return _analysis(kwargs["chunk"].index, kwargs["chunk"].end_time_seconds)


class OpenAIEvaluatorTests(unittest.TestCase):
    def test_two_second_sampling_includes_the_final_moment(self):
        self.assertEqual(_sample_timestamps(5, 2), [0.0, 2.0, 4.0, 4.95])

    def test_motion_aware_sampling_avoids_a_transition_anchor(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "transition.mp4"
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"mp4v"), 20, (64, 48)
            )
            for index in range(80):
                if index < 35:
                    value = 0
                elif index <= 45:
                    value = int((index - 35) * 25.5)
                else:
                    value = 255
                writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
            writer.release()
            capture = cv2.VideoCapture(str(path))
            selected = _select_low_motion_timestamps(capture, [2.0], 4.0, 2.0)
            capture.release()

        _, timestamp, motion, is_stable, stable_duration = selected[0]
        self.assertGreater(abs(timestamp - 2.0), 0.25)
        self.assertLess(motion, 2.0)
        self.assertTrue(is_stable)
        self.assertGreaterEqual(stable_duration, 0.5)

    def test_timestamped_transcript_is_rendered_for_the_vision_prompt(self):
        transcript = {
            "segments": [
                {"start": 0, "end": 1.25, "text": " Binary starts with bits. "},
                {"start": 1.25, "end": 2.0, "text": ""},
            ]
        }
        self.assertEqual(
            _format_transcript(transcript),
            "[0.00s-1.25s] Binary starts with bits.",
        )

    def test_openai_images_keep_their_real_mime_type(self):
        self.assertEqual(_image_mime_type(b"\xff\xd8\xff\xe0jpeg"), "image/jpeg")
        self.assertEqual(_image_mime_type(b"\x89PNG\r\n\x1a\npng"), "image/png")

    def test_combined_extractor_preserves_the_existing_chunk_schema(self):
        chunk = VideoChunk(index=2, start_time_seconds=0, end_time_seconds=11)
        with tempfile.TemporaryDirectory() as temp_dir:
            analysis = ChunkAnalyzer(_FakeVideoLLM()).analyze(
                "unused.mp4",
                chunk,
                frame_interval_seconds=2,
                debug_dir=Path(temp_dir),
            )
        self.assertEqual(analysis.chunk_index, 2)
        self.assertEqual(analysis.content.end_time_seconds, 11)
        self.assertEqual(analysis.visual_multimedia.chunk_index, 2)
        self.assertEqual(analysis.pedagogy.chunk_index, 2)

    def test_later_chunk_evidence_is_shifted_to_full_video_time(self):
        analysis = _analysis(1, 10)
        analysis.content.claims = [
            EvidenceItem(
                start_time_seconds=1,
                end_time_seconds=2,
                description="A claim",
                confidence=0.9,
            )
        ]
        shift_chunk_timestamps(analysis, 120)
        self.assertEqual(analysis.start_time_seconds, 120)
        self.assertEqual(analysis.end_time_seconds, 130)
        self.assertEqual(analysis.content.claims[0].start_time_seconds, 121)


if __name__ == "__main__":
    unittest.main()
