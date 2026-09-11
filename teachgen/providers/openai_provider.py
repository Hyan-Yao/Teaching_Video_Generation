"""Default backend: everything via OpenAI, driven by a single OPENAI_API_KEY."""

from __future__ import annotations

import base64
import io
import json
import tempfile
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Config
from ..schema import WordTiming

T = TypeVar("T", bound=BaseModel)


GPT5_MIN_COMPLETION_TOKENS = 12000


class OpenAIProvider:
    def __init__(self, cfg: Config):
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise SystemExit("Missing dependency. Run: pip install openai") from e
        self.cfg = cfg
        self.m = cfg.models
        self.client = OpenAI(api_key=cfg.api_key, base_url="https://api.openai.com/v1")

    # ------------------------------------------------------------------ text
    def chat(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4000,
        model: str | None = None,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._chat_completion_create(
            model=model or self.m.text, messages=messages, max_tokens=max_tokens
        )
        raw = _message_content(resp)
        if not raw:
            raise RuntimeError(
                "OpenAI chat returned empty content "
                f"(model={model or self.m.text}, finish_reason={_finish_reason(resp)})"
            )
        return raw.strip()

    def chat_json(
        self,
        prompt: str,
        schema: Type[T],
        *,
        system: str = "",
        max_tokens: int = 4000,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> T:
        """JSON mode + pydantic validation, with one self-correcting retry."""
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
        for attempt in range(2):
            kwargs = {
                "model": model or self.m.text,
                "messages": messages,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if seed is not None:
                kwargs["seed"] = seed
            resp = self._chat_completion_create(**kwargs)
            raw = _message_content(resp)
            if not raw:
                last_err = RuntimeError(
                    "OpenAI chat_json returned empty content "
                    f"(model={model or self.m.text}, finish_reason={_finish_reason(resp)})"
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was empty. Return ONLY the JSON object "
                            "matching the schema. Do not include prose."
                        ),
                    }
                )
                continue
            try:
                return schema.model_validate_json(raw)
            except (ValidationError, ValueError) as e:
                last_err = e
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {"role": "user", "content": f"That failed validation: {e}. Fix and resend."}
                )
        raise ValueError(f"chat_json failed schema validation: {last_err}")

    def _chat_completion_create(self, **kwargs):
        kwargs = _normalize_chat_kwargs(kwargs)
        try:
            return self.client.chat.completions.create(**kwargs)
        except Exception as e:
            message = str(e)
            retry_kwargs = dict(kwargs)
            changed = False
            if "max_tokens" in message and "max_tokens" in retry_kwargs:
                retry_kwargs["max_completion_tokens"] = retry_kwargs.pop("max_tokens")
                changed = True
            if "temperature" in message and "temperature" in retry_kwargs:
                retry_kwargs.pop("temperature", None)
                changed = True
            if "seed" in message and "seed" in retry_kwargs:
                retry_kwargs.pop("seed", None)
                changed = True
            if not changed:
                raise
            return self.client.chat.completions.create(**retry_kwargs)

    # ---------------------------------------------------------------- vision
    def vision(
        self,
        prompt: str,
        images: list[bytes],
        *,
        system: str = "",
        max_tokens: int = 4000,
        model: str | None = None,
    ) -> str:
        content = [{"type": "text", "text": prompt}]
        for img in images:
            b64 = base64.b64encode(img).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{_image_mime_type(img)};base64,{b64}"
                    },
                }
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        resp = self._chat_completion_create(
            model=model or self.m.vision, messages=messages, max_tokens=max_tokens
        )
        raw = _message_content(resp)
        if not raw:
            raise RuntimeError(
                "OpenAI vision returned empty content "
                f"(model={model or self.m.vision}, finish_reason={_finish_reason(resp)})"
            )
        return raw.strip()

    # ------------------------------------------------------------------- tts
    def tts(self, text: str, *, voice: str = "alloy") -> tuple[bytes, list[WordTiming]]:
        """Synthesize speech, then transcribe it back for word-level timings.

        OpenAI's TTS endpoint does not return timestamps, so we run the audio
        through whisper with word granularity. This double pass is what lets the
        compositor sync visuals (and any cursor) to the spoken words.
        """
        speech = self.client.audio.speech.create(
            model=self.m.tts, voice=voice, input=text
        )
        audio_bytes = speech.read() if hasattr(speech, "read") else speech.content

        words: list[WordTiming] = []
        with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            try:
                with open(tmp.name, "rb") as fh:
                    tr = self.client.audio.transcriptions.create(
                        model=self.m.transcribe,
                        file=fh,
                        response_format="verbose_json",
                        timestamp_granularities=["word"],
                    )
            except Exception:
                return audio_bytes, words
            for w in getattr(tr, "words", None) or []:
                words.append(
                    WordTiming(
                        word=getattr(w, "word", ""),
                        start=getattr(w, "start", 0.0),
                        end=getattr(w, "end", 0.0),
                    )
                )
        return audio_bytes, words

    # ----------------------------------------------------------------- image
    def image(self, prompt: str, *, size: str = "1536x1024", quality: str = "high") -> bytes:
        result = self.client.images.generate(
            model=self.m.image, prompt=prompt, size=size, quality=quality, n=1
        )
        b64 = result.data[0].b64_json
        if b64:
            return base64.b64decode(b64)
        # Some deployments return a URL instead of inline base64.
        import urllib.request

        with urllib.request.urlopen(result.data[0].url) as r:
            return r.read()


def _normalize_chat_kwargs(kwargs: dict) -> dict:
    """Adapt chat-completions kwargs for GPT-5-style reasoning models."""
    normalized = dict(kwargs)
    model = str(normalized.get("model", ""))
    if not _is_gpt5_model(model):
        return normalized

    if "max_tokens" in normalized:
        requested = normalized.pop("max_tokens") or 0
        normalized["max_completion_tokens"] = max(
            int(requested),
            GPT5_MIN_COMPLETION_TOKENS,
        )

    # Some GPT-5 deployments reject these old chat-completion controls.
    normalized.pop("temperature", None)
    normalized.pop("seed", None)
    return normalized


def _is_gpt5_model(model: str) -> bool:
    lowered = model.casefold()
    return lowered.startswith("gpt-5") or "/gpt-5" in lowered


def _image_mime_type(image: bytes) -> str:
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return "application/octet-stream"


def _message_content(response) -> str:
    try:
        content = response.choices[0].message.content
    except Exception:
        return ""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(content)


def _finish_reason(response) -> str:
    try:
        return str(response.choices[0].finish_reason)
    except Exception:
        return "unknown"
