#!/bin/bash
# Mneme launcher for macOS .app bundle
DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$DIR"

# Use python3 from PATH or common Homebrew locations
PYTHON=$(command -v python3 || echo /usr/local/bin/python3)
exec "$PYTHON" scripts/tray.py
