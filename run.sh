#!/usr/bin/env bash
# macOS / Linux convenience launcher (Windows users: double-click IsoResearchAI.bat)
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python examples/make_synthetic_data.py
fi
exec .venv/bin/python -m isoresearch "$@"
