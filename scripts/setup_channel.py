#!/usr/bin/env python3
"""
AI Frontiers — Complete YouTube channel setup.

Configures:
  1. Channel description, keywords, country, default language
  2. Channel banner (2560×1440 — generated with Pillow)
  3. Watermark (subscribe button overlay on all videos)
  4. Default upload category + tags
"""

import io
import math
import sys
from pathlib import Path

# ─── Channel identity ─────────────────────────────────────────────────────────

CHANNEL_DESCRIPTION = """\
🤖 AI Frontiers — Where Tomorrow's AI Happens Today

We cover the most important breakthroughs in Artificial Intelligence, \
delivered clearly, fast, and ahead of everyone else.

From invisible CEO agents running global supply chains, to AI deciding your \
mortgage, to autonomous robots changing how we work — we break it all down so \
YOU understand what's really happening in 2026 and beyond.

📌 New videos every week
🔔 Subscribe + hit the bell so you never miss a drop

Topics we cover:
• Agentic AI & autonomous systems
• AI in finance, healthcare & supply chains
• Future of work & career in the age of AI
• Robotics & physical AI
• AI governance, ethics & regulation
• The latest model releases & what they mean

Business enquiries: sohaib1083@gmail.com
"""

CHANNEL_KEYWORDS = [
    "AI", "artificial intelligence", "AI agents", "agentic AI", "2026",
    "future of work", "machine learning", "AI news", "AI trends",
    "autonomous AI", "AI technology", "tech news", "AI Frontiers",
    "generative AI", "large language models", "robotics",
]

CHANNEL_COUNTRY = "US"
DEFAULT_CATEGORY_ID = "28"   # Science & Technology
DEFAULT_TAGS = ["AI", "artificial intelligence", "AI agents", "2026", "tech news", "AI Frontiers"]

# ─── Banner generation ────────────────────────────────────────────────────────

BANNER_W, BANNER_H = 2560, 1440          # YouTube recommended
SAFE_W, SAFE_H = 1546, 423              # visible on ALL devices (TV/desktop/mobile)
SAFE_X = (BANNER_W - SAFE_W) // 2       # 507
SAFE_Y = (BANNER_H - SAFE_H) // 2       # 508


