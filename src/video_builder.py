"""
Video assembly using MoviePy + PIL.

For each section:
  1. Resize background image to 1920×1080
  2. Add subtitle bar with narration text (PIL, no ImageMagick dependency)
  3. Attach voiceover audio
  4. Concatenate all sections → final.mp4
"""

import textwrap
from pathlib import Path

import numpy as np
import yaml
from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

# Font search paths (Linux / macOS)
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
]


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _make_subtitle_frame(
    bg_path: Path,
    text: str,
    width: int = 1920,
    height: int = 1080,
    font_size: int = 42,
    bar_height: int = 160,
) -> np.ndarray:
    """Return an RGBA numpy array: background image + subtitle bar."""
    # Load and resize background
    bg = Image.open(bg_path).convert("RGB").resize((width, height), Image.LANCZOS)
    frame = bg.convert("RGBA")

    # Dark gradient bar at bottom
    bar = Image.new("RGBA", (width, bar_height), (0, 0, 0, 0))
    draw_bar = ImageDraw.Draw(bar)
    for y in range(bar_height):
        alpha = int(200 * (y / bar_height))  # fade in from top of bar
        draw_bar.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    frame.paste(bar, (0, height - bar_height), bar)

    # Text
    draw = ImageDraw.Draw(frame)
    font = _find_font(font_size)
    max_chars = (width - 80) // (font_size // 2)  # rough chars per line
    lines = textwrap.wrap(text, width=max_chars)[:3]  # max 3 lines

    line_height = font_size + 8
    total_text_height = len(lines) * line_height
    y = height - bar_height + (bar_height - total_text_height) // 2

    for line in lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
        except AttributeError:
            text_width = draw.textlength(line, font=font)
        x = (width - text_width) // 2
        # Shadow
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height

    return np.array(frame)


def _build_section_clip(
    section: dict,
    image_path: Path,
    audio_path: Path,
    width: int,
    height: int,
) -> CompositeVideoClip:
    audio = AudioFileClip(str(audio_path))
    duration = audio.duration

    frame = _make_subtitle_frame(image_path, section["narration"], width, height)
    clip = ImageClip(frame[:, :, :3], duration=duration)  # RGB for video
    clip = clip.set_audio(audio)
    return clip


def build_video(
    sections: list[dict],
    image_paths: list[Path],
    audio_paths: list[Path],
    slug: str,
    videos_base: Path = None,
) -> Path:
    """
    Assemble section clips into a final MP4.

    Returns path to the output video file.
    """
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

    # Explicit cleanup to prevent resource warnings
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
