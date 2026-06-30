import base64
from io import BytesIO
from pathlib import Path
from openai import OpenAI
from typing import TypeVar
from pydantic import BaseModel

OutputModel = TypeVar("OutputModel", bound=BaseModel)

class VideoLLM:
    def __init__(self, model: str = "gpt-4o", frame_count: int = 8):
        self.model = model
        self.frame_count = frame_count
        self.client = OpenAI()

    def analyze(
        self,
        video_path: str | Path,
        prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        
        path = Path(video_path)

        if not path.is_file():
            raise FileNotFoundError(f"Video not found: {path}")

        frames = _sample_video_frames(path, self.frame_count)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        *[
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{frame}"},
                            }
                            for frame in frames
                        ],
                    ],
                }
            ],
            temperature=0,
            seed=12345,
            response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": output_model.__name__,
                "strict": True,
                "schema": output_model.model_json_schema()
            },
        },
        )
        answer = response.choices[0].message.content
        if not answer:
            raise RuntimeError(f"Model {self.model} returned no content for video {path}")

        return output_model.model_validate_json(answer)


def _sample_video_frames(video_path: Path, frame_count: int) -> list[str]:
    from PIL import Image
    from teachgen.mpcompat import VideoFileClip

    clip = VideoFileClip(str(video_path))
    try:
        duration = clip.duration or 0
        if duration <= 0:
            return []

        frames: list[str] = []
        for i in range(frame_count):
            t = duration * (i + 0.5) / frame_count
            frame = clip.get_frame(t)
            buf = BytesIO()
            Image.fromarray(frame).save(buf, format="PNG")
            frames.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
        return frames
    finally:
        clip.close()
