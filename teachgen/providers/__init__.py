"""Provider abstraction — the 'one key' layer.

Every model call (text, structured, vision, TTS, image) goes through a Provider.
The default OpenAIProvider routes everything through OpenAI so a single
OPENAI_API_KEY is all the user needs. TeachGen currently supports the OpenAI
backend only.
"""

from __future__ import annotations

from ..config import Config
from .base import Provider


def get_provider(cfg: Config) -> Provider:
    from .openai_provider import OpenAIProvider

    return OpenAIProvider(cfg)


__all__ = ["Provider", "get_provider"]
