import os
import hashlib
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class TextLLM:
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("TEACHGEN_EVAL_TEXT_MODEL", "openai/gpt-4.1")
        self.max_retries = int(os.environ.get("TEACHGEN_EVAL_TEXT_RETRIES", "3"))
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def analyze(
        self,
        prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        last_error: Exception | None = None
        last_answer = ""

        for attempt in range(self.max_retries + 1):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                seed=12345 + attempt,
                max_tokens=8000,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_model.__name__,
                        "strict": True,
                        "schema": output_model.model_json_schema(),
                    },
                },
                extra_body={
                    "session_id": _stable_session_id(
                        self.model,
                        output_model.__name__,
                        prompt,
                        attempt=attempt,
                    ),
                },
            )

            answer = response.choices[0].message.content
            last_answer = answer or ""
            if not answer:
                last_error = RuntimeError(f"Model {self.model} returned no content")
                continue

            try:
                return output_model.model_validate_json(answer)
            except ValidationError as exc:
                last_error = exc

        snippet = last_answer[:500].replace("\n", "\\n")
        raise RuntimeError(
            f"Model {self.model} did not return valid JSON after "
            f"{self.max_retries + 1} attempts for {output_model.__name__}. "
            f"Last error: {last_error}. Last response prefix: {snippet}"
        )


def _stable_session_id(model: str, schema_name: str, prompt: str, *, attempt: int = 0) -> str:
    key = f"{model}\n{schema_name}\n{attempt}\n{prompt}".encode("utf-8")
    return f"eval-{hashlib.sha256(key).hexdigest()[:32]}"
