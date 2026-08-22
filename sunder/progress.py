"""Cancellation and progress callbacks for long-running jobs."""

from __future__ import annotations

from typing import Any, Callable, Optional

ProgressFn = Optional[Callable[[dict[str, Any]], None]]
CancelFn = Optional[Callable[[], bool]]


class Cancelled(RuntimeError):
    """Raised when a desktop (or other) job is cancelled mid-run."""


def check_cancel(should_cancel: CancelFn) -> None:
    if should_cancel is not None and should_cancel():
        raise Cancelled("Cancelled.")


def emit(progress: ProgressFn, **payload: Any) -> None:
    if progress is not None:
        progress(payload)
