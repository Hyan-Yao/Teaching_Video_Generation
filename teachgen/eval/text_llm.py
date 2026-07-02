import os
import hashlib
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class TextLLM:
    def __init__(self, model: str = "openai/gpt-4.1"):
        self.model = model
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def analyze(
        self,
        prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            seed=12345,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "strict": True,
                    "schema": output_model.model_json_schema(),
                },
            },
            extra_body={
                "session_id": _stable_session_id(self.model, output_model.__name__, prompt),
            },
        )

        answer = response.choices[0].message.content
        if not answer:
            raise RuntimeError(f"Model {self.model} returned no content")

        return output_model.model_validate_json(answer)


def _stable_session_id(model: str, schema_name: str, prompt: str) -> str:
    key = f"{model}\n{schema_name}\n{prompt}".encode("utf-8")
    return f"eval-{hashlib.sha256(key).hexdigest()[:32]}"
