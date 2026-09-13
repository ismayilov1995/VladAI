#!/usr/bin/env bash
# Build the frontend, set up Python, and serve the app on http://localhost:8000
#
#   ./run.sh
#
# Safe to re-run: it skips work that is already done. Pass --clean to redo
# everything from scratch.

set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
VENV=".venv"
CLEAN=0
[ "${1:-}" = "--clean" ] && CLEAN=1

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
dim()  { printf '\033[2m%s\033[0m\n' "$1"; }
die()  { printf '\033[31m%s\033[0m\n' "$1" >&2; exit 1; }

# --- prerequisites ----------------------------------------------------------
command -v node >/dev/null 2>&1 \
  || die "Node is not installed. Get it from https://nodejs.org (version 20 or newer)."
command -v npm >/dev/null 2>&1 \
  || die "npm is missing, though node is installed. Reinstall Node from https://nodejs.org"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
[ -n "$PY" ] || die "Python 3.11 or newer is not installed. Get it from https://python.org"

node_major="$(node -v | sed 's/^v\([0-9]*\).*/\1/')"
[ "$node_major" -ge 20 ] \
  || die "Node $(node -v) is too old. Version 20 or newer is needed: https://nodejs.org"

bold "Vlada AI — embroidery fill"
dim  "node $(node -v) · $($PY --version)"
echo

if [ "$CLEAN" = "1" ]; then
  dim "--clean: removing the virtualenv and previous build"
  rm -rf "$VENV" backend/static frontend/node_modules
fi

# --- frontend ---------------------------------------------------------------
if [ ! -d frontend/node_modules ]; then
  bold "1/3  Installing frontend packages (a minute or so, once)"
  (cd frontend && npm install --no-audit --no-fund)
else
  dim "1/3  Frontend packages already installed"
fi

if [ ! -f backend/static/index.html ] || [ "$CLEAN" = "1" ]; then
  bold "2/3  Building the frontend"
  (cd frontend && npm run build)
else
  dim "2/3  Frontend already built (delete backend/static to rebuild)"
fi

# --- backend ----------------------------------------------------------------
if [ ! -d "$VENV" ]; then
  bold "3/3  Setting up Python and installing packages"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r backend/requirements.txt
else
  dim "3/3  Python packages already installed"
fi

# --- serve ------------------------------------------------------------------
echo
bold "Ready.  Open  ->  http://localhost:$PORT"
dim  "Drop samples/Velvet.svg onto the page.  Press Ctrl+C to stop."
echo

cd backend
exec "../$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
