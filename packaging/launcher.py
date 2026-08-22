"""Thin Windows launcher. Never import sunder — PyInstaller would pull torch."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

CREATE_NEW_CONSOLE = 0x00000010


def message_box(text: str, caption: str = "Sunder") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, caption, 0x10)
    except Exception:
        try:
            sys.stderr.write(text + "\n")
        except Exception:
            pass


def start_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_project_root(start: Path | None = None) -> Path | None:
    here = start or start_dir()
    for folder in [here, *here.parents]:
        package = folder / "sunder" / "__init__.py"
        venv_py = folder / ".venv" / "Scripts" / "python.exe"
        if package.is_file() and venv_py.is_file():
            return folder
    return None


def venv_python(root: Path, *, gui: bool) -> Path | None:
    scripts = root / ".venv" / "Scripts"
    if gui:
        pythonw = scripts / "pythonw.exe"
        if pythonw.is_file():
            return pythonw
    python = scripts / "python.exe"
    return python if python.is_file() else None


def run_venv(root: Path, extra: list[str]) -> int:
    gui = not extra
    python = venv_python(root, gui=gui)
    if python is None:
        message_box(
            "No virtualenv found.\n\n"
            "From the repo root run:\n"
            "  py -3.9 -m venv .venv\n"
            "  .\\.venv\\Scripts\\pip install -r requirements.txt"
        )
        return 1
    args = [str(python), "-m", "sunder"]
    args.extend(extra if extra else ["app"])
    flags = 0 if gui else CREATE_NEW_CONSOLE
    try:
        completed = subprocess.run(
            args,
            cwd=str(root),
            env=os.environ.copy(),
            creationflags=flags,
        )
    except OSError as exc:
        message_box(f"Could not start Sunder:\n{exc}")
        return 1
    code = int(completed.returncode or 0)
    if code != 0:
        message_box(f"Sunder exited with code {code}.")
    return code


def main(argv: list[str] | None = None) -> int:
    extra = list(sys.argv[1:] if argv is None else argv)
    root = find_project_root()
    if root is None:
        message_box(
            "Sunder could not find this project.\n\n"
            "Keep Sunder.exe in the repo folder (next to .venv and the sunder package)."
        )
        return 1
    return run_venv(root, extra)


if __name__ == "__main__":
    raise SystemExit(main())
