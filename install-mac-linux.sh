#!/bin/bash
# Mneme Installer for macOS and Linux
set -e

echo
echo "  ==================================================================="
echo "   MNEME INSTALLER"
echo "  ==================================================================="
echo

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check Python ──────────────────────────────────────────────────────

echo "  [1/4] Checking Python installation..."

if ! command -v python3 &>/dev/null; then
    echo
    echo "   Python 3 is not installed or not in PATH."
    echo
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "   Install via Homebrew:  brew install python3"
    else
        echo "   Install via your package manager:"
        echo "     Ubuntu/Debian:  sudo apt install python3 python3-pip"
        echo "     Fedora:         sudo dnf install python3 python3-pip"
        echo "     Arch:           sudo pacman -S python python-pip"
    fi
    echo
    exit 1
fi

PYVER=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "       Python $PYVER found."

# ── Install dependencies ──────────────────────────────────────────────

echo
echo "  [2/4] Installing Python dependencies..."
echo

python3 -m pip install --upgrade pip
python3 -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo
echo "       Dependencies installed."

# ── Copy example files ────────────────────────────────────────────────

echo
echo "  [3/4] Preparing configuration files..."

if [ ! -f "$SCRIPT_DIR/system_instructions.txt" ] && [ -f "$SCRIPT_DIR/system_instructions.example.txt" ]; then
    cp "$SCRIPT_DIR/system_instructions.example.txt" "$SCRIPT_DIR/system_instructions.txt"
    echo "       System instructions created."
fi

echo "       Configuration will be completed in the browser."

# ── Platform-specific shortcuts ───────────────────────────────────────

echo
echo "  [4/4] Creating launcher..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS: set up .app bundle
    chmod +x "$SCRIPT_DIR/Mneme.app/Contents/MacOS/launch.sh"
    cp "$SCRIPT_DIR/Logos/mneme.icns" "$SCRIPT_DIR/Mneme.app/Contents/Resources/mneme.icns"

    # Copy to /Applications if user agrees
    echo
    read -p "       Install to /Applications? (y/n): " INSTALL_APP
    if [[ "$INSTALL_APP" =~ ^[Yy]$ ]]; then
        cp -R "$SCRIPT_DIR/Mneme.app" /Applications/Mneme.app
        echo "       Mneme.app installed to /Applications."
    else
        echo "       Skipped. You can drag Mneme.app to Applications manually."
    fi
else
    # Linux: generate .desktop file from template
    DESKTOP_FILE="$SCRIPT_DIR/mneme.desktop"
    sed "s|MNEME_PATH|$SCRIPT_DIR|g" "$SCRIPT_DIR/scripts/mneme.desktop.template" > "$DESKTOP_FILE"
    chmod +x "$DESKTOP_FILE"

    # Install to applications menu
    mkdir -p "$HOME/.local/share/applications"
    cp "$DESKTOP_FILE" "$HOME/.local/share/applications/mneme.desktop"

    # Desktop shortcut
    if [ -d "$HOME/Desktop" ]; then
        cp "$DESKTOP_FILE" "$HOME/Desktop/mneme.desktop"
        chmod +x "$HOME/Desktop/mneme.desktop"
        echo "       Desktop shortcut created."
    fi

    # Update desktop database
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null
    fi

    echo "       Application menu entry created."
fi

# ── Done ──────────────────────────────────────────────────────────────

echo
echo "  ==================================================================="
echo "   INSTALLATION COMPLETE"
echo "  ==================================================================="
echo
echo "   Next steps:"
echo
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "     1. Open Mneme from Applications (or double-click Mneme.app)"
else
    echo "     1. Launch Mneme from your application menu or desktop"
    echo "        (or run: python3 scripts/tray.py)"
fi
echo
echo "     2. Open http://localhost:8080 in your browser"
echo
echo "     3. Complete the setup wizard with your API keys"
echo
echo "     4. Start chatting!"
echo
echo "  ==================================================================="
echo

read -p "  Launch Mneme now? (y/n): " LAUNCH
if [[ "$LAUNCH" =~ ^[Yy]$ ]]; then
    echo
    echo "  Starting Mneme..."
    python3 "$SCRIPT_DIR/scripts/tray.py" &
    sleep 3
    if command -v xdg-open &>/dev/null; then
        xdg-open "http://localhost:8080"
    elif command -v open &>/dev/null; then
        open "http://localhost:8080"
    fi
fi
