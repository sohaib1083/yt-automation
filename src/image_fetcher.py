"""
Image fetching from Pexels API (free tier: 200 req/hour, 20k req/month).
Downloads one landscape image per section into assets/{slug}/images/.
"""

import os
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"
_PEXELS_SEARCH = "https://api.pexels.com/v1/search"
_FALLBACK_COLOR = (30, 30, 40)  # dark blue-grey used if API fails


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)["pexels"]


def _download(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


def _fallback_image(dest: Path, width: int = 1920, height: int = 1080) -> None:
    """Create a plain dark image when Pexels is unavailable."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=_FALLBACK_COLOR)
    img.save(dest, "JPEG")


def fetch_images(sections: list[dict], slug: str, assets_base: Path = None) -> list[Path]:
    """
    Download one background image per section using the section's image_query.

    Returns list of image paths in section order.
    """
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        print("[images] ⚠ PEXELS_API_KEY not set — using fallback images")

    if assets_base is None:
        assets_base = Path(__file__).parent.parent / "assets"
    image_dir = assets_base / slug / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    cfg = _load_config()
    headers = {"Authorization": api_key} if api_key else {}
    paths = []

    for i, section in enumerate(sections):
        dest = image_dir / f"section_{i:02d}.jpg"
        paths.append(dest)

        if dest.exists() and dest.stat().st_size > 0:
            print(f"[images] ↩ Skip (exists) section_{i:02d}.jpg")
            continue

        query = section.get("image_query", section.get("heading", "nature landscape"))

        if not api_key:
            _fallback_image(dest)
            print(f"[images] ✓ Fallback image → {dest}")
            continue

        try:
            resp = requests.get(
                _PEXELS_SEARCH,
                headers=headers,
                params={
                    "query": query,
                    "per_page": cfg["per_page"],
                    "orientation": cfg["orientation"],
                },
                timeout=15,
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])

            if not photos:
                print(f"[images] ⚠ No results for '{query}' — using fallback")
                _fallback_image(dest)
                continue

            # Pick the largest photo that meets minimum width
            min_width = cfg.get("min_width", 1920)
            photo = next(
                (p for p in photos if p["width"] >= min_width),
                photos[0],  # fall back to first if none are wide enough
            )
            url = photo["src"]["original"]
            _download(url, dest)
            print(f"[images] ✓ section_{i:02d}.jpg ← '{query}'")

        except Exception as exc:
            print(f"[images] ✗ Failed section_{i:02d} ({exc}) — using fallback")
            _fallback_image(dest)

    return paths


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True, help="Path to script.json")
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    script = json.loads(Path(args.script).read_text())
    fetch_images(script["sections"], args.slug)
