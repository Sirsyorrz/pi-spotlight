#!/usr/bin/env python3
"""
Spotlight Chat — macOS Spotlight-style overlay for the `pi` agent.

Modes
-----
Quick mode  — single-prompt, JSON streaming (original behaviour)
Agent mode  — full interactive `pi` session via PTY + ANSI→HTML renderer

Config  ~/.config/spotlight-chat/config.json
Socket  /tmp/spotlight-chat-<uid>.sock   (toggle / show / hide)
"""

import sys
import os
import re
import pty
import fcntl
import termios
import struct
import socket
import subprocess
import threading
import signal
import time
import json
import html
import shutil
import glob

# ── PyQt5 / PyQt6 compat shim ────────────────────────────────────────────────
try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
        QTextEdit, QLabel, QComboBox, QSizePolicy, QPushButton,
        QFileDialog, QFrame, QScrollArea, QStackedWidget,
    )
    from PyQt5.QtCore import (
        Qt, QThread, pyqtSignal, QTimer, QRect, QPoint, QSize,
    )
    from PyQt5.QtGui import (
        QColor, QPainter, QPainterPath, QFont, QFontDatabase,
        QPalette, QTextCursor,
    )
except ImportError:
    from PyQt6.QtWidgets import (                          # type: ignore
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
        QTextEdit, QLabel, QComboBox, QSizePolicy, QPushButton,
        QFileDialog, QFrame, QScrollArea, QStackedWidget,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QRect, QPoint, QSize  # type: ignore
    from PyQt6.QtGui import (                              # type: ignore
        QColor, QPainter, QPainterPath, QFont,
        QPalette, QTextCursor,
    )

# ─── Config defaults ──────────────────────────────────────────────────────────

SOCKET_PATH = f"/tmp/spotlight-chat-{os.getuid()}.sock"
CONFIG_PATH = os.path.expanduser("~/.config/spotlight-chat/config.json")

AVAILABLE_MODELS = [
    ("Sonnet 4.5",  "anthropic/claude-sonnet-4-5"),
    ("Sonnet 4.0",  "anthropic/claude-sonnet-4-0"),
    ("Haiku 3.5",   "anthropic/claude-haiku-3-5"),
    ("Opus 4",      "anthropic/claude-opus-4-0"),
]

DEFAULT_CONFIG = {
    "model":            "anthropic/claude-sonnet-4-5",
    "quick_tools":      "read",
    "agent_cwd":        "~",
    "pi_bin":           "",
    "font_family":      "JetBrains Mono",
    "font_size":        13,
    "window_width":     720,
    "position_y_fraction": 0.15,
}

WINDOW_W         = 720
WINDOW_H_QUICK   = 72    # collapsed (input only)
WINDOW_H_QUICK_X = 560   # expanded with response
WINDOW_H_AGENT   = 700   # agent mode height


# ─── pi binary discovery ──────────────────────────────────────────────────────

def find_pi_binary() -> str:
    """Return path to the `pi` binary, or empty string if not found."""
    candidates = [
        shutil.which("pi"),
        os.path.expanduser("~/.npm/bin/pi"),
        os.path.expanduser("~/.local/bin/pi"),
        os.path.expanduser("~/node_modules/.bin/pi"),
        "/usr/local/bin/pi",
        "/usr/bin/pi",
    ]
    # nvm glob
    for p in glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/pi")):
        candidates.append(p)

    for p in candidates:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return ""


# ─── Config I/O ──────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    if not cfg.get("pi_bin"):
        cfg["pi_bin"] = find_pi_binary()
    return cfg


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ─── ANSI → HTML renderer ────────────────────────────────────────────────────

_ANSI_RE = re.compile(
    r'\x1b(?:'
    r'\[([0-9;?]*)([A-Za-z])'    # CSI sequences
    r'|'
    r'\]([^\x07\x1b]*)(?:\x07|\x1b\\)'  # OSC sequences
    r'|'
    r'[()][AB012]'               # charset designation — ignore
    r'|'
    r'[=>]'                      # keypad mode — ignore
    r'|'
    r'[MNOPQRSTUVWXYZ\\]'        # single-char Fe sequences
    r')'
)

# xterm 256-colour palette (first 16 standard + 6×6×6 cube + 24 greys)
def _xterm256(n: int) -> str:
    if n < 16:
        _base = [
            "#000000","#cc0000","#00cc00","#cccc00",
            "#0000cc","#cc00cc","#00cccc","#cccccc",
            "#888888","#ff0000","#00ff00","#ffff00",
            "#0000ff","#ff00ff","#00ffff","#ffffff",
        ]
        return _base[n]
    if n < 232:
        n -= 16
        b = n % 6; n //= 6
        g = n % 6; r = n // 6
        return "#{:02x}{:02x}{:02x}".format(r*51, g*51, b*51)
    grey = 8 + (n - 232) * 10
    return "#{:02x}{:02x}{:02x}".format(grey, grey, grey)


class AnsiRenderer:
    """
    Stateful ANSI escape code parser.
    Feed raw bytes → get HTML fragments back.
    """

    def __init__(self):
        self._buf      = b""
        self._fg       = None   # None = default
        self._bg       = None
        self._bold     = False
        self._italic   = False
        self._underline= False
        self._dim      = False
        self._span_open= False

    # ── public API ────────────────────────────────────────────────────────────

    def feed(self, raw: bytes) -> str:
        """Process raw bytes, return HTML fragment."""
        self._buf += raw
        text = self._buf.decode("utf-8", errors="replace")
        self._buf = b""

        result_parts = []
        pos = 0
        for m in _ANSI_RE.finditer(text):
            # emit literal text before this escape
            if m.start() > pos:
                result_parts.append(self._render_text(text[pos:m.start()]))
            pos = m.end()
            params, cmd = m.group(1), m.group(2)
            if cmd:
                self._handle_csi(params or "", cmd, result_parts)
            # OSC / others → silently ignored
        # remaining literal text
        if pos < len(text):
            result_parts.append(self._render_text(text[pos:]))
        return "".join(result_parts)

    def close_span(self) -> str:
        if self._span_open:
            self._span_open = False
            return "</span>"
        return ""

    # ── internals ────────────────────────────────────────────────────────────

    def _render_text(self, text: str) -> str:
        if not text:
            return ""
        escaped = html.escape(text).replace("\n", "<br>").replace(" ", "&nbsp;")
        style = self._current_style()
        if style:
            return f'<span style="{style}">{escaped}</span>'
        return escaped

    def _current_style(self) -> str:
        parts = []
        if self._fg:
            parts.append(f"color:{self._fg}")
        if self._bg:
            parts.append(f"background:{self._bg}")
        if self._bold:
            parts.append("font-weight:bold")
        if self._italic:
            parts.append("font-style:italic")
        if self._underline:
            parts.append("text-decoration:underline")
        if self._dim:
            parts.append("opacity:0.55")
        return ";".join(parts)

    def _handle_csi(self, params: str, cmd: str, out: list):
        # Only handle SGR (m = Select Graphic Rendition) for style
        # All cursor-movement / erase / etc. commands are discarded
        if cmd != "m":
            return
        nums = [int(x) if x else 0 for x in params.split(";")]
        i = 0
        while i < len(nums):
            n = nums[i]
            if n == 0:
                self._reset()
            elif n == 1:
                self._bold = True
            elif n == 2:
                self._dim = True
            elif n == 3:
                self._italic = True
            elif n == 4:
                self._underline = True
            elif n == 22:
                self._bold = False; self._dim = False
            elif n == 23:
                self._italic = False
            elif n == 24:
                self._underline = False
            elif 30 <= n <= 37:
                self._fg = _xterm256(n - 30)
            elif n == 38:
                if i + 2 < len(nums) and nums[i+1] == 5:
                    self._fg = _xterm256(nums[i+2]); i += 2
                elif i + 4 < len(nums) and nums[i+1] == 2:
                    self._fg = "#{:02x}{:02x}{:02x}".format(*nums[i+2:i+5]); i += 4
            elif n == 39:
                self._fg = None
            elif 40 <= n <= 47:
                self._bg = _xterm256(n - 40)
            elif n == 48:
                if i + 2 < len(nums) and nums[i+1] == 5:
                    self._bg = _xterm256(nums[i+2]); i += 2
                elif i + 4 < len(nums) and nums[i+1] == 2:
                    self._bg = "#{:02x}{:02x}{:02x}".format(*nums[i+2:i+5]); i += 4
            elif n == 49:
                self._bg = None
            elif 90 <= n <= 97:
                self._fg = _xterm256(8 + n - 90)
            elif 100 <= n <= 107:
                self._bg = _xterm256(8 + n - 100)
            i += 1

    def _reset(self):
        self._fg = self._bg = None
        self._bold = self._italic = self._underline = self._dim = False


# ─── Quick-mode worker ────────────────────────────────────────────────────────

class PiWorker(QThread):
    thinking = pyqtSignal(str)
    chunk    = pyqtSignal(str)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, prompt: str, model: str, pi_bin: str, tools: str = "read"):
        super().__init__()
        self.prompt  = prompt
        self.model   = model
        self.pi_bin  = pi_bin
        self.tools   = tools
        self._proc   = None

    def run(self):
        if not self.pi_bin:
            self.error.emit("pi binary not found. Set it in Settings (⚙).")
            self.finished.emit()
            return
        try:
            self._proc = subprocess.Popen(
                [self.pi_bin, "--model", self.model, "--no-session",
                 "--mode", "json", "--tools", self.tools,
                 "-p", self.prompt],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    self.chunk.emit(line + "\n")
                    continue
                if obj.get("type") != "message_update":
                    continue
                evt   = obj.get("assistantMessageEvent", {})
                etype = evt.get("type", "")
                if etype == "thinking_delta":
                    self.thinking.emit(evt.get("delta", ""))
                elif etype == "text_delta":
                    self.chunk.emit(evt.get("delta", ""))
            self._proc.wait()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def stop(self):
        if self._proc:
            self._proc.terminate()


# ─── PTY-based agent worker ──────────────────────────────────────────────────

class PtyWorker(QThread):
    output   = pyqtSignal(bytes)
    finished = pyqtSignal()

    def __init__(self, pi_bin: str, model: str, cwd: str):
        super().__init__()
        self._pi_bin = pi_bin
        self._model  = model
        self._cwd    = os.path.expanduser(cwd)
        self._master_fd = None
        self._proc      = None
        self._running   = False

    def run(self):
        if not self._pi_bin:
            self.output.emit(b"\x1b[31m[spotlight-chat] pi binary not found. Set it in Settings.\x1b[0m\r\n")
            self.finished.emit()
            return

        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd

        # Set terminal size (80 cols × 40 rows)
        winsize = struct.pack("HHHH", 40, 120, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        self._proc = subprocess.Popen(
            [self._pi_bin, "--model", self._model],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=self._cwd,
            close_fds=True,
            preexec_fn=os.setsid,
        )
        os.close(slave_fd)

        self._running = True
        while self._running:
            try:
                data = os.read(master_fd, 4096)
                if not data:
                    break
                self.output.emit(data)
            except OSError:
                break

        try:
            os.close(master_fd)
        except OSError:
            pass
        self.finished.emit()

    def send_input(self, text: str):
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, (text + "\n").encode())
            except OSError:
                pass

    def send_key(self, raw: bytes):
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, raw)
            except OSError:
                pass

    def stop(self):
        self._running = False
        if self._proc:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except Exception:
                try:
                    self._proc.terminate()
                except Exception:
                    pass


