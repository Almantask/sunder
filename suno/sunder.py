#!/usr/bin/env python3
"""Download your Suno playlists and liked songs as tagged MP3s."""

from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import requests
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TRCK, ID3NoHeaderError
from mutagen.mp3 import MP3

BASE_API = "https://studio-api.prod.suno.com/api"
ORIGIN = "https://suno.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
FEED_PAGE_SIZE = 50
MAX_PAGES = 500
MAX_RETRIES = 6
MAX_BACKOFF = 60
DEFAULT_WORKERS = 4
CDN_HOSTS = ("cdn1.suno.ai", "cdn2.suno.ai", "audiopipe.suno.ai")

WIN_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = SCRIPT_DIR / "downloads"


class AuthExpired(Exception):
    """JWT was rejected and could not be refreshed."""


class ApiError(Exception):
    """Suno API returned an unrecoverable error."""


@dataclass
class Clip:
    id: str
    title: str
    artist: str
    audio_url: str
    image_url: str
    genre: str
    year: str
    status: str
    raw: dict[str, Any]


@dataclass
class Playlist:
    id: str
    name: str
    num_clips: int


@dataclass
class Job:
    clip: Clip
    dest: Path
    album: str
    track: int
    track_total: int
    label: str


@dataclass
class Stats:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    no_audio: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def bump(self, field_name: str) -> None:
        with self.lock:
            setattr(self, field_name, getattr(self, field_name) + 1)


class TokenStore:
    """Thread-safe Bearer token with a one-prompt-per-expiry refresh."""

    def __init__(self, token: str, interactive: bool) -> None:
        self._lock = threading.Lock()
        self._token = token
        self._generation = 0
        self._interactive = interactive

    def headers(self) -> dict[str, str]:
        with self._lock:
            token = self._token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": ORIGIN,
            "Referer": f"{ORIGIN}/",
            "User-Agent": USER_AGENT,
        }

    def refresh_after_401(self, seen_generation: int) -> None:
        with self._lock:
            if self._generation != seen_generation:
                return
            if not self._interactive:
                raise AuthExpired(
                    "Token expired or invalid. Pass a fresh --token / SUNO_TOKEN."
                )
            print(
                "\nAuthentication failed (HTTP 401/403). The session token expired.",
                file=sys.stderr,
            )
            self._token = prompt_token()
            self._generation += 1

    def generation(self) -> int:
        with self._lock:
            return self._generation


def prompt_token() -> str:
    print(
        "\nPaste your Suno Bearer token (the JWT after 'Bearer ' in DevTools).\n"
        "See README.md for step-by-step instructions.\n",
        file=sys.stderr,
    )
    try:
        raw = input("Token: ").strip()
    except EOFError as exc:
        raise AuthExpired("No token provided (stdin closed).") from exc
    token = normalize_token(raw)
    if not token:
        raise AuthExpired("Empty token.")
    return token


def normalize_token(raw: str) -> str:
    token = raw.strip().strip('"').strip("'")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def sanitize_component(name: str, max_len: int = 80) -> str:
    cleaned = WIN_INVALID.sub("", name or "").replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned:
        cleaned = "untitled"
    stem = cleaned.split(".")[0].upper()
    if stem in WIN_RESERVED:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip().rstrip(".")
    return cleaned or "untitled"


def pad_width(count: int, minimum: int) -> int:
    return max(minimum, len(str(max(count, 1))))


