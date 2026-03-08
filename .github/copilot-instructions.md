# Copilot Instructions

## Project Overview

End-to-end YouTube content automation pipeline in Python. Runs entirely on free tiers.
Pipeline: topic string → Gemini script → edge-tts voiceovers → Pexels images → MoviePy video → YouTube upload.

## Free Services

| Stage | Service | Notes |
|-------|---------|-------|
| Script | Google Gemini 2.0 Flash | `GEMINI_API_KEY` in `.env` |
| TTS | edge-tts (Microsoft Edge) | No API key, no limits |
| Images | Pexels API | `PEXELS_API_KEY` in `.env` |
| Video | MoviePy 1.0.3 (local) | Requires ffmpeg |
| Upload | YouTube Data API v3 | OAuth2; `credentials/client_secrets.json` |

## Architecture

Each stage is independently runnable. Artifacts are files on disk — stages can be skipped/resumed.

```
src/pipeline.py          ← main orchestrator (run this)
src/script_gen.py        ← Gemini 2.0 Flash → scripts/{slug}/script.json
src/tts.py               ← edge-tts async → assets/{slug}/audio/section_NN.mp3
src/image_fetcher.py     ← Pexels API → assets/{slug}/images/section_NN.jpg
src/video_builder.py     ← MoviePy + PIL → videos/{slug}/final.mp4
src/auth.py              ← YouTube OAuth2 token management
src/uploader.py          ← YouTube Data API v3 resumable upload
config/settings.yaml     ← all tunable parameters (resolution, voice, privacy, etc.)
```

## Environment Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # add GEMINI_API_KEY and PEXELS_API_KEY
```

YouTube upload requires `credentials/client_secrets.json` (OAuth Desktop app from Google Cloud Console).

## Commands

```bash
# Full pipeline
python -m src.pipeline --topic "10 Facts About Black Holes"

# Skip upload (generate video only)
python -m src.pipeline --topic "..." --skip-upload

# Resume a failed run (skips stages with existing output)
python -m src.pipeline --topic "..." --resume

# Upload publicly
python -m src.pipeline --topic "..." --privacy public

# Individual stages
python -m src.script_gen --topic "..."
python -m src.tts --script scripts/my-slug/script.json --slug my-slug
python -m src.image_fetcher --script scripts/my-slug/script.json --slug my-slug
python -m src.video_builder --script scripts/my-slug/script.json --slug my-slug
python -m src.uploader --video videos/my-slug/final.mp4 --script scripts/my-slug/script.json
```

## Key Conventions

- **Slug-based artifact layout**: all outputs for a topic go under `{scripts,assets,videos}/{slug}/`. Slug is derived from topic via `_slugify()` in `script_gen.py`.
- **Resume pattern**: every stage checks if its output already exists and skips if `--resume` is passed (or in tts/images, always skips existing files).
- **All secrets via `python-dotenv`**: `load_dotenv()` at module top. Never hardcode keys.
- **YouTube auth**: OAuth2 only (not API key) for upload. Token cached in `credentials/token.pickle`. Auth flow in `src/auth.py`.
- **Text overlay without ImageMagick**: `video_builder.py` uses PIL to draw subtitle bars directly onto numpy arrays — no ImageMagick dependency.
- **MoviePy 1.0.3 pinned**: use `clip.close()` explicitly after `write_videofile()` to avoid resource leaks.
- **edge-tts is async**: `tts.py` wraps everything in `asyncio.run()`. Use `asyncio.gather()` for parallel section synthesis.
- **Gemini response parsing**: strip markdown code fences before `json.loads()` — Gemini often wraps JSON in ` ```json ``` ` blocks. See `_extract_json()` in `script_gen.py`.
- **Config over hardcoding**: resolution, FPS, voice, section count, privacy status all come from `config/settings.yaml`.
