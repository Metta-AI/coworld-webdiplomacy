#!/usr/bin/env bash
# Create a standalone webDiplomacy optimizer outside this repository.
#
#   optimizer/install.sh <target-dir> [--harness claude-code|none]
#
# 1. Clone optimizer-seed at the commit pinned in seed.lock into <target-dir>,
#    on a fresh `main` branch. The seed remote is renamed to `seed` so the
#    user can add their own `origin`.
# 2. Copy optimizer/mixin/ to games/webdiplomacy/ and stamp its provenance
#    (source repo, commit, date) into MIXIN.md, as the seed's add_game.sh does.
#    add_game.sh itself cannot be used: it clones a repository root, and the
#    mixin is a subdirectory here.
# 3. Copy optimizer/ide/ to ide/, when it exists.
# 4. List the lab under "Active games" in the root WORKING_CONTEXT.md, record the seed
#    commit in SEED.md, replace the onboarding's "pick a game" beat (the game is already
#    installed), and put a webDiplomacy banner on README.md.
# 5. Run the seed's harness wiring (default: claude-code), plus a SessionStart hook
#    that warns when the coworld or softmax CLI is stale, plus the IDE's hooks, MCP
#    server entry and skill link, plus links to the lab's press-audit, opponent-profile
#    and matchup-writeup skills; record the wiring in WORKING_CONTEXT.md.
# 6. Commit the install as one unit in the new repository.
#
# Only files git would track are copied (tracked, or untracked and not
# ignored), so local caches and virtualenvs never leave this repository.
# Uncommitted source changes are copied too; the provenance says so.
set -euo pipefail

usage() {
  echo "usage: optimizer/install.sh <target-dir> [--harness claude-code|none]" >&2
  exit 2
}

TARGET=""
HARNESS="claude-code"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness) [[ $# -ge 2 ]] || usage; HARNESS="$2"; shift 2 ;;
    -h|--help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [[ -z "$TARGET" ]] || usage; TARGET="$1"; shift ;;
  esac
done
[[ -n "$TARGET" ]] || usage
case "$HARNESS" in
  claude-code|none) ;;
  *) echo "error: --harness must be claude-code or none" >&2; exit 2 ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
# shellcheck source=seed.lock
source "$HERE/seed.lock"

if [[ -e "$TARGET" ]] && [[ -n "$(ls -A "$TARGET")" ]]; then
  echo "error: $TARGET exists and is not empty" >&2
  exit 1
