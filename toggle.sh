#!/usr/bin/env bash
# Launch or toggle pi-spotlight.
# Assign this script to a keyboard shortcut:
#   KDE:   System Settings → Shortcuts → Custom Shortcuts → Command: /path/to/toggle.sh
#   GNOME: Settings → Keyboard → Custom Shortcuts
#   Other: bind to Alt+Space in your WM config

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/pi-spotlight.py"
