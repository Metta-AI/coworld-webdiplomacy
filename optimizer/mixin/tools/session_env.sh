# Source this file; do not run it.
#
#   source games/webdiplomacy/tools/session_env.sh [<player id>]
#
# Sets up the private credentials directory this lab asks every session to use
# (docs/platform.md, "Setup"), so another session switching players cannot change
# this one's identity:
#   - copies ~/.softmax/credentials.yaml into a private directory,
#   - points HOME at it,
#   - points DOCKER_CONFIG at the real ~/.docker (without it, builds under the
#     private HOME fall back to the legacy builder and fail with "content digest
#     not found"),
#   - with a player id, runs `coworld player use <id>`,
#   - prints which identity commands will now act as.
#   - wraps `git` and `gh` so they run with the real HOME (credentials, user.name), so
#     `git push` still works in this shell,
# The directory is $WEBDIP_SESSION_HOME if set, otherwise a new temporary one.
# Works in bash and zsh.
#
# In an agent harness, shell state does not persist between commands. Source this at the
# start of EVERY command line, and set WEBDIP_SESSION_HOME to one fixed directory first:
#
#   export WEBDIP_SESSION_HOME=<a scratch directory for this session>
#   source games/webdiplomacy/tools/session_env.sh            # no player id after the first time
#
# Without a fixed WEBDIP_SESSION_HOME each command gets a NEW private directory, copied
# fresh from the shared file, and so acts as whichever player the shared file names.

_webdip_real_home="${WEBDIP_REAL_HOME:-$HOME}"
if [ ! -f "$_webdip_real_home/.softmax/credentials.yaml" ]; then
  echo "session_env: no $_webdip_real_home/.softmax/credentials.yaml; run 'softmax login' first" >&2
  return 1 2>/dev/null || exit 1
fi

export WEBDIP_REAL_HOME="$_webdip_real_home"
export WEBDIP_SESSION_HOME="${WEBDIP_SESSION_HOME:-$(mktemp -d "${TMPDIR:-/tmp}/webdip-session.XXXXXX")}"
mkdir -p "$WEBDIP_SESSION_HOME/.softmax"
# Copy only when the private copy does not exist yet, so a re-source keeps this
# session's active player instead of resetting it to the shared file's.
if [ ! -f "$WEBDIP_SESSION_HOME/.softmax/credentials.yaml" ]; then
  cp "$WEBDIP_REAL_HOME/.softmax/credentials.yaml" "$WEBDIP_SESSION_HOME/.softmax/"
fi
export DOCKER_CONFIG="${DOCKER_CONFIG:-$WEBDIP_REAL_HOME/.docker}"
# git and gh need the REAL home: the credential helper is in the real ~/.gitconfig, and on
# macOS gh keeps its token in the login keychain, which is found through HOME (pointing
# GIT_CONFIG_GLOBAL / GH_CONFIG_DIR at the real files is not enough: tried 2026-10-10).
# Without this, `git push` under the private HOME fails with "could not read Username".
git() { HOME="$WEBDIP_REAL_HOME" command git "$@"; }
gh() { HOME="$WEBDIP_REAL_HOME" command gh "$@"; }
export HOME="$WEBDIP_SESSION_HOME"

if [ -n "${1:-}" ]; then
  coworld player use "$1" >/dev/null || echo "session_env: 'coworld player use $1' failed" >&2
fi
softmax status 2>/dev/null | grep -E '^(user_email|subject_type|subject_id):' | sed 's/^/session_env: /'
unset _webdip_real_home
