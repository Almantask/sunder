"""PyInstaller entry for a bundled Sunder desktop app."""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from sunder.desktop.runtime import prepare_frozen_env
    from sunder.desktop import launch

    prepare_frozen_env()
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
