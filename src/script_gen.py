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
You are the head scriptwriter for "AI Frontiers" — a fast-growing YouTube channel covering
the latest developments in Artificial Intelligence. Target audience: curious, tech-savvy
people aged 18-40 who want to understand AI without a CS degree.

CHANNEL STYLE:
  • Hook-first: the FIRST sentence must grab the viewer in ≤10 seconds — use a shocking stat,
    bold claim, urgent question, or "you won't believe this" framing
  • 3-act narrative arc per video:
      Act 1 (sections 1-2): Set the scene, drop the hook, give stakes — WHY does this matter?
      Act 2 (sections 3-4): The substance — what happened, how it works, real examples
      Act 3 (sections 5-6): Implications + future + emotional payoff + CTA
  • Emotional language: use words like "terrifying", "incredible", "quietly", "nobody noticed"
  • Personal stakes: always answer "what does this mean for ME, the viewer?"
  • Fast-paced: every sentence earns its place — no filler, no "In this video we'll explore..."
  • Each section ends with a micro-hook that pulls viewers into the next section

The goal is MAXIMUM retention, watch-time, and shares to drive monetization.
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
  "title": "Viral YouTube title ≤80 chars — curiosity gap, urgency, or bold claim (e.g. 'This AI Just Made Doctors Obsolete', '5 AI Breakthroughs Nobody Is Talking About')",
  "description": "2-3 punchy sentences (150-250 chars) teasing the key revelation, ending with 6-8 trending hashtags: #AI #ArtificialIntelligence #AINews #Tech #MachineLearning + 2-3 topic-specific ones",
  "tags": ["AI", "Artificial Intelligence", "AI News", "Machine Learning", "Deep Learning", "OpenAI", "Google AI", ...6-9 more specific to this topic],
  "sections": [
    {{
      "heading": "Short chapter label (internal use)",
      "narration": "~{words} words of punchy spoken script. Section 1 MUST open with a power hook. Each section ends pulling viewer to the next. No bullet points — flowing, conversational prose only.",
      "image_query": "Cinematic Pexels search: specific, visual, photogenic (e.g. 'humanoid robot in glowing laboratory blue light', NOT 'concept of AI')"
    }}
  ]
}}

Structural requirements:
- Exactly {num_sections} sections following the 3-act arc
- Section 1: Power hook + stakes (WHY should I watch?)
- Sections 2-3: The story — what happened, evidence, real-world examples
- Section 4: The twist or surprising implication
- Section 5: What this means for the viewer personally
- Section 6: Emotional payoff + natural CTA (woven into narrative, not tacked on)
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
