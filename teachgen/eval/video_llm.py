"""OpenAI frame-and-audio evaluator backend.

GPT-5 accepts image inputs but not raw MP4 inputs. Each evaluator chunk is
represented as timestamped JPEG frames plus a Whisper transcript with matching
local timestamps.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypeVar

import cv2
import numpy as np
from openai import OpenAI
from pydantic import BaseModel

from teachgen.eval.video import VideoChunk

OutputModel = TypeVar("OutputModel", bound=BaseModel)


@dataclass
class SampledFrame:
    timestamp_seconds: float
    jpeg_bytes: bytes
    width: int
    height: int
    anchor_timestamp_seconds: float | None = None
    motion_score: float | None = None
    is_stable: bool = False
    stable_duration_seconds: float = 0.0


class VideoLLM:
    """Structured visual extraction from sampled frames and aligned audio."""

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("TEACHGEN_EVAL_VISION_MODEL", "gpt-5.6-sol")
        self.transcribe_model = os.environ.get("TEACHGEN_EVAL_TRANSCRIBE_MODEL", "whisper-1")
        self.max_retries = int(os.environ.get("TEACHGEN_EVAL_VIDEO_RETRIES", "3"))
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the evaluator")
        self.client = OpenAI(api_key=api_key)

    def analyze(
        self,
        video_path: str | Path,
        prompt: str,
        output_model: type[OutputModel],
        *,
        chunk: VideoChunk,
        frame_interval_seconds: float,
        debug_dir: Path,
    ) -> OutputModel:
        path = Path(video_path)
        if not path.is_file():
            raise FileNotFoundError(f"Video not found: {path}")
        if frame_interval_seconds <= 0:
            raise ValueError("frame_interval_seconds must be greater than zero")

        transcript = self._transcribe(path)
        frames = self._sample_frames(path, chunk.end_time_seconds, frame_interval_seconds)
        if not frames:
            raise RuntimeError(f"Could not sample frames from evaluator chunk: {path}")
        self._write_debug(debug_dir, chunk, transcript, frames)

        transcript_text = _format_transcript(transcript)
        content = [
            {
                "type": "text",
                "text": (
                    f"{prompt}\n\n"
                    "Timestamped transcript for this chunk:\n"
                    f"{transcript_text or '[No speech was transcribed.]'}\n\n"
                    "Timestamped frames follow in chronological order. Each frame is "
                    "preceded by its local chunk timestamp. Use the displayed frames "
                    "and transcript as timestamped evidence. Any authoritative source "
                    "narration in the instructions is only a spelling/symbol reference, "
                    "not timestamped evidence."
                ),
            }
        ]
        for frame in frames:
            stability_label = "stable state" if frame.is_stable else "transition candidate"
            content.append(
                {
                    "type": "text",
                    "text": (
                        f"Frame timestamp: {frame.timestamp_seconds:.2f}s ({stability_label}; "
                        f"regular anchor {frame.anchor_timestamp_seconds:.2f}s; "
                        f"local motion score {frame.motion_score:.3f}; "
                        f"stable duration {frame.stable_duration_seconds:.2f}s). "
                        "Only use stable-state frames as evidence of finished layout or "
                        "rendering quality. A transition candidate may be used to understand "
                        "timing or sequence, but its temporary overlap, partial text, or "
                        "incomplete geometry must not be reported as a finished visual defect. "
                        "Treat an animation defect as persistent only when two stable-state "
                        "samples confirm it."
                    ),
                }
            )
            encoded = base64.b64encode(frame.jpeg_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )

        last_error: Exception | None = None
        last_answer = ""
        for _attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": content}],
                    max_completion_tokens=12000,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": output_model.__name__,
                            "strict": True,
                            "schema": output_model.model_json_schema(),
                        },
                    },
                )
                answer = response.choices[0].message.content or ""
                last_answer = answer
                if not answer:
                    last_error = RuntimeError(f"Model {self.model} returned no evaluator content")
                    continue
                return output_model.model_validate_json(answer)
            except Exception as exc:
                last_error = exc

        snippet = last_answer[:500].replace("\n", "\\n")
        raise RuntimeError(
            f"Model {self.model} did not return valid evaluator JSON after "
            f"{self.max_retries + 1} attempts. Last error: {last_error}. "
            f"Last response prefix: {snippet}"
        )

    def _transcribe(self, video_path: Path) -> dict:
        with tempfile.TemporaryDirectory(prefix="teachgen-eval-audio-") as temp_dir:
            audio_path = Path(temp_dir) / "chunk.mp3"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(video_path), "-map", "0:a:0",
                    "-vn", "-ac", "1", "-ar", "16000", str(audio_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode != 0 or not audio_path.is_file():
                raise RuntimeError(f"Could not extract evaluator audio: {result.stderr[-1000:]}")
            with audio_path.open("rb") as audio_file:
                response = self.client.audio.transcriptions.create(
                    model=self.transcribe_model,
                    file=audio_file,
                    response_format="verbose_json",
                    timestamp_granularities=["segment", "word"],
                )
        return _model_to_dict(response)

    @staticmethod
    def _sample_frames(
        video_path: Path,
        duration_seconds: float,
        interval_seconds: float,
    ) -> list[SampledFrame]:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(f"Could not open evaluator video chunk: {video_path}")

        anchors = _sample_timestamps(duration_seconds, interval_seconds)
        selected = _select_low_motion_timestamps(
            capture,
            anchors,
            duration_seconds,
            interval_seconds,
        )
        frames: list[SampledFrame] = []
        for anchor, timestamp, motion_score, is_stable, stable_duration in selected:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            encoded_ok, buffer = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            )
            if encoded_ok:
                frames.append(
                    SampledFrame(
                        timestamp,
                        buffer.tobytes(),
                        width,
                        height,
                        anchor_timestamp_seconds=anchor,
                        motion_score=motion_score,
                        is_stable=is_stable,
                        stable_duration_seconds=stable_duration,
                    )
                )
        capture.release()
        return frames

    @staticmethod
    def _write_debug(
        debug_dir: Path,
        chunk: VideoChunk,
        transcript: dict,
        frames: list[SampledFrame],
    ) -> None:
        transcripts_dir = debug_dir / "transcripts"
        manifests_dir = debug_dir / "frame_manifests"
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        manifests_dir.mkdir(parents=True, exist_ok=True)
        chunk_name = f"chunk_{chunk.index:03d}.json"
        (transcripts_dir / chunk_name).write_text(
            json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        manifest = {
            "chunk_index": chunk.index,
            "start_time_seconds": chunk.start_time_seconds,
            "end_time_seconds": chunk.end_time_seconds,
            "frame_count": len(frames),
            "frames": [
                {
                    "timestamp_seconds": frame.timestamp_seconds,
                    "anchor_timestamp_seconds": frame.anchor_timestamp_seconds,
                    "motion_score": frame.motion_score,
                    "is_stable": frame.is_stable,
                    "stable_duration_seconds": frame.stable_duration_seconds,
                    "selection_method": (
                        "consecutive_low_motion_plateau_near_regular_anchor"
                        if frame.is_stable
                        else "lowest_motion_transition_candidate_near_regular_anchor"
                    ),
                    "mime_type": "image/jpeg",
                    "width": frame.width,
                    "height": frame.height,
                }
                for frame in frames
            ],
        }
        (manifests_dir / chunk_name).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )


def _sample_timestamps(duration_seconds: float, interval_seconds: float) -> list[float]:
    if duration_seconds <= 0:
        return [0.0]
    timestamps: list[float] = []
    current = 0.0
    while current < duration_seconds:
        timestamps.append(round(current, 3))
        current += interval_seconds
    final = max(duration_seconds - 0.05, 0.0)
    if not timestamps or final - timestamps[-1] > 0.25:
        timestamps.append(round(final, 3))
    return timestamps


def _select_low_motion_timestamps(
    capture: cv2.VideoCapture,
    anchors: list[float],
    duration_seconds: float,
    interval_seconds: float,
) -> list[tuple[float, float, float, bool, float]]:
    """Choose a deterministic settled frame near each regular sampling anchor.

    Fixed timestamps frequently land in the middle of a Manim Transform/Write/Fade.
    We cheaply probe nearby frames, estimate local motion from consecutive probes,
    and prefer a frame inside a consecutive low-motion plateau. If no plateau
    exists near an anchor, retain the lowest-motion candidate but mark it as a
    transition candidate so it cannot be used as finished-layout evidence.
    """
    if not anchors:
        return []

    probe_step = min(0.25, max(0.12, interval_seconds / 8))
    search_radius = min(0.75, max(0.25, interval_seconds * 0.375))
    final_time = max(0.0, duration_seconds - 0.05)
    probe_times: list[float] = []
    current = 0.0
    while current <= final_time + 1e-6:
        probe_times.append(round(current, 3))
        current += probe_step
    if not probe_times or final_time - probe_times[-1] > probe_step / 2:
        probe_times.append(round(final_time, 3))

    thumbnails: list[np.ndarray | None] = [None] * len(probe_times)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    frame_index = 0
    probe_index = 0
    while probe_index < len(probe_times):
        ok, frame = capture.read()
        if not ok:
            break
        timestamp = frame_index / fps
        frame_index += 1
        while (
            probe_index < len(probe_times)
            and timestamp + (0.5 / fps) >= probe_times[probe_index]
        ):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            thumbnails[probe_index] = cv2.resize(
                gray, (160, 90), interpolation=cv2.INTER_AREA
            )
            probe_index += 1

    pair_motion: list[float] = []
    for index in range(max(0, len(thumbnails) - 1)):
        left, right = thumbnails[index], thumbnails[index + 1]
        if left is None or right is None:
            pair_motion.append(float("inf"))
        else:
            pair_motion.append(float(np.mean(cv2.absdiff(left, right))))

    local_motion: list[float] = []
    for index, thumbnail in enumerate(thumbnails):
        if thumbnail is None:
            local_motion.append(float("inf"))
            continue
        neighbors = []
        if index > 0:
            neighbors.append(pair_motion[index - 1])
        if index < len(pair_motion):
            neighbors.append(pair_motion[index])
        local_motion.append(sum(neighbors) / len(neighbors) if neighbors else 0.0)

    stable_motion_threshold = float(
        os.environ.get("TEACHGEN_EVAL_STABLE_MOTION_THRESHOLD", "0.03")
    )
    stable_pairs = [value <= stable_motion_threshold for value in pair_motion]

    def stable_run_for(index: int) -> tuple[bool, float]:
        left = index - 1
        while left >= 0 and stable_pairs[left]:
            left -= 1
        right = index
        while right < len(stable_pairs) and stable_pairs[right]:
            right += 1
        pair_count = right - left - 1
        duration = pair_count * probe_step
        # Two consecutive low-motion intervals provide at least ~0.5 seconds
        # of settled evidence at the default probe rate.
        return pair_count >= 2, duration

    selected: list[tuple[float, float, float, bool, float]] = []
    for anchor in anchors:
        candidates = [
            index
            for index, timestamp in enumerate(probe_times)
            if abs(timestamp - anchor) <= search_radius and thumbnails[index] is not None
        ]
        if not candidates:
            selected.append((anchor, anchor, float("inf"), False, 0.0))
            continue
        stable_candidates = [index for index in candidates if stable_run_for(index)[0]]
        candidate_pool = stable_candidates or candidates
        best_index = min(
            candidate_pool,
            key=lambda index: (local_motion[index], abs(probe_times[index] - anchor)),
        )
        is_stable, stable_duration = stable_run_for(best_index)
        selected.append(
            (
                anchor,
                probe_times[best_index],
                round(local_motion[best_index], 3),
                is_stable,
                round(stable_duration, 3),
            )
        )
    return selected


def _model_to_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "json"):
        return json.loads(value.json())
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return asdict(value)


def _format_transcript(transcript: dict) -> str:
    lines = []
    for segment in transcript.get("segments") or []:
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        text = str(segment.get("text", "")).strip()
        if text:
            lines.append(f"[{start:.2f}s-{end:.2f}s] {text}")
    return "\n".join(lines)
