#!/usr/bin/env bash
# deps_check.sh — check for required and optional dependencies
# Prints warnings and sets DEPS_OK=1 if all required deps are present, 0 otherwise.

DEPS_OK=1

check_cmd() {
    local cmd="$1" label="${2:-$1}" required="${3:-required}"
    if command -v "$cmd" &>/dev/null; then
        echo "  ✓ $label"
    else
        if [[ "$required" == "required" ]]; then
            echo "  ✗ $label  ← MISSING (required)"
            DEPS_OK=0
        else
            echo "  ○ $label  ← not found (optional)"
        fi
    fi
}

check_python_pkg() {
    local pkg="$1" required="${2:-required}"
    if python3 -c "import $pkg" &>/dev/null 2>&1; then
        echo "  ✓ python3/$pkg"
    else
        if [[ "$required" == "required" ]]; then
            echo "  ✗ python3/$pkg  ← MISSING  →  pip install $pkg"
            DEPS_OK=0
        else
            echo "  ○ python3/$pkg  ← not found (optional, pip install $pkg)"
        fi
    fi
}

echo "── Checking dependencies ─────────────────────────────────────────────────"
check_cmd python3
check_cmd pip3 "pip3 (for python packages)"

# PyQt5 or PyQt6
if python3 -c "import PyQt5" &>/dev/null 2>&1; then
    echo "  ✓ python3/PyQt5"
elif python3 -c "import PyQt6" &>/dev/null 2>&1; then
    echo "  ✓ python3/PyQt6 (PyQt5 not found, will use PyQt6)"
else
    echo "  ✗ python3/PyQt5 or PyQt6  ← MISSING  →  pip install PyQt5"
    DEPS_OK=0
fi

# Optional: qtermwidget python bindings (for richer agent mode terminal)
check_python_pkg "qtermwidget5" optional 2>/dev/null || true
if python3 -c "import qtermwidget5" &>/dev/null 2>&1; then
    echo "     (qtermwidget5 found — agent mode will use full terminal emulator)"
fi

# Check for pi binary
PI_FOUND=0
for p in \
    "$(command -v pi 2>/dev/null)" \
    "$HOME/.npm/bin/pi" \
    "$HOME/.local/bin/pi" \
    "$HOME/node_modules/.bin/pi" \
    "/usr/local/bin/pi" \
    "/usr/bin/pi"
do
    if [[ -n "$p" && -x "$p" ]]; then
        echo "  ✓ pi binary: $p"
        PI_FOUND=1
        break
    fi
done
if [[ $PI_FOUND -eq 0 ]]; then
    # Try nvm glob
    for p in "$HOME"/.nvm/versions/node/*/bin/pi; do
        if [[ -x "$p" ]]; then
            echo "  ✓ pi binary (nvm): $p"
            PI_FOUND=1
            break
        fi
    done
fi
if [[ $PI_FOUND -eq 0 ]]; then
    echo "  ✗ pi binary  ← NOT FOUND  →  npm install -g @anthropic-ai/claude-code"
    DEPS_OK=0
fi

echo "─────────────────────────────────────────────────────────────────────────"

if [[ $DEPS_OK -eq 1 ]]; then
    echo "  All required dependencies found."
else
    echo "  ⚠ Some required dependencies are missing. Please install them and re-run."
fi
echo
