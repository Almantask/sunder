"""Persisted desktop-app settings (paths and classify options)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sunder.classify import DEFAULT_MIN_MARGIN, DEFAULT_THRESHOLD

DEFAULTS: dict[str, Any] = {
    "library": "",
    "cache": ".sunder_cache",
    "categories": "categories.yaml",
    "results": "results.csv",
    "report": "report.html",
    "organize_dest": "organized",
    "device": "auto",
    "recursive": True,
    "limit": None,
    "force": False,
    "save_file": True,
    "embed_track": False,
    "threshold": DEFAULT_THRESHOLD,
    "min_margin": DEFAULT_MIN_MARGIN,
}


def settings_path() -> Path:
    return Path.cwd() / ".sunder_cache" / "desktop.json"


def resolve_path(value: str | Path | None) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else Path()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def load_settings() -> dict[str, Any]:
    data = dict(DEFAULTS)
    path = settings_path()
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if key in DEFAULTS:
                    data[key] = value
    return _clean(data)


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    data = load_settings()
    for key, value in patch.items():
        if key in DEFAULTS:
            data[key] = value
    data = _clean(data)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    data["recursive"] = bool(data.get("recursive", True))
    data["force"] = bool(data.get("force", False))
    data["save_file"] = bool(data.get("save_file", True))
    data["embed_track"] = bool(data.get("embed_track", False))
    limit = data.get("limit")
    if limit in ("", None):
        data["limit"] = None
    else:
        try:
            data["limit"] = max(0, int(limit))
        except (TypeError, ValueError):
            data["limit"] = None
    try:
        data["threshold"] = float(data.get("threshold", DEFAULT_THRESHOLD))
        data["min_margin"] = float(data.get("min_margin", DEFAULT_MIN_MARGIN))
    except (TypeError, ValueError):
        data["threshold"] = DEFAULT_THRESHOLD
        data["min_margin"] = DEFAULT_MIN_MARGIN
    device = str(data.get("device") or "auto").strip().lower()
    data["device"] = device if device in {"auto", "cpu", "cuda", "mps"} else "auto"
    for key in ("library", "cache", "categories", "results", "report", "organize_dest"):
        data[key] = str(data.get(key) or DEFAULTS[key])
    return data


def device_arg(settings: dict[str, Any]) -> str | None:
    device = str(settings.get("device") or "auto")
    return None if device in {"", "auto"} else device
