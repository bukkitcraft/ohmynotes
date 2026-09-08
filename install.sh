#!/bin/sh
#
# oh-my-notes (omn) — one-command installer.
#
# POSIX sh, so it runs on every common distro and macOS without bashisms.
# Copies the project into ~/.local/share/omn/lib (so the tool keeps working
# even after the download folder is deleted) and symlinks the `omn` and
# `ohmynotes` aliases into ~/.local/bin. On interactive terminals it can also
# add ~/.local/bin to your shell's PATH for you.
#
# Usage:  sh install.sh     (or:  ./install.sh)
# Uninstall: rm -rf ~/.local/bin/omn ~/.local/bin/ohmynotes ~/.local/share/omn
set -eu

SOURCE="$0"
# Resolve symlinks so install.sh works however it's invoked.
while [ -h "$SOURCE" ]; do
  DIR=$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)
  SOURCE=$(readlink "$SOURCE")
  case "$SOURCE" in
    /*) ;;
    *) SOURCE="$DIR/$SOURCE" ;;
  esac
done
PROJECT_DIR=$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)

BIN_DIR="${OMN_BIN_DIR:-$HOME/.local/bin}"
DATA_ROOT="${OMN_DATA_DIR:-$HOME/.local/share/omn}"
LIB_DIR="$DATA_ROOT/lib"

# Pre-flight: the tool needs python3 on PATH.
if ! command -v python3 >/dev/null 2>&1; then
  echo "oh-my-notes: python3 not found on PATH (required)" >&2
  exit 1
fi

# ── copy the project into a stable location ────────────────────────────────
mkdir -p "$BIN_DIR" "$LIB_DIR"
cp -R "$PROJECT_DIR/src" "$PROJECT_DIR/omn" "$LIB_DIR/"
cp "$PROJECT_DIR/bannerlong.txt" "$PROJECT_DIR/bannershort.txt" "$LIB_DIR/" 2>/dev/null || true
chmod +x "$LIB_DIR/omn"

# Install as `omn` and `ohmynotes` (both aliases point to the same launcher).
ln -sf "$LIB_DIR/omn" "$BIN_DIR/omn"
ln -sf "$LIB_DIR/omn" "$BIN_DIR/ohmynotes"

echo "Installed oh-my-notes."
echo "  launcher : $BIN_DIR/omn      -> $LIB_DIR/omn"
echo "  alias    : $BIN_DIR/ohmynotes -> $LIB_DIR/omn"
echo

# Make sure the data directory is created on first real use, and verify.
if "$BIN_DIR/omn" --version >/dev/null 2>&1 && "$BIN_DIR/ohmynotes" --version >/dev/null 2>&1; then
  ver=$("$BIN_DIR/omn" --version)
  echo "Verified: $ver (omn + ohmynotes)"
  echo
else
  echo "Warning: could not verify the install — check your PATH." >&2
  exit 1
fi

# ── PATH setup ─────────────────────────────────────────────────────────────
case ":$PATH:" in
  *":$BIN_DIR:"*) in_path=1 ;;
  *) in_path=0 ;;
esac
if [ "$in_path" = 0 ] && [ "${OMN_AUTO_PATH:-1}" != 0 ]; then
  if [ -t 0 ]; then
    printf '%s' "Add '$BIN_DIR' to your PATH? [Y/n]: "
    read -r answer || true
    case "$answer" in
      ""|y|Y|yes|YES) answer="y" ;;
      *) answer="n" ;;
    esac
  else
    # Non-interactive: never touch dotfiles automatically.
    answer="n"
  fi
  if [ "$answer" = "y" ]; then
    path_line='export PATH="$HOME/.local/bin:$PATH"'
    added=0
    for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
      [ -f "$rc" ] || continue
      if ! grep -Fqx "$path_line" "$rc" 2>/dev/null; then
        printf '\n%s\n' "$path_line" >>"$rc"
        echo "  PATH updated in $rc"
        added=1
      else
        added=1
      fi
    done
    if [ "$added" = 0 ]; then
      printf '\n%s\n' "$path_line" >>"$HOME/.profile"
      echo "  PATH updated in $HOME/.profile"
    fi
  fi
fi
if [ "$in_path" = 0 ]; then
  echo "If '$BIN_DIR' isn't on your PATH yet, add:"
  echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo
fi

# ── presentation preferences (banner style + gradient) ────────────────────
# Interactive when stdin is a TTY; otherwise use $OMN_BANNER / $OMN_GRADIENT
# env vars, falling back to sane defaults. Can be changed later with:
#     omn config -b long|short
#     omn config -g default|rainbow|pastel-rainbow|sunset|ocean|forest|fire
banner="${OMN_BANNER:-}"
gradient="${OMN_GRADIENT:-}"

if [ -t 0 ]; then
  echo "Presentation preferences (change later with 'omn config'):"
  echo
  if [ "$banner" = "" ]; then
    echo "  Banner style:"
    echo "    1) short   compact, one-line tall   *"
    echo "    2) long    wide, blocky headline"
    printf '%s' "  (default 1): "
    read -r bnr_choice || true
    case "${bnr_choice:-1}" in
      1) banner="short" ;;
      2) banner="long" ;;
      *) banner="short" ;;
    esac
  fi
  if [ "$gradient" = "" ]; then
    # Swatch preview: 16 blocks on the long banner, 4 on the short one.
    sw="$LIB_DIR/src"
    echo
    echo "  Gradient:"
    i=0
    for key in default rainbow pastel-rainbow sunset ocean forest fire; do
      i=$((i + 1))
      if [ "$banner" = "long" ]; then width=16; else width=4; fi
      swatch=$(PYTHONPATH="$sw" python3 -c \
        "from omn.render import gradient_swatch; import sys; print(gradient_swatch(sys.argv[1], int(sys.argv[2]), force=True))" \
        "$key" "$width")
      case "$key" in
        default) desc="blue → red" ;;
        rainbow) desc="full-colour hue sweep" ;;
        pastel-rainbow) desc="soft, chalky rainbow" ;;
        sunset) desc="deep blue → warm orange" ;;
        ocean) desc="deep blue → cyan" ;;
        forest) desc="green → lime" ;;
        fire) desc="red → yellow" ;;
        *) desc="" ;;
      esac
      if [ "$key" = "pastel-rainbow" ]; then marker="  *"; else marker=""; fi
      printf '    %d) %-16s %s %s%s\n' "$i" "$key" "$swatch" "$desc" "$marker"
    done
    printf '%s' "  (default 3): "
    read -r grad_choice || true
    case "${grad_choice:-3}" in
      1) gradient="default" ;;
      2) gradient="rainbow" ;;
      3) gradient="pastel-rainbow" ;;
      4) gradient="sunset" ;;
      5) gradient="ocean" ;;
      6) gradient="forest" ;;
      7) gradient="fire" ;;
      *) gradient="pastel-rainbow" ;;
    esac
  fi
else
  # Non-interactive: env overrides, else defaults.
  gradient="${gradient:-pastel-rainbow}"
  banner="${banner:-short}"
fi

# Persist choices into <data-root>/config.json.
printf 'install config => %s/config.json\n' "$DATA_ROOT"
"$BIN_DIR/omn" config -b "$banner" -g "$gradient" >/dev/null

echo
echo "Quick start:"
echo '    omn add "Welcome to oh-my-notes" -m "Notes live in your terminal."'
echo "    omn list"