# ─── Settings Panel ──────────────────────────────────────────────────────────

class SettingsPanel(QWidget):
    saved         = pyqtSignal(dict)
    switch_agent  = pyqtSignal()
    closed        = pyqtSignal()

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = dict(cfg)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("SETTINGS")
        title.setObjectName("settingsTitle")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("settingsClose")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.closed.emit)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(close_btn)
        layout.addLayout(hdr)

        # ── Model ──
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Default model"))
        self._model_combo = QComboBox()
        self._model_combo.setObjectName("settingsCombo")
        for label, _ in AVAILABLE_MODELS:
            self._model_combo.addItem(label)
        # Select current
        cur_model = self._cfg.get("model", "")
        for idx, (_, mid) in enumerate(AVAILABLE_MODELS):
            if mid == cur_model:
                self._model_combo.setCurrentIndex(idx)
                break
        row1.addWidget(self._model_combo)
        layout.addLayout(row1)

        # ── Quick tools ──
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Quick mode tools"))
        self._tools_read = QPushButton("Read-only")
        self._tools_read.setObjectName("toolsBtn")
        self._tools_read.setCheckable(True)
        self._tools_all = QPushButton("All tools")
        self._tools_all.setObjectName("toolsBtn")
        self._tools_all.setCheckable(True)
        if self._cfg.get("quick_tools", "read") == "read":
            self._tools_read.setChecked(True)
        else:
            self._tools_all.setChecked(True)
        self._tools_read.clicked.connect(lambda: self._tools_all.setChecked(False))
        self._tools_all.clicked.connect(lambda: self._tools_read.setChecked(False))
        row2.addWidget(self._tools_read)
        row2.addWidget(self._tools_all)
        layout.addLayout(row2)

        # ── Divider ──
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setObjectName("settingsDivider")
        layout.addWidget(div)

        # ── Advanced ──
        adv = QLabel("Advanced")
        adv.setObjectName("settingsSection")
        layout.addWidget(adv)

        # Working dir
        wd_row = QHBoxLayout()
        wd_row.addWidget(QLabel("Working dir"))
        self._cwd_edit = QLineEdit(self._cfg.get("agent_cwd", "~"))
        self._cwd_edit.setObjectName("settingsInput")
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("settingsBrowse")
        browse_btn.clicked.connect(self._browse_cwd)
        wd_row.addWidget(self._cwd_edit, 1)
        wd_row.addWidget(browse_btn)
        layout.addLayout(wd_row)

        # pi binary
        pi_row = QHBoxLayout()
        pi_row.addWidget(QLabel("pi binary"))
        self._pi_edit = QLineEdit(self._cfg.get("pi_bin", ""))
        self._pi_edit.setObjectName("settingsInput")
        detect_btn = QPushButton("Detect")
        detect_btn.setObjectName("settingsBrowse")
        detect_btn.clicked.connect(self._detect_pi)
        pi_row.addWidget(self._pi_edit, 1)
        pi_row.addWidget(detect_btn)
        layout.addLayout(pi_row)

        # Font size
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Terminal font size"))
        self._font_size_edit = QLineEdit(str(self._cfg.get("font_size", 13)))
        self._font_size_edit.setObjectName("settingsInput")
        self._font_size_edit.setFixedWidth(50)
        font_row.addWidget(self._font_size_edit)
        font_row.addStretch()
        layout.addLayout(font_row)

        # ── Actions ──
        act_row = QHBoxLayout()
        agent_btn = QPushButton("⚡  Switch to Agent Mode")
        agent_btn.setObjectName("agentSwitchBtn")
        agent_btn.clicked.connect(self.switch_agent.emit)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self._save)
        act_row.addWidget(agent_btn)
        act_row.addStretch()
        act_row.addWidget(save_btn)
        layout.addLayout(act_row)

    def _browse_cwd(self):
        d = QFileDialog.getExistingDirectory(self, "Choose working directory",
                                             os.path.expanduser(self._cwd_edit.text()))
        if d:
            self._cwd_edit.setText(d)

    def _detect_pi(self):
        p = find_pi_binary()
        if p:
            self._pi_edit.setText(p)
        else:
            self._pi_edit.setText("not found — install with: npm install -g @anthropic-ai/claude-code")

    def _save(self):
        idx = self._model_combo.currentIndex()
        self._cfg["model"]      = AVAILABLE_MODELS[idx][1]
        self._cfg["quick_tools"]= "read" if self._tools_read.isChecked() else "all"
        self._cfg["agent_cwd"]  = self._cwd_edit.text()
        self._cfg["pi_bin"]     = self._pi_edit.text()
        try:
            self._cfg["font_size"] = int(self._font_size_edit.text())
        except ValueError:
            pass
        self.saved.emit(self._cfg)


