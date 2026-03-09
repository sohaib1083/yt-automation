"""
Image fetching from Pexels API (free tier: 200 req/hour, 20k req/month).
Downloads 3 background images per section into assets/{slug}/images/.
Falls back to gradient images when Pexels is unavailable.
"""

import os
import time
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"
_PEXELS_SEARCH = "https://api.pexels.com/v1/search"

# Visually distinct gradient palettes for fallback sections (dark-to-color gradients)
_GRADIENT_PALETTES = [
    ((5, 5, 20), (20, 60, 120)),      # deep blue
    ((5, 15, 5), (20, 90, 60)),       # deep green
    ((20, 5, 5), (100, 30, 30)),      # deep red
    ((15, 5, 20), (60, 20, 100)),     # deep purple
    ((20, 15, 5), (100, 70, 20)),     # deep amber
    ((5, 15, 20), (20, 80, 100)),     # deep teal
    ((20, 10, 10), (80, 50, 20)),     # deep orange
    ((10, 5, 20), (40, 20, 90)),      # indigo
    ((5, 20, 15), (20, 100, 70)),     # emerald
    ((20, 5, 15), (90, 20, 70)),      # crimson
]


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)["pexels"]


def _download(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


def _fallback_image(dest: Path, width: int = 1920, height: int = 1080, palette_idx: int = 0) -> None:
    """Create a visually distinctive gradient image when Pexels is unavailable."""
    from PIL import Image, ImageDraw
    import math

    p_idx = palette_idx % len(_GRADIENT_PALETTES)
    top_color, bottom_color = _GRADIENT_PALETTES[p_idx]

    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Diagonal gradient
    for y in range(height):
        t = y / height
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Subtle radial glow at centre
    cx, cy = width // 2, height // 2
    glow_r, glow_g, glow_b = bottom_color
    for radius in range(min(width, height) // 2, 0, -4):
        alpha = 1 - (radius / (min(width, height) // 2))
        cr = int(glow_r * alpha * 0.4)
        cg = int(glow_g * alpha * 0.4)
        cb = int(glow_b * alpha * 0.4)
        x0, y0 = cx - radius, cy - radius
        x1, y1 = cx + radius, cy + radius
        # Use a subtle ellipse
        draw.ellipse([x0, y0, x1, y1], outline=(cr, cg, cb), width=1)

    img.save(dest, "JPEG", quality=85)


def fetch_multi_images(
    sections: list[dict],
    slug: str,
    n_per_section: int = 3,
    orientation: str = "landscape",
    assets_base: Path = None,
) -> list[list[Path]]:
    """
    Download up to n_per_section background images per section.
    Makes ONE Pexels API call per section (not per image) to stay within rate limits.
    Falls back to gradient images if Pexels is unavailable.

    Returns list[list[Path]] — one inner list per section.
    """
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        print("[images] ⚠ PEXELS_API_KEY not set — using gradient fallback images")

    if assets_base is None:
        assets_base = Path(__file__).parent.parent / "assets"
    image_dir = assets_base / slug / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    cfg = _load_config()
    headers = {"Authorization": api_key} if api_key else {}
    results: list[list[Path]] = []

    for i, section in enumerate(sections):
        section_imgs: list[Path] = []

        # Check which images already exist
        missing_indices = [
            j for j in range(n_per_section)
            if not (image_dir / f"section_{i:02d}_img_{j}.jpg").exists()
            or (image_dir / f"section_{i:02d}_img_{j}.jpg").stat().st_size == 0
        ]

        fetched_urls: list[str] = []
        if missing_indices and api_key:
            query = section.get("image_query", section.get("heading", "technology"))
            # ONE API call per section — get n_per_section photos
            for attempt in range(2):
                try:
                    resp = requests.get(
                        _PEXELS_SEARCH,
                        headers=headers,
                        params={"query": query, "per_page": n_per_section, "orientation": orientation},
                        timeout=15,
                    )
                    resp.raise_for_status()
                    min_w = cfg.get("min_width", 1920) if orientation == "landscape" else 1080
                    photos = resp.json().get("photos", [])
                    for p in photos:
                        url = p["src"]["original"] if p.get("width", 0) >= min_w else p["src"]["large"]
                        fetched_urls.append(url)
                    if fetched_urls:
                        print(f"[images] ✓ Fetched {len(fetched_urls)} URLs for section_{i:02d} ← '{query}'")
                    break
                except Exception as exc:
                    if attempt == 0:
                        time.sleep(2)  # brief pause before retry
                    else:
                        print(f"[images] ⚠ Pexels unavailable for section_{i:02d} — using gradient")

        for j in range(n_per_section):
            dest = image_dir / f"section_{i:02d}_img_{j}.jpg"

            if dest.exists() and dest.stat().st_size > 0:
                print(f"[images] ↩ Skip (exists) section_{i:02d}_img_{j}.jpg")
                section_imgs.append(dest)
                continue

            if fetched_urls:
                url = fetched_urls[j % len(fetched_urls)]
                try:
                    _download(url, dest)
                    print(f"[images] ✓ section_{i:02d}_img_{j}.jpg downloaded")
                    section_imgs.append(dest)
                    continue
                except Exception as exc:
                    print(f"[images] ✗ Download error ({exc}) — gradient fallback")

            # Gradient fallback: each image in section gets slightly different palette
            _fallback_image(dest, palette_idx=i * n_per_section + j)
            print(f"[images] ✓ section_{i:02d}_img_{j}.jpg (gradient palette {(i*n_per_section+j) % len(_GRADIENT_PALETTES)})")
            section_imgs.append(dest)

        results.append(section_imgs)

    return results


def fetch_images(sections: list[dict], slug: str, assets_base: Path = None) -> list[Path]:
    """Download one background image per section (backwards-compat wrapper)."""
    multi = fetch_multi_images(sections, slug, n_per_section=1, assets_base=assets_base)
    return [imgs[0] for imgs in multi]


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True, help="Path to script.json")
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    script = json.loads(Path(args.script).read_text())
    fetch_multi_images(script["sections"], args.slug)


    script = json.loads(Path(args.script).read_text())
    fetch_multi_images(script["sections"], args.slug)
