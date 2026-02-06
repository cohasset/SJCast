#!/usr/bin/env python3
"""
SJC Oral Arguments - YouTube Upload Monitor

Checks the Massachusetts Supreme Judicial Court YouTube channel for new uploads.
Maintains a local state file of seen video IDs to detect new content.

Usage:
    python monitor.py              # Check for new videos
    python monitor.py --init       # Initialize state with current videos (no downloads)
    python monitor.py --list 10    # List the 10 most recent videos

Requires:
    - YouTube Data API key (set as YOUTUBE_API_KEY environment variable)
    - pip install google-api-python-client
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("Missing dependency. Install with: pip install google-api-python-client")
    sys.exit(1)


# Configuration
CHANNEL_ID = "UCOftbmknBche29CG41v19cA"
UPLOADS_PLAYLIST_ID = "UUOftbmknBche29CG41v19cA"  # UC -> UU
STATE_FILE = Path(__file__).parent / "state.json"


def get_api_key():
    """Get YouTube API key from environment."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("Error: YOUTUBE_API_KEY environment variable not set")
        print("\nTo get an API key:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project (or select existing)")
        print("3. Enable 'YouTube Data API v3'")
        print("4. Create credentials -> API Key")
        print("5. export YOUTUBE_API_KEY='your-key-here'")
        sys.exit(1)
    return key


def load_state():
    """Load seen video IDs from state file."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"seen_ids": [], "last_check": None}


def save_state(state):
    """Save state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_recent_uploads(youtube, max_results=50):
    """
    Fetch recent uploads from the channel's uploads playlist.
    
    Returns list of dicts with video info:
        - id: YouTube video ID
        - title: Video title
        - published_at: ISO timestamp
        - description: Video description (truncated)
    """
    videos = []
    
    request = youtube.playlistItems().list(
        part="snippet",
        playlistId=UPLOADS_PLAYLIST_ID,
        maxResults=min(max_results, 50)  # API max is 50
    )
    
    response = request.execute()
    
    for item in response.get("items", []):
        snippet = item["snippet"]
        videos.append({
            "id": snippet["resourceId"]["videoId"],
            "title": snippet["title"],
            "published_at": snippet["publishedAt"],
            "description": snippet.get("description", "")[:200]
        })
    
    return videos


def parse_case_info(title):
    """
    Extract case name and docket number from video title.
    
    Examples:
        "Commonwealth v. Emilio Delarosa, SJC-13444" 
            -> {"case_name": "Commonwealth v. Emilio Delarosa", "docket": "SJC-13444"}
        "Mass Bar Association Presents Annual State of the Judiciary"
            -> {"case_name": "Mass Bar Association Presents...", "docket": None}
    """
    import re
    
    # Try to match "..., SJC-XXXXX" pattern
    match = re.search(r'^(.+),\s*(SJC-\d+)$', title)
    if match:
        return {
            "case_name": match.group(1).strip(),
            "docket": match.group(2)
        }
    
    # No docket number found
    return {
        "case_name": title,
        "docket": None
    }


def check_for_new_videos(youtube, state):
    """
    Check for new videos not in our seen list.
    Returns list of new video dicts.
    """
    recent = fetch_recent_uploads(youtube)
    seen_ids = set(state.get("seen_ids", []))
    
    new_videos = [v for v in recent if v["id"] not in seen_ids]
    
    return new_videos


def main():
    parser = argparse.ArgumentParser(description="Monitor SJC YouTube channel for new uploads")
    parser.add_argument("--init", action="store_true", 
                        help="Initialize state with current videos (won't trigger downloads)")
    parser.add_argument("--list", type=int, metavar="N",
                        help="List N most recent videos")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON (for piping to other scripts)")
    parser.add_argument("--all", action="store_true",
                        help="Output all recent videos (ignore seen state, for backfill)")
    args = parser.parse_args()
    
    api_key = get_api_key()
    youtube = build("youtube", "v3", developerKey=api_key)
    
    state = load_state()
    
    # --list mode: just show recent videos
    if args.list:
        videos = fetch_recent_uploads(youtube, max_results=args.list)
        if args.json:
            print(json.dumps(videos, indent=2))
        else:
            print(f"Recent {len(videos)} uploads:\n")
            for v in videos:
                case_info = parse_case_info(v["title"])
                docket = f" [{case_info['docket']}]" if case_info['docket'] else ""
                print(f"  {v['id']} - {v['title'][:60]}{docket}")
                print(f"             Published: {v['published_at'][:10]}")
        return
    
    # --init mode: populate state without triggering downloads
    if args.init:
        videos = fetch_recent_uploads(youtube)
        state["seen_ids"] = [v["id"] for v in videos]
        state["last_check"] = datetime.utcnow().isoformat()
        save_state(state)
        print(f"Initialized state with {len(videos)} existing videos")
        print("Future runs will only report new uploads")
        return
    
    # Normal mode: check for new videos
    if args.all:
        # Backfill mode: return all recent videos regardless of seen state
        new_videos = fetch_recent_uploads(youtube)
    else:
        new_videos = check_for_new_videos(youtube, state)

    if args.json:
        # In --json mode, just output and exit. Do NOT update state here.
        # State should only be updated after successful processing by
        # process_videos.py, so failed downloads get retried next run.
        print(json.dumps(new_videos, indent=2))
        sys.exit(0 if new_videos else 1)

    if new_videos:
        print(f"Found {len(new_videos)} new video(s):\n")
        for v in new_videos:
            case_info = parse_case_info(v["title"])
            print(f"  NEW: {v['title']}")
            print(f"       ID: {v['id']}")
            print(f"       Docket: {case_info['docket'] or 'N/A'}")
            print(f"       URL: https://www.youtube.com/watch?v={v['id']}")
            print()
    else:
        print("No new videos found")

    # Update state only in interactive (non-json) mode
    if new_videos:
        state["seen_ids"].extend([v["id"] for v in new_videos])
    state["last_check"] = datetime.utcnow().isoformat()
    save_state(state)

    # Exit with code indicating whether new videos were found
    # (useful for cron: only proceed to download step if exit code is 0)
    sys.exit(0 if new_videos else 1)


if __name__ == "__main__":
    main()
