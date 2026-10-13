"""Repository-local reuse seam; shared parsers remain owned by the optimizer tools."""
import sys

from .paths import PROJECT

TOOLS = PROJECT.parents[1] / "optimizer" / "mixin" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from fetch_league import episode_dir, suffix_for  # noqa: E402,F401
from matchups import stat  # noqa: E402,F401
from press_audit import ABBREVIATION, movement_phases, province  # noqa: E402,F401
from webdip_episodes import POWERS, episode_taint, load_episode, read_json_file  # noqa: E402,F401
