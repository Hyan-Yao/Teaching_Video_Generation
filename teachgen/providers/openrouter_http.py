"""Small OpenRouter HTTP client used by the pipeline and evaluator."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class OpenRouterHTTPError(RuntimeError):
    """Raised when OpenRouter returns a non-2xx response."""


@dataclass
class OpenRouterClient:
    api_key: str | None = None
    base_url: str = "https://openrouter.ai/api/v1"
    app_title: str = "Teaching Video Generation"

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise SystemExit(
                "OPENROUTER_API_KEY is not set. Export it first:\n"
                "    export OPENROUTER_API_KEY=sk-or-..."
            )

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        if temperature is not None:
            payload["temperature"] = temperature
        return self._post_json("/chat/completions", payload)

    def speech(
        self,
        *,
        model: str,
        text: str,
        voice: str,
        response_format: str = "mp3",
    ) -> bytes:
        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
        }
        content_type, body = self._post_raw("/audio/speech", payload)
        if content_type.startswith("audio/") or content_type == "application/octet-stream":
            return body
        data = _json_from_bytes(body)
        return _extract_media_bytes(data)

    def image_generation(
        self,
        *,
        model: str,
        prompt: str,
        size: str,
        quality: str,
    ) -> bytes:
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": 1,
        }
        content_type, body = self._post_raw("/images", payload)
        if content_type.startswith("image/") or content_type == "application/octet-stream":
            return body
        data = _json_from_bytes(body)
        return _extract_media_bytes(data)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        content_type, body = self._post_raw(path, payload)
        if not content_type.startswith("application/json"):
            raise OpenRouterHTTPError(
                f"Expected JSON from OpenRouter {path}, got {content_type or 'unknown'}"
            )
        return _json_from_bytes(body)

    def _post_raw(self, path: str, payload: dict[str, Any]) -> tuple[str, bytes]:
        req = urllib.request.Request(
            self.base_url.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/",
                "X-Title": self.app_title,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                content_type = resp.headers.get_content_type()
                return content_type, resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise OpenRouterHTTPError(f"OpenRouter {path} failed: {e.code} {detail}") from e


def chat_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter response did not include choices")
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if content is None:
        content = choice.get("text")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        content = "".join(parts)
    text = str(content or "").strip()
    if not text:
        preview = json.dumps(response, ensure_ascii=False)[:1200]
        raise RuntimeError(f"OpenRouter response returned no message content: {preview}")
    return text


def clean_json_text(text: str) -> str:
    """Remove common markdown wrappers around model-produced JSON."""
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def normalize_model_json(text: str, model_name: str) -> str:
    """Clean JSON text and unwrap {"ModelName": {...}} responses."""
    cleaned = clean_json_text(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return cleaned
    if isinstance(data, dict) and set(data.keys()) == {model_name}:
        return json.dumps(data[model_name], ensure_ascii=False)
    return cleaned


def _json_from_bytes(body: bytes) -> dict[str, Any]:
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        preview = body[:200].decode("utf-8", errors="replace")
        raise OpenRouterHTTPError(f"Expected JSON body, got: {preview}") from e


def _extract_media_bytes(data: dict[str, Any]) -> bytes:
    for value in _walk_values(data):
        if not isinstance(value, str):
            continue
        if value.startswith("data:"):
            return _decode_data_url(value)
        if value.startswith("http://") or value.startswith("https://"):
            return _download(value)
        decoded = _try_decode_base64(value)
        if decoded:
            return decoded
    raise OpenRouterHTTPError("OpenRouter response did not contain media bytes, a URL, or base64")


def _walk_values(value: Any):
    if isinstance(value, dict):
        priority = ("b64_json", "audio", "image", "url")
        for key in priority:
            if key in value:
                yield value[key]
        for key, child in value.items():
            if key not in priority:
                yield from _walk_values(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value


def _decode_data_url(value: str) -> bytes:
    _, _, encoded = value.partition(",")
    if not encoded:
        raise OpenRouterHTTPError("Invalid data URL returned by OpenRouter")
    return base64.b64decode(encoded)


def _try_decode_base64(value: str) -> bytes | None:
    if len(value) < 80:
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception:
        return None
    return decoded or None


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as resp:
        return resp.read()