def _make_banner() -> bytes:
    """Generate a professional 2560×1440 channel banner as PNG bytes."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    img = Image.new("RGB", (BANNER_W, BANNER_H), "#000000")
    draw = ImageDraw.Draw(img)

    # ── Deep gradient background ──────────────────────────────────────────────
    for y in range(BANNER_H):
        t = y / BANNER_H
        r = int(0x0a + t * (0x00 - 0x0a))
        g = int(0x0e + t * (0x04 - 0x0e))
        b = int(0x1a + t * (0x1a - 0x1a))
        draw.line([(0, y), (BANNER_W, y)], fill=(r, g, b))

    # ── Subtle hexagonal grid pattern (background texture) ───────────────────
    hex_size = 60
    hex_color = (255, 255, 255, 8)
    grid_img = Image.new("RGBA", (BANNER_W, BANNER_H), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid_img)
    for col in range(-1, BANNER_W // (hex_size * 2) + 2):
        for row in range(-1, BANNER_H // (hex_size * 2) + 2):
            cx = col * hex_size * 1.75
            cy = row * hex_size * 2 + (hex_size if col % 2 else 0)
            pts = [
                (cx + hex_size * math.cos(math.radians(60 * i + 30)),
                 cy + hex_size * math.sin(math.radians(60 * i + 30)))
                for i in range(6)
            ]
            grid_draw.polygon(pts, outline=hex_color, fill=None)
    # Blend
    base_rgba = img.convert("RGBA")
    base_rgba = Image.alpha_composite(base_rgba, grid_img)
    img = base_rgba.convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Glowing accent lines ───────────────────────────────────────────────────
    # Horizontal cyan lines flanking the safe zone
    accent_y_top = SAFE_Y - 10
    accent_y_bot = SAFE_Y + SAFE_H + 10
    for thickness, alpha in [(8, 60), (3, 180), (1, 255)]:
        c = int(alpha)
        draw.line([(SAFE_X, accent_y_top), (SAFE_X + SAFE_W, accent_y_top)],
                  fill=(0, c, min(255, c + 55)), width=thickness)
        draw.line([(SAFE_X, accent_y_bot), (SAFE_X + SAFE_W, accent_y_bot)],
                  fill=(0, c, min(255, c + 55)), width=thickness)

    # ── Node + line decoration on left ────────────────────────────────────────
    node_cx, node_cy = SAFE_X - 60, BANNER_H // 2
    for i, angle_deg in enumerate(range(0, 360, 45)):
        rad = math.radians(angle_deg)
        line_len = 80 if i % 2 == 0 else 50
        ex = int(node_cx + math.cos(rad) * line_len)
        ey = int(node_cy + math.sin(rad) * line_len)
        draw.line([(node_cx, node_cy), (ex, ey)], fill=(0, 180, 255), width=2)
        draw.ellipse([(ex - 5, ey - 5), (ex + 5, ey + 5)], fill=(0, 220, 255))
    draw.ellipse([(node_cx - 12, node_cy - 12), (node_cx + 12, node_cy + 12)],
                 fill=(0, 212, 255))

    # Mirror node on right side
    node_rx = SAFE_X + SAFE_W + 60
    for i, angle_deg in enumerate(range(0, 360, 45)):
        rad = math.radians(angle_deg)
        line_len = 60 if i % 2 == 0 else 40
        ex = int(node_rx + math.cos(rad) * line_len)
        ey = int(node_cy + math.sin(rad) * line_len)
        draw.line([(node_rx, node_cy), (ex, ey)], fill=(124, 58, 237), width=2)
        draw.ellipse([(ex - 4, ey - 4), (ex + 4, ey + 4)], fill=(167, 100, 255))
    draw.ellipse([(node_rx - 10, node_cy - 10), (node_rx + 10, node_cy + 10)],
                 fill=(139, 92, 246))

    # ── Channel name: "AI FRONTIERS" ──────────────────────────────────────────
    center_x = BANNER_W // 2
    center_y = BANNER_H // 2

    # Try to load a bold system font, fall back to default
    font_title = None
    font_tag = None
    font_sub = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if Path(font_path).exists():
            font_title = ImageFont.truetype(font_path, size=130)
            font_tag = ImageFont.truetype(font_path, size=46)
            font_sub = ImageFont.truetype(font_path, size=36)
            break

    if font_title is None:
        font_title = ImageFont.load_default()
        font_tag = font_title
        font_sub = font_title

    title_text = "AI FRONTIERS"
    tag_text = "WHERE TOMORROW'S AI HAPPENS TODAY"
    sub_text = "NEW VIDEOS EVERY WEEK  •  SUBSCRIBE NOW"

    # Shadow
    shadow_offset = 4
    draw.text((center_x + shadow_offset, center_y - 60 + shadow_offset),
              title_text, font=font_title, fill=(0, 0, 0, 180), anchor="mm")
    # Gradient-like title: two-tone rendering (draw twice, offset)
    draw.text((center_x, center_y - 60), title_text,
              font=font_title, fill=(255, 255, 255), anchor="mm")
    # Cyan highlight on first 2 chars
    draw.text((center_x, center_y - 60), title_text[:2],
              font=font_title, fill=(0, 212, 255), anchor="mm")

    # Tagline
    draw.text((center_x, center_y + 50), tag_text,
              font=font_tag, fill=(180, 180, 200), anchor="mm")

    # Subtle bottom subscribe line
    draw.text((center_x, center_y + 110), sub_text,
              font=font_sub, fill=(100, 100, 120), anchor="mm")

    # ── Subtle vignette ────────────────────────────────────────────────────────
    vignette = Image.new("RGBA", (BANNER_W, BANNER_H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for radius_frac in range(30, 0, -1):
        a = int((1 - radius_frac / 30) ** 2 * 140)
        rx = int(BANNER_W * (1 - radius_frac / 30) / 2)
        ry = int(BANNER_H * (1 - radius_frac / 30) / 2)
        vd.ellipse([(BANNER_W // 2 - rx, BANNER_H // 2 - ry),
                    (BANNER_W // 2 + rx, BANNER_H // 2 + ry)],
                   fill=(0, 0, 0, 0))
    img_rgba = img.convert("RGBA")
    img = Image.alpha_composite(img_rgba, vignette).convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _make_watermark() -> bytes:
    """A 150×150 'SUBSCRIBE' button PNG (YouTube requires ≥100×100)."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = 150, 150
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Dark semi-transparent circle background
    draw.ellipse([(2, 2), (w - 3, h - 3)], fill=(10, 14, 26, 210), outline=(0, 212, 255, 200), width=3)
    # Bell icon area (top half)
    draw.ellipse([(45, 25), (105, 80)], fill=(0, 212, 255, 240))
    # SUBSCRIBE text
    font = None
    for fp in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if Path(fp).exists():
            font = ImageFont.truetype(fp, size=16)
            break
    if font is None:
        font = ImageFont.load_default()
    draw.text((w // 2, 105), "SUBSCRIBE", font=font, fill=(255, 255, 255, 255), anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─── API helpers ──────────────────────────────────────────────────────────────

def get_channel_id(yt) -> str:
    resp = yt.channels().list(part="id", mine=True).execute()
    return resp["items"][0]["id"]


def update_channel_metadata(yt, channel_id: str, banner_url: str = ""):
    print("[setup] Updating channel description, keywords + banner …")
    body = {
        "id": channel_id,
        "brandingSettings": {
            "channel": {
                "name": "AI Frontiers",
                "description": CHANNEL_DESCRIPTION,
                "keywords": " ".join(f'"{k}"' for k in CHANNEL_KEYWORDS),
                "country": CHANNEL_COUNTRY,
                "defaultLanguage": "en",
                "defaultTab": "Featured",
                "showBrowseView": True,
                "showRelatedChannels": True,
            },
            "watch": {
                "textColor": "#FFFFFF",
                "backgroundColor": "#0a0e1a",
            },
        },
    }
    if banner_url:
        body["brandingSettings"]["image"] = {"bannerExternalUrl": banner_url}
    yt.channels().update(part="brandingSettings", body=body).execute()
    print("[setup] ✓ Description, keywords" + (" + banner" if banner_url else "") + " updated")


def upload_banner(yt, channel_id: str, png_bytes: bytes) -> str:
    print("[setup] Uploading channel banner (2560×1440) …")
    import googleapiclient.http as ghttp

    media = ghttp.MediaIoBaseUpload(
        io.BytesIO(png_bytes), mimetype="image/png", resumable=True
    )
    resp = yt.channelBanners().insert(body={}, media_body=media).execute()
    banner_url = resp.get("url", "")
    print(f"[setup] ✓ Banner uploaded → {banner_url[:80]}…")
    return banner_url


def upload_watermark(yt, channel_id: str, png_bytes: bytes):
    print("[setup] Setting subscribe watermark …")
    import googleapiclient.http as ghttp
    media = ghttp.MediaIoBaseUpload(
        io.BytesIO(png_bytes), mimetype="image/png", resumable=False
    )
    # offsetMs from end = when watermark appears; durationMs = how long it stays
    yt.watermarks().set(
        channelId=channel_id,
        body={
            "position": {"cornerPosition": "bottomRight", "type": "corner"},
            "timing": {
                "type": "offsetFromEnd",
                "durationMs": "15000",
                "offsetMs": "15000",
            },
        },
        media_body=media,
    ).execute()
    print("[setup] ✓ Subscribe watermark set (appears last 15s of every video)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  AI Frontiers — YouTube Channel Setup")
    print("=" * 65)

    # Import after sys.path is set properly
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.auth import get_youtube_client

    yt = get_youtube_client()
    channel_id = get_channel_id(yt)
    print(f"[setup] Channel ID: {channel_id}\n")

    # 1 + 2. Generate banner, upload it, then apply with description in one call
    banner_out = Path(__file__).parent.parent / "assets" / "channel_banner.png"
    banner_out.parent.mkdir(parents=True, exist_ok=True)
    print("[setup] Generating channel banner …")
    banner_bytes = _make_banner()
    banner_out.write_bytes(banner_bytes)
    print(f"[setup]   Saved locally → {banner_out} ({len(banner_bytes) // 1024} KB)")

    banner_url = ""
    try:
        banner_url = upload_banner(yt, channel_id, banner_bytes)
    except Exception as exc:
        print(f"[setup] ⚠ Banner upload failed: {exc}")
        print(f"[setup]   Manually upload {banner_out} at YouTube Studio → Customization → Branding")

    # Metadata + banner applied together
    update_channel_metadata(yt, channel_id, banner_url)

    # 3. Watermark
    wm_bytes = _make_watermark()
    try:
        upload_watermark(yt, channel_id, wm_bytes)
    except Exception as exc:
        print(f"[setup] ⚠ Watermark failed: {exc}")

    print("\n" + "=" * 65)
    print("  Channel setup complete!")
    print("=" * 65)
    print("""
Remaining manual steps in YouTube Studio (studio.youtube.com):
  • Profile picture  →  Customization → Branding → Profile picture
  • Channel trailer  →  Customization → Layout → Add channel trailer
  • Sections         →  Customization → Layout → Add section
  • Sort videos      →  Content → Videos → sort by Date
""")


if __name__ == "__main__":
    main()
