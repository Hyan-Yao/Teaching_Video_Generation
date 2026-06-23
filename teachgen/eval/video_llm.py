import base64
import os
from pathlib import Path
from openai import OpenAI
from typing import TypeVar
from pydantic import BaseModel

OutputModel = TypeVar("OutputModel", bound=BaseModel)

class VideoLLM:
    def __init__(self, model: str = "google/gemini-3.5-flash"):
        self.model = model
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def analyze(
        self,
        video_path: str | Path,
        prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        
        path = Path(video_path)

        if not path.is_file():
            raise FileNotFoundError(f"Video not found: {path}")

        encoded_video = base64.b64encode(path.read_bytes()).decode("utf-8")
        video_url = f"data:video/mp4;base64,{encoded_video}"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "video_url",
                            "video_url": {"url": video_url},
                        },
                    ],
                }
            ],
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