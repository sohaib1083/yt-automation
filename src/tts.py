"""
Text-to-speech using gTTS (Google Translate TTS — free, no API key).
Generates one MP3 per section into assets/{slug}/audio/.
"""

import time
from pathlib import Path

import yaml
from gtts import gTTS

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"


def _load_lang() -> str:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)["tts"].get("lang", "en")


def _synthesize(text: str, output_path: Path, lang: str) -> None:
    tts = gTTS(text=text, lang=lang, slow=False)
    tts.save(str(output_path))


def generate_voiceovers(sections: list[dict], slug: str, assets_base: Path = None) -> list[Path]:
    """
    Generate MP3 voiceovers for all sections.

    Returns list of paths in section order.
    """
    if assets_base is None:
        assets_base = Path(__file__).parent.parent / "assets"
    audio_dir = assets_base / slug / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    lang = _load_lang()
    paths = []

    for i, section in enumerate(sections):
        path = audio_dir / f"section_{i:02d}.mp3"
        paths.append(path)

        if path.exists() and path.stat().st_size > 0:
            print(f"[tts] ↩ Skip (exists) section_{i:02d}.mp3")
            continue

        for attempt in range(3):
            try:
                _synthesize(section["narration"], path, lang)
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                print(f"[tts] ⚠ section_{i:02d} attempt {attempt+1} failed ({exc}) — retry in {wait}s")
                time.sleep(wait)

        print(f"[tts] ✓ section_{i:02d}.mp3 → {path}")

    return paths


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True, help="Path to script.json")
    parser.add_argument("--slug", required=True, help="Slug for asset naming")
    args = parser.parse_args()

    script = json.loads(Path(args.script).read_text())
    generate_voiceovers(script["sections"], args.slug)
