#!/usr/bin/env python3
"""
Process new YouTube videos: download audio, upload to B2, update RSS feed.

Reads new_videos.json (output from monitor.py) and processes each video.
"""

import os
import sys
import json
import subprocess
import re
from pathlib import Path
from datetime import datetime

# Optional imports - check availability
try:
    from b2sdk.v2 import B2Api, InMemoryAccountInfo
    HAS_B2 = True
except ImportError:
    HAS_B2 = False
    print("Warning: b2sdk not installed, B2 upload will be skipped")

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, COMM
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False
    print("Warning: mutagen not installed, ID3 tagging will be skipped")

try:
    from feedgen.feed import FeedGenerator
    HAS_FEEDGEN = True
except ImportError:
    HAS_FEEDGEN = False
    print("Warning: feedgen not installed, RSS generation will be skipped")


# Configuration
EPISODES_FILE = Path("episodes.json")
FEED_FILE = Path("feed.xml")
AUDIO_DIR = Path("audio")

# Podcast metadata
PODCAST_TITLE = "SJC Oral Arguments"
PODCAST_DESCRIPTION = "Oral argument recordings from the Massachusetts Supreme Judicial Court"
PODCAST_AUTHOR = "Massachusetts Supreme Judicial Court"
PODCAST_EMAIL = "sjc@example.com"  # Update with real contact
PODCAST_WEBSITE = "https://www.mass.gov/orgs/supreme-judicial-court"
PODCAST_IMAGE = ""  # Add URL to podcast artwork


def parse_case_info(title):
    """Extract case name and docket number from video title."""
    match = re.search(r'^(.+),\s*(SJC-\d+)$', title)
    if match:
        return {"case_name": match.group(1).strip(), "docket": match.group(2)}
    return {"case_name": title, "docket": None}


def download_audio(video_id, title):
    """Download video and extract audio as MP3."""
    AUDIO_DIR.mkdir(exist_ok=True)

    # Sanitize filename
    safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()
    output_path = AUDIO_DIR / f"{video_id}.mp3"

    if output_path.exists():
        print(f"  Audio already exists: {output_path}")
        return output_path

    url = f"https://www.youtube.com/watch?v={video_id}"

    cmd = [
        "yt-dlp",
        "-x",  # Extract audio
        "--audio-format", "mp3",
        "--audio-quality", "128K",
        "-o", str(AUDIO_DIR / f"{video_id}.%(ext)s"),
        "--no-playlist",
        url
    ]

    print(f"  Downloading: {url}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  Error downloading: {result.stderr}")
        return None

    return output_path


def tag_audio(audio_path, video_info):
    """Add ID3 tags to MP3 file."""
    if not HAS_MUTAGEN:
        return

    case_info = parse_case_info(video_info["title"])

    try:
        audio = MP3(audio_path, ID3=ID3)
    except Exception:
        audio = MP3(audio_path)
        audio.add_tags()

    audio.tags.add(TIT2(encoding=3, text=video_info["title"]))
    audio.tags.add(TPE1(encoding=3, text=PODCAST_AUTHOR))
    audio.tags.add(TALB(encoding=3, text=PODCAST_TITLE))
    audio.tags.add(TCON(encoding=3, text="Podcast"))

    # Extract year from published date
    pub_date = video_info.get("published_at", "")[:4]
    if pub_date:
        audio.tags.add(TDRC(encoding=3, text=pub_date))

    if case_info["docket"]:
        audio.tags.add(COMM(encoding=3, lang="eng", desc="Docket",
                           text=case_info["docket"]))

    audio.save()
    print(f"  Tagged: {audio_path}")


def upload_to_b2(audio_path, video_id):
    """Upload audio file to Backblaze B2."""
    if not HAS_B2:
        return None

    key_id = os.environ.get("B2_APPLICATION_KEY_ID")
    app_key = os.environ.get("B2_APPLICATION_KEY")
    bucket_name = os.environ.get("B2_BUCKET", "sjc-podcast")

    if not all([key_id, app_key, bucket_name]):
        print("  Warning: B2 credentials not set, skipping upload")
        return None

    info = InMemoryAccountInfo()
    b2_api = B2Api(info)
    b2_api.authorize_account("production", key_id, app_key)

    bucket = b2_api.get_bucket_by_name(bucket_name)

    remote_name = f"episodes/{video_id}.mp3"

    print(f"  Uploading to B2: {remote_name}")
    file_info = bucket.upload_local_file(
        local_file=str(audio_path),
        file_name=remote_name,
        content_type="audio/mpeg"
    )

    # Construct public URL
    base_url = os.environ.get("PODCAST_BASE_URL",
                              "https://f000.backblazeb2.com/file/sjc-podcast")
    return f"{base_url}/{remote_name}"


