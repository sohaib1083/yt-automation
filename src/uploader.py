"""
Upload a video to YouTube via YouTube Data API v3.

Quota cost: ~1600 units per upload.
Free quota: 10,000 units/day → ~6 uploads/day.
"""

import json
import time
from pathlib import Path

import yaml
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"
_RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
_MAX_RETRIES = 5


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)["youtube"]


def upload_video(
    video_path: Path,
    script: dict,
    youtube_client,
    privacy_status: str = None,
) -> str:
    """
    Upload *video_path* to YouTube using metadata from *script*.

    Returns the YouTube video URL on success.
    """
    cfg = _load_config()
    status = privacy_status or cfg["privacy_status"]

    body = {
        "snippet": {
            "title": script["title"],
            "description": script["description"],
            "tags": script.get("tags", []),
            "categoryId": cfg["category_id"],
        },
        "status": {
            "privacyStatus": status,
            "madeForKids": cfg["made_for_kids"],
            "selfDeclaredMadeForKids": cfg["made_for_kids"],
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
        resumable=True,
    )

    request = youtube_client.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    print(f"[uploader] Uploading: {video_path.name} ({video_path.stat().st_size / 1e6:.1f} MB)")
    print(f"[uploader] Title: {script['title']}")
    print(f"[uploader] Privacy: {status}")

    response = None
    retries = 0
    while response is None:
        try:
            status_obj, response = request.next_chunk()
            if status_obj:
                pct = int(status_obj.progress() * 100)
                print(f"[uploader] Upload progress: {pct}%", end="\r")
        except HttpError as e:
            if e.resp.status in _RETRIABLE_STATUS_CODES and retries < _MAX_RETRIES:
                retries += 1
                wait = 2 ** retries
                print(f"[uploader] HTTP {e.resp.status} — retry {retries}/{_MAX_RETRIES} in {wait}s")
                time.sleep(wait)
            else:
                raise

    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"\n[uploader] ✓ Upload complete → {url}")
    return url


if __name__ == "__main__":
    import argparse

    from src.auth import get_youtube_client

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Path to final.mp4")
    parser.add_argument("--script", required=True, help="Path to script.json")
    parser.add_argument("--privacy", default=None, choices=["public", "private", "unlisted"])
    args = parser.parse_args()

    script_data = json.loads(Path(args.script).read_text())
    yt = get_youtube_client()
    upload_video(Path(args.video), script_data, yt, args.privacy)
