"""Where the lab's own files are, for tests that borrow its tools, fixtures and templates."""

from pathlib import Path


def lab_source() -> Path:
    """`games/webdiplomacy/` in an installed optimizer, `mixin/` in the source repository."""
    root = Path(__file__).resolve().parents[2]
    installed = root / "games" / "webdiplomacy"
    return installed if installed.is_dir() else root / "mixin"
