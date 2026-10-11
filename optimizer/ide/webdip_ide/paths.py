"""Where the IDE finds the lab and keeps its own files.

The IDE is installed at `<optimizer root>/ide/` next to `games/webdiplomacy/` (the lab).
In the source repository it sits at `optimizer/ide/` next to `optimizer/mixin/`, which
has the same layout as an installed lab. `WEBDIP_LAB` overrides both.

Standard library only: hooks and the agent's CLI commands import this without `uv`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

IDE_DIR = Path(__file__).resolve().parent.parent


def lab_dir() -> Path:
    override = os.environ.get("WEBDIP_LAB")
    if override:
        return Path(override).resolve()
    installed = IDE_DIR.parent / "games" / "webdiplomacy"
    return installed if installed.is_dir() else IDE_DIR.parent / "mixin"


def state_dir() -> Path:
    """Chat, agent cards and server state. Under `.runtime/`, so git ignores it."""
    path = lab_dir() / ".runtime" / "ide"
    path.mkdir(parents=True, exist_ok=True)
    return path


def annotations_dir() -> Path:
    """Replay annotations, one JSON file per episode. Tracked: they are lab knowledge."""
    path = lab_dir() / "annotations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir() -> Path:
    """Write-ups produced by skills (`reports/matchups/`, `reports/opponents/`). Tracked."""
    return lab_dir() / "reports"


def artifacts_dir() -> Path:
    """Fetched episodes: `.runtime/artifacts/<batch>/<episode>/`."""
    return lab_dir() / ".runtime" / "artifacts"


def press_dir() -> Path:
    """Press audits: `.runtime/press/<episode id>/` holds `ledger.json`, `annotate.json`, `claims.json`,
    `audit.json` and `audit.html` (written by the lab's `tools/press_audit.py`; the IDE reads `audit.json`)."""
    return lab_dir() / ".runtime" / "press"


def use_lab_tools() -> None:
    """Make the lab's `tools/` importable (`import webdip_episodes`, `import matchups`)."""
    tools = str(lab_dir() / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
