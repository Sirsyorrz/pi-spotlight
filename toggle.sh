#!/usr/bin/env bash
# Hotkey script — toggles the spotlight window.
# If the daemon isn't running, starts it.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOCKET="/tmp/spotlight-chat-$(id -u).sock"
PID_FILE="/tmp/spotlight-chat-$(id -u).pid"
LOG_FILE="/tmp/spotlight-chat.log"

# Try to toggle a running daemon
if [ -S "$SOCKET" ]; then
    python3 "$SCRIPT_DIR/spotlight.py" --toggle 2>/dev/null
    exit 0
fi

# Daemon not running — launch it
nohup python3 "$SCRIPT_DIR/spotlight.py" --toggle \
    > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