# ─── Main Window ─────────────────────────────────────────────────────────────

class SpotlightWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._cfg            = load_config()
        self._current_model  = self._cfg["model"]
        self._mode           = "quick"     # "quick" | "agent"
        self._worker         = None        # PiWorker in quick mode
        self._pty_worker     = None        # PtyWorker in agent mode
        self._expanded       = False
        self._settings_open  = False
        self._in_thinking    = False
        self._ansi           = AnsiRenderer()

        self._setup_window()
        self._setup_ui()
        self._setup_socket_listener()

    # ── Window ────────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(WINDOW_W)
        self.setFixedHeight(WINDOW_H_QUICK)
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - WINDOW_W) // 2
        y = int(screen.height() * self._cfg.get("position_y_fraction", 0.15))
        self.move(x, y)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._card = QWidget()
        self._card.setObjectName("card")
        self._card.setFixedWidth(WINDOW_W)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(10)

        # ── Header row ──
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self._icon = QLabel("⌘")
        self._icon.setObjectName("icon")
        self._icon.setFixedSize(32, 32)
        self._icon.setAlignment(Qt.AlignCenter)

        self._input = QLineEdit()
        self._input.setObjectName("input")
        self._input.setPlaceholderText("Ask anything…")
        self._input.setFixedHeight(40)
        self._input.returnPressed.connect(self._on_input_enter)

        self._spinner = QLabel("")
        self._spinner.setObjectName("spinner")
        self._spinner.setFixedSize(20, 20)
        self._spinner.setAlignment(Qt.AlignCenter)

        self._model_picker = QComboBox()
        self._model_picker.setObjectName("modelPicker")
        for label, _ in AVAILABLE_MODELS:
            self._model_picker.addItem(label)
        # Select current model
        for idx, (_, mid) in enumerate(AVAILABLE_MODELS):
            if mid == self._current_model:
                self._model_picker.setCurrentIndex(idx)
                break
        self._model_picker.currentIndexChanged.connect(self._on_model_changed)
        self._model_picker.setFocusPolicy(Qt.NoFocus)
        self._model_picker.setFixedHeight(36)
        self._model_picker.setMinimumWidth(130)

        # Mode toggle button
        self._mode_btn = QPushButton("⚡ Agent")
        self._mode_btn.setObjectName("modeBtn")
        self._mode_btn.setFixedHeight(36)
        self._mode_btn.setFocusPolicy(Qt.NoFocus)
        self._mode_btn.clicked.connect(self._toggle_mode)

        # Settings gear
        self._gear_btn = QPushButton("⚙")
        self._gear_btn.setObjectName("gearBtn")
        self._gear_btn.setFixedSize(36, 36)
        self._gear_btn.setFocusPolicy(Qt.NoFocus)
        self._gear_btn.clicked.connect(self._toggle_settings)

        header_row.addWidget(self._icon)
        header_row.addWidget(self._input, 1)
        header_row.addWidget(self._model_picker)
        header_row.addWidget(self._mode_btn)
        header_row.addWidget(self._gear_btn)
        header_row.addWidget(self._spinner)

        # ── Divider ──
        self._divider = QWidget()
        self._divider.setObjectName("divider")
        self._divider.setFixedHeight(1)
        self._divider.hide()

        # ── Quick mode: response area ──
        self._response = QTextEdit()
        self._response.setObjectName("response")
        self._response.setReadOnly(True)
        self._response.setFixedHeight(WINDOW_H_QUICK_X - WINDOW_H_QUICK - 60)
        self._response.hide()
        self._response.setLineWrapMode(QTextEdit.WidgetWidth)

        # ── Agent mode: output area ──
        self._agent_output = QTextEdit()
        self._agent_output.setObjectName("agentOutput")
        self._agent_output.setReadOnly(True)
        self._agent_output.hide()
        self._agent_output.setLineWrapMode(QTextEdit.WidgetWidth)

        # Agent input row
        self._agent_input_row = QWidget()
        self._agent_input_row.hide()
        ai_layout = QVBoxLayout(self._agent_input_row)
        ai_layout.setContentsMargins(0, 4, 0, 0)
        ai_layout.setSpacing(4)

        self._agent_input = QLineEdit()
        self._agent_input.setObjectName("agentInput")
        self._agent_input.setPlaceholderText("❯ type here, enter sends to pi…")
        self._agent_input.setFixedHeight(36)
        self._agent_input.returnPressed.connect(self._agent_send)

        self._agent_hint = QLabel(
            "↵ send  ·  ctrl+c interrupt  ·  esc hide  ·  ctrl+q quick mode"
        )
        self._agent_hint.setObjectName("hint")
        self._agent_hint.setAlignment(Qt.AlignCenter)

        ai_layout.addWidget(self._agent_input)
        ai_layout.addWidget(self._agent_hint)

        # ── Quick mode hint ──
        self._hint = QLabel("↵ ask  ·  esc close  ·  ctrl+l clear  ·  ctrl+m model  ·  ctrl+a agent")
        self._hint.setObjectName("hint")
        self._hint.setAlignment(Qt.AlignCenter)

        # ── Settings panel ──
        self._settings_panel = SettingsPanel(self._cfg)
        self._settings_panel.setObjectName("settingsPanel")
        self._settings_panel.saved.connect(self._on_settings_saved)
        self._settings_panel.switch_agent.connect(self._switch_to_agent_from_settings)
        self._settings_panel.closed.connect(self._close_settings)
        self._settings_panel.hide()

        card_layout.addLayout(header_row)
        card_layout.addWidget(self._divider)
        card_layout.addWidget(self._response)
        card_layout.addWidget(self._agent_output)
        card_layout.addWidget(self._agent_input_row)
        card_layout.addWidget(self._hint)
        card_layout.addWidget(self._settings_panel)

        root.addWidget(self._card)
        self._apply_styles()

        # Spinner
        self._spin_chars = ["◐", "◓", "◑", "◒"]
        self._spin_idx   = 0
        self._spin_timer = QTimer()
        self._spin_timer.timeout.connect(self._tick_spinner)

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        fs = self._cfg.get("font_size", 13)
        ff = self._cfg.get("font_family", "JetBrains Mono")
        mono_stack = f"'{ff}', 'Fira Code', 'Cascadia Code', monospace"

        self.setStyleSheet(f"""
            QWidget#card {{
                background: rgba(18, 18, 22, 0.93);
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }}
            QLabel#icon {{
                color: #7c6af7;
                font-size: 18px;
                background: rgba(124, 106, 247, 0.15);
                border-radius: 8px;
                font-family: monospace;
            }}
            QLineEdit#input {{
                background: transparent;
                border: none;
                color: #f0eeff;
                font-size: 18px;
                font-family: 'SF Pro Display', 'Segoe UI', 'Noto Sans', sans-serif;
                selection-background-color: #7c6af7;
            }}
            QLabel#spinner {{
                color: #7c6af7;
                font-size: 16px;
            }}
            QComboBox#modelPicker {{
                background: rgba(124, 106, 247, 0.12);
                border: 1px solid rgba(124, 106, 247, 0.25);
                border-radius: 6px;
                color: rgba(180, 170, 255, 0.85);
                font-size: 12px;
                padding: 0px 8px;
            }}
            QComboBox#modelPicker:hover {{
                border-color: rgba(124, 106, 247, 0.55);
            }}
            QComboBox#modelPicker::drop-down {{ border: none; width: 16px; }}
            QComboBox#modelPicker::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid rgba(124, 106, 247, 0.7);
            }}
            QComboBox QAbstractItemView {{
                background: rgba(22, 20, 32, 0.97);
                border: 1px solid rgba(124, 106, 247, 0.3);
                border-radius: 8px;
                color: #c8c0f5;
                font-size: 12px;
                selection-background-color: rgba(124, 106, 247, 0.35);
                padding: 4px;
            }}
            QPushButton#modeBtn {{
                background: rgba(255, 200, 50, 0.10);
                border: 1px solid rgba(255, 200, 50, 0.25);
                border-radius: 6px;
                color: rgba(255, 210, 80, 0.85);
                font-size: 12px;
                padding: 0px 10px;
            }}
            QPushButton#modeBtn:hover {{
                background: rgba(255, 200, 50, 0.20);
                border-color: rgba(255, 200, 50, 0.5);
            }}
            QPushButton#modeBtn[mode="quick"] {{
                background: rgba(100, 200, 150, 0.10);
                border: 1px solid rgba(100, 200, 150, 0.25);
                color: rgba(120, 220, 160, 0.85);
            }}
            QPushButton#gearBtn {{
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                color: rgba(160, 150, 210, 0.6);
                font-size: 16px;
            }}
            QPushButton#gearBtn:hover {{
                background: rgba(255, 255, 255, 0.05);
                color: rgba(180, 170, 255, 0.9);
            }}
            QWidget#divider {{
                background: rgba(255, 255, 255, 0.07);
            }}
            QTextEdit#response, QTextEdit#agentOutput {{
                background: transparent;
                border: none;
                color: #c8c0f5;
                font-size: {fs}px;
                font-family: {mono_stack};
                selection-background-color: #7c6af7;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(124, 106, 247, 0.4);
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QLabel#hint {{
                color: rgba(150, 140, 200, 0.35);
                font-size: 11px;
                font-family: 'Noto Sans', sans-serif;
                padding-top: 2px;
            }}
            QLineEdit#agentInput {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(124, 106, 247, 0.2);
                border-radius: 6px;
                color: #e0dcff;
                font-size: {fs}px;
                font-family: {mono_stack};
                padding: 0 10px;
                selection-background-color: #7c6af7;
            }}
            QWidget#settingsPanel {{
                background: rgba(14, 13, 20, 0.6);
                border-top: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 0 0 14px 14px;
            }}
            QLabel#settingsTitle {{
                color: rgba(180, 170, 255, 0.5);
                font-size: 10px;
                font-family: monospace;
                letter-spacing: 2px;
            }}
            QLabel#settingsSection {{
                color: rgba(150, 140, 200, 0.4);
                font-size: 10px;
                font-family: monospace;
                letter-spacing: 1px;
            }}
            QPushButton#settingsClose {{
                background: transparent;
                border: none;
                color: rgba(200, 180, 255, 0.4);
                font-size: 14px;
            }}
            QPushButton#settingsClose:hover {{ color: #e06c6c; }}
            QWidget#settingsPanel QLabel {{
                color: rgba(180, 170, 255, 0.7);
                font-size: 12px;
            }}
            QComboBox#settingsCombo {{
                background: rgba(124, 106, 247, 0.12);
                border: 1px solid rgba(124, 106, 247, 0.25);
                border-radius: 5px;
                color: #c8c0f5;
                font-size: 12px;
                padding: 2px 8px;
                min-width: 140px;
            }}
            QComboBox#settingsCombo QAbstractItemView {{
                background: rgba(22, 20, 32, 0.97);
                border: 1px solid rgba(124, 106, 247, 0.3);
                color: #c8c0f5;
                selection-background-color: rgba(124, 106, 247, 0.35);
            }}
            QLineEdit#settingsInput {{
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                color: #c8c0f5;
                font-size: 12px;
                font-family: monospace;
                padding: 2px 8px;
                height: 28px;
            }}
            QPushButton#toolsBtn {{
                background: rgba(124, 106, 247, 0.10);
                border: 1px solid rgba(124, 106, 247, 0.2);
                border-radius: 5px;
                color: rgba(180, 170, 255, 0.7);
                font-size: 11px;
                padding: 3px 10px;
            }}
            QPushButton#toolsBtn:checked {{
                background: rgba(124, 106, 247, 0.30);
                border-color: rgba(124, 106, 247, 0.6);
                color: #c8c0f5;
            }}
            QPushButton#settingsBrowse {{
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                color: rgba(180, 170, 255, 0.7);
                font-size: 11px;
                padding: 3px 10px;
            }}
            QPushButton#settingsBrowse:hover {{
                background: rgba(255, 255, 255, 0.10);
                color: #c8c0f5;
            }}
            QFrame#settingsDivider {{
                color: rgba(255, 255, 255, 0.07);
            }}
            QPushButton#agentSwitchBtn {{
                background: rgba(255, 200, 50, 0.10);
                border: 1px solid rgba(255, 200, 50, 0.25);
                border-radius: 6px;
                color: rgba(255, 210, 80, 0.85);
                font-size: 12px;
                padding: 4px 14px;
            }}
            QPushButton#agentSwitchBtn:hover {{
                background: rgba(255, 200, 50, 0.20);
            }}
            QPushButton#saveBtn {{
                background: rgba(124, 106, 247, 0.25);
                border: 1px solid rgba(124, 106, 247, 0.5);
                border-radius: 6px;
                color: #c8c0f5;
                font-size: 12px;
                padding: 4px 18px;
            }}
            QPushButton#saveBtn:hover {{
                background: rgba(124, 106, 247, 0.40);
            }}
        """)

    # ── paint (glow shadow) ───────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for i in range(10, 0, -1):
            color = QColor(80, 60, 200, max(0, 4 - abs(i - 5)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            r = QPainterPath()
            r.addRoundedRect(4 - i, 4 - i,
                             self.width() - 8 + i * 2,
                             self.height() - 8 + i * 2, 16 + i, 16 + i)
            painter.drawPath(r)

    # ── Toggle show / hide ────────────────────────────────────────────────────

    def toggle(self):
        if self.isVisible():
            self._hide_window()
        else:
            self._show_window()

    def _show_window(self):
        self._center_on_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        if self._mode == "quick":
            self._input.clear()
            self._collapse_response()
            self._input.setFocus()
        else:
            self._agent_input.setFocus()

    def _hide_window(self):
        if self._worker:
            self._worker.stop()
        self.hide()

    # ── Quick mode: expand / collapse ────────────────────────────────────────

    def _expand_response(self):
        if self._expanded:
            return
        self._expanded = True
        self._divider.show()
        self._response.show()
        self.setFixedHeight(WINDOW_H_QUICK_X)

    def _collapse_response(self):
        self._expanded = False
        self._response.clear()
        self._response.hide()
        self._divider.hide()
        self._spinner.setText("")
        self._spin_timer.stop()
        self.setFixedHeight(WINDOW_H_QUICK)

    # ── Mode switching ────────────────────────────────────────────────────────

    def _toggle_mode(self):
        if self._mode == "quick":
            self._enter_agent_mode()
        else:
            self._enter_quick_mode()

    def _enter_agent_mode(self):
        if self._mode == "agent":
            return
        self._mode = "agent"
        self._mode_btn.setText("⌘ Quick")
        self._mode_btn.setProperty("mode", "quick")
        self._mode_btn.style().polish(self._mode_btn)

        self._input.hide()
        self._model_picker.hide()
        self._hint.hide()
        self._collapse_response()
        self._response.hide()

        self._divider.show()
        self._agent_output.show()
        self._agent_input_row.show()

        out_h = WINDOW_H_AGENT - WINDOW_H_QUICK - 90
        self._agent_output.setFixedHeight(out_h)
        self.setFixedHeight(WINDOW_H_AGENT)

        self._icon.setText("⚡")
        self._input.setPlaceholderText("")

        self._close_settings()
        self._start_pty()

    def _enter_quick_mode(self):
        if self._mode == "quick":
            return
        self._stop_pty()
        self._mode = "quick"
        self._mode_btn.setText("⚡ Agent")
        self._mode_btn.setProperty("mode", "")
        self._mode_btn.style().polish(self._mode_btn)

        self._agent_output.hide()
        self._agent_input_row.hide()
        self._divider.hide()

        self._input.show()
        self._model_picker.show()
        self._hint.show()
        self._icon.setText("⌘")
        self._input.setPlaceholderText("Ask anything…")
        self.setFixedHeight(WINDOW_H_QUICK)
        self._input.setFocus()

    def _switch_to_agent_from_settings(self):
        self._close_settings()
        self._enter_agent_mode()

    # ── PTY management ────────────────────────────────────────────────────────

    def _start_pty(self):
        self._stop_pty()
        self._agent_output.clear()
        self._ansi = AnsiRenderer()

        pi_bin = self._cfg.get("pi_bin", "") or find_pi_binary()
        cwd    = self._cfg.get("agent_cwd", "~")

        self._pty_worker = PtyWorker(pi_bin, self._current_model, cwd)
        self._pty_worker.output.connect(self._on_pty_output)
        self._pty_worker.finished.connect(self._on_pty_done)
        self._pty_worker.start()

    def _stop_pty(self):
        if self._pty_worker:
            self._pty_worker.stop()
            self._pty_worker.wait(2000)
            self._pty_worker = None

    def _on_pty_output(self, raw: bytes):
        html_frag = self._ansi.feed(raw)
        if html_frag:
            cursor = self._agent_output.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertHtml(html_frag)
            self._agent_output.setTextCursor(cursor)
            self._agent_output.ensureCursorVisible()

    def _on_pty_done(self):
        cursor = self._agent_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml('<br><span style="color:rgba(124,106,247,0.4);">[pi session ended]</span>')
        self._agent_output.setTextCursor(cursor)

    def _agent_send(self):
        text = self._agent_input.text()
        self._agent_input.clear()
        if self._pty_worker and self._pty_worker.isRunning():
            self._pty_worker.send_input(text)
        else:
            # Session ended — restart
            self._start_pty()

    # ── Quick mode: submit ────────────────────────────────────────────────────

    def _on_input_enter(self):
        if self._mode == "quick":
            self._submit()

    def _submit(self):
        prompt = self._input.text().strip()
        if not prompt:
            return
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait()

        self._expand_response()
        self._response.clear()
        self._spin_timer.start(120)
        self._in_thinking = False

        pi_bin = self._cfg.get("pi_bin", "") or find_pi_binary()
        tools  = self._cfg.get("quick_tools", "read")

        self._worker = PiWorker(prompt, self._current_model, pi_bin, tools)
        self._worker.thinking.connect(self._on_thinking)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _insert_html(self, fragment: str):
        cursor = self._response.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(fragment)
        self._response.setTextCursor(cursor)
        self._response.ensureCursorVisible()

    def _on_thinking(self, text: str):
        if not self._in_thinking:
            self._in_thinking = True
            self._insert_html(
                '<span style="color:#5a4fa0;font-size:11px;font-style:italic;">💭 thinking</span><br>'
            )
        escaped = html.escape(text).replace("\n", "<br>")
        self._insert_html(f'<span style="color:#6b5fbf;font-size:12px;font-style:italic;">{escaped}</span>')

    def _on_chunk(self, text: str):
        if self._in_thinking:
            self._in_thinking = False
            self._insert_html(
                '<br><span style="color:rgba(124,106,247,0.3);">──────────────────</span><br>'
            )
        escaped = html.escape(text).replace("\n", "<br>")
        self._insert_html(f'<span style="color:#c8c0f5;font-size:14px;">{escaped}</span>')

    def _on_done(self):
        self._spin_timer.stop()
        self._spinner.setText("✓")
        self._input.clear()
        self._input.setFocus()
        QTimer.singleShot(1500, lambda: self._spinner.setText(""))

    def _on_error(self, msg: str):
        self._spin_timer.stop()
        self._spinner.setText("✗")
        self._insert_html(f'<br><span style="color:#e06c6c;">[error] {html.escape(msg)}</span>')

    def _tick_spinner(self):
        self._spinner.setText(self._spin_chars[self._spin_idx % 4])
        self._spin_idx += 1

    def _on_model_changed(self, idx: int):
        self._current_model = AVAILABLE_MODELS[idx][1]
        self._cfg["model"]  = self._current_model

    def _cycle_model(self):
        idx = self._model_picker.currentIndex()
        self._model_picker.setCurrentIndex((idx + 1) % len(AVAILABLE_MODELS))

    # ── Settings ──────────────────────────────────────────────────────────────

    def _toggle_settings(self):
        if self._settings_open:
            self._close_settings()
        else:
            self._open_settings()

    def _open_settings(self):
        self._settings_open = True
        # Rebuild panel with current cfg
        self._settings_panel.deleteLater()
        self._settings_panel = SettingsPanel(self._cfg)
        self._settings_panel.setObjectName("settingsPanel")
        self._settings_panel.saved.connect(self._on_settings_saved)
        self._settings_panel.switch_agent.connect(self._switch_to_agent_from_settings)
        self._settings_panel.closed.connect(self._close_settings)
        # Insert into card layout (last widget)
        self._card.layout().addWidget(self._settings_panel)
        self._apply_styles()
        self._settings_panel.show()
        self._resize_for_content()

    def _close_settings(self):
        if not self._settings_open:
            return
        self._settings_open = False
        self._settings_panel.hide()
        self._resize_for_content()

    def _resize_for_content(self):
        if self._mode == "agent":
            extra = 220 if self._settings_open else 0
            self.setFixedHeight(WINDOW_H_AGENT + extra)
        elif self._expanded:
            extra = 220 if self._settings_open else 0
            self.setFixedHeight(WINDOW_H_QUICK_X + extra)
        else:
            extra = 220 if self._settings_open else 0
            self.setFixedHeight(WINDOW_H_QUICK + extra)

    def _on_settings_saved(self, new_cfg: dict):
        self._cfg = new_cfg
        self._current_model = new_cfg.get("model", self._current_model)
        # Update model picker
        for idx, (_, mid) in enumerate(AVAILABLE_MODELS):
            if mid == self._current_model:
                self._model_picker.setCurrentIndex(idx)
                break
        save_config(self._cfg)
        self._apply_styles()
        self._close_settings()

    # ── Key events ────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        if key == Qt.Key_Escape:
            self._hide_window()
        elif key == Qt.Key_L and mods == Qt.ControlModifier:
            if self._mode == "quick":
                self._collapse_response()
                self._input.clear()
                self._input.setFocus()
            else:
                self._agent_output.clear()
        elif key == Qt.Key_M and mods == Qt.ControlModifier:
            self._cycle_model()
        elif key == Qt.Key_A and mods == Qt.ControlModifier:
            if self._mode == "quick":
                self._enter_agent_mode()
        elif key == Qt.Key_Q and mods == Qt.ControlModifier:
            if self._mode == "agent":
                self._enter_quick_mode()
        elif key == Qt.Key_C and mods == Qt.ControlModifier:
            if self._mode == "agent" and self._pty_worker:
                self._pty_worker.send_key(b"\x03")
            elif self._worker:
                self._worker.stop()
        else:
            super().keyPressEvent(event)

    # ── Socket ────────────────────────────────────────────────────────────────

    def _setup_socket_listener(self):
        t = threading.Thread(target=self._socket_server, daemon=True)
        t.start()

    def _socket_server(self):
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET_PATH)
        srv.listen(5)
        while True:
            try:
                conn, _ = srv.accept()
                data = conn.recv(64).decode().strip()
                conn.close()
                if data == "toggle":
                    QTimer.singleShot(0, self.toggle)
                elif data == "show":
                    QTimer.singleShot(0, self._show_window)
                elif data == "hide":
                    QTimer.singleShot(0, self._hide_window)
            except Exception:
                pass


# ─── Toggle helper ────────────────────────────────────────────────────────────

def send_toggle() -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCKET_PATH)
        s.sendall(b"toggle")
        s.close()
        return True
    except Exception:
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if "--toggle" in args:
        if send_toggle():
            sys.exit(0)
        # Daemon not running — fall through and start it

    app = QApplication(sys.argv)
    app.setApplicationName("spotlight-chat")
    app.setQuitOnLastWindowClosed(False)

    win = SpotlightWindow()

    if "--toggle" in args or "--daemon" not in args:
        win._show_window()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
