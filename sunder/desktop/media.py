"""Audio file allow-list and HTTP Range responses."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

from sunder.embeddings import AUDIO_SUFFIXES

MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
}


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header or size <= 0:
        return None
    header = header.strip()
    if not header.lower().startswith("bytes="):
        return None
    spec = header.split("=", 1)[1].split(",")[0].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            suffix = int(end_s)
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            return start, size - 1
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size:
        return None
    end = min(end, size - 1)
    if end < start:
        return None
    return start, end


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def is_allowed_media(path: Path, roots: list[Path], extra_files: set[Path] | None = None) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    if not resolved.is_file():
        return False
    if resolved.suffix.lower() not in AUDIO_SUFFIXES:
        return False
    if extra_files:
        extra = {item.resolve() for item in extra_files}
        if resolved in extra:
            return True
    return any(is_under(resolved, root) for root in roots if root)


def send_audio(handler: BaseHTTPRequestHandler, path: Path) -> None:
    size = path.stat().st_size
    ctype = MIME.get(path.suffix.lower(), "application/octet-stream")
    rng = parse_range(handler.headers.get("Range"), size)
    if rng is None:
        start, end = 0, size - 1 if size else 0
        handler.send_response(200)
        length = size
    else:
        start, end = rng
        length = end - start + 1
        handler.send_response(206)
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.send_header("Content-Type", ctype)
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(max(0, length)))
    handler.send_header("Cache-Control", "private, max-age=120")
    handler.end_headers()
    if handler.command == "HEAD" or length <= 0:
        return
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(64 * 1024, remaining))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)


def decode_media_path(raw: str) -> Path:
    return Path(unquote(raw))