def load_episodes():
    """Load existing episodes from JSON file."""
    if EPISODES_FILE.exists():
        with open(EPISODES_FILE) as f:
            return json.load(f)
    return []


def save_episodes(episodes):
    """Save episodes to JSON file."""
    with open(EPISODES_FILE, "w") as f:
        json.dump(episodes, f, indent=2)


def generate_feed(episodes):
    """Generate RSS feed from episodes."""
    if not HAS_FEEDGEN:
        return

    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.title(PODCAST_TITLE)
    fg.description(PODCAST_DESCRIPTION)
    fg.link(href=PODCAST_WEBSITE, rel="alternate")
    fg.language("en")
    fg.podcast.itunes_author(PODCAST_AUTHOR)
    fg.podcast.itunes_category("Government")
    fg.podcast.itunes_explicit("no")

    if PODCAST_IMAGE:
        fg.podcast.itunes_image(PODCAST_IMAGE)

    # Sort episodes by date (newest first)
    sorted_episodes = sorted(episodes,
                            key=lambda x: x.get("published_at", ""),
                            reverse=True)

    for ep in sorted_episodes:
        fe = fg.add_entry()
        fe.id(ep["video_id"])
        fe.title(ep["title"])
        fe.description(ep.get("description", ""))
        fe.published(ep["published_at"])

        if ep.get("audio_url"):
            fe.enclosure(ep["audio_url"],
                        ep.get("file_size", 0),
                        "audio/mpeg")

        case_info = parse_case_info(ep["title"])
        if case_info["docket"]:
            fe.podcast.itunes_subtitle(f"Docket: {case_info['docket']}")

    fg.rss_file(str(FEED_FILE), pretty=True)
    print(f"Generated feed: {FEED_FILE}")


def process_video(video_info):
    """Process a single video: download, tag, upload, return episode data."""
    video_id = video_info["id"]
    title = video_info["title"]

    print(f"\nProcessing: {title}")

    # Download audio
    audio_path = download_audio(video_id, title)
    if not audio_path or not audio_path.exists():
        print(f"  Failed to download audio for {video_id}")
        return None

    # Tag audio file
    tag_audio(audio_path, video_info)

    # Get file size
    file_size = audio_path.stat().st_size

    # Upload to B2
    audio_url = upload_to_b2(audio_path, video_id)

    # Build episode record
    episode = {
        "video_id": video_id,
        "title": title,
        "description": video_info.get("description", ""),
        "published_at": video_info.get("published_at"),
        "audio_url": audio_url,
        "file_size": file_size,
        "processed_at": datetime.utcnow().isoformat()
    }

    # Clean up local file after upload
    if audio_url and audio_path.exists():
        audio_path.unlink()
        print(f"  Cleaned up local file")

    return episode


def main():
    # Load new videos from monitor output
    new_videos_file = Path("new_videos.json")
    if not new_videos_file.exists():
        print("No new_videos.json file found")
        sys.exit(0)

    with open(new_videos_file) as f:
        new_videos = json.load(f)

    if not new_videos:
        print("No new videos to process")
        sys.exit(0)

    print(f"Processing {len(new_videos)} new video(s)...")

    # Load existing episodes
    episodes = load_episodes()
    existing_ids = {ep["video_id"] for ep in episodes}

    # Process each new video
    for video in new_videos:
        if video["id"] in existing_ids:
            print(f"Skipping already processed: {video['id']}")
            continue

        episode = process_video(video)
        if episode:
            episodes.append(episode)

    # Save updated episodes
    save_episodes(episodes)

    # Generate RSS feed
    generate_feed(episodes)

    print(f"\nDone! Processed {len(new_videos)} video(s)")


if __name__ == "__main__":
    main()
