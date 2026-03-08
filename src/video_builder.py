"""
Video assembly using FFmpeg native filters + PIL subtitle rendering.

Why FFmpeg instead of MoviePy callbacks:
  - Native C zoompan filter: 10-100× faster than Python per-frame PIL
  - Real zoom (scale change) not just pan
  - xfade-quality dissolves between sections
  - 6 alternating camera styles per section for visual variety

Pipeline per section:
  1. PIL renders subtitle as transparent RGBA PNG
  2. FFmpeg: scale image → zoompan → overlay subtitle → audio + fades → temp MP4
  3. FFmpeg concat demuxer joins all sections → final.mp4
"""

import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
]

# 6 camera movement styles — rotate through sections for visual variety
# Each tuple: (zoom_expr, x_expr, y_expr)
_CAMERA_STYLES = [
    # 0 — slow zoom-in to centre
    ("min(zoom+0.0006,1.12)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    # 1 — slow zoom-in from top-left
    ("min(zoom+0.0006,1.12)", "0", "0"),
    # 2 — slow zoom-in from bottom-right
    ("min(zoom+0.0006,1.12)", "iw-(iw/zoom)", "ih-(ih/zoom)"),
    # 3 — slow zoom-out from centre
    ("if(lte(zoom,1.0),1.0,max(zoom-0.0005,1.0))", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    # 4 — slow pan left-to-right (steady zoom)
    ("1.06", "iw/2-(iw/zoom/2)+(iw/zoom/2)*in/duration_frames", "ih/2-(ih/zoom/2)"),
    # 5 — slow zoom-in from top-right
    ("min(zoom+0.0006,1.12)", "iw-(iw/zoom)", "0"),
]

_FADE_SEC = 0.4


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _get_ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _get_audio_duration(audio_path: Path) -> float:
    """Get audio duration via FFmpeg -f null probe."""
    ffmpeg = _get_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-i", str(audio_path), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    # FFmpeg prints "Duration: HH:MM:SS.xx" in stderr
    for line in result.stderr.splitlines():
        if "Duration:" in line:
            t = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise ValueError(f"Could not determine duration of {audio_path}")


def _render_subtitle_png(text: str, width: int, height: int, out_path: Path) -> None:
    """
    Render subtitle as a full-canvas RGBA PNG.
    Transparent everywhere except the lower-third subtitle box.
    The box is sized to the actual measured text — never overflows screen.
    """
    font_size = 36
    font = _find_font(font_size)

    # Measure each line individually using actual font metrics
    pad_x, pad_y = 40, 18
    line_h = font_size + 12
    max_box_w = width - 120  # hard limit: 60px margin each side

    # Start with a rough wrap estimate, then tighten if lines are too wide
    def wrap_and_measure(chars_per_line: int):
        wrapped = textwrap.wrap(text, width=chars_per_line)[:3]
        probe = Image.new("RGBA", (1, 1))
        d = ImageDraw.Draw(probe)
        widths = []
        for ln in wrapped:
            try:
                bb = d.textbbox((0, 0), ln, font=font)
                widths.append(bb[2] - bb[0])
            except AttributeError:
                widths.append(int(len(ln) * font_size * 0.58))
        return wrapped, widths

    chars = max(20, (max_box_w - pad_x * 2) // int(font_size * 0.58))
    lines, widths = wrap_and_measure(chars)

    # Shrink chars-per-line until all lines fit in max_box_w
    while any(w > max_box_w - pad_x * 2 for w in widths) and chars > 15:
        chars -= 3
        lines, widths = wrap_and_measure(chars)

    actual_w = max(widths) if widths else 200
    box_w = min(actual_w + pad_x * 2, max_box_w)
    box_h = len(lines) * line_h + pad_y * 2

    # Position: centred horizontally, 72px from bottom — clamped so it never clips
    box_x = (width - box_w) // 2
    box_y = max(height // 2, height - box_h - 72)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # Semi-transparent dark pill box
    box_img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(box_img)
    bd.rounded_rectangle(
        [0, 0, box_w - 1, box_h - 1],
        radius=min(22, box_h // 2),
        fill=(8, 8, 18, 210),
    )
    canvas.paste(box_img, (box_x, box_y), box_img)

    # Draw text — white with drop shadow
    draw = ImageDraw.Draw(canvas)
    ty = box_y + pad_y
    for line, lw in zip(lines, widths):
        tx = (width - lw) // 2
        draw.text((tx + 2, ty + 2), line, font=font, fill=(0, 0, 0, 160))  # shadow
        draw.text((tx, ty), line, font=font, fill=(255, 255, 255, 255))
        ty += line_h

    canvas.save(str(out_path))


def _build_section_video(
    image_path: Path,
    audio_path: Path,
    subtitle_text: str,
    out_path: Path,
    width: int,
    height: int,
    fps: int,
    tmp_dir: Path,
    style_idx: int = 0,
) -> None:
    """Build one section MP4 with FFmpeg zoompan + subtitle overlay + fades."""
    duration = _get_audio_duration(audio_path)
    frames = max(1, int(duration * fps))
    ffmpeg = _get_ffmpeg()

    # Render subtitle PNG
    sub_png = tmp_dir / f"sub_{out_path.stem}.png"
    _render_subtitle_png(subtitle_text, width, height, sub_png)

    zoom_z, zoom_x, zoom_y = _CAMERA_STYLES[style_idx % len(_CAMERA_STYLES)]
    # Replace 'duration_frames' placeholder with actual frame count
    zoom_x = zoom_x.replace("duration_frames", str(frames))
    zoom_y = zoom_y.replace("duration_frames", str(frames))

    # Scale source to 2× so zoompan has room to crop
    scale_filter = f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2}"
    zoompan_filter = f"zoompan=z='{zoom_z}':x='{zoom_x}':y='{zoom_y}':d={frames}:s={width}x{height}:fps={fps}"
    fade_v = f"fade=t=in:st=0:d={_FADE_SEC},fade=t=out:st={max(0, duration - _FADE_SEC)}:d={_FADE_SEC}"
    fade_a = f"afade=t=in:st=0:d={_FADE_SEC},afade=t=out:st={max(0, duration - _FADE_SEC)}:d={_FADE_SEC}"

    filter_complex = (
        f"[0:v]{scale_filter},{zoompan_filter},{fade_v}[bg];"
        f"[2:v]format=rgba[sub];"
        f"[bg][sub]overlay=0:0[v]"
    )

    cmd = [
        ffmpeg, "-y",
        "-loop", "1", "-framerate", str(fps), "-i", str(image_path),   # [0:v] image
        "-i", str(audio_path),                                           # [1:a] audio
        "-i", str(sub_png),                                              # [2:v] subtitle PNG
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "1:a",
        "-af", fade_a,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg section error (section {out_path.stem}):\n{result.stderr[-3000:]}")


def build_video(
    sections: list[dict],
    image_paths: list[Path],
    audio_paths: list[Path],
    slug: str,
    videos_base: Path = None,
) -> Path:
    """Assemble section clips into a final MP4. Returns output path."""
    cfg = _load_config()
    w = cfg["video"]["width"]
    h = cfg["video"]["height"]
    fps = cfg["video"]["fps"]

    if videos_base is None:
        videos_base = Path(__file__).parent.parent / "videos"
    out_dir = videos_base / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "final.mp4"

    if out_path.exists():
        print(f"[video] ↩ Skip (exists) {out_path}")
        return out_path

    ffmpeg = _get_ffmpeg()
    print(f"[video] Building {len(sections)} section clips with FFmpeg …")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        section_paths: list[Path] = []

        for i, (section, img, aud) in enumerate(zip(sections, image_paths, audio_paths)):
            print(f"[video]   {i + 1}/{len(sections)}: {section['heading']}")
            sec_out = tmp_dir / f"section_{i:02d}.mp4"
            _build_section_video(img, aud, section["narration"], sec_out, w, h, fps, tmp_dir, style_idx=i)
            section_paths.append(sec_out)

        # Write concat list
        concat_txt = tmp_dir / "concat.txt"
        concat_txt.write_text("\n".join(f"file '{p}'" for p in section_paths) + "\n")

        print(f"[video] Concatenating → {out_path}")
        concat_cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c", "copy",
            str(out_path),
        ]
        result = subprocess.run(concat_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat error:\n{result.stderr[-2000:]}")

    print(f"[video] ✓ Video ready → {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    import json as _json

    base = Path(__file__).parent.parent
    script = _json.loads((base / "scripts" / args.slug / "script.json").read_text())
    imgs = [base / "assets" / args.slug / "images" / f"section_{i:02d}.jpg" for i in range(len(script["sections"]))]
    auds = [base / "assets" / args.slug / "audio" / f"section_{i:02d}.mp3" for i in range(len(script["sections"]))]
    build_video(script["sections"], imgs, auds, args.slug)
