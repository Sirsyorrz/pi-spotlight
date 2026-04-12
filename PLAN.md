# spotlight-chat — Upgrade Plan

## Goals
1. **Universal Linux installer** — works on any distro/DE, not just KDE/Arch
2. **Agent mode** — full interactive `pi` terminal embedded inside the spotlight window, same look/feel, all extensions/skills/tools active

---

## Phase 1 — Universal Installer

### Problem
Current `install.sh` is KDE-only (`kwriteconfig5`, `khotkeysrc`). Hotkey registration is DE-specific and there are at least 6 common environments to handle.

### DE Detection Matrix

| Desktop | Session | Hotkey Method |
|---|---|---|
| KDE Plasma | Wayland / X11 | `kwriteconfig5` → `khotkeysrc` + `qdbus reread_configuration` |
| GNOME | Wayland / X11 | `gsettings` custom-keybindings array |
| Hyprland | Wayland | Append `bind = Alt, Space, exec, bash /path/toggle.sh` to `hyprland.conf` |
| Sway | Wayland | Append `bindsym Alt+Space exec bash /path/toggle.sh` to `~/.config/sway/config` |
| i3 | X11 | Same as Sway (`~/.config/i3/config`) |
| XFCE | X11 | `xfconf-query` on `xfce4-keyboard-shortcuts` channel |
| Generic X11 (any) | X11 | `xbindkeys` — write `~/.xbindkeysrc` entry, autostart xbindkeys |
| Generic Wayland (unknown) | Wayland | Print manual instructions only |

### Autostart (universal)
XDG autostart (`~/.config/autostart/spotlight-chat.desktop`) already works on all DEs that respect the XDG spec (KDE, GNOME, XFCE, i3 with autostart helper, etc.). For i3/Sway/Hyprland, also offer a `exec` line in their config as a more reliable fallback.

### Dependency Detection
`install.sh` will check for and report missing deps before proceeding:

```
Required:   python3, pip/python3 (for PyQt5)
Python pkg: PyQt5  (pip install PyQt5)
            PyQt6  (fallback if PyQt5 unavailable)
Optional:   qtermwidget5 python bindings (for Agent mode — best experience)
            xbindkeys (Generic X11 fallback hotkey)
```

PyQt5 vs PyQt6 is handled at runtime in `spotlight.py` with a try/except import.

### `pi` Binary Discovery
Replace hardcoded `~/.npm/bin/pi` with a runtime search:

```python
PI_SEARCH_PATHS = [
    shutil.which("pi"),                          # already on PATH
    "~/.npm/bin/pi",
    "~/.local/bin/pi",
    "~/node_modules/.bin/pi",
    "~/.nvm/versions/node/*/bin/pi",             # nvm glob
    "/usr/local/bin/pi",
    "/usr/bin/pi",
]
```

First hit wins. If none found, show an error in the window with install instructions.

### New File Structure

```
spotlight-chat/
├── spotlight.py          # single-file app (all modes)
├── install.sh            # universal installer entry point
├── install/
│   ├── detect.sh         # echoes: kde | gnome | hyprland | sway | i3 | xfce | x11 | wayland | unknown
│   ├── kde.sh
│   ├── gnome.sh
│   ├── hyprland.sh
│   ├── sway_i3.sh        # shared (same config syntax)
│   ├── xfce.sh
│   ├── xbindkeys.sh      # generic X11 fallback
│   └── deps_check.sh     # prints missing dependencies
├── toggle.sh
└── README.md
```

`install.sh` sources `detect.sh`, calls the right sub-script, and falls back gracefully with manual instructions if the DE is unknown.

---

## Phase 2 — Agent Mode (embedded `pi` terminal)

### The Core Challenge
`pi` in interactive mode is a rich TUI:
- ANSI colors + bold/dim formatting
- A status bar rendered with cursor-positioning escape codes
- Interactive confirmation prompts from `pi-nolo` (y/n keypresses)
- Slash commands (`/yolo`, `/reload`, `/share`, etc.)
- Multi-line responses streamed in real time

A plain `QTextEdit` can't handle cursor positioning. A full terminal emulator widget (`qtermwidget`) can, but isn't always installed. We need a pragmatic middle ground.

### Chosen Approach: PTY + ANSI-to-HTML Renderer

Spawn `pi` inside a **pseudo-terminal (PTY)** using Python's built-in `pty` module. Read raw bytes from the master end, run them through a lightweight ANSI parser that converts color/style codes to HTML spans, and discard cursor-positioning codes (which are only used for the status bar). Forward keystrokes from a `QLineEdit` to the PTY's stdin.

**What renders correctly:**
- All text output, responses, thinking blocks
- ANSI 16 + 256 + truecolor foreground/background
- Bold, italic, dim, underline
- Tool call output (colored `bash`, `edit`, `write` blocks)
- `pi-nolo` confirmation prompts ("Allow this edit? [y/n]")
- `/yolo` mode toggle output

**What gets stripped/simplified:**
- Status bar (cursor-position codes discarded — we show model/mode in our own header instead)
- Cursor blinking, alternate screen buffer (not needed)

**Why not `qtermwidget`?** It would give us 100% terminal fidelity but requires an OS package install and won't be available everywhere. We offer it as an optional upgrade path — if it's detected, use it; otherwise use the PTY+HTML renderer.

