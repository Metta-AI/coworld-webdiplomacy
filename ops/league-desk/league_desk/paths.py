from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
PROJECT = PACKAGE.parent


def runtime_dir() -> Path:
    return PROJECT / ".runtime"
