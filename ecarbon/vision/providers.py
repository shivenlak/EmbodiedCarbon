"""The model behind vision, chosen by ECARBON_VISION=claude|gemini|cache.

`cache` replays saved Claude answers and never calls the API.

Unset means off, and nothing here is imported or called. The SDKs are the
optional `vision` extra and are imported only when a provider is built.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Protocol

from ecarbon.vision.tasks import PROMPTS, SCHEMAS, Task

log = logging.getLogger(__name__)


class Provider(Protocol):
    name: str
    model: str

    def read(self, png: bytes, task: Task) -> dict | None: ...


class ClaudeProvider:
    name = "claude"

    def __init__(self, model: str | None = None):
        import anthropic

        self.model = model or os.environ.get("ECARBON_VISION_MODEL", "claude-opus-5-5")
        self._client = anthropic.Anthropic()

    def read(self, png: bytes, task: Task) -> dict | None:
        import anthropic

        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=4096,
                output_config={"effort": "low"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": base64.standard_b64encode(png).decode(),
                                },
                            },
                            {"type": "text", "text": PROMPTS[task]},
                        ],
                    }
                ],
                output_format=SCHEMAS[task],
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            log.warning("vision (claude) %s failed: %s", task, e)
            return None
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            log.warning("vision (claude) %s stopped: %s", task, response.stop_reason)
            return None
        return response.parsed_output.model_dump()


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str | None = None):
        from google import genai

        self.model = model or os.environ.get("ECARBON_VISION_MODEL", "gemini-2.5-pro")
        self._client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    def read(self, png: bytes, task: Task) -> dict | None:
        from google.genai import types

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=png, mime_type="image/png"), PROMPTS[task]],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": SCHEMAS[task],
                },
            )
        except Exception as e:  # the SDK's error types vary by release
            log.warning("vision (gemini) %s failed: %s", task, e)
            return None
        parsed = response.parsed
        return parsed.model_dump() if parsed is not None else None


class CachedOnlyProvider:
    """Claude's saved answers, with no key and no call: a page never read
    before stays unread. For a deployment that ships the vision cache."""

    name = "claude"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("ECARBON_VISION_MODEL", "claude-opus-5-5")

    def read(self, png: bytes, task: Task) -> dict | None:
        return None


def provider_from_env() -> Provider | None:
    which = os.environ.get("ECARBON_VISION", "").strip().lower()
    if which == "cache":
        return CachedOnlyProvider()
    if which == "claude":
        return ClaudeProvider()
    if which == "gemini":
        return GeminiProvider()
    return None
