"""Paths and stdio helpers for frozen (PyInstaller) and normal runs."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


class _NullStream:
    def write(self, data) -> int:
        return len(data) if data is not None else 0

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_home() -> Path:
    """Working folder for cache, YAML, and results."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def bundled_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def static_dir() -> Path:
    if is_frozen():
        return bundled_root() / "sunder" / "desktop" / "static"
    return Path(__file__).resolve().parent / "static"


def icon_path() -> Path:
    return static_dir() / "favicon.ico"


def ensure_stdio() -> None:
    """Windowed exes often have stdout/stderr set to None."""
    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _NullStream()
    if getattr(sys, "__stdout__", None) is None:
        sys.__stdout__ = sys.stdout
    if getattr(sys, "__stderr__", None) is None:
        sys.__stderr__ = sys.stderr


def seed_defaults(home: Path) -> None:
    dest = home / "categories.yaml"
    if dest.is_file():
        return
    src = bundled_root() / "categories.yaml"
    if src.is_file():
        shutil.copy2(src, dest)


def prepare_frozen_env() -> Path:
    ensure_stdio()
    home = app_home()
    os.chdir(home)
    seed_defaults(home)
    return home
