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
#    that warns when the coworld or softmax CLI is stale; record the wiring in
#    WORKING_CONTEXT.md.
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
ENTRY="- \`games/webdiplomacy/\`: webDiplomacy, installed $TODAY by coworld-webdiplomacy \`optimizer/install.sh\`"
if grep -qF "$PLACEHOLDER" "$WORKING_CONTEXT"; then
  python3 - "$WORKING_CONTEXT" "$PLACEHOLDER" "$ENTRY" << 'PYEOF'
import pathlib, sys
path, placeholder, entry = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
path.write_text(path.read_text().replace(placeholder, entry, 1))
PYEOF
else
  echo "warning: WORKING_CONTEXT.md has no 'Active games' placeholder; add the lab by hand" >&2
fi

# --- 4a. seed provenance ---
# SEED.md says to diff against the recorded seed version, but the seed records only
# "0.1.0-dev". Record the commit: template copies squash history and drop the seed remote,
# so this row is the only place the planted seed commit survives.
python3 - "$TARGET/SEED.md" "$SEED_COMMIT" << 'PYEOF'
import pathlib, sys
path, commit = pathlib.Path(sys.argv[1]), sys.argv[2]
anchor = "| **Upstream** | https://github.com/Metta-AI/optimizer-seed |\n"
text = path.read_text()
if anchor not in text:
    sys.exit(f"error: {path} has no Upstream row; update install.sh for this seed version")
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

Show the webDiplomacy leagues (`coworld leagues`) with one plain line each: the
main league plays with press (negotiation), the Gunboat league without. Explain
that their optimizer already has a **lab** for this game: its rules, its
community's earned knowledge, a reference policy, and the tools to measure it.
Then set the expectation for the next beat: **"before we change anything,
we're going to learn how this game is actually won."**

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
(Kissinger search, with an optional press layer that is off by default).

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

---

EOF
  cat "$README"
} > "$README.new"
mv "$README.new" "$README"

# --- 5. harness ---
if [[ "$HARNESS" == "claude-code" ]]; then
  "$TARGET/harness/claude-code/install.sh"
  # Add the lab's CLI version check to SessionStart. It prints only when the coworld or
  # softmax uv tool is missing or older than PyPI's latest, and never fails the session.
  python3 - "$TARGET/.claude/settings.json" << 'PYEOF'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
settings = json.loads(path.read_text())
settings["hooks"]["SessionStart"].append({"hooks": [{
    "type": "command",
    "command": 'python3 "$CLAUDE_PROJECT_DIR/games/webdiplomacy/tools/check_clis.py"',
    "timeout": 20,
    "statusMessage": "Checking coworld and softmax CLI versions",
}]})
path.write_text(json.dumps(settings, indent=2) + "\n")
PYEOF
  echo "Hooks: added the webDiplomacy CLI version check to SessionStart."
  # Record the wiring, as harness/README.md's self-wiring step requires, so the first
  # session can tell from disk that Claude Code is already wired.
  python3 - "$WORKING_CONTEXT" "$TODAY" << 'PYEOF'
import pathlib, sys
path, today = pathlib.Path(sys.argv[1]), sys.argv[2]
placeholder = """*(recorded by the self-wiring step during onboarding: which runtime, which
hooks were installed, date)*"""
record = f"""- Claude Code: wired by `optimizer/install.sh` on {today}. Skills are linked in
  `.claude/skills/`; `.claude/settings.json` runs `rotate_lessons.sh` and the lab's
  `check_clis.py` at SessionStart, and both stop nudges at Stop. Nothing to do.
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
