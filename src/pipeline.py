"""
End-to-end YouTube automation pipeline.

Usage:
  python -m src.pipeline --topic "10 Mind-Blowing Facts About Black Holes"
  python -m src.pipeline --topic "..." --privacy public
  python -m src.pipeline --topic "..." --skip-upload
  python -m src.pipeline --topic "..." --resume   # skip stages with existing output
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent


def _find_existing_slug(topic: str) -> str | None:
    """Return a slug whose script.json matches this topic, if it exists."""
    scripts_dir = BASE / "scripts"
    if not scripts_dir.exists():
        return None
    for d in scripts_dir.iterdir():
        script_file = d / "script.json"
        if script_file.exists():
            data = json.loads(script_file.read_text())
            if data.get("_topic", "") == topic:
                return d.name
    return None


def run(
    topic: str,
    skip_upload: bool = False,
    privacy: str = None,
    resume: bool = False,
) -> dict:
    """
    Run the full pipeline and return a result dict with paths and YouTube URL.
    """
    print("=" * 60)
    print(f"  YouTube Automation Pipeline")
    print(f"  Topic: {topic}")
    print("=" * 60)

    # ── Stage 1: Script Generation ─────────────────────────────────────────
    from src.script_gen import _slugify, generate_script

    slug = _slugify(topic)
    script_path = BASE / "scripts" / slug / "script.json"

    if resume and script_path.exists():
        print(f"\n[pipeline] Stage 1 — Script (resuming from {script_path})")
        script = json.loads(script_path.read_text())
    else:
        print(f"\n[pipeline] Stage 1 — Script Generation")
        script, slug = generate_script(topic)
        # Store topic in script for resume detection
        script["_topic"] = topic
        with open(script_path, "w") as f:
            json.dump(script, f, indent=2)

    sections = script["sections"]

    # ── Stage 2: Text-to-Speech ────────────────────────────────────────────
    print(f"\n[pipeline] Stage 2 — Text-to-Speech ({len(sections)} sections)")
    from src.tts import generate_voiceovers

    audio_paths = generate_voiceovers(sections, slug)

    # ── Stage 3: Image Fetching ────────────────────────────────────────────
    print(f"\n[pipeline] Stage 3 — Image Fetching ({len(sections)} images)")
    from src.image_fetcher import fetch_images

    image_paths = fetch_images(sections, slug)

    # ── Stage 4: Video Assembly ────────────────────────────────────────────
    print(f"\n[pipeline] Stage 4 — Video Assembly")
    from src.video_builder import build_video

    video_path = build_video(sections, image_paths, audio_paths, slug)

    result = {
        "slug": slug,
        "script": script,
        "script_path": str(script_path),
        "video_path": str(video_path),
        "youtube_url": None,
    }

    # ── Stage 5: YouTube Upload ────────────────────────────────────────────
    if skip_upload:
        print(f"\n[pipeline] Stage 5 — Upload SKIPPED (--skip-upload)")
        print(f"[pipeline] Video ready at: {video_path}")
    else:
        print(f"\n[pipeline] Stage 5 — YouTube Upload")
        from src.auth import get_youtube_client
        from src.uploader import upload_video

        yt = get_youtube_client()
        url = upload_video(video_path, script, yt, privacy)
        result["youtube_url"] = url

    print("\n" + "=" * 60)
    print("  Pipeline complete!")
    if result["youtube_url"]:
        print(f"  YouTube URL: {result['youtube_url']}")
    else:
        print(f"  Video: {result['video_path']}")
    print("=" * 60)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end YouTube content automation pipeline"
    )
    parser.add_argument(
        "--topic", required=True, help="Video topic (e.g. '10 facts about black holes')"
    )
    parser.add_argument(
        "--privacy",
        default=None,
        choices=["public", "private", "unlisted"],
        help="YouTube privacy status (overrides config/settings.yaml)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Stop after video assembly; do not upload to YouTube",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip stages whose output already exists on disk",
    )

    args = parser.parse_args()

    try:
        run(
            topic=args.topic,
            skip_upload=args.skip_upload,
            privacy=args.privacy,
            resume=args.resume,
        )
    except EnvironmentError as e:
        print(f"\n[pipeline] ✗ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[pipeline] Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
