# SJC Oral Arguments Podcast Pipeline

Monitors the Massachusetts Supreme Judicial Court YouTube channel for new oral argument recordings, extracts audio, and publishes as a podcast feed.

## Architecture

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  GitHub Actions     │────▶│  Backblaze B2    │────▶│  Podcast Feed   │
│  (runs every 6 hrs) │     │  (audio storage) │     │  (RSS in repo)  │
└─────────────────────┘     └──────────────────┘     └─────────────────┘
         │
         ▼
┌─────────────────────┐
│  YouTube Data API   │
│  + yt-dlp download  │
└─────────────────────┘
```

## Setup

### 1. Fork/Clone This Repository

### 2. Get API Keys

**YouTube Data API:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Go to **APIs & Services > Library**
4. Search for "YouTube Data API v3" and enable it
5. Go to **APIs & Services > Credentials**
6. Click **Create Credentials > API Key**

**Backblaze B2:**
1. Sign up at [backblaze.com](https://www.backblaze.com/b2/cloud-storage.html)
2. Create a bucket (set to **Public**)
3. Go to **App Keys** and create a new application key
4. Note the `keyID` and `applicationKey`

### 3. Configure GitHub Secrets

Go to your repo's **Settings > Secrets and variables > Actions** and add:

| Secret | Description |
|--------|-------------|
| `YOUTUBE_API_KEY` | Your YouTube Data API key |
| `B2_APPLICATION_KEY_ID` | Backblaze B2 keyID |
| `B2_APPLICATION_KEY` | Backblaze B2 applicationKey |

### 4. Configure GitHub Variables

Go to **Settings > Secrets and variables > Actions > Variables** and add:

| Variable | Description | Default |
|----------|-------------|---------|
| `B2_BUCKET` | Your B2 bucket name | `sjc-podcast` |
| `PODCAST_BASE_URL` | Public URL for your bucket | `https://f000.backblazeb2.com/file/sjc-podcast` |

> **Note:** The defaults above are already configured in `process_videos.py`, so these variables are optional unless you need different values.

### 5. Initialize the State

Run the workflow manually once with an initialization step, or run locally:

```bash
export YOUTUBE_API_KEY='your-key'
python monitor.py --init
git add state.json
git commit -m "Initialize video state"
git push
```

### 6. Enable the Workflow

The workflow runs automatically every 6 hours. You can also trigger it manually from **Actions > Check for New Videos & Publish > Run workflow**.

## Local Development

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Check for New Videos

```bash
export YOUTUBE_API_KEY='your-key'
python monitor.py --list 10    # List recent videos
python monitor.py              # Check for new videos
```

### Process Videos Locally

```bash
export B2_APPLICATION_KEY_ID='your-key-id'
export B2_APPLICATION_KEY='your-key'
export B2_BUCKET='your-bucket'
python process_videos.py
```

## Files

| File | Purpose |
|------|---------|
| `monitor.py` | Checks YouTube for new uploads, maintains seen state |
| `process_videos.py` | Downloads audio, tags, uploads to B2, generates RSS |
| `state.json` | Tracks which videos have been seen (cached in Actions) |
| `episodes.json` | Metadata for all processed episodes |
| `feed.xml` | The podcast RSS feed |
| `.github/workflows/check-and-publish.yml` | GitHub Actions automation |

## Channel Info

- **Channel:** Massachusetts Supreme Judicial Court
- **Handle:** @sjcarguments
- **Channel ID:** UCOftbmknBche29CG41v19cA

## Costs

- **GitHub Actions:** Free tier includes 2,000 minutes/month (this uses ~5 min/run)
- **YouTube API:** Free tier includes 10,000 units/day (this uses ~3 units/check)
- **Backblaze B2:** First 10GB storage free, then $0.005/GB/month

## Customization

Edit `process_videos.py` to customize:
- `PODCAST_TITLE`, `PODCAST_DESCRIPTION`, etc.
- Audio quality settings in `download_audio()`
- ID3 tag fields in `tag_audio()`