def clip_from_raw(raw: dict[str, Any]) -> Clip | None:
    clip_id = str(raw.get("id") or "").strip()
    if not clip_id:
        return None
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    title = str(raw.get("title") or "").strip() or "Untitled"
    artist = str(raw.get("display_name") or "").strip() or "Suno"
    genre = str(raw.get("display_tags") or meta.get("tags") or "").strip()
    created = str(raw.get("created_at") or "")
    year = created[:4] if len(created) >= 4 and created[:4].isdigit() else ""
    image = str(raw.get("image_large_url") or raw.get("image_url") or "").strip()
    audio = str(
        raw.get("audio_url")
        or raw.get("audio_url_2")
        or raw.get("audio_url_proxy")
        or ""
    ).strip()
    if not audio:
        audio = f"https://cdn1.suno.ai/{clip_id}.mp3"
    status = str(raw.get("status") or "").strip().lower()
    return Clip(
        id=clip_id,
        title=title,
        artist=artist,
        audio_url=audio,
        image_url=image,
        genre=genre,
        year=year,
        status=status,
        raw=raw,
    )


def unwrap_playlist_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    inner = entry.get("clip")
    if isinstance(inner, dict):
        return inner
    return entry


def filename_for(clip: Clip, index: int, width: int) -> str:
    title = sanitize_component(clip.title, max_len=90)
    short_id = clip.id.replace("-", "")[:8]
    return f"{index:0{width}d} - {title} [{short_id}].mp3"


