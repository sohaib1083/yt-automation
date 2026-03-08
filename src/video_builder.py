"""
Video assembly using MoviePy + PIL.

Improvements over v1:
  - 16:9 1920×1080 @ 30fps (YouTube standard)
  - Ken Burns slow-zoom effect on each image
  - Fade-in / fade-out transitions between sections
  - Redesigned subtitle: centered pill-shaped box with clean white text
  - Higher bitrate (6000k) for crisp 1080p output
"""

import textwrap
from pathlib import Path

import numpy as np
import yaml
from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
]

_FADE_DURATION = 0.5  # seconds for fade in/out


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _ken_burns_clip(image_path: Path, duration: float, width: int, height: int) -> VideoClip:
    """
    Ken Burns pan effect using pure numpy slicing (no per-frame PIL resize → fast).
    Loads image at 108% size, then pans the crop window from edge to center.
    This creates a subtle camera-movement illusion.
    """
    oversized_w = int(width * 1.08)
    oversized_h = int(height * 1.08)
    big = np.array(
        Image.open(image_path).convert("RGB").resize((oversized_w, oversized_h), Image.LANCZOS)
    )
    max_x = oversized_w - width
    max_y = oversized_h - height

    def make_frame(t: float) -> np.ndarray:
        p = min(t / max(duration, 0.001), 1.0)
        # Pan from (0,0) toward center as time progresses (slow zoom-in feel)
        x0 = int(max_x * p / 2)
        y0 = int(max_y * p / 2)
        return big[y0 : y0 + height, x0 : x0 + width]

    return VideoClip(make_frame, duration=duration)


def _build_section_clip(
    section: dict,
    image_path: Path,
    audio_path: Path,
    width: int,
    height: int,
) -> CompositeVideoClip:
    audio = AudioFileClip(str(audio_path))
    duration = audio.duration

    # Ken Burns background (fast numpy pan, no per-frame PIL)
    bg_clip = _ken_burns_clip(image_path, duration, width, height)

    # Subtitle overlay: RGBA image with transparent background, only the box+text drawn
    sub_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sub_overlay)
    font_size = 46
    font = _find_font(font_size)
    max_chars = max(20, (width - 120) // (font_size // 2))
    lines = textwrap.wrap(section["narration"], width=max_chars)[:3]
    line_height = font_size + 10
    total_h = len(lines) * line_height
    padding_y = 20
    box_w = width - 160
    box_h = total_h + padding_y * 2
    box_x = (width - box_w) // 2
    box_y = height - box_h - 60

    box = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    box_draw = ImageDraw.Draw(box)
    box_draw.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=min(30, box_h // 2), fill=(0, 0, 0, 175))
    sub_overlay.paste(box, (box_x, box_y), box)

    text_y = box_y + padding_y
    for line in lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
        except AttributeError:
            text_w = draw.textlength(line, font=font)
        text_x = (width - text_w) // 2
        draw.text((text_x + 2, text_y + 2), line, font=font, fill=(0, 0, 0, 180))
        draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
        text_y += line_height

    sub_clip = ImageClip(np.array(sub_overlay), duration=duration, ismask=False)

    composite = CompositeVideoClip([bg_clip, sub_clip], size=(width, height))
    composite = composite.set_audio(audio)
    composite = composite.fadein(_FADE_DURATION).fadeout(_FADE_DURATION)
    return composite


def build_video(
    sections: list[dict],
    image_paths: list[Path],
    audio_paths: list[Path],
    slug: str,
    videos_base: Path = None,
) -> Path:
    """Assemble section clips into a final MP4. Returns path to output file."""
    cfg = _load_config()
    w = cfg["video"]["width"]
    h = cfg["video"]["height"]
    fps = cfg["video"]["fps"]
    codec = cfg["video"]["codec"]
    bitrate = cfg["video"]["bitrate"]

    if videos_base is None:
        videos_base = Path(__file__).parent.parent / "videos"
    out_dir = videos_base / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "final.mp4"

    if out_path.exists():
        print(f"[video] ↩ Skip (exists) {out_path}")
        return out_path

    print(f"[video] Building {len(sections)} section clips …")
    clips = []
    for i, (section, img, aud) in enumerate(zip(sections, image_paths, audio_paths)):
        print(f"[video]   section {i + 1}/{len(sections)}: {section['heading']}")
        clip = _build_section_clip(section, img, aud, w, h)
        clips.append(clip)

    final = concatenate_videoclips(clips, method="compose")

    print(f"[video] Writing → {out_path}")
    final.write_videofile(
        str(out_path),
        fps=fps,
        codec=codec,
        bitrate=bitrate,
        audio_codec="aac",
        temp_audiofile=str(out_dir / "temp_audio.m4a"),
        remove_temp=True,
        logger="bar",
    )

    final.close()
    for c in clips:
        c.close()

    print(f"[video] ✓ Video ready → {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    base = Path(__file__).parent.parent
    script = json.loads((base / "scripts" / args.slug / "script.json").read_text())
    imgs = [base / "assets" / args.slug / "images" / f"section_{i:02d}.jpg" for i in range(len(script["sections"]))]
    auds = [base / "assets" / args.slug / "audio" / f"section_{i:02d}.mp3" for i in range(len(script["sections"]))]
    build_video(script["sections"], imgs, auds, args.slug)
