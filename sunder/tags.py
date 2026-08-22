"""Write the assigned category into audio-file metadata (ID3 / Vorbis)."""

from __future__ import annotations

from pathlib import Path

from sunder.classify import Classification
from sunder.embeddings import EmbeddingCache
from sunder.progress import check_cancel, emit as emit_progress

SUNDER_CATEGORY_DESC = "SUNDER_CATEGORY"
SUNDER_CONFIDENCE_DESC = "SUNDER_CONFIDENCE"
SUNDER_PROMPT_DESC = "SUNDER_PROMPT"


def write_category_tags(
    path: str | Path,
    category: str,
    *,
    confidence: float | None = None,
    matched_prompt: str | None = None,
) -> None:
    """Stamp genre plus Sunder-specific frames. Audio samples are unchanged."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        _write_id3(path, category, confidence, matched_prompt, wrapper=None)
        return
    if suffix == ".wav":
        _write_wav(path, category, confidence, matched_prompt)
        return
    if suffix == ".flac":
        _write_flac(path, category, confidence, matched_prompt)
        return
    if suffix in {".ogg", ".oga"}:
        _write_ogg(path, category, confidence, matched_prompt)
        return
    raise ValueError(f"No tag writer for {suffix}: {path}")


def read_category_tags(path: str | Path) -> dict[str, str]:
    """Return genre / SUNDER_* values for tests and inspection."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".mp3", ".wav"}:
        return _read_id3(path)
    if suffix == ".flac":
        from mutagen.flac import FLAC

        return _from_vorbis(FLAC(str(path)))
    if suffix in {".ogg", ".oga"}:
        from mutagen.oggvorbis import OggVorbis

        return _from_vorbis(OggVorbis(str(path)))
    return {}


def write_row_tags(row: Classification) -> None:
    write_category_tags(
        row.path,
        row.category,
        confidence=row.confidence,
        matched_prompt=row.matched_prompt,
    )


def tag_rows(
    rows: list[Classification],
    cache: EmbeddingCache | None = None,
    progress=None,
    should_cancel=None,
) -> tuple[int, int]:
    """Write tags for each row. Refresh embedding-cache stats so files are not re-embedded."""
    written = 0
    errors = 0
    total = len(rows)
    for index, row in enumerate(rows, 1):
        check_cancel(should_cancel)
        emit_progress(
            progress,
            stage="tag",
            message=row.path.name,
            current=index,
            total=total,
            path=str(row.path),
        )
        if not row.path.is_file():
            errors += 1
            print(f"MISSING {row.path}", flush=True)
            continue
        try:
            write_row_tags(row)
            if cache is not None:
                cache.refresh_stat(row.path)
            written += 1
        except Exception as exc:
            errors += 1
            print(f"TAG FAIL {row.path.name}: {exc}", flush=True)
    if cache is not None:
        cache.save()
    return written, errors


def _write_id3(
    path: Path,
    category: str,
    confidence: float | None,
    matched_prompt: str | None,
    *,
    wrapper,
) -> None:
    from mutagen.id3 import COMM, ID3, ID3NoHeaderError, TCON, TXXX

    if wrapper is None:
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
    else:
        if wrapper.tags is None:
            wrapper.add_tags()
        tags = wrapper.tags

    tags.delall("TCON")
    tags.add(TCON(encoding=3, text=[category]))
    _set_txxx(tags, TXXX, SUNDER_CATEGORY_DESC, category)
    if confidence is not None:
        _set_txxx(tags, TXXX, SUNDER_CONFIDENCE_DESC, f"{confidence:.6f}")
    if matched_prompt:
        _set_txxx(tags, TXXX, SUNDER_PROMPT_DESC, matched_prompt)
    tags.delall("COMM:Sunder:eng")
    tags.add(COMM(encoding=3, lang="eng", desc="Sunder", text=[f"category={category}"]))

    if wrapper is None:
        tags.save(str(path), v2_version=3)
    else:
        wrapper.save()


def _set_txxx(tags, txxx_cls, desc: str, value: str) -> None:
    key = f"TXXX:{desc}"
    tags.delall(key)
    tags.add(txxx_cls(encoding=3, desc=desc, text=[value]))


def _write_wav(path: Path, category: str, confidence: float | None, matched_prompt: str | None) -> None:
    from mutagen.wave import WAVE

    audio = WAVE(str(path))
    _write_id3(path, category, confidence, matched_prompt, wrapper=audio)


def _write_flac(path: Path, category: str, confidence: float | None, matched_prompt: str | None) -> None:
    from mutagen.flac import FLAC

    audio = FLAC(str(path))
    _set_vorbis(audio, category, confidence, matched_prompt)
    audio.save()


def _write_ogg(path: Path, category: str, confidence: float | None, matched_prompt: str | None) -> None:
    from mutagen.oggvorbis import OggVorbis

    audio = OggVorbis(str(path))
    _set_vorbis(audio, category, confidence, matched_prompt)
    audio.save()


def _set_vorbis(audio, category: str, confidence: float | None, matched_prompt: str | None) -> None:
    audio["genre"] = [category]
    audio["sunder_category"] = [category]
    if confidence is not None:
        audio["sunder_confidence"] = [f"{confidence:.6f}"]
    if matched_prompt:
        audio["sunder_prompt"] = [matched_prompt]


def _read_id3(path: Path) -> dict[str, str]:
    from mutagen.id3 import ID3, ID3NoHeaderError

    tags = None
    if path.suffix.lower() == ".wav":
        from mutagen.wave import WAVE

        audio = WAVE(str(path))
        tags = audio.tags
    else:
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = None
    if tags is None:
        return {}
    out: dict[str, str] = {}
    if "TCON" in tags:
        out["genre"] = str(tags["TCON"].text[0])
    for desc, key in (
        (SUNDER_CATEGORY_DESC, "sunder_category"),
        (SUNDER_CONFIDENCE_DESC, "sunder_confidence"),
        (SUNDER_PROMPT_DESC, "sunder_prompt"),
    ):
        frame = tags.get(f"TXXX:{desc}")
        if frame is not None and frame.text:
            out[key] = str(frame.text[0])
    return out


def _from_vorbis(audio) -> dict[str, str]:
    def first(key: str) -> str:
        values = audio.get(key) or []
        return str(values[0]) if values else ""

    return {
        "genre": first("genre"),
        "sunder_category": first("sunder_category"),
        "sunder_confidence": first("sunder_confidence"),
        "sunder_prompt": first("sunder_prompt"),
    }
