"""
Text-to-speech with multiple providers, tried in priority order:
  1. ElevenLabs  — best quality, requires ELEVENLABS_API_KEY
  2. Edge-TTS    — Microsoft neural voices, completely FREE, no key needed
  3. Deepgram    — natural Aura voices, requires DEEPGRAM_API_KEY
  4. gTTS        — last resort (robotic but always works)

Generates one MP3 per section into assets/{slug}/audio/.
"""

import asyncio
import os
import time
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

# Edge-TTS voices — natural Microsoft neural voices, rotating for variety
_EDGE_VOICES = [
    "en-US-AndrewNeural",      # male, warm authoritative narrator
    "en-US-ChristopherNeural", # male, clear documentary style
    "en-US-BrianNeural",       # male, engaging storyteller
    "en-US-AriaNeural",        # female, confident and expressive
    "en-US-JennyNeural",       # female, friendly professional
    "en-US-EricNeural",        # male, deep and trustworthy
]
_DEFAULT_EDGE_VOICE = "en-US-AndrewNeural"


def _load_tts_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f).get("tts", {})


# ─── Provider implementations ────────────────────────────────────────────────

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


def _synthesize_edge_tts(text: str, output_path: Path, voice: str) -> None:
    """Microsoft Edge neural TTS — free, no API key required."""
    import edge_tts

    async def _run():
        # Retry up to 5 times — Microsoft endpoint occasionally resets connections
        last_exc = None
        delays = [1, 2, 3, 4, 5]
        for attempt, delay in enumerate(delays):
            try:
                communicate = edge_tts.Communicate(text, voice, rate="+5%", volume="+10%")
                await communicate.save(str(output_path))
                return
            except Exception as exc:
                last_exc = exc
                if attempt < len(delays) - 1:
                    await asyncio.sleep(delay)
        raise last_exc

    asyncio.run(_run())


def _synthesize_deepgram(text: str, output_path: Path) -> None:
    """Deepgram Aura TTS — natural voices, free tier available."""
    import urllib.request
    import json as _json
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    url = "https://api.deepgram.com/v1/speak?model=aura-asteria-en"
    payload = _json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        output_path.write_bytes(resp.read())


def _synthesize_gtts(text: str, output_path: Path, lang: str) -> None:
    from gtts import gTTS
    gTTS(text=text, lang=lang, slow=False).save(str(output_path))


# ─── Ordered provider chain ───────────────────────────────────────────────────

def _is_elevenlabs_auth_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("missing_permissions", "401", "unauthorized", "forbidden"))


def _synthesize_with_fallback(text: str, output_path: Path, cfg: dict) -> str:
    """
    Try providers in order. Returns name of provider that succeeded.
    """
    voice_id = cfg.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
    model_id = cfg.get("elevenlabs_model", "eleven_multilingual_v2")
    edge_voice = cfg.get("edge_voice", _DEFAULT_EDGE_VOICE)
    lang = cfg.get("lang", "en")

    # 1. ElevenLabs
    if os.environ.get("ELEVENLABS_API_KEY"):
        try:
            _synthesize_elevenlabs(text, output_path, voice_id, model_id)
            return "ElevenLabs"
        except Exception as exc:
            if _is_elevenlabs_auth_error(exc):
                print(f"[tts] ⚠ ElevenLabs auth error — trying Edge-TTS")
            else:
                print(f"[tts] ⚠ ElevenLabs failed ({exc}) — trying Edge-TTS")

    # 2. Edge-TTS (Microsoft neural voices — always free)
    try:
        _synthesize_edge_tts(text, output_path, edge_voice)
        return f"Edge-TTS ({edge_voice})"
    except Exception as exc:
        print(f"[tts] ⚠ Edge-TTS failed ({exc}) — trying Deepgram")

    # 3. Deepgram Aura
    if os.environ.get("DEEPGRAM_API_KEY"):
        try:
            _synthesize_deepgram(text, output_path)
            return "Deepgram"
        except Exception as exc:
            print(f"[tts] ⚠ Deepgram failed ({exc}) — falling back to gTTS")

    # 4. gTTS (last resort)
    _synthesize_gtts(text, output_path, lang)
    return "gTTS"


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_voiceovers(sections: list[dict], slug: str, assets_base: Path = None) -> list[Path]:
    """
    Generate MP3 voiceovers for all sections.
    Provider priority: ElevenLabs → Edge-TTS → Deepgram → gTTS.
    Returns list of paths in section order.
    """
    if assets_base is None:
        assets_base = Path(__file__).parent.parent / "assets"
    audio_dir = assets_base / slug / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    cfg = _load_tts_config()

    paths = []
    for i, section in enumerate(sections):
        path = audio_dir / f"section_{i:02d}.mp3"
        paths.append(path)

        if path.exists() and path.stat().st_size > 0:
            print(f"[tts] ↩ Skip (exists) section_{i:02d}.mp3")
            continue

        for attempt in range(3):
            try:
                provider = _synthesize_with_fallback(section["narration"], path, cfg)
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                print(f"[tts] ⚠ section_{i:02d} attempt {attempt+1} all providers failed ({exc}) — retry in {wait}s")
                time.sleep(wait)

        print(f"[tts] ✓ section_{i:02d}.mp3 [{provider}] → {path}")
        # Small pause between sections to avoid Edge-TTS rate-limiting
        if i < len(sections) - 1:
            time.sleep(1.5)

    return paths


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True, help="Path to script.json")
    parser.add_argument("--slug", required=True, help="Slug for asset naming")
    parser.add_argument("--voice", default=None, help=f"Edge-TTS voice name. Available: {', '.join(_EDGE_VOICES)}")
    args = parser.parse_args()

    if args.voice:
        os.environ["EDGE_VOICE_OVERRIDE"] = args.voice

    script = json.loads(Path(args.script).read_text())
    generate_voiceovers(script["sections"], args.slug)
