# Sunder — Suno library downloader

Downloads **all of your Suno playlists** (one folder per playlist) and **liked songs** (separate folder) as MP3s with ID3 tags and cover art.

Suno has no official bulk export. This script uses the same internal API the website uses, with a session token from your logged-in browser. It is unofficial and can break if Suno changes their API.

## Setup (Windows)

From this folder:

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

(`py -3.9` is the Windows Python launcher. If `python` is on your PATH, `python -m venv .venv` is equivalent.)

## How to get your token

The token is a JWT. It lasts about **one hour**. Never commit it or paste it into a file in git.

1. Open [https://suno.com/me](https://suno.com/me) in Chrome or Edge and make sure you are logged in.
2. Press **F12** to open Developer Tools.
3. Open the **Network** tab.
4. Reload the page (**F5**).
5. In the filter box, type `feed` (or `playlist`).
6. Click a request to `studio-api.prod.suno.com` (the `v3` POST under `feed` is a reliable one).
7. Open **Request Headers** and find `Authorization`. It looks like:

   `Bearer eyJhbGciOi...`

8. Copy **only the part after `Bearer `** — the long `eyJ...` string.

If a download run dies with HTTP 401, the token expired. Paste a fresh one when the script asks (already-downloaded files are skipped).

## Usage

```powershell
# See what would be downloaded (no files written)
.\.venv\Scripts\python sunder.py --dry-run --token "eyJ..."

# Download playlists + liked songs into .\downloads
.\.venv\Scripts\python sunder.py --token "eyJ..."

# Or set the env var so you don't pass --token every time (current session only)
$env:SUNO_TOKEN = "eyJ..."
.\.venv\Scripts\python sunder.py
```

If you omit `--token` and `SUNO_TOKEN`, the script prompts you to paste it.

### Flags

| Flag | Meaning |
|---|---|
| `--out DIR` | Output root (default: `downloads` next to this script) |
| `--liked-only` | Only liked songs |
| `--playlists-only` | Only playlists |
| `--playlist NAME` | Only playlists whose name matches (case-insensitive; substring ok) |
| `--dry-run` | List planned files; download nothing |
| `--workers N` | Parallel MP3 downloads (default: 4) |

## Output layout

```
downloads/
  Playlists/
    My Mix/
      01 - Song Title [a1b2c3d4].mp3
      02 - Another Song [e5f6g7h8].mp3
  Liked Songs/
    001 - A Liked Track [11223344].mp3
```

- Playlist tracks keep **playlist order** and are numbered.
- Liked songs keep **newest-liked first** (same as the site) and are numbered from 001.
- The 8-character id suffix avoids collisions when two tracks share a title, and makes re-runs skip files that are already present.

## Notes

- Files that already exist (non-empty `.mp3`) are skipped. Re-run anytime to pick up new likes or playlist tracks.
- Clips still generating, or with no `audio_url`, are reported and skipped.
- Audio is the same MP3 the site's download button produces. WAV/lossless is not supported.
