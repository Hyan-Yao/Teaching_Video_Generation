from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class TextLLM:
    def __init__(self, model: str = "gpt-4o"):
        self.model = model
        self.client = OpenAI()

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
        )

        answer = response.choices[0].message.content
        if not answer:
            raise RuntimeError(f"Model {self.model} returned no content")

        return output_model.model_validate_json(answer)
