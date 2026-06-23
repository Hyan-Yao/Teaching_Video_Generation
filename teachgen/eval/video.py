from pydantic import BaseModel, Field
from pathlib import Path
from moviepy import VideoFileClip


class VideoChunk(BaseModel):
    index: int = Field(ge=0)
    start_time_seconds: float = Field(ge=0)
    end_time_seconds: float = Field(ge=0)


def plan_video_chunks(
    duration_seconds: float,
    chunk_duration_seconds: float = 900,
) -> list[VideoChunk]:
    
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")

    if chunk_duration_seconds <= 0:
        raise ValueError("chunk_duration_seconds must be greater than zero")
    
    chunks: list[VideoChunk] = []
    start_time = 0.0
    index = 0

    while start_time < duration_seconds:
        end_time = min(
            start_time + chunk_duration_seconds,
            duration_seconds,
        )
        chunks.append(
            VideoChunk(
                index=index,
                start_time_seconds=start_time,
                end_time_seconds=end_time,
            )
        )
        start_time = end_time
        index += 1
    return chunks
def get_video_duration(video_path: str | Path) -> float:
    path = Path(video_path)

    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")
    
    with VideoFileClip(str(path)) as video:
        duration = video.duration

    if duration is None or duration <= 0:
        raise ValueError(f"Could not determine video duration: {path}")

    return float(duration)

def plan_chunks_for_video(video_path: str | Path,
    chunk_duration_seconds: float = 900,
) -> list[VideoChunk]:

    duration = get_video_duration(video_path)

    return plan_video_chunks(duration, chunk_duration_seconds)

def write_video_chunk(video_path: str | Path, chunk: VideoChunk, output_path: str | Path) -> Path:

    source = Path(video_path)
    destination = Path(output_path)

    if not source.is_file():
        raise FileNotFoundError(f"Video not found: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    with VideoFileClip(str(source)) as video:
        clipped_video = video.subclipped(
            chunk.start_time_seconds,
            chunk.end_time_seconds,
        )
        clipped_video.write_videofile(
            str(destination),
            codec="libx264",
            audio_codec="aac",
        )
        clipped_video.close()

    return destination

