from __future__ import annotations

import os
from pathlib import Path


def tracked_root() -> Path:
    configured = os.environ.get("OOPSIEFS_TRACK_ROOT") or os.environ.get("OOPSIEFS_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path("/").resolve()


def watched_roots() -> list[Path]:
    configured = os.environ.get("OOPSIEFS_WATCH_ROOTS")
    if configured:
        return [Path(item).expanduser().resolve() for item in configured.split(":") if item]
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Pictures",
        home / "Videos",
        home / "Music",
        home / "Academics",
    ]
    return [path for path in candidates if path.exists()]


def store_root() -> Path:
    configured = os.environ.get("OOPSIEFS_STORE")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".local/share/oopsiefs").resolve()


def scan_window_seconds() -> int:
    configured = os.environ.get("OOPSIEFS_SCAN_WINDOW_SECONDS")
    if configured:
        return max(1, int(configured))
    minutes = os.environ.get("OOPSIEFS_SCAN_WINDOW_MINUTES")
    if minutes:
        return max(1, int(float(minutes) * 60))
    return 5 * 60


def workspace_root() -> Path:
    return tracked_root()
