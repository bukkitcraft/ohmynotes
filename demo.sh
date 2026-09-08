#!/usr/bin/env bash
#
# oh-my-notes (omn) — feature demo.
#
# Runs through the core feature set against a throwaway OMN_DATA_DIR so the
# demo never touches real notes. Requires: bash, python3, and the tool
# available as `omn` (i.e. run ./install.sh first, or set OMN_BIN to the
# repo's ./omn launcher).
#
# Usage:  ./demo.sh
set -euo pipefail

# Resolve the repo dir (works from a symlink too).
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
REPO_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"

BIN="${OMN_BIN:-$REPO_DIR/omn}"
DEMO_DATA="$(mktemp -d)/omn-data"
export OMN_DATA_DIR="$DEMO_DATA"
export NO_COLOR=1
export VISUAL="${VISUAL:-vi}"

say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
step() { printf '\n\033[1;33m$ %s\033[0m\n' "$*"; "$@"; }

trap 'rm -rf "${DEMO_DATA%/*}"' EXIT

say "oh-my-notes demo — data dir: $DEMO_DATA"

step "$BIN" --version

say "Create notes (inline + tag)"
step "$BIN" add "Intro to omn" -m "Notes that live entirely in your terminal." -t meta
step "$BIN" add "SSH key rotation" -m "Rotate every 90 days; store passphrase in the vault." -t ops
step "$BIN" add "Postgres tuning" -m "shared_buffers = 25% RAM; effective_cache_size = 75%." -t db

say "List all notes"
step "$BIN" list

say "View a single note"
step "$BIN" show ssh-key-rotation

say "Full-text search"
step "$BIN" search "postgres"

say "Tag index"
step "$BIN" tags

say "Pick from a tag's notes (show <tag> when no slug matches)"
step "$BIN" show ops <<'EOF'
1
EOF

say "Edit a note inline"
step "$BIN" edit postgres-tuning -m "shared_buffers = 25% RAM; work_mem bumped for the import job."

say "Search with a tag filter"
step "$BIN" search "shared_buffers" -t db

say "Delete a note (forced)"
step "$BIN" rm ssh-key-rotation --force

say "Final state"
step "$BIN" list

say "Demo complete."