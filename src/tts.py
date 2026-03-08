"""
Text-to-speech using ElevenLabs (human-like voice).
Falls back to gTTS if ELEVENLABS_API_KEY is not set.
Generates one MP3 per section into assets/{slug}/audio/.
"""

import os
import time
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"


def _load_tts_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f).get("tts", {})


def _synthesize_elevenlabs(text: str, output_path: Path, voice_id: str, model_id: str) -> None:
    from elevenlabs.client import ElevenLabs

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    client = ElevenLabs(api_key=api_key)
    audio = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=model_id,
        output_format="mp3_44100_128",
    )
    with open(output_path, "wb") as f:
        for chunk in audio:
            f.write(chunk)


def _synthesize_gtts(text: str, output_path: Path, lang: str) -> None:
    from gtts import gTTS
    gTTS(text=text, lang=lang, slow=False).save(str(output_path))


def generate_voiceovers(sections: list[dict], slug: str, assets_base: Path = None) -> list[Path]:
    """
    Generate MP3 voiceovers for all sections.
    Uses ElevenLabs if ELEVENLABS_API_KEY is set, otherwise falls back to gTTS.
    Returns list of paths in section order.
    """
    if assets_base is None:
        assets_base = Path(__file__).parent.parent / "assets"
    audio_dir = assets_base / slug / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    cfg = _load_tts_config()
    use_elevenlabs = bool(os.environ.get("ELEVENLABS_API_KEY"))
    voice_id = cfg.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")  # Rachel
    model_id = cfg.get("elevenlabs_model", "eleven_multilingual_v2")
    lang = cfg.get("lang", "en")

    provider = "ElevenLabs" if use_elevenlabs else "gTTS"
    print(f"[tts] Provider: {provider}")

    paths = []
    for i, section in enumerate(sections):
        path = audio_dir / f"section_{i:02d}.mp3"
        paths.append(path)

        if path.exists() and path.stat().st_size > 0:
            print(f"[tts] ↩ Skip (exists) section_{i:02d}.mp3")
            continue

        for attempt in range(3):
            try:
                if use_elevenlabs:
                    _synthesize_elevenlabs(section["narration"], path, voice_id, model_id)
                else:
                    _synthesize_gtts(section["narration"], path, lang)
                break
            except Exception as exc:
                # If ElevenLabs fails with auth/permission error, fall back to gTTS immediately
                if use_elevenlabs and ("missing_permissions" in str(exc) or "401" in str(exc) or "unauthorized" in str(exc).lower()):
                    print(f"[tts] ⚠ ElevenLabs auth error — falling back to gTTS")
                    _synthesize_gtts(section["narration"], path, lang)
                    break
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