fi
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"
case "$TARGET/" in
  "$SOURCE_REPO"/*)
    rmdir "$TARGET"
    echo "error: install outside this repository; the optimizer is its own git repository" >&2
    exit 1 ;;
esac

SOURCE_URL="https://github.com/Metta-AI/coworld-webdiplomacy"
SOURCE_COMMIT="$(git -C "$SOURCE_REPO" rev-parse HEAD)"
if [[ -n "$(git -C "$SOURCE_REPO" status --porcelain -- optimizer)" ]]; then
  SOURCE_COMMIT="$SOURCE_COMMIT (plus uncommitted changes under optimizer/)"
fi
TODAY="$(TZ=America/Los_Angeles date +%Y-%m-%d)"

# Copy the files git would track under optimizer/<name>/ into <dest>.
copy_component() {
  local name="$1" dest="$2"
  mkdir -p "$dest"
  # Skip tracked files deleted from the working tree, so uncommitted deletions install cleanly.
  (cd "$HERE/$name" && git ls-files -z --cached --others --exclude-standard |
    while IFS= read -r -d '' file; do if [[ -e "$file" ]]; then printf '%s\0' "$file"; fi; done |
    xargs -0 tar -cf - --) |
    tar -xf - -C "$dest"
}

# --- 1. seed ---
echo "Cloning optimizer-seed at ${SEED_COMMIT:0:12} ..."
git clone --quiet "$SEED_URL" "$TARGET"
git -C "$TARGET" checkout --quiet -B main "$SEED_COMMIT"
git -C "$TARGET" remote rename origin seed

# --- 2. mixin ---
LAB="$TARGET/games/webdiplomacy"
copy_component mixin "$LAB"
# The lab's copy of the changelog is what tools/check_coworld.py compares with upstream.
cp "$SOURCE_REPO/CHANGELOG.md" "$LAB/CHANGELOG.md"
mkdir -p "$LAB/lessons_archive"
touch "$LAB/lessons_archive/.gitkeep"
sed -i.bak \
  -e "s|{{MIXIN_REPO_URL}}|$SOURCE_URL (\`optimizer/mixin/\`)|" \
  -e "s|{{COMMIT}}|$SOURCE_COMMIT|" \
  -e "s|{{DATE}}|$TODAY|" \
  "$LAB/MIXIN.md"
rm "$LAB/MIXIN.md.bak"
echo "Installed games/webdiplomacy/."

# --- 3. IDE ---
if [[ -d "$HERE/ide" ]]; then
  copy_component ide "$TARGET/ide"
  printf 'Copied from %s (`optimizer/ide/`) at %s on %s.\n' \
    "$SOURCE_URL" "$SOURCE_COMMIT" "$TODAY" > "$TARGET/ide/PROVENANCE.md"
  echo "Installed ide/."
else
  echo "No optimizer/ide/ yet; skipped the IDE."
fi

# --- 4. active games ---
WORKING_CONTEXT="$TARGET/WORKING_CONTEXT.md"
PLACEHOLDER='*(none installed — `tools/add_game.sh <mixin-repo-url>`)*'
ENTRY="- \`games/webdiplomacy/\`: webDiplomacy, installed $TODAY by coworld-webdiplomacy \`optimizer/install.sh\`. Every tool and skill of the lab is listed under \"Tool and skill index\" in \`games/webdiplomacy/AGENTS.md\`"
if grep -qF "$PLACEHOLDER" "$WORKING_CONTEXT"; then
  python3 - "$WORKING_CONTEXT" "$PLACEHOLDER" "$ENTRY" << 'PYEOF'
import pathlib, sys
path, placeholder, entry = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
path.write_text(path.read_text().replace(placeholder, entry, 1))
PYEOF
else
  echo "warning: WORKING_CONTEXT.md has no 'Active games' placeholder; add the lab by hand" >&2
fi

# --- 4-index. where the lab's tools and skills are listed ---
# The seed's AGENTS.md says to read a lab's AGENTS.md and MIXIN.md. Name the one section that
# lists every tool and skill, so an agent finds it from the root file.
python3 - "$TARGET/AGENTS.md" << 'PYEOF'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
anchor = "Core skills never contain game conditionals; mixins never modify core files.\n"
pointer = """**webDiplomacy lab:** every tool and every skill of the lab is listed once, with the
skills that use each tool, under "Tool and skill index" in `games/webdiplomacy/AGENTS.md`.
Look there before writing an analysis script.

"""
text = path.read_text()
if text.count(anchor) != 1:
    sys.exit(f"error: {path} has no 'Working in a game lab' closing line; update install.sh for this seed version")
path.write_text(text.replace(anchor, pointer + anchor, 1))
PYEOF

# --- 4a. seed provenance ---
# SEED.md says to diff against the recorded seed version, but the seed records only
# "0.1.0-dev". Record the commit: template copies squash history and drop the seed remote,
# so this row is the only place the planted seed commit survives.
python3 - "$TARGET/SEED.md" "$SEED_COMMIT" "$TODAY" << 'PYEOF'
import pathlib, sys
path, commit, today = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
anchor = "| **Upstream** | https://github.com/Metta-AI/optimizer-seed |\n"
unstamped = "| **Planted** | *(date stamped when a user clones and onboards)* |\n"
text = path.read_text()
if anchor not in text or unstamped not in text:
    sys.exit(f"error: {path} has no Upstream or Planted row; update install.sh for this seed version")
# The seed leaves "Planted" for onboarding to stamp, and nothing in onboarding does. This date
# is the day install.sh ran: for a copy made from the published template, the day the template
# was generated, so say that; the copy's own first commit dates the copy.
planted = (f"| **Planted** | {today}, by coworld-webdiplomacy `optimizer/install.sh` (a copy made from the "
           f"published template: see the date of this repository's first commit) |\n")
text = text.replace(unstamped, planted, 1)
path.write_text(text.replace(anchor, anchor + f"| **Commit** | {commit} |\n", 1))
PYEOF

# --- 4b. onboarding ---
# The seed's guided session has the user pick a game and run add_game.sh. This optimizer
# already has its game, so replace that beat; an agent following it would try to reinstall.
python3 - "$TARGET/docs/getting-started.md" << 'PYEOF'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
beat = """### 2 · Your game: webDiplomacy

This optimizer already has its game: the webDiplomacy lab is installed in
`games/webdiplomacy/` and listed under "Active games" in `WORKING_CONTEXT.md`.
**Do not run `tools/add_game.sh`** and do not offer other games.

Show the two webDiplomacy leagues with one plain line each: the main league plays
with press (negotiation), the Gunboat league without. **Work in the main (press)
league** unless the user asks for Gunboat: the reference policy builds in press
mode by default. Say early that a hosted press game runs about an hour and a batch
comes back 70 to 130 minutes after launch (the lab manual's "Run one A/B" has the
dated numbers), so the first evaluation will finish after a one-hour session;
launch it before the wrap and read it next time. The league IDs
and the standings commands are under "Leagues" in `games/webdiplomacy/docs/game.md`; plain
`coworld leagues` lists every public league, so don't scan it. Explain
that their optimizer already has a **lab** for this game: its rules, a reference
policy, and the tools and skills to measure it. The lab ships no knowledge of the
current field of opponents: that comes from their own games.
Then set the expectation for the next beat: **"before we change anything,
we're going to learn how this game is actually won."**

This optimizer also has a local web page, the IDE: offer to open it
(`ide/ide start --open`) when there is a replay, a result or a report worth
looking at together. `games/webdiplomacy/skills/ide/SKILL.md` has the commands.

"""
text = path.read_text()
pattern = re.compile(r"### 2 · Pick a game\n.*?tools/add_game\.sh <mixin-repo-url>.*?(?=### 3 · )", re.S)
text, count = pattern.subn(lambda _: beat, text)
if count != 1:
    sys.exit(f"error: {path} has no 'Pick a game' beat to replace; update install.sh for this seed version")
path.write_text(text)
PYEOF

# --- 4c. README banner ---
# The seed's README describes the bare seed; say what this copy is first.
README="$TARGET/README.md"
{
  cat << EOF
# webDiplomacy optimizer

An [optimizer-seed](https://github.com/Metta-AI/optimizer-seed) with the
webDiplomacy lab installed in \`games/webdiplomacy/\`. Generated by
\`optimizer/install.sh\` in [coworld-webdiplomacy](https://github.com/Metta-AI/coworld-webdiplomacy/tree/main/optimizer).
**Prototype.** The lab has game docs, the five skill bindings, analysis tools in
\`games/webdiplomacy/tools/\`, and a reference policy, \`games/webdiplomacy/players/castlereagh/\`
(a search core plus an LLM press layer for negotiation). \`ide/\` is a local web IDE for
replays, results and reports: start your coding agent in this folder and say
**"open the IDE"**.

Make your own **private** copy: it will collect your experiments and notes.
Use GitHub's "Use this template" button, or:

\`\`\`sh
gh repo create my-webdip-optimizer --template Metta-AI/webdip-optimizer --private --clone
\`\`\`

Install the Softmax CLIs with [uv](https://docs.astral.sh/uv/)
(\`uv tool install coworld\` and \`uv tool install softmax-cli\`), sign in with
\`softmax login\`, then start your coding agent in the clone and have it open
\`docs/getting-started.md\`. Cloud sessions keep nothing that is
not pushed, so commit and push before a session ends.

Everything below this line is the README of the seed this copy was made from. It is
background: its quick start (clone the seed, \`tools/add_game.sh\`) is already done here.

---

EOF
  cat "$README"
} > "$README.new"
mv "$README.new" "$README"

# --- 5. harness ---
if [[ "$HARNESS" == "claude-code" ]]; then
  "$TARGET/harness/claude-code/install.sh"
  # Claude Code loads CLAUDE.md, not AGENTS.md. The seed ships none, so the root rules (and
  # the pointer to the lab's tool and skill index) would not be in a session's context.
  if [[ -e "$TARGET/CLAUDE.md" ]]; then
    echo "error: the seed now ships CLAUDE.md; update install.sh for this seed version" >&2
    exit 1
  fi
  printf '@AGENTS.md\n' > "$TARGET/CLAUDE.md"
  echo "CLAUDE.md: loads AGENTS.md at the root; games/webdiplomacy/CLAUDE.md loads the lab manual."
  # Add the lab's CLI version check to SessionStart. It prints only when the coworld or
  # softmax uv tool is missing or older than PyPI's latest, and never fails the session.
  python3 - "$TARGET/.claude/settings.json" << 'PYEOF'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
settings = json.loads(path.read_text())
# "startup" only: a resumed or compacted session has already had its check.
settings["hooks"]["SessionStart"].append({"matcher": "startup", "hooks": [{
    "type": "command",
    "command": 'python3 "$CLAUDE_PROJECT_DIR/games/webdiplomacy/tools/check_clis.py"',
    "timeout": 20,
    "statusMessage": "Checking coworld and softmax CLI versions",
}, {
    # Prints only when the Coworld or the optimizer template has changed since the lab's
    # copy of the changelog.
    "type": "command",
    "command": 'python3 "$CLAUDE_PROJECT_DIR/games/webdiplomacy/tools/check_coworld.py"',
    "timeout": 40,
    "statusMessage": "Checking the webDiplomacy Coworld version and changelog",
}]})
path.write_text(json.dumps(settings, indent=2) + "\n")
PYEOF
  echo "Hooks: added the webDiplomacy CLI and Coworld version checks to SessionStart."
  # Wire the IDE into the session: hooks that hand the user's browser messages to the
  # running agent (the entries come from the IDE itself, ide/webdip_ide/hooks.py), an MCP
  # server with the same actions, and the IDE skill where Claude Code discovers skills.
  if [[ -d "$TARGET/ide" ]]; then
    python3 - "$TARGET" << 'PYEOF'
import json, pathlib, sys
target = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(target / "ide"))
from webdip_ide.hooks import hook_settings

path = target / ".claude" / "settings.json"
settings = json.loads(path.read_text())
for event, entries in hook_settings().items():
    settings["hooks"].setdefault(event, []).extend(entries)
path.write_text(json.dumps(settings, indent=2) + "\n")

mcp = target / ".mcp.json"
config = json.loads(mcp.read_text()) if mcp.exists() else {}
config.setdefault("mcpServers", {})["webdip-ide"] = {
    "type": "stdio",
    "command": "python3",
    "args": ["${CLAUDE_PROJECT_DIR:-.}/ide/ide", "mcp"],
}
mcp.write_text(json.dumps(config, indent=2) + "\n")

skill = target / "games" / "webdiplomacy" / "skills" / "ide" / "SKILL.md"
if not skill.exists():
    sys.exit(f"error: {skill} is missing; the IDE hooks point the agent at it")
(target / ".claude" / "skills" / "webdiplomacy-ide").symlink_to("../../games/webdiplomacy/skills/ide")
PYEOF
    echo "IDE: added hooks to .claude/settings.json, the webdip-ide server to .mcp.json, and the skill link."
  fi
  # The seed links only its own skills. Link the lab's extra skills too (the ones that are
  # not bindings of a core skill), so Claude Code lists them by name.
  for skill in press-audit opponent-profile matchup-writeup; do
    [[ -f "$LAB/skills/$skill/SKILL.md" ]] || { echo "error: lab skill $skill is missing" >&2; exit 1; }
    ln -s "../../games/webdiplomacy/skills/$skill" "$TARGET/.claude/skills/webdiplomacy-$skill"
  done
  echo "Skills: linked the lab's press-audit, opponent-profile and matchup-writeup skills."
  # Record the wiring, as harness/README.md's self-wiring step requires, so the first
  # session can tell from disk that Claude Code is already wired.
  python3 - "$WORKING_CONTEXT" "$TODAY" << 'PYEOF'
import pathlib, sys
path, today = pathlib.Path(sys.argv[1]), sys.argv[2]
placeholder = """*(recorded by the self-wiring step during onboarding: which runtime, which
hooks were installed, date)*"""
record = f"""- Claude Code: wired by `optimizer/install.sh` on {today}. `CLAUDE.md` loads `AGENTS.md`
  (and `games/webdiplomacy/CLAUDE.md` the lab manual). Skills are linked in
  `.claude/skills/`; `.claude/settings.json` runs `rotate_lessons.sh` and the lab's
  `check_clis.py` and `check_coworld.py` at SessionStart, and both stop nudges at Stop. The IDE (`ide/`) adds
  `ide/ide hook <event>` at SessionStart, UserPromptSubmit, PostToolUse, Stop and SessionEnd
  (they hand the user's browser messages to the session and tell the page when it ends), a
  background waiter (`ide/ide hook Rewake`, marked `asyncRewake`) at the first four and at
  FileChanged (the IDE's chat file) that wakes an idle or interrupted session, the
  `webdip-ide` server in `.mcp.json`, and the `webdiplomacy-ide` skill link. The lab's `press-audit`, `opponent-profile` and
  `matchup-writeup` skills are linked in `.claude/skills/` too. Nothing to do.
- Any other runtime: not wired. Do the self-wiring step in `harness/README.md`
  and record it here."""
text = path.read_text()
if placeholder not in text:
    sys.exit(f"error: {path} has no 'Harness wiring' placeholder; update install.sh for this seed version")
path.write_text(text.replace(placeholder, record, 1))
PYEOF
fi

# --- 6. commit ---
git -C "$TARGET" add -A
git -C "$TARGET" commit --quiet -m "Install webDiplomacy lab from coworld-webdiplomacy

Seed: $SEED_URL @ $SEED_COMMIT
Source: $SOURCE_URL @ $SOURCE_COMMIT"

echo
echo "Optimizer ready at $TARGET (seed ${SEED_COMMIT:0:12}, source ${SOURCE_COMMIT:0:12})."
echo "Next: cd $TARGET, sign in with 'softmax login', start your coding agent there,"
echo "and have it open docs/getting-started.md."
