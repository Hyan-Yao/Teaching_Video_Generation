"""Default backend: everything through OpenRouter."""

from __future__ import annotations

import base64
import json
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Config
from ..schema import WordTiming
from .openrouter_http import OpenRouterClient, chat_text, normalize_model_json

T = TypeVar("T", bound=BaseModel)


class OpenRouterProvider:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.m = cfg.models
        self.client = OpenRouterClient(api_key=cfg.api_key)
        self._sdk_client = None

    # ------------------------------------------------------------------ text
    def chat(self, prompt: str, *, system: str = "", max_tokens: int = 4000) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self.client.chat_completion(
            model=self.m.text,
            messages=messages,
            max_tokens=max_tokens,
        )
        return chat_text(response)

    def chat_json(
        self, prompt: str, schema: Type[T], *, system: str = "", max_tokens: int = 4000
    ) -> T:
        """Structured output validated against a pydantic model, with one retry."""
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        sys_msg = (
            (system + "\n\n" if system else "")
            + "Respond with ONLY a JSON object matching this JSON Schema:\n"
            + schema_json
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]
        last_err = None
        for attempt in range(3):
            use_json_mode = attempt < 2
            response = self.client.chat_completion(
                model=self.m.text,
                messages=messages,
                max_tokens=max_tokens,
                response_format={"type": "json_object"} if use_json_mode else None,
            )
            try:
                raw = chat_text(response)
            except RuntimeError as e:
                last_err = e
                messages.append(
                    {
                        "role": "user",
                        "content": "Your previous response was empty. Return the JSON object now.",
                    }
                )
                continue
            try:
                return schema.model_validate_json(normalize_model_json(raw, schema.__name__))
            except (ValidationError, ValueError) as e:
                last_err = e
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {"role": "user", "content": f"That failed validation: {e}. Fix and resend."}
                )
        raise ValueError(f"chat_json failed schema validation: {last_err}")

    # ---------------------------------------------------------------- vision
    def vision(
        self, prompt: str, images: list[bytes], *, system: str = "", max_tokens: int = 4000
    ) -> str:
        content = [{"type": "text", "text": prompt}]
        for img in images:
            b64 = base64.b64encode(img).decode("utf-8")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        response = self.client.chat_completion(
            model=self.m.vision,
            messages=messages,
            max_tokens=max_tokens,
        )
        return chat_text(response)

    # ------------------------------------------------------------------- tts
    def tts(self, text: str, *, voice: str = "alloy") -> tuple[bytes, list[WordTiming]]:
        """Synthesize narration through OpenRouter.

        OpenRouter TTS does not provide word timings here, so the compositor
        falls back to audio duration probing for segment timing.
        """
        speech = self._openai_sdk().audio.speech.create(
            model=self.m.tts,
            input=text,
            voice=_openrouter_voice(voice),
            response_format="mp3",
        )
        audio_bytes = speech.read() if hasattr(speech, "read") else speech.content
        return audio_bytes, []

    # ----------------------------------------------------------------- image
    def image(self, prompt: str, *, size: str = "1536x1024", quality: str = "high") -> bytes:
        return self.client.image_generation(
            model=self.m.image,
            prompt=prompt,
            size=size,
            quality=quality,
        )

    def _openai_sdk(self):
        if self._sdk_client is None:
            try:
                from openai import OpenAI
            except ImportError as e:  # pragma: no cover
                raise SystemExit("Missing dependency. Run: pip install openai") from e
            self._sdk_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.cfg.api_key,
            )
        return self._sdk_client


def _openrouter_voice(voice: str) -> str:
    voices = {
        "alloy": "Eve",
        "echo": "Rex",
        "fable": "Leo",
        "onyx": "Rex",
        "nova": "Ara",
        "shimmer": "Sal",
    }
    return voices.get(voice, voice)
