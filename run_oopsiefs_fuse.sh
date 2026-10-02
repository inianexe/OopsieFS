#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if [ ! -d ".venv" ]; then
  echo "Creating local Python environment..."
  python3 -m venv .venv
fi

if [ ! -f ".venv/.oopsiefs_deps_installed" ] || [ requirements.txt -nt ".venv/.oopsiefs_deps_installed" ]; then
  echo "Installing Python dependencies..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  touch ".venv/.oopsiefs_deps_installed"
fi

exec .venv/bin/python oopsiefs_fuse.py