class SunoClient:
    def __init__(self, tokens: TokenStore) -> None:
        self.tokens = tokens
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=8, pool_maxsize=8, max_retries=0
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.cdn = requests.Session()
        self.cdn.mount("https://", adapter)

    def api_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{BASE_API}{path}"
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            gen = self.tokens.generation()
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self.tokens.headers(),
                    params=params,
                    json=json_body,
                    timeout=45,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                self._sleep_backoff(attempt, str(exc))
                continue

            if response.status_code in (401, 403):
                try:
                    self.tokens.refresh_after_401(gen)
                except AuthExpired:
                    raise
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = int(retry_after) + 1 if retry_after and retry_after.isdigit() else None
                self._sleep_backoff(attempt, "429 Too Many Requests", wait)
                continue

            if response.status_code in (500, 502, 503, 504):
                self._sleep_backoff(attempt, f"HTTP {response.status_code}")
                continue

            if response.status_code >= 400:
                raise ApiError(
                    f"{method} {path} failed: HTTP {response.status_code} {response.text[:300]}"
                )

            if not response.content:
                return {}
            return response.json()

        raise ApiError(f"{method} {path} failed after {MAX_RETRIES} attempts: {last_error}")

    def list_playlists(self) -> list[Playlist]:
        playlists: list[Playlist] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            data = self.api_json(
                "GET",
                "/playlist/me",
                params={
                    "page": page,
                    "show_trashed": "false",
                    "show_sharelist": "false",
                },
            )
            batch = data.get("playlists") if isinstance(data, dict) else None
            if not batch:
                break
            added = 0
            for raw in batch:
                if not isinstance(raw, dict):
                    continue
                pid = str(raw.get("id") or "").strip()
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                name = str(raw.get("name") or "").strip() or "Untitled"
                num = raw.get("num_total_results")
                playlists.append(
                    Playlist(
                        id=pid,
                        name=name,
                        num_clips=int(num) if isinstance(num, int) else 0,
                    )
                )
                added += 1
            if added == 0:
                break
            time.sleep(0.2)
        return playlists

    def playlist_clips(self, playlist_id: str) -> list[Clip]:
        clips: list[Clip] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            data = self.api_json(
                "GET",
                f"/playlist/{playlist_id}/",
                params={"page": page},
            )
            if not isinstance(data, dict):
                break
            raw_entries = data.get("playlist_clips") or []
            if not raw_entries:
                break
            page_added = 0
            for entry in raw_entries:
                inner = unwrap_playlist_entry(entry)
                if not inner:
                    continue
                clip = clip_from_raw(inner)
                if not clip or clip.id in seen:
                    continue
                seen.add(clip.id)
                clips.append(clip)
                page_added += 1
            total = data.get("num_total_results")
            if isinstance(total, int) and len(clips) >= total:
                break
            if page_added == 0:
                break
            time.sleep(0.2)
        return clips

    def liked_clips(self) -> list[Clip]:
        clips: list[Clip] = []
        seen: set[str] = set()
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            body: dict[str, Any] = {
                "limit": FEED_PAGE_SIZE,
                "filters": {"trashed": "False", "liked": "True"},
            }
            if cursor:
                body["cursor"] = cursor
            data = self.api_json("POST", "/feed/v3", json_body=body)
            if not isinstance(data, dict):
                break
            batch = data.get("clips") or []
            if not batch:
                break
            for raw in batch:
                if not isinstance(raw, dict):
                    continue
                clip = clip_from_raw(raw)
                if not clip or clip.id in seen:
                    continue
                seen.add(clip.id)
                clips.append(clip)
            if not data.get("has_more"):
                break
            next_cursor = data.get("next_cursor")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            time.sleep(0.2)
        return clips

    def _download_headers(self, url: str, *, auth: bool) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"{ORIGIN}/",
        }
        if auth or not any(host in url for host in CDN_HOSTS):
            headers.update(self.tokens.headers())
        return headers

    def _open_download(self, url: str, *, auth: bool):
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = self.cdn.get(
                    url,
                    headers=self._download_headers(url, auth=auth),
                    timeout=90,
                    stream=True,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                self._sleep_backoff(attempt, str(exc))
                continue
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = int(retry_after) + 1 if retry_after and retry_after.isdigit() else None
                self._sleep_backoff(attempt, "429 download", wait)
                continue
            if response.status_code in (500, 502, 503, 504):
                self._sleep_backoff(attempt, f"HTTP {response.status_code} download")
                continue
            response.raise_for_status()
            return response
        raise ApiError(f"download failed after {MAX_RETRIES} attempts: {url} ({last_error})")

    def download_bytes(self, url: str, *, auth: bool = False) -> bytes:
        response = self._open_download(url, auth=auth)
        try:
            chunks: list[bytes] = []
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    def download_file(self, url: str, dest: Path, *, auth: bool = False) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        response = self._open_download(url, auth=auth)
        try:
            with part.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        handle.write(chunk)
            if part.stat().st_size < 1024:
                part.unlink(missing_ok=True)
                raise ApiError("audio response too small to be an MP3")
            part.replace(dest)
        except Exception:
            part.unlink(missing_ok=True)
            raise
        finally:
            response.close()

    @staticmethod
    def _sleep_backoff(attempt: int, reason: str, explicit: int | None = None) -> None:
        wait = explicit if explicit is not None else min(2 ** attempt, MAX_BACKOFF)
        print(f"  retry in {wait}s ({reason})", flush=True)
        time.sleep(wait)


def clip_has_audio(clip: Clip) -> bool:
    if clip.status in {"error", "failed"}:
        return False
    return bool(clip.audio_url)


def embed_tags(mp3_path: Path, job: Job, cover: bytes | None, cover_mime: str) -> None:
    try:
        tags = ID3(str(mp3_path))
    except ID3NoHeaderError:
        tags = ID3()
    tags["TIT2"] = TIT2(encoding=3, text=job.clip.title)
    tags["TPE1"] = TPE1(encoding=3, text=job.clip.artist)
    tags["TALB"] = TALB(encoding=3, text=job.album)
    tags["TRCK"] = TRCK(encoding=3, text=f"{job.track}/{job.track_total}")
    if job.clip.year:
        tags["TDRC"] = TDRC(encoding=3, text=job.clip.year)
    if job.clip.genre:
        tags["TCON"] = TCON(encoding=3, text=job.clip.genre[:80])
    if cover:
        tags["APIC"] = APIC(
            encoding=3,
            mime=cover_mime,
            type=3,
            desc="Cover",
            data=cover,
        )
    tags.save(str(mp3_path), v2_version=3)
    # Keep mutagen from leaving an unsynced audio object around.
    try:
        MP3(str(mp3_path))
    except Exception:
        pass


def guess_image_mime(data: bytes, url: str) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    lower = url.lower().split("?", 1)[0]
    if lower.endswith(".png"):
        return "image/png"
    return "image/jpeg"


def process_job(
    client: SunoClient,
    job: Job,
    stats: Stats,
    index: int,
    total: int,
    out_root: Path,
) -> str:
    dest = job.dest
    try:
        rel = dest.relative_to(out_root)
    except ValueError:
        rel = dest

    if dest.exists() and dest.stat().st_size > 0:
        stats.bump("skipped")
        return f"[{index}/{total}] skipped     {rel}"

    try:
        client.download_file(job.clip.audio_url, dest)
        cover = None
        mime = "image/jpeg"
        if job.clip.image_url:
            try:
                cover = client.download_bytes(job.clip.image_url)
                mime = guess_image_mime(cover, job.clip.image_url)
            except Exception as exc:
                print(f"  cover failed for {job.clip.title}: {exc}", flush=True)
                cover = None
        embed_tags(dest, job, cover, mime)
        stats.bump("downloaded")
        return f"[{index}/{total}] downloaded  {rel}"
    except Exception as exc:
        stats.bump("failed")
        return f"[{index}/{total}] FAILED     {rel}  ({exc})"


def match_playlist(name: str, needle: str) -> bool:
    return needle.lower() in name.lower()


def build_playlist_jobs(
    client: SunoClient,
    playlists: list[Playlist],
    out_root: Path,
    needle: str | None,
) -> tuple[list[Job], list[str]]:
    jobs: list[Job] = []
    notes: list[str] = []
    playlists_root = out_root / "Playlists"
    used_folders: dict[str, Path] = {}

    selected = playlists
    if needle:
        selected = [p for p in playlists if match_playlist(p.name, needle)]
        if not selected:
            notes.append(f'No playlist matched --playlist "{needle}".')
            return jobs, notes

    for pl in selected:
        print(f"  playlist: {pl.name} ({pl.num_clips or '?'} tracks) …", flush=True)
        clips = client.playlist_clips(pl.id)
        folder_name = sanitize_component(pl.name)
        if folder_name in used_folders:
            folder = playlists_root / f"{folder_name} [{pl.id.replace('-', '')[:8]}]"
        else:
            folder = playlists_root / folder_name
        used_folders[folder_name] = folder
        total = len(clips)
        width = pad_width(total, 2)
        ready = 0
        for i, clip in enumerate(clips, start=1):
            if not clip_has_audio(clip):
                notes.append(f"  no audio: {pl.name} / {clip.title} [{clip.id[:8]}]")
                continue
            ready += 1
            dest = folder / filename_for(clip, i, width)
            jobs.append(
                Job(
                    clip=clip,
                    dest=dest,
                    album=pl.name,
                    track=i,
                    track_total=total,
                    label=f"Playlists/{folder.name}",
                )
            )
        print(f"    {ready}/{total} downloadable", flush=True)
    return jobs, notes


def build_liked_jobs(client: SunoClient, out_root: Path) -> tuple[list[Job], list[str]]:
    print("  liked songs …", flush=True)
    clips = client.liked_clips()
    folder = out_root / "Liked Songs"
    total = len(clips)
    width = pad_width(total, 3)
    jobs: list[Job] = []
    notes: list[str] = []
    ready = 0
    for i, clip in enumerate(clips, start=1):
        if not clip_has_audio(clip):
            notes.append(f"  no audio: Liked Songs / {clip.title} [{clip.id[:8]}]")
            continue
        ready += 1
        dest = folder / filename_for(clip, i, width)
        jobs.append(
            Job(
                clip=clip,
                dest=dest,
                album="Liked Songs",
                track=i,
                track_total=total,
                label="Liked Songs",
            )
        )
    print(f"    {ready}/{total} downloadable", flush=True)
    return jobs, notes


def print_dry_run(jobs: list[Job], notes: list[str]) -> None:
    print(f"\nDry run — {len(jobs)} file(s) would be written:\n")
    grouped: dict[str, list[Job]] = {}
    for job in jobs:
        grouped.setdefault(job.label, []).append(job)
    for label, group in grouped.items():
        print(f"  {label}/  ({len(group)})")
        preview = group[:12]
        for job in preview:
            print(f"    {job.dest.name}")
        remaining = len(group) - len(preview)
        if remaining > 0:
            print(f"    … +{remaining} more")
        print()
    if notes:
        print("Notes:")
        for note in notes:
            print(note)


def run_downloads(client: SunoClient, jobs: list[Job], workers: int, out_root: Path) -> Stats:
    stats = Stats()
    total = len(jobs)
    print(f"\nDownloading {total} file(s) with {workers} worker(s)…\n", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(process_job, client, job, stats, i, total, out_root): i
            for i, job in enumerate(jobs, start=1)
        }
        for future in as_completed(futures):
            try:
                line = future.result()
            except Exception as exc:
                stats.bump("failed")
                line = f"FAILED ({exc})"
            print(line, flush=True)
    return stats


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download your Suno playlists and liked songs as tagged MP3s."
    )
    parser.add_argument(
        "--token",
        help="Bearer JWT from DevTools (overrides SUNO_TOKEN).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output directory (default: {DEFAULT_OUT})",
    )
    parser.add_argument("--liked-only", action="store_true", help="Download liked songs only.")
    parser.add_argument(
        "--playlists-only", action="store_true", help="Download playlists only."
    )
    parser.add_argument(
        "--playlist",
        metavar="NAME",
        help="Only playlists whose name contains NAME (case-insensitive).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List planned files without downloading.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel downloads (default: {DEFAULT_WORKERS}).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def resolve_token(args: argparse.Namespace) -> str:
    token = normalize_token(args.token or os.environ.get("SUNO_TOKEN") or "")
    if token:
        return token
    if not sys.stdin.isatty():
        raise AuthExpired(
            "No token. Pass --token, set SUNO_TOKEN, or run in a terminal to paste one."
        )
    return prompt_token()


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.liked_only and args.playlists_only:
        print("Use only one of --liked-only / --playlists-only.", file=sys.stderr)
        return 2
    try:
        token = resolve_token(args)
    except AuthExpired as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    tokens = TokenStore(token, interactive=sys.stdin.isatty())
    client = SunoClient(tokens)
    out_root = args.out.expanduser().resolve()

    print("Sunder — Suno library downloader")
    print(f"Output: {out_root}\n")
    print("Enumerating library…", flush=True)

    jobs: list[Job] = []
    notes: list[str] = []
    try:
        do_playlists = not args.liked_only
        do_liked = not args.playlists_only
        if do_playlists:
            playlists = client.list_playlists()
            print(f"  {len(playlists)} playlist(s) found")
            pl_jobs, pl_notes = build_playlist_jobs(
                client, playlists, out_root, args.playlist
            )
            jobs.extend(pl_jobs)
            notes.extend(pl_notes)
        if do_liked:
            liked_jobs, liked_notes = build_liked_jobs(client, out_root)
            jobs.extend(liked_jobs)
            notes.extend(liked_notes)
    except AuthExpired as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except ApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 1

    no_audio = len(notes)
    if args.dry_run:
        print_dry_run(jobs, notes)
        print(f"Would download {len(jobs)} file(s); {no_audio} clip(s) without audio.")
        return 0

    if not jobs:
        print("Nothing to download.")
        if notes:
            print("Notes:")
            for note in notes:
                print(note)
        return 0

    stats = run_downloads(client, jobs, args.workers, out_root)
    stats.no_audio = no_audio
    print(
        f"\nDone. downloaded={stats.downloaded}  skipped={stats.skipped}  "
        f"failed={stats.failed}  no_audio={stats.no_audio}"
    )
    print(f"Files: {out_root}")
    if notes:
        print("\nClips without audio:")
        for note in notes:
            print(note)
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
