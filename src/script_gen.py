"""
Script generation using Google Gemini 2.5 Flash (free tier).
Optimised for the "AI Frontiers" YouTube channel — viral AI news/explainers.
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

# System-level persona baked into every generation
_CHANNEL_PERSONA = """
You are the scriptwriter for "AI Frontiers" — a fast-growing YouTube channel covering
the latest developments in Artificial Intelligence. The audience is curious, tech-savvy
but not necessarily engineers (age 18-40). The channel's style is:
  • Hook-first: open with a shocking fact, question, or bold claim in the first 10 seconds
  • Conversational but authoritative — like a knowledgeable friend explaining the news
  • Fast-paced: no filler, every sentence earns its place
  • Unique angles: go beyond surface-level coverage — give context, implications, what it means for everyday people
  • Call-to-action aware: viewers should feel compelled to share/comment
The goal is MAXIMUM retention and watch-time to grow the channel toward monetization.
""".strip()


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


def generate_script(topic: str, output_base: Path = None) -> tuple:
    """
    Generate a YouTube video script for *topic* using Gemini Flash.
    Returns (script_dict, slug) and saves to scripts/{slug}/script.json.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set in .env")

    cfg = _load_config()
    num_sections = cfg["script"]["sections"]
    words = cfg["script"]["words_per_section"]

    client = genai.Client(api_key=api_key)

    prompt = f"""{_CHANNEL_PERSONA}

Create a complete "AI Frontiers" video script about:

TOPIC: {topic}

Return ONLY a valid JSON object (no markdown, no extra text) with this exact structure:
{{
  "title": "Viral YouTube title under 80 chars — curiosity gap, numbers, or shock value work best",
  "description": "2-3 sentence YouTube description (150-300 chars) that teases the content + ends with 5-8 trending hashtags like #AI #ArtificialIntelligence #Tech",
  "tags": ["AI", "Artificial Intelligence", "Machine Learning", ...12-15 specific tags relevant to the topic],
  "sections": [
    {{
      "heading": "Section heading (internal label)",
      "narration": "Spoken script ~{words} words. Open section 1 with a STRONG hook — a surprising stat, bold statement, or open question. Keep all sections fast-paced and conversational.",
      "image_query": "Specific Pexels search query for a cinematic background visual (e.g. 'futuristic robot laboratory glowing blue', NOT abstract concepts)"
    }}
  ]
}}

Requirements:
- Exactly {num_sections} sections
- Section 1 narration MUST open with a powerful hook (e.g. "What if I told you...", "In the last 48 hours...", a shocking number)
- Last section ends with a call-to-action (like/subscribe/comment prompt woven naturally into the script)
- Image queries must be concrete, cinematic, and photogenic
- Titles should be curiosity-gap or list-style (e.g. "This AI Just Changed Everything", "5 AI Breakthroughs Nobody Is Talking About")
- Do NOT wrap in markdown code blocks"""

    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    script = _extract_json(response.text)

    if output_base is None:
        output_base = Path(__file__).parent.parent / "scripts"
    slug = _slugify(topic)
    out_dir = output_base / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    script["_topic"] = topic  # store for --resume detection

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
