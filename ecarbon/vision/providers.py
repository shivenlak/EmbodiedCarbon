"""The model behind vision, chosen by ECARBON_VISION=claude|gemini|cache.

`cache` replays saved Claude answers and never calls the API.

Unset means off, and nothing here is imported or called. The SDKs are the
optional `vision` extra and are imported only when a provider is built.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Protocol

from ecarbon.vision.tasks import PROMPTS, SCHEMAS, Task

log = logging.getLogger(__name__)

# $ per million tokens (input, output), first-party API rates, Nov 2026.
PRICE_PER_MTOK = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}


def _usage_log() -> Path:
    return Path(os.environ.get("ECARBON_VISION_USAGE", "~/.cache/ecarbon/vision_usage.jsonl")).expanduser()


def spent_usd() -> float:
    """Dollars logged so far in the usage log (ECARBON_VISION_USAGE)."""
    try:
        return sum(json.loads(ln)["usd"] for ln in _usage_log().read_text().splitlines() if ln.strip())
    except FileNotFoundError:
        return 0.0


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

        # A hard stop, so an overnight run cannot spend past what was agreed.
        budget = os.environ.get("ECARBON_VISION_BUDGET_USD")
        if budget is not None and spent_usd() >= float(budget):
            log.warning("vision (claude) budget $%s reached; %s not read", budget, task)
            return None
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
        self._log_usage(task, response.usage)
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            log.warning("vision (claude) %s stopped: %s", task, response.stop_reason)
            return None
        return response.parsed_output.model_dump()

    def _log_usage(self, task: Task, usage) -> None:
        pin, pout = PRICE_PER_MTOK.get(self.model, (4.0, 20.0))
        usd = (usage.input_tokens * pin + usage.output_tokens * pout) / 1e6
        path = _usage_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps({"model": self.model, "task": str(task), "in": usage.input_tokens,
                                "out": usage.output_tokens, "usd": round(usd, 5)}) + "\n")


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
