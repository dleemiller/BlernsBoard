#!/bin/sh
# Install BlernsBoard as a shell command. Interactive by default: asks where to
# put things and before overwriting an existing install. Ctrl-C aborts at any point.
#
#   sh install.sh                    prompt for the prefix (default ~/.local)
#   sh install.sh --prefix /usr/local
#   sh install.sh --uninstall [--prefix ...]
#   FORCE=1 sh install.sh --prefix ~/.local   no prompts (for scripts)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DEFAULT_PREFIX="$HOME/.local"
PREFIX=""; MODE=install
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX=$2; shift 2 ;;
    --prefix=*) PREFIX=${1#--prefix=}; shift ;;
    --uninstall) MODE=uninstall; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

interactive=0
if [ -z "$FORCE" ] && ( : < /dev/tty ) 2>/dev/null && ( : > /dev/tty ) 2>/dev/null; then interactive=1; fi
trap 'echo; echo "aborted, nothing changed."; exit 130' INT
ask() { # ask "prompt" "default" -> answer in $REPLY
  if [ $interactive -eq 1 ]; then printf '%s' "$1" > /dev/tty; read -r REPLY < /dev/tty || exit 130; else REPLY=""; fi
  [ -n "$REPLY" ] || REPLY=$2
}
expand_tilde() { case "$1" in "~") echo "$HOME" ;; "~/"*) echo "$HOME/${1#\~/}" ;; *) echo "$1" ;; esac; }

PYTHON=$(command -v python3 || command -v python || true)
if [ "$MODE" = install ]; then
  [ -n "$PYTHON" ] || { echo "python3 not found; BlernsBoard needs Python 3.8 or newer." >&2; exit 1; }
  "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || { echo "Python 3.8 or newer is required (found $("$PYTHON" --version 2>&1))." >&2; exit 1; }
  for f in blernsboard.html serve.py; do [ -f "$HERE/$f" ] || { echo "missing $HERE/$f" >&2; exit 1; }; done
fi

if [ -z "$PREFIX" ]; then
  echo "BlernsBoard installs two things under a prefix:"
  echo "  <prefix>/bin/blernsboard          the command"
  echo "  <prefix>/share/blernsboard/       blernsboard.html and serve.py"
  echo "Press Enter for the default, type another path, or Ctrl-C to stop."
  ask "Prefix [$DEFAULT_PREFIX]: " "$DEFAULT_PREFIX"
  PREFIX=$(expand_tilde "$REPLY")
fi
case "$PREFIX" in /*) ;; *) PREFIX="$PWD/$PREFIX" ;; esac
BIN="$PREFIX/bin"; SHARE="$PREFIX/share/blernsboard"

if [ "$MODE" = uninstall ]; then
  if [ ! -e "$BIN/blernsboard" ] && [ ! -d "$SHARE" ]; then echo "nothing installed under $PREFIX"; exit 0; fi
  ask "Remove $BIN/blernsboard and $SHARE? [Y/n]: " "y"
  case "$REPLY" in n|N|no) echo "left in place."; exit 0 ;; esac
  rm -f "$BIN/blernsboard"; rm -rf "$SHARE"
  echo "removed."; exit 0
fi

if [ -e "$BIN/blernsboard" ] || [ -d "$SHARE" ]; then
  have=$(grep -o '__version__ = "[^"]*"' "$SHARE/serve.py" 2>/dev/null | cut -d'"' -f2)
  echo "An existing install${have:+ (version $have)} was found:"
  [ -e "$BIN/blernsboard" ] && echo "  $BIN/blernsboard"
  [ -d "$SHARE" ] && echo "  $SHARE/"
  if [ $interactive -eq 1 ]; then
    ask "Overwrite it? [Y/n]: " "y"
    case "$REPLY" in n|N|no) echo "nothing changed."; exit 0 ;; esac
  elif [ -z "$FORCE" ]; then
    echo "refusing to overwrite without a terminal; rerun with FORCE=1 to replace it." >&2; exit 1
  fi
fi

mkdir -p "$SHARE" "$BIN"
cp "$HERE/blernsboard.html" "$HERE/serve.py" "$SHARE/"
printf '#!/bin/sh\nexec "%s" "%s/serve.py" "$@"\n' "$PYTHON" "$SHARE" > "$BIN/blernsboard"
chmod +x "$BIN/blernsboard"
echo "installed $BIN/blernsboard  (files in $SHARE)"
case ":$PATH:" in
  *":$BIN:"*) echo "try: blernsboard --logdir /path/to/runs" ;;
  *) echo; echo "note: $BIN is not on your PATH. Add this line to ~/.bashrc or ~/.zshrc, then open a new shell:"
     echo "  export PATH=\"$BIN:\$PATH\"" ;;
esac
