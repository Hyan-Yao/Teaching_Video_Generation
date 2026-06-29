"""
Unified LLM / vision request module.

All config is read from the project-root .env file:

  OPENAI_API_KEY=sk-proj-...
  OPENAI_BASE_URL=https://api.openai.com/v1   # optional, this is the default
  LLM_MODEL=gpt-4o                             # model for text generation
  VISION_MODEL=gpt-4o                          # model for vision feedback (defaults to LLM_MODEL)
"""

import os
import base64
import time
import random
import pathlib
import cv2
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
_API_KEY = os.getenv("OPENAI_API_KEY", "")
_LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
_VISION_MODEL = os.getenv("VISION_MODEL") or _LLM_MODEL


def _client() -> OpenAI:
    return OpenAI(base_url=_BASE_URL, api_key=_API_KEY)


def request_llm(prompt: str, max_tokens: int = 10000, max_retries: int = 3):
    """
    Text completion via the configured LLM_MODEL.
    Returns (response, usage_dict) — compatible with TeachingVideoAgent's API callable.
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    client = _client()
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=_LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            if resp.usage:
                usage["prompt_tokens"] = resp.usage.prompt_tokens or 0
                usage["completion_tokens"] = resp.usage.completion_tokens or 0
                usage["total_tokens"] = resp.usage.total_tokens or 0
            return resp, usage
        except Exception as e:
            if attempt == max_retries:
                raise
            delay = (2 ** attempt) * 0.1 + random.random() * 0.1
            print(f"LLM request failed: {e}. Retry {attempt}/{max_retries} in {delay:.1f}s...")
            time.sleep(delay)
    return None, usage


def request_vision(prompt: str, image_b64_list: list, max_tokens: int = 10000, max_retries: int = 3):
    """
    Vision completion with one or more base64-encoded images (JPEG or PNG auto-detected).
    Returns the raw OpenAI response object.
    """
    client = _client()
    content = [{"type": "text", "text": prompt}]
    for b64 in image_b64_list:
        mime = "image/jpeg" if b64.startswith("/9j/") else "image/png"
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    for attempt in range(1, max_retries + 1):
        try:
            return client.chat.completions.create(
                model=_VISION_MODEL,
                messages=[{"role": "user", "content": content}],
                max_tokens=max_tokens,
            )
        except Exception as e:
            if attempt == max_retries:
                raise
            delay = (2 ** attempt) * 0.2 + random.random() * 0.2
            print(f"Vision request failed: {e}. Retry {attempt}/{max_retries} in {delay:.1f}s...")
            time.sleep(delay)


def request_gpt5_video_img(
    prompt: str, video_path: str, image_path: str, max_tokens: int = 10000, **_kwargs
):
    """
    Evaluate a rendered video against a reference grid image.
    Extracts 3 frames (10 / 50 / 90 %) and sends them together with the reference
    image to request_vision.
    """
    cap = cv2.VideoCapture(video_path)
    total = max(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 1)
    frames_b64 = []
    for frac in (0.1, 0.5, 0.9):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * frac))
        ok, frame = cap.read()
        if ok:
            _, buf = cv2.imencode(".jpg", frame)
            frames_b64.append(base64.b64encode(buf).decode())
    cap.release()

    with open(image_path, "rb") as f:
        ref_b64 = base64.b64encode(f.read()).decode()

    return request_vision(prompt, [*frames_b64, ref_b64], max_tokens=max_tokens)
