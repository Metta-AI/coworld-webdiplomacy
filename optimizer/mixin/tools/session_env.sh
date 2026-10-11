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
# The directory is $WEBDIP_SESSION_HOME if set, otherwise a new temporary one.
# Works in bash and zsh. In an agent harness where shell state does not persist
# between commands, source it at the start of each command line instead.

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
export HOME="$WEBDIP_SESSION_HOME"

if [ -n "${1:-}" ]; then
  coworld player use "$1" >/dev/null || echo "session_env: 'coworld player use $1' failed" >&2
fi
softmax status 2>/dev/null | grep -E '^(user_email|subject_type|subject_id):' | sed 's/^/session_env: /'
unset _webdip_real_home
