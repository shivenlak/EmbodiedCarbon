"""The overnight spend cap: once the usage log reaches the budget, no call is made."""

import json

from ecarbon.vision.providers import ClaudeProvider, spent_usd


def test_the_budget_stops_calls_before_they_are_made(tmp_path, monkeypatch):
    log = tmp_path / "usage.jsonl"
    log.write_text(json.dumps({"usd": 1.2}) + "\n" + json.dumps({"usd": 0.9}) + "\n")
    monkeypatch.setenv("ECARBON_VISION_USAGE", str(log))
    monkeypatch.setenv("ECARBON_VISION_BUDGET_USD", "2.0")
    assert spent_usd() == 2.1
    p = object.__new__(ClaudeProvider)
    p.model, p._client = "claude-opus-5-5", None  # a call would raise on None
    assert p.read(b"", "levels") is None
