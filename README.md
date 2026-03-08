# YouTube Automation Pipeline

End-to-end pipeline: topic → script → voiceover → images → video → YouTube upload.  
**Runs entirely on free tiers — no paid services required.**

## Free Services Used

| Stage | Service | Free Tier |
|-------|---------|-----------|
| Script generation | [Google Gemini 2.0 Flash](https://aistudio.google.com/) | 1,500 req/day, 1M tokens/day |
| Text-to-speech | [edge-tts](https://github.com/rany2/edge-tts) (Microsoft Edge voices) | Unlimited, no API key |
| Background images | [Pexels API](https://www.pexels.com/api/) | 200 req/hour, 20k/month |
| Video assembly | MoviePy (local) | Free / open source |
| Upload | [YouTube Data API v3](https://console.cloud.google.com/) | 10,000 units/day (~6 uploads) |

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get API keys

**Gemini API key** (script generation):
1. Go to https://aistudio.google.com/apikey
2. Click "Create API Key"

**Pexels API key** (background images):
1. Go to https://www.pexels.com/api/
2. Sign up and copy your key

**YouTube OAuth credentials** (upload):
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → **APIs & Services** → **Enable APIs** → search "YouTube Data API v3" → Enable
3. **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID** → Desktop app
4. Download JSON → save as `credentials/client_secrets.json`

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your Gemini and Pexels keys
```

## Usage

```bash
# Full pipeline (generates video and uploads to YouTube)
python -m src.pipeline --topic "10 Mind-Blowing Facts About Black Holes"

# Generate video only, skip upload
python -m src.pipeline --topic "History of the Internet" --skip-upload

# Upload as public (default in config is private)
python -m src.pipeline --topic "..." --privacy public

# Resume a failed run (skips completed stages)
python -m src.pipeline --topic "..." --resume

# Run individual stages
python -m src.script_gen --topic "..."
python -m src.tts --script scripts/my-topic/script.json --slug my-topic
python -m src.image_fetcher --script scripts/my-topic/script.json --slug my-topic
python -m src.video_builder --script scripts/my-topic/script.json --slug my-topic
python -m src.uploader --video videos/my-topic/final.mp4 --script scripts/my-topic/script.json
```

## Pipeline Flow

```
Topic (string)
    │
    ▼
[script_gen]  → scripts/{slug}/script.json
    │             (title, description, tags, sections[])
    ▼
[tts]         → assets/{slug}/audio/section_NN.mp3
    │             (one MP3 per section via edge-tts)
    ▼
[image_fetcher] → assets/{slug}/images/section_NN.jpg
    │               (Pexels landscape images)
    ▼
[video_builder] → videos/{slug}/final.mp4
    │               (MoviePy: image + audio + subtitle bar)
    ▼
[uploader]    → https://youtube.com/watch?v=...
                  (YouTube Data API v3, resumable upload)
```

## Configuration

Edit `config/settings.yaml` to change:
- Video resolution and FPS
- TTS voice (see [available voices](https://github.com/rany2/edge-tts#usage))
- Number of sections and words per section
- YouTube category and default privacy status

## First-time YouTube auth

The first time you run the pipeline with upload enabled, a browser window will open for Google account consent. After approving, the token is saved to `credentials/token.pickle` and reused automatically.

## Output

| Path | Description |
|------|-------------|
| `scripts/{slug}/script.json` | Generated script with title, description, tags, sections |
| `assets/{slug}/audio/` | MP3 voiceovers per section |
| `assets/{slug}/images/` | Background images per section |
| `videos/{slug}/final.mp4` | Assembled video (ready for upload) |
