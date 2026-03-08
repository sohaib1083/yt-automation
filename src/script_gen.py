"""
Script generation using Google Gemini 2.0 Flash (free tier).
Produces a structured JSON script saved to scripts/{slug}/script.json.
"""

import json
import os
import re
import unicodedata
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google import genai

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:60]


def _extract_json(raw: str) -> dict:
    """Strip markdown code fences then parse JSON."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"```$", "", cleaned.strip())
    return json.loads(cleaned)


def generate_script(topic: str, output_base: Path = None) -> dict:
    """
    Generate a YouTube video script for *topic* using Gemini Flash.

    Returns the parsed script dict and saves it to
    scripts/{slug}/script.json.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set in .env")

    cfg = _load_config()
    num_sections = cfg["script"]["sections"]
    words = cfg["script"]["words_per_section"]

    client = genai.Client(api_key=api_key)

    prompt = f"""You are a YouTube scriptwriter. Create a complete video script about:

TOPIC: {topic}

Return ONLY a valid JSON object (no markdown, no extra text) with this exact structure:
{{
  "title": "Catchy YouTube title under 90 characters",
  "description": "YouTube description 200-400 characters with relevant hashtags at the end",
  "tags": ["tag1", "tag2", ...],
  "sections": [
    {{
      "heading": "Section heading",
      "narration": "Spoken text for this section (~{words} words, engaging tone)",
      "image_query": "Specific Pexels image search query for relevant background visual"
    }}
  ]
}}

Requirements:
- Exactly {num_sections} sections
- Tags: 12-15 relevant tags
- Each narration ~{words} words (about 30 seconds when spoken)
- Image queries must be concrete and visual (e.g. "mountain sunrise landscape" not "concept of growth")
- Do NOT wrap in markdown code blocks"""

    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    script = _extract_json(response.text)

    # Persist to disk
    if output_base is None:
        output_base = Path(__file__).parent.parent / "scripts"
    slug = _slugify(topic)
    out_dir = output_base / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    script_path = out_dir / "script.json"
    with open(script_path, "w") as f:
        json.dump(script, f, indent=2)

    print(f"[script_gen] ✓ Script saved → {script_path}")
    print(f"[script_gen]   Title: {script['title']}")
    print(f"[script_gen]   Sections: {len(script['sections'])}")
    return script, slug


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True, help="Video topic")
    args = parser.parse_args()
    generate_script(args.topic)
