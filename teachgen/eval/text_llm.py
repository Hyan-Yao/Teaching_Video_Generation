import os
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class TextLLM:
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("TEACHGEN_EVAL_TEXT_MODEL", "gpt-5.6-sol")
        self.max_retries = int(os.environ.get("TEACHGEN_EVAL_TEXT_RETRIES", "3"))
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the evaluator")
        self.client = OpenAI(api_key=api_key)

    def analyze(
        self,
        prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        last_error: Exception | None = None
        last_answer = ""

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
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
            except Exception as exc:
                last_error = exc
                continue

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
