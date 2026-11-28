"""Voice the demo narration with ElevenLabs, one audio file per line.

    .venv/bin/python scripts/narrate.py lines.json out_dir/

lines.json is a list of strings. Each becomes out_dir/NN.mp3, and
out_dir/durations.json lists their lengths in seconds, so the recording can
hold each scene exactly as long as its line takes to say.

The key is ELEVENLABS_API_KEY, read from the environment or from the
project's .env (set up by `npx @elevenlabs/cli onboard init`). It is never
printed. Install with: pip install -e ".[narrate]"
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # George, narrative
MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_v4")


def load_env(path: Path = ROOT / ".env") -> None:
    """Put .env's keys in the process environment before the SDK is imported."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip().removeprefix("export "), v.strip().strip("\"'"))


def duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    )
    return float(out)


def main() -> None:
    lines_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    load_env()
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("ELEVENLABS_API_KEY is not set: run `npx -y @elevenlabs/cli@latest onboard init`")

    from elevenlabs import ElevenLabs, VoiceSettings

    client = ElevenLabs()
    lines = json.loads(lines_path.read_text())
    durations = []
    for i, text in enumerate(lines):
        mp3 = out_dir / f"{i:02d}.mp3"
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=VOICE_ID,
            model_id=MODEL_ID,
            voice_settings=VoiceSettings(stability=0.55, similarity_boost=0.75),
        )
        with open(mp3, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        durations.append(round(duration(mp3), 2))
        print(f"{i:2d} {durations[-1]:5.2f}s  {text[:60]}")
    (out_dir / "durations.json").write_text(json.dumps(durations))
    print(f"total speech {sum(durations):.1f}s")


if __name__ == "__main__":
    main()
