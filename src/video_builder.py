"""
Video assembly using FFmpeg native filters + PIL subtitle/title rendering.

Improvements over v1:
  - Multiple images per section with smooth xfade crossfades (eliminates stationary look)
  - Animated section title cards (1.5 s overlay at section start)
  - Background music mixed at 10% volume (SoundHelix CC0)
  - Shorts format support (1080×1920 portrait)

Pipeline per section:
  1. PIL renders subtitle PNG + title-card PNG
  2. FFmpeg: scale images → zoompan → xfade between images → overlay title + subtitle → audio fades → temp MP4
  3. FFmpeg concat demuxer joins all sections → temp final
  4. FFmpeg mixes in background music → final.mp4
"""

import json
import random
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
_CAMERA_STYLES = [
    ("min(zoom+0.0006,1.12)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("min(zoom+0.0006,1.12)", "0", "0"),
    ("min(zoom+0.0006,1.12)", "iw-(iw/zoom)", "ih-(ih/zoom)"),
    ("if(lte(zoom,1.0),1.0,max(zoom-0.0005,1.0))", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("1.06", "iw/2-(iw/zoom/2)+(iw/zoom/2)*in/duration_frames", "ih/2-(ih/zoom/2)"),
    ("min(zoom+0.0006,1.12)", "iw-(iw/zoom)", "0"),
]

_FADE_SEC = 0.4
_XFADE_DUR = 0.7   # crossfade between images within a section
_TITLE_DUR = 1.8   # seconds the section title card is visible
_MUSIC_VOL = 0.10  # background music volume (10%)
_SOUNDHELIX_COUNT = 17


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
    for line in result.stderr.splitlines():
        if "Duration:" in line:
            t = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise ValueError(f"Could not determine duration of {audio_path}")


def _render_subtitle_png(text: str, width: int, height: int, out_path: Path) -> None:
    """
    Render subtitle as full-canvas RGBA PNG.
    Pill-shaped box at lower-third — never overflows screen.
    """
    font_size = max(28, width // 50)
    font = _find_font(font_size)

    pad_x, pad_y = 40, 18
    line_h = font_size + 12
    max_box_w = width - 120

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

    while any(w > max_box_w - pad_x * 2 for w in widths) and chars > 15:
        chars -= 3
        lines, widths = wrap_and_measure(chars)

    actual_w = max(widths) if widths else 200
    box_w = min(actual_w + pad_x * 2, max_box_w)
    box_h = len(lines) * line_h + pad_y * 2

    box_x = (width - box_w) // 2
    box_y = max(height // 2, height - box_h - 72)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    box_img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(box_img)
    bd.rounded_rectangle(
        [0, 0, box_w - 1, box_h - 1],
        radius=min(22, box_h // 2),
        fill=(8, 8, 18, 210),
    )
    canvas.paste(box_img, (box_x, box_y), box_img)

    draw = ImageDraw.Draw(canvas)
    ty = box_y + pad_y
    for line, lw in zip(lines, widths):
        tx = (width - lw) // 2
        draw.text((tx + 2, ty + 2), line, font=font, fill=(0, 0, 0, 160))
        draw.text((tx, ty), line, font=font, fill=(255, 255, 255, 255))
        ty += line_h

    canvas.save(str(out_path))


def _render_title_card_png(heading: str, width: int, height: int, out_path: Path) -> None:
    """
    Render section title card as full-canvas RGBA PNG.
    Centred text on a dark gradient bar — shown for first ~1.5s of each section.
    """
    title_font_size = max(36, width // 28)
    font = _find_font(title_font_size)

    probe = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(probe)
    try:
        bb = d.textbbox((0, 0), heading, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
    except AttributeError:
        tw = int(len(heading) * title_font_size * 0.58)
        th = title_font_size

    pad_x, pad_y = 60, 30
    bar_w = min(tw + pad_x * 2, width - 80)
    bar_h = th + pad_y * 2
    bar_x = (width - bar_w) // 2
    bar_y = height // 2 - bar_h // 2  # vertically centred

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    bar = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    bd.rounded_rectangle([0, 0, bar_w - 1, bar_h - 1], radius=18, fill=(10, 10, 30, 220))

    # accent line at top of bar
    accent_h = 5
    bd.rounded_rectangle([0, 0, bar_w - 1, accent_h], radius=4, fill=(80, 160, 255, 255))

    canvas.paste(bar, (bar_x, bar_y), bar)

    draw = ImageDraw.Draw(canvas)
    tx = bar_x + (bar_w - tw) // 2
    ty = bar_y + pad_y
    draw.text((tx + 2, ty + 2), heading, font=font, fill=(0, 0, 0, 140))
    draw.text((tx, ty), heading, font=font, fill=(255, 255, 255, 255))

    canvas.save(str(out_path))


def _build_section_video(
    image_paths: "list[Path] | Path",
    audio_path: Path,
    subtitle_text: str,
    heading: str,
    out_path: Path,
    width: int,
    height: int,
    fps: int,
    tmp_dir: Path,
    style_idx: int = 0,
) -> None:
    """
    Build one section MP4.

    Accepts one or multiple images:
    - 1 image  → zoompan + subtitle + title card
    - N images → zoompan each → xfade chain → subtitle + title card
    """
    # Normalise to list
    if isinstance(image_paths, Path):
        image_paths = [image_paths]

    duration = _get_audio_duration(audio_path)
    ffmpeg = _get_ffmpeg()

    # Render overlays
    sub_png = tmp_dir / f"sub_{out_path.stem}.png"
    title_png = tmp_dir / f"title_{out_path.stem}.png"
    _render_subtitle_png(subtitle_text, width, height, sub_png)
    _render_title_card_png(heading, width, height, title_png)

    N = len(image_paths)
    xfade_dur = _XFADE_DUR
    # Each image clip duration so total = audio duration after xfade overlap
    img_dur = (duration + (N - 1) * xfade_dur) / N if N > 1 else duration

    # Build FFmpeg inputs: images first, then audio, then PNGs
    inputs: list[str] = []
    for img in image_paths:
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(img)]
    audio_idx = N
    inputs += ["-i", str(audio_path)]
    sub_idx = N + 1
    inputs += ["-i", str(sub_png)]
    title_idx = N + 2
    inputs += ["-i", str(title_png)]

    filter_parts: list[str] = []

    # Per-image: scale to 2× then zoompan
    for j, _ in enumerate(image_paths):
        z, x, y = _CAMERA_STYLES[(style_idx + j) % len(_CAMERA_STYLES)]
        frames = max(1, int(img_dur * fps))
        x = x.replace("duration_frames", str(frames))
        y = y.replace("duration_frames", str(frames))
        scale_f = f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2}"
        zp_f = f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps}"
        filter_parts.append(f"[{j}:v]{scale_f},{zp_f}[v{j}]")

    # Chain xfade between zoompan outputs
    if N == 1:
        current = "v0"
    else:
        for j in range(N - 1):
            prev = "v0" if j == 0 else f"xf{j - 1}"
            nxt = f"v{j + 1}"
            out_label = f"xf{j}" if j < N - 2 else "bg_raw"
            offset = (j + 1) * (img_dur - xfade_dur)
            filter_parts.append(
                f"[{prev}][{nxt}]xfade=transition=fade:duration={xfade_dur:.3f}:offset={offset:.3f}[{out_label}]"
            )
        current = "bg_raw"

    # Video fades on background
    fade_out_st = max(0.0, duration - _FADE_SEC)
    filter_parts.append(
        f"[{current}]fade=t=in:st=0:d={_FADE_SEC},"
        f"fade=t=out:st={fade_out_st:.3f}:d={_FADE_SEC}[bg]"
    )

    # Overlay subtitle (constant) + title card (first _TITLE_DUR seconds)
    filter_parts.append(f"[{sub_idx}:v]format=rgba[sub]")
    filter_parts.append(f"[{title_idx}:v]format=rgba[title]")
    filter_parts.append(f"[bg][sub]overlay=0:0[bg_sub]")
    filter_parts.append(
        f"[bg_sub][title]overlay=0:0:enable='between(t,0,{_TITLE_DUR:.1f})'[v]"
    )

    filter_complex = ";".join(filter_parts)

    fade_a = f"afade=t=in:st=0:d={_FADE_SEC},afade=t=out:st={fade_out_st:.3f}:d={_FADE_SEC}"

    cmd = [
        ffmpeg, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", f"{audio_idx}:a",
        "-af", fade_a,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg section error ({out_path.stem}):\n{result.stderr[-3000:]}")


def _fetch_background_music(cache_dir: Path) -> "Path | None":
    """Download a random SoundHelix CC0 track (cached). Returns None on failure."""
    import requests

    cache_dir.mkdir(parents=True, exist_ok=True)
    n = random.randint(1, _SOUNDHELIX_COUNT)
    dest = cache_dir / f"SoundHelix-Song-{n}.mp3"
    if dest.exists() and dest.stat().st_size > 10_000:
        print(f"[music] ↩ Using cached {dest.name}")
        return dest

    url = f"https://www.soundhelix.com/examples/mp3/SoundHelix-Song-{n}.mp3"
    try:
        print(f"[music] Downloading {url} …")
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
        print(f"[music] ✓ {dest.name} ({dest.stat().st_size // 1024} KB)")
        return dest
    except Exception as exc:
        print(f"[music] ⚠ Could not download music ({exc}) — no background music")
        return None


def _mix_music(video_path: Path, music_path: Path, out_path: Path) -> None:
    """Mix background music into video at _MUSIC_VOL volume."""
    ffmpeg = _get_ffmpeg()
    print(f"[music] Mixing background music at {int(_MUSIC_VOL * 100)}% volume …")

    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex",
        f"[1:a]volume={_MUSIC_VOL}[music];[0:a][music]amix=inputs=2:duration=first[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg music mix error:\n{result.stderr[-2000:]}")


def build_video(
    sections: list[dict],
    image_paths: "list[list[Path]] | list[Path]",
    audio_paths: list[Path],
    slug: str,
    videos_base: Path = None,
    fmt: str = "landscape",
) -> Path:
    """
    Assemble section clips into a final MP4 with background music.

    image_paths: list[list[Path]] (multi-image per section) or list[Path] (one per section)
    fmt: 'landscape' (1920×1080) or 'shorts' (1080×1920)
    Returns output path.
    """
    cfg = _load_config()
    if fmt == "shorts":
        w = cfg["video"].get("shorts_width", 1080)
        h = cfg["video"].get("shorts_height", 1920)
    else:
        w = cfg["video"]["width"]
        h = cfg["video"]["height"]
    fps = cfg["video"]["fps"]

    # Normalise image_paths to list[list[Path]]
    if image_paths and not isinstance(image_paths[0], (list, tuple)):
        image_paths = [[p] for p in image_paths]

    if videos_base is None:
        videos_base = Path(__file__).parent.parent / "videos"
    out_dir = videos_base / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "final.mp4"

    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"[video] ↩ Skip (exists) {out_path}")
        return out_path

    ffmpeg = _get_ffmpeg()
    print(f"[video] Building {len(sections)} sections ({fmt}, {w}×{h}) …")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        section_paths: list[Path] = []

        for i, (section, imgs, aud) in enumerate(zip(sections, image_paths, audio_paths)):
            print(f"[video]   {i + 1}/{len(sections)}: {section['heading']} ({len(imgs)} img)")
            sec_out = tmp_dir / f"section_{i:02d}.mp4"
            _build_section_video(
                imgs, aud,
                section["narration"],
                section["heading"],
                sec_out, w, h, fps, tmp_dir,
                style_idx=i,
            )
            section_paths.append(sec_out)

        # Concatenate sections
        concat_txt = tmp_dir / "concat.txt"
        concat_txt.write_text("\n".join(f"file '{p}'" for p in section_paths) + "\n")

        # If music: concat → temp, then mix; else concat → final
        music_path = _fetch_background_music(Path(__file__).parent.parent / "assets" / "music")
        if music_path:
            no_music = tmp_dir / "final_nomusic.mp4"
            tgt = no_music
        else:
            tgt = out_path

        print(f"[video] Concatenating sections → {tgt.name}")
        concat_cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c", "copy",
            str(tgt),
        ]
        result = subprocess.run(concat_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat error:\n{result.stderr[-2000:]}")

        if music_path:
            _mix_music(no_music, music_path, out_path)

    print(f"[video] ✓ Video ready → {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--format", default="landscape", choices=["landscape", "shorts"])
    args = parser.parse_args()

    base = Path(__file__).parent.parent
    script = json.loads((base / "scripts" / args.slug / "script.json").read_text())
    imgs = [[base / "assets" / args.slug / "images" / f"section_{i:02d}_img_{j}.jpg"
             for j in range(3)] for i in range(len(script["sections"]))]
    auds = [base / "assets" / args.slug / "audio" / f"section_{i:02d}.mp3"
            for i in range(len(script["sections"]))]
    build_video(script["sections"], imgs, auds, args.slug, fmt=args.format)
