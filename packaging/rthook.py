"""Runtime hook for the standalone Windows bundle."""

from __future__ import annotations

import multiprocessing
import os
import sys


def _null():
    class _N:
        def write(self, data):
            return 0

        def flush(self):
            return None

        def isatty(self):
            return False

    return _N()


multiprocessing.freeze_support()

if sys.stdout is None:
    sys.stdout = _null()
if sys.stderr is None:
    sys.stderr = _null()
if getattr(sys, "__stdout__", None) is None:
    sys.__stdout__ = sys.stdout
if getattr(sys, "__stderr__", None) is None:
    sys.__stderr__ = sys.stderr

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