### UI Layout for Agent Mode

The window gains a **mode toggle button** in the header (next to the model picker), switching between:

```
[ ⌘ ] [ Quick mode input…          ] [ Sonnet 4.5 ▾ ] [⚙] [◐]
```

**Quick mode** (current behavior — unchanged)

**Agent mode:**
```
┌──────────────────────────────────────────────────────────────┐
│  ⌘  Working directory: ~/projects/myapp          [⚡ Agent] ⚙ │
├──────────────────────────────────────────────────────────────┤
│  [pi colored output streams here, ANSI→HTML rendered]        │
│  > Reading src/main.py...                                    │
│  > Allow edit to src/main.py? [y/n]                         │  ← nolo prompt
│                                                              │
│  > ──────────────────────────────────────────────────────   │
├──────────────────────────────────────────────────────────────┤
│  ❯ _type here, enter sends to pi stdin_                      │
│  ↵ send  ·  ctrl+c interrupt  ·  esc hide  ·  ctrl+q quick  │
└──────────────────────────────────────────────────────────────┘
```

The input bar at the bottom sends raw text to the PTY stdin. `Ctrl+C` sends `SIGINT`. `Ctrl+Q` switches back to Quick mode.

### Settings Panel (⚙ gear icon)

Clicking ⚙ in the header slides open a settings pane below the input bar:

```
┌──────────────────────────────────────────────────────────────┐
│  ⌘  Ask anything…                        [Sonnet 4.5 ▾] [⚙] │
├──────────────────────────────────────────────────────────────┤
│  SETTINGS                                              [✕]   │
│                                                              │
│  Default model   [Sonnet 4.5              ▾]                 │
│  Quick mode      ○ Read-only tools   ● All tools             │
│                                                              │
│  ─── Advanced ─────────────────────────────────────────────  │
│  Working dir     [~                              ] [Browse]  │
│  pi binary       [~/.npm/bin/pi                 ] [Detect]  │
│  Terminal font   [JetBrains Mono 13px           ] [Change]  │
│                                                              │
│  [  Switch to Agent Mode  ]    [  Save  ]                   │
└──────────────────────────────────────────────────────────────┘
```

Settings are persisted to `~/.config/spotlight-chat/config.json`.

"Switch to Agent Mode" closes settings and switches the window to Agent mode.

### `PtyWorker` (new class alongside `PiWorker`)

```python
class PtyWorker(QThread):
    output   = pyqtSignal(bytes)   # raw PTY bytes → ANSI renderer
    finished = pyqtSignal()

    def __init__(self, pi_bin, model, cwd):
        # spawns: pi --model <model> (interactive, no -p flag)
        # inside a PTY via pty.openpty() + subprocess
        ...

    def send_input(self, text: str):
        # writes text + '\n' to PTY master fd
        ...

    def send_key(self, raw_bytes: bytes):
        # forwards raw keypresses (ctrl+c = b'\x03', etc.)
        ...
```

### `AnsiRenderer` (new class)

Stateful ANSI escape code parser:
- Maintains current foreground/background color + style stack
- Input: stream of raw bytes  
- Output: HTML fragment strings ready for `QTextEdit.insertHtml()`
- Handles: SGR color codes (16/256/truecolor), bold/italic/dim/underline/reset
- Discards: CSI cursor movement, OSC window title, alternate screen

---

## Phase 3 — Polish & Config Persistence

### `~/.config/spotlight-chat/config.json`
```json
{
  "model": "anthropic/claude-sonnet-4-5",
  "quick_tools": "read",
  "agent_cwd": "~",
  "pi_bin": "~/.npm/bin/pi",
  "font_family": "JetBrains Mono",
  "font_size": 13,
  "window_width": 720,
  "position_y_fraction": 0.15
}
```

### Keyboard shortcuts (final set)

| Key | Quick Mode | Agent Mode |
|---|---|---|
| `Enter` | Submit query | Send line to pi |
| `Esc` | Hide window | Hide window |
| `Ctrl+L` | Clear | Clear output |
| `Ctrl+M` | Cycle model | — |
| `Ctrl+A` | → Agent mode | — |
| `Ctrl+Q` | — | → Quick mode |
| `Ctrl+C` | Stop worker | Send SIGINT to pi |
| `⚙` click | Open settings | Open settings |

---

## Implementation Order

1. **`install/detect.sh`** + sub-scripts for each DE  
2. **`install/deps_check.sh`** + updated `install.sh` that orchestrates them  
3. **`pi` binary auto-discovery** in `spotlight.py`  
4. **Config persistence** (`~/.config/spotlight-chat/config.json` read/write)  
5. **Settings panel UI** (gear icon, slide-in pane, save button)  
6. **`AnsiRenderer`** class (ANSI → HTML, testable in isolation)  
7. **`PtyWorker`** class (PTY spawn, read loop, send_input)  
8. **Agent mode panel** (output `QTextEdit` + input `QLineEdit` + keyboard routing)  
9. **Mode toggle button** in header + `Ctrl+A` / `Ctrl+Q` shortcuts  
10. **Window resize** (Agent mode is taller: `WINDOW_H_AGENT = 700`)  
11. **README rewrite** covering both modes and all supported DEs
