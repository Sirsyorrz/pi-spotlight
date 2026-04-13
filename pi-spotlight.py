#!/usr/bin/env python3
"""
pi-spotlight — macOS Spotlight-style overlay for the `pi` agent.

Modes
-----
Quick mode  — single-prompt, JSON streaming
Agent mode  — full embedded terminal (pyte VT100 + PTY, rendered via QPainter)
              runs `pi --model <model>` directly, supports all terminal features

Config  ~/.config/pi-spotlight/config.json
Socket  /tmp/pi-spotlight-<uid>.sock   (toggle / show / hide)
"""

import sys
import os
import pty
import fcntl
import termios
import struct
import subprocess
import threading
import signal
import json
import html
import shutil
import glob

import pyte

# ── PyQt5 / PyQt6 compat shim ────────────────────────────────────────────────
try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
        QTextEdit, QLabel, QComboBox, QSizePolicy, QPushButton,
        QFileDialog, QFrame,
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
    from PyQt5.QtGui import (
        QColor, QPainter, QPainterPath, QFont, QFontMetrics, QTextCursor,
    )
except ImportError:
    from PyQt6.QtWidgets import (                          # type: ignore
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
        QTextEdit, QLabel, QComboBox, QSizePolicy, QPushButton,
        QFileDialog, QFrame,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize  # type: ignore
    from PyQt6.QtGui import (                              # type: ignore
        QColor, QPainter, QPainterPath, QFont, QFontMetrics, QTextCursor,
    )

# ─── Config defaults ──────────────────────────────────────────────────────────

CONFIG_PATH = os.path.expanduser("~/.config/pi-spotlight/config.json")

PI_SETTINGS_PATH = os.path.expanduser("~/.pi/agent/settings.json")

# Fallback model list used when pi settings are unavailable
_FALLBACK_MODELS = [
    ("Sonnet 4.5",  "anthropic/claude-sonnet-4-5"),
    ("Sonnet 4.0",  "anthropic/claude-sonnet-4-0"),
    ("Haiku 3.5",   "anthropic/claude-haiku-3-5"),
    ("Opus 4",      "anthropic/claude-opus-4-0"),
]


def _model_label(model_id: str) -> str:
    """Derive a short human label from a fully-qualified model id.
    e.g. 'anthropic/claude-sonnet-4-6' -> 'Sonnet 4.6'
         'anthropic/claude-opus-4-6'   -> 'Opus 4.6'
         'openai/gpt-4o'               -> 'GPT-4o'
    """
    name = model_id.split("/")[-1]          # strip provider prefix
    name = name.replace("claude-", "")
    parts = name.split("-")
    # capitalise first word, keep the rest
    if parts:
        parts[0] = parts[0].capitalize()
    return " ".join(parts)


def load_pi_models() -> list[tuple[str, str]]:
    """
    Read ~/.pi/agent/settings.json and return a list of (label, model_id) pairs
    sourced from enabledModels (with the defaultModel first).
    Falls back to _FALLBACK_MODELS if the file is missing or malformed.
    """
    try:
        with open(PI_SETTINGS_PATH) as f:
            pi_cfg = json.load(f)

        enabled = pi_cfg.get("enabledModels", [])
        default = pi_cfg.get("defaultModel", "")

        # Normalise: ensure every entry has the provider prefix
        def _normalise(mid: str) -> str:
            if "/" not in mid:
                mid = f"anthropic/{mid}"
            return mid

        enabled = [_normalise(m) for m in enabled]
        default = _normalise(default)

        # Put the default model first; then the rest in order; deduplicate
        ordered: list[str] = []
        if default:
            ordered.append(default)
        for m in enabled:
            if m not in ordered:
                ordered.append(m)

        if ordered:
            return [(_model_label(m), m) for m in ordered]
    except Exception:
        pass

    return list(_FALLBACK_MODELS)


# Populated at import time; re-read on each Settings save
AVAILABLE_MODELS: list[tuple[str, str]] = load_pi_models()

DEFAULT_CONFIG = {
    "model":               (AVAILABLE_MODELS[0][1] if AVAILABLE_MODELS else "anthropic/claude-sonnet-4-5"),
    "agent_cwd":           "~",
    "pi_bin":              "",
    "font_family":         "JetBrains Mono",
    "font_size":           8,
    "terminal_cols":       150,
    "terminal_rows":       25,
    "position_y_fraction": 0.10,
}

# Card chrome measurements (margins + header + divider + hint + spacings)
CARD_MARGIN_H = 40    # left 20 + right 20
CARD_MARGIN_V = 118   # top 16 + header~40 + spacings + divider + hint~15 + bottom 16

WINDOW_W_QUICK    = 720
WINDOW_H_QUICK    = 72
WINDOW_H_QUICK_X  = 560
WINDOW_W_SETTINGS = 780


# ─── Terminal colour palette (One Dark-ish) ───────────────────────────────────

TERM_FG_DEFAULT = "#c8c0f5"
TERM_BG_DEFAULT = "#0d0c14"
TERM_CURSOR_FG  = "#0d0c14"
TERM_CURSOR_BG  = "#c8c0f5"

# pyte delivers colors as named strings ('red', 'brightred') or 6-char hex ('ff0000')
_NAMED_COLORS = {
    "black":         "#1a1a2e",
    "red":           "#e06c75",
    "green":         "#98c379",
    "yellow":        "#e5c07b",
    "blue":          "#61afef",
    "magenta":       "#c678dd",
    "cyan":          "#56b6c2",
    "white":         "#abb2bf",
    "brightblack":   "#5c6370",
    "brightred":     "#be5046",
    "brightgreen":   "#98c379",
    "brightyellow":  "#d19a66",
    "brightblue":    "#61afef",
    "brightmagenta": "#c678dd",
    "brightcyan":    "#56b6c2",
    "brightwhite":   "#ffffff",
}

# Qt key → terminal byte sequence
_KEY_SEQS = {
    Qt.Key_Up:       b"\x1b[A",
    Qt.Key_Down:     b"\x1b[B",
    Qt.Key_Right:    b"\x1b[C",
    Qt.Key_Left:     b"\x1b[D",
    Qt.Key_Home:     b"\x1b[H",
    Qt.Key_End:      b"\x1b[F",
    Qt.Key_PageUp:   b"\x1b[5~",
    Qt.Key_PageDown: b"\x1b[6~",
    Qt.Key_Delete:   b"\x1b[3~",
    Qt.Key_Insert:   b"\x1b[2~",
    Qt.Key_F1:       b"\x1bOP",
    Qt.Key_F2:       b"\x1bOQ",
    Qt.Key_F3:       b"\x1bOR",
    Qt.Key_F4:       b"\x1bOS",
    Qt.Key_F5:       b"\x1b[15~",
    Qt.Key_F6:       b"\x1b[17~",
    Qt.Key_F7:       b"\x1b[18~",
    Qt.Key_F8:       b"\x1b[19~",
    Qt.Key_F9:       b"\x1b[20~",
    Qt.Key_F10:      b"\x1b[21~",
    Qt.Key_F11:      b"\x1b[23~",
    Qt.Key_F12:      b"\x1b[24~",
}


# ─── pi binary discovery ──────────────────────────────────────────────────────

def find_pi_binary() -> str:
    candidates = [
        shutil.which("pi"),
        os.path.expanduser("~/.npm/bin/pi"),
        os.path.expanduser("~/.local/bin/pi"),
        os.path.expanduser("~/node_modules/.bin/pi"),
        "/usr/local/bin/pi",
        "/usr/bin/pi",
    ]
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
    # If the saved model isn't in the current AVAILABLE_MODELS list, reset to
    # whatever pi's settings consider the default (first in list).
    valid_ids = {mid for _, mid in AVAILABLE_MODELS}
    if cfg.get("model") not in valid_ids and AVAILABLE_MODELS:
        cfg["model"] = AVAILABLE_MODELS[0][1]
    return cfg


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


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
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
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


# ─── PTY worker ───────────────────────────────────────────────────────────────

class PtyWorker(QThread):
    """Opens a PTY pair, spawns `pi`, forwards raw bytes via signal."""

    output   = pyqtSignal(bytes)
    finished = pyqtSignal()

    def __init__(self, pi_bin: str, model: str, cwd: str, cols: int, rows: int):
        super().__init__()
        self._pi_bin    = pi_bin
        self._model     = model
        self._cwd       = os.path.expanduser(cwd)
        self._cols      = cols
        self._rows      = rows
        self._master_fd = None
        self._proc      = None
        self._running   = False

    def run(self):
        if not self._pi_bin:
            self.output.emit(
                b"\r\n\x1b[31m[pi-spotlight] pi binary not found."
                b" Configure it in Settings (\xe2\x9a\x99).\x1b[0m\r\n"
            )
            self.finished.emit()
            return

        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd

        # Set terminal dimensions
        winsize = struct.pack("HHHH", self._rows, self._cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        env = dict(os.environ)
        env["TERM"]      = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["COLUMNS"]   = str(self._cols)
        env["LINES"]     = str(self._rows)

        self._proc = subprocess.Popen(
            [self._pi_bin, "--model", self._model],
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            cwd=self._cwd,
            env=env,
            close_fds=True,
            preexec_fn=os.setsid,
        )
        os.close(slave_fd)

        self._running = True
        while self._running:
            try:
                data = os.read(master_fd, 8192)
                if not data:
                    break
                self.output.emit(data)
            except OSError:
                break

        try:
            os.close(master_fd)
        except OSError:
            pass

        self._master_fd = None
        self.finished.emit()

    def send_bytes(self, data: bytes):
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, data)
            except OSError:
                pass

    def resize(self, cols: int, rows: int):
        self._cols = cols
        self._rows = rows
        if self._master_fd is not None:
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
                if self._proc:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGWINCH)
            except Exception:
                pass

    def send_signal(self, sig: int):
        if self._proc:
            try:
                os.killpg(os.getpgid(self._proc.pid), sig)
            except Exception:
                try:
                    self._proc.send_signal(sig)
                except Exception:
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


# ─── Terminal widget ──────────────────────────────────────────────────────────

class TerminalWidget(QWidget):
    """
    Embedded terminal emulator.

    Uses pyte as a VT100/xterm-256color state machine and QPainter to render
    the resulting character grid.  Keyboard events are translated to terminal
    byte sequences and written back to the PTY master fd via the PtyWorker.

    Supports:
      • 16/256/true-colour via pyte → QPainter
      • Bold, italic, underline, reverse-video
      • Cursor blink
      • Full key mapping (arrows, Ctrl, F-keys, etc.)
      • SIGWINCH on resize
    """

    def __init__(self, cols: int, rows: int,
                 font_family: str = "JetBrains Mono",
                 font_size: int = 13,
                 parent=None):
        super().__init__(parent)

        self._cols = cols
        self._rows = rows
        self._pty: PtyWorker | None = None

        # ── pyte screen ──
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.ByteStream(self._screen)
        self._lock   = threading.Lock()

        # ── fonts ──
        self._font = QFont(font_family, font_size)
        self._font.setFixedPitch(True)
        self._font.setStyleHint(QFont.Monospace)
        self._font_bold = QFont(self._font)
        self._font_bold.setBold(True)
        self._font_bold_italic = QFont(self._font_bold)
        self._font_bold_italic.setItalic(True)
        self._font_italic = QFont(self._font)
        self._font_italic.setItalic(True)

        fm = QFontMetrics(self._font)
        try:
            self._cw = fm.horizontalAdvance("M")
        except AttributeError:
            self._cw = fm.width("M")          # Qt < 5.11 fallback
        self._ch      = fm.height()
        self._ascent  = fm.ascent()

        # fixed size — window is sized around this
        self.setFixedSize(cols * self._cw, rows * self._ch)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

        # ── cursor blink ──
        self._cursor_on  = True
        self._blink      = QTimer(self)
        self._blink.timeout.connect(self._blink_tick)
        self._blink.start(530)

    # ── public API ────────────────────────────────────────────────────────────

    def attach_pty(self, worker: PtyWorker):
        self._pty = worker

    def feed(self, data: bytes):
        """Process raw PTY output through pyte, then repaint."""
        with self._lock:
            self._stream.feed(data)
        self.update()

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(TERM_BG_DEFAULT))

        with self._lock:
            buf   = self._screen.buffer
            cur_x = self._screen.cursor.x
            cur_y = self._screen.cursor.y
            has_focus = self.hasFocus()

        cw, ch = self._cw, self._ch

        for row in range(self._rows):
            row_buf = buf[row]
            py = row * ch
            for col in range(self._cols):
                char   = row_buf[col]
                px     = col * cw
                is_cur = (col == cur_x and row == cur_y)

                fg = self._color(char.fg, default=TERM_FG_DEFAULT)
                bg = self._color(char.bg, default=TERM_BG_DEFAULT)

                if char.reverse:
                    fg, bg = bg, fg

                if is_cur and has_focus:
                    if self._cursor_on:
                        fg = QColor(TERM_CURSOR_FG)
                        bg = QColor(TERM_CURSOR_BG)
                    else:
                        # hollow cursor outline
                        painter.setPen(QColor(TERM_CURSOR_BG))
                        painter.drawRect(px, py, cw - 1, ch - 1)

                # background
                if bg != QColor(TERM_BG_DEFAULT) or is_cur:
                    painter.fillRect(px, py, cw, ch, bg)

                # glyph
                ch_data = char.data
                if ch_data and ch_data != " ":
                    if char.bold and char.italics:
                        painter.setFont(self._font_bold_italic)
                    elif char.bold:
                        painter.setFont(self._font_bold)
                    elif char.italics:
                        painter.setFont(self._font_italic)
                    else:
                        painter.setFont(self._font)
                    painter.setPen(fg)
                    painter.drawText(px, py + self._ascent, ch_data)

        painter.end()

    # ── colour resolution ─────────────────────────────────────────────────────

    @staticmethod
    def _color(raw: str, default: str) -> QColor:
        if not raw or raw == "default":
            return QColor(default)
        if len(raw) == 6 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return QColor("#" + raw)
        if raw in _NAMED_COLORS:
            return QColor(_NAMED_COLORS[raw])
        # fallback: try as Qt color name
        c = QColor(raw)
        return c if c.isValid() else QColor(default)

    # ── cursor blink ──────────────────────────────────────────────────────────

    def _blink_tick(self):
        self._cursor_on = not self._cursor_on
        cx = self._screen.cursor.x * self._cw
        cy = self._screen.cursor.y * self._ch
        self.update(cx, cy, self._cw, self._ch)

    def focusInEvent(self, event):
        self._cursor_on = True
        self._blink.start(530)
        self.update()

    def focusOutEvent(self, event):
        self._blink.stop()
        self._cursor_on = False
        self.update()

    # ── keyboard ─────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        # Named special keys
        if key in _KEY_SEQS:
            self._write(_KEY_SEQS[key])
            return

        # Core control keys
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._write(b"\r")
            return
        if key == Qt.Key_Backspace:
            self._write(b"\x7f")
            return
        if key == Qt.Key_Tab:
            if mods & Qt.ShiftModifier:
                self._write(b"\x1b[Z")   # Shift-Tab / back-tab
            else:
                self._write(b"\t")
            return
        if key == Qt.Key_Escape:
            self._write(b"\x1b")
            return

        # Ctrl + letter → control character
        if mods & Qt.ControlModifier:
            text = event.text()
            if text:
                lo = text.lower()
                if "a" <= lo <= "z":
                    self._write(bytes([ord(lo) - ord("a") + 1]))
                    return
                mapping = {"@": b"\x00", "[": b"\x1b", "\\": b"\x1c",
                           "]": b"\x1d", "^": b"\x1e", "_": b"\x1f"}
                if text in mapping:
                    self._write(mapping[text])
                    return

        # Alt/Meta + key → ESC prefix
        if mods & Qt.AltModifier:
            text = event.text()
            if text:
                self._write(b"\x1b" + text.encode("utf-8"))
                return

        # Regular printable text
        text = event.text()
        if text:
            self._write(text.encode("utf-8"))

    def _write(self, data: bytes):
        if self._pty:
            self._pty.send_bytes(data)

    # ── resize ────────────────────────────────────────────────────────────────

    def resizeTerminal(self, cols: int, rows: int):
        """Call when the user resizes the window — updates pyte + PTY."""
        if cols == self._cols and rows == self._rows:
            return
        self._cols = cols
        self._rows = rows
        with self._lock:
            self._screen.resize(rows, cols)
        self.setFixedSize(cols * self._cw, rows * self._ch)
        if self._pty:
            self._pty.resize(cols, rows)

    @property
    def cols(self):
        return self._cols

    @property
    def rows(self):
        return self._rows


# ─── Settings Panel ──────────────────────────────────────────────────────────

class SettingsPanel(QWidget):
    saved        = pyqtSignal(dict)
    switch_agent = pyqtSignal()
    closed       = pyqtSignal()

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._cfg = dict(cfg)
        self._build_ui()

    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setFixedWidth(130)
        return l

    def _build_ui(self):
        ROW_H   = 34
        BTN_W   = 80
        SPACING = 14

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(SPACING)

        hdr = QHBoxLayout()
        title = QLabel("SETTINGS")
        title.setObjectName("settingsTitle")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("settingsClose")
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self.closed.emit)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(close_btn)
        layout.addLayout(hdr)

        # Model
        row1 = QHBoxLayout(); row1.setSpacing(10)
        row1.addWidget(self._lbl("Default model"))
        self._model_combo = QComboBox()
        self._model_combo.setObjectName("settingsCombo")
        self._model_combo.setFixedHeight(ROW_H)
        for label, _ in AVAILABLE_MODELS:
            self._model_combo.addItem(label)
        for idx, (_, mid) in enumerate(AVAILABLE_MODELS):
            if mid == self._cfg.get("model", ""):
                self._model_combo.setCurrentIndex(idx)
                break
        row1.addWidget(self._model_combo, 1)
        layout.addLayout(row1)

        div = QFrame(); div.setFrameShape(QFrame.HLine); div.setObjectName("settingsDivider")
        layout.addWidget(div)

        adv = QLabel("Advanced"); adv.setObjectName("settingsSection")
        layout.addWidget(adv)

        # Working dir
        wd_row = QHBoxLayout(); wd_row.setSpacing(10)
        wd_row.addWidget(self._lbl("Working dir"))
        self._cwd_edit = QLineEdit(self._cfg.get("agent_cwd", "~"))
        self._cwd_edit.setObjectName("settingsInput"); self._cwd_edit.setFixedHeight(ROW_H)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("settingsBrowse"); browse_btn.setFixedSize(BTN_W, ROW_H)
        browse_btn.clicked.connect(self._browse_cwd)
        wd_row.addWidget(self._cwd_edit, 1); wd_row.addWidget(browse_btn)
        layout.addLayout(wd_row)

        # pi binary
        pi_row = QHBoxLayout(); pi_row.setSpacing(10)
        pi_row.addWidget(self._lbl("pi binary"))
        self._pi_edit = QLineEdit(self._cfg.get("pi_bin", ""))
        self._pi_edit.setObjectName("settingsInput"); self._pi_edit.setFixedHeight(ROW_H)
        detect_btn = QPushButton("Detect")
        detect_btn.setObjectName("settingsBrowse"); detect_btn.setFixedSize(BTN_W, ROW_H)
        detect_btn.clicked.connect(self._detect_pi)
        pi_row.addWidget(self._pi_edit, 1); pi_row.addWidget(detect_btn)
        layout.addLayout(pi_row)

        # Font size
        font_row = QHBoxLayout(); font_row.setSpacing(10)
        font_row.addWidget(self._lbl("Font size"))
        self._font_size_edit = QLineEdit(str(self._cfg.get("font_size", 13)))
        self._font_size_edit.setObjectName("settingsInput")
        self._font_size_edit.setFixedSize(64, ROW_H)
        font_row.addWidget(self._font_size_edit)
        font_row.addStretch()
        layout.addLayout(font_row)

        # Terminal size
        term_row = QHBoxLayout(); term_row.setSpacing(10)
        term_row.addWidget(self._lbl("Terminal size"))
        self._cols_edit = QLineEdit(str(self._cfg.get("terminal_cols", 118)))
        self._cols_edit.setObjectName("settingsInput"); self._cols_edit.setFixedSize(52, ROW_H)
        self._rows_edit = QLineEdit(str(self._cfg.get("terminal_rows", 34)))
        self._rows_edit.setObjectName("settingsInput"); self._rows_edit.setFixedSize(52, ROW_H)
        x_lbl = QLabel("×"); x_lbl.setFixedWidth(14)
        term_row.addWidget(self._cols_edit)
        term_row.addWidget(x_lbl)
        term_row.addWidget(self._rows_edit)
        term_row.addStretch()
        layout.addLayout(term_row)

        # Actions
        act_row = QHBoxLayout(); act_row.setSpacing(10)
        agent_btn = QPushButton("⚡  Switch to Agent Mode")
        agent_btn.setObjectName("agentSwitchBtn"); agent_btn.setFixedHeight(ROW_H)
        agent_btn.clicked.connect(self.switch_agent.emit)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveBtn"); save_btn.setFixedHeight(ROW_H)
        save_btn.clicked.connect(self._save)
        act_row.addWidget(agent_btn); act_row.addStretch(); act_row.addWidget(save_btn)
        layout.addLayout(act_row)

    def _browse_cwd(self):
        d = QFileDialog.getExistingDirectory(
            self, "Choose working directory",
            os.path.expanduser(self._cwd_edit.text()))
        if d:
            self._cwd_edit.setText(d)

    def _detect_pi(self):
        p = find_pi_binary()
        self._pi_edit.setText(p if p else "not found — install: npm install -g @badlogic/pi")

    def _save(self):
        idx = self._model_combo.currentIndex()
        self._cfg["model"]         = AVAILABLE_MODELS[idx][1]
        self._cfg["agent_cwd"]     = self._cwd_edit.text()
        self._cfg["pi_bin"]        = self._pi_edit.text()
        try:
            self._cfg["font_size"] = int(self._font_size_edit.text())
        except ValueError:
            pass
        try:
            self._cfg["terminal_cols"] = int(self._cols_edit.text())
            self._cfg["terminal_rows"] = int(self._rows_edit.text())
        except ValueError:
            pass
        self.saved.emit(self._cfg)


# ─── Main Window ─────────────────────────────────────────────────────────────

class SpotlightWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._cfg           = load_config()
        self._current_model = self._cfg["model"]
        self._mode          = "quick"
        self._worker        = None   # PiWorker  (quick)
        self._pty_worker    = None   # PtyWorker (agent)
        self._term_widget   = None   # TerminalWidget
        self._expanded      = False
        self._settings_open = False
        self._in_thinking   = False

        self._setup_window()
        self._setup_ui()

    # ── Window ────────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(WINDOW_W_QUICK)
        self.setFixedHeight(WINDOW_H_QUICK)
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = int(screen.height() * self._cfg.get("position_y_fraction", 0.10))
        self.move(x, y)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._card = QWidget()
        self._card.setObjectName("card")
        self._card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(10)

        # ── Header ──
        hdr = QHBoxLayout(); hdr.setSpacing(10)

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
        for idx, (_, mid) in enumerate(AVAILABLE_MODELS):
            if mid == self._current_model:
                self._model_picker.setCurrentIndex(idx)
                break
        self._model_picker.currentIndexChanged.connect(self._on_model_changed)
        self._model_picker.setFocusPolicy(Qt.NoFocus)
        self._model_picker.setFixedHeight(36)
        self._model_picker.setMinimumWidth(120)

        self._mode_btn = QPushButton("⚡ Agent")
        self._mode_btn.setObjectName("modeBtn")
        self._mode_btn.setFixedHeight(36)
        self._mode_btn.setFocusPolicy(Qt.NoFocus)
        self._mode_btn.clicked.connect(self._toggle_mode)

        self._gear_btn = QPushButton("⚙")
        self._gear_btn.setObjectName("gearBtn")
        self._gear_btn.setFixedSize(36, 36)
        self._gear_btn.setFocusPolicy(Qt.NoFocus)
        self._gear_btn.clicked.connect(self._toggle_settings)

        hdr.addWidget(self._icon)
        hdr.addWidget(self._input, 1)
        hdr.addWidget(self._model_picker)
        hdr.addWidget(self._mode_btn)
        hdr.addWidget(self._gear_btn)
        hdr.addWidget(self._spinner)

        # ── Divider ──
        self._divider = QWidget()
        self._divider.setObjectName("divider")
        self._divider.setFixedHeight(1)
        self._divider.hide()

        # ── Quick response area ──
        self._response = QTextEdit()
        self._response.setObjectName("response")
        self._response.setReadOnly(True)
        self._response.setMinimumHeight(200)
        self._response.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._response.setLineWrapMode(QTextEdit.WidgetWidth)
        self._response.hide()

        # ── Agent: terminal container ──
        # TerminalWidget is created/destroyed on mode switch
        self._term_container = QWidget()
        self._term_container.setObjectName("termContainer")
        self._term_container.hide()
        self._term_layout = QVBoxLayout(self._term_container)
        self._term_layout.setContentsMargins(0, 0, 0, 0)
        self._term_layout.setSpacing(0)

        # ── Hints ──
        self._hint = QLabel(
            "↵ ask  ·  esc close"
        )
        self._hint.setObjectName("hint")
        self._hint.setAlignment(Qt.AlignCenter)

        self._agent_hint = QLabel("")
        self._agent_hint.hide()

        # ── Settings ──
        self._settings_panel = SettingsPanel(self._cfg)
        self._settings_panel.setObjectName("settingsPanel")
        self._settings_panel.saved.connect(self._on_settings_saved)
        self._settings_panel.switch_agent.connect(self._switch_to_agent_from_settings)
        self._settings_panel.closed.connect(self._close_settings)
        self._settings_panel.hide()

        cl.addLayout(hdr)
        cl.addWidget(self._divider)
        cl.addWidget(self._response, 1)
        cl.addWidget(self._term_container, 1)
        cl.addWidget(self._hint)
        cl.addWidget(self._settings_panel)

        root.addWidget(self._card, 1)
        self._apply_styles()

        # Spinner animation
        self._spin_chars = ["◐", "◓", "◑", "◒"]
        self._spin_idx   = 0
        self._spin_timer = QTimer()
        self._spin_timer.timeout.connect(self._tick_spinner)

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        fs = self._cfg.get("font_size", 13)
        ff = self._cfg.get("font_family", "JetBrains Mono")
        mono = f"'{ff}', 'Fira Code', 'Cascadia Code', monospace"

        self.setStyleSheet(f"""
            QWidget#card {{
                background: rgba(18, 18, 22, 0.93);
                border-radius: 16px;
                border: 1px solid rgba(255,255,255,0.08);
            }}
            QLabel#icon {{
                color: #7c6af7;
                font-size: 18px;
                background: rgba(124,106,247,0.15);
                border-radius: 8px;
                font-family: monospace;
            }}
            QLineEdit#input {{
                background: transparent;
                border: none;
                color: #f0eeff;
                font-size: 18px;
                font-family: 'SF Pro Display','Segoe UI','Noto Sans',sans-serif;
                selection-background-color: #7c6af7;
            }}
            QLabel#spinner {{ color:#7c6af7; font-size:16px; }}
            QComboBox#modelPicker {{
                background: rgba(124,106,247,0.12);
                border: 1px solid rgba(124,106,247,0.25);
                border-radius: 6px;
                color: rgba(180,170,255,0.85);
                font-size: 12px;
                padding: 0 8px;
            }}
            QComboBox#modelPicker:hover {{ border-color: rgba(124,106,247,0.55); }}
            QComboBox#modelPicker::drop-down {{ border:none; width:16px; }}
            QComboBox#modelPicker::down-arrow {{
                image:none;
                border-left:4px solid transparent;
                border-right:4px solid transparent;
                border-top:5px solid rgba(124,106,247,0.7);
            }}
            QComboBox QAbstractItemView {{
                background: rgba(22,20,32,0.97);
                border: 1px solid rgba(124,106,247,0.3);
                border-radius: 8px;
                color: #c8c0f5;
                font-size:12px;
                selection-background-color: rgba(124,106,247,0.35);
                padding:4px;
            }}
            QPushButton#modeBtn {{
                background: rgba(255,200,50,0.10);
                border: 1px solid rgba(255,200,50,0.25);
                border-radius: 6px;
                color: rgba(255,210,80,0.85);
                font-size: 12px;
                padding: 0 10px;
            }}
            QPushButton#modeBtn:hover {{
                background: rgba(255,200,50,0.20);
                border-color: rgba(255,200,50,0.5);
            }}
            QPushButton#modeBtn[mode="quick"] {{
                background: rgba(100,200,150,0.10);
                border-color: rgba(100,200,150,0.25);
                color: rgba(120,220,160,0.85);
            }}
            QPushButton#gearBtn {{
                background: transparent;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px;
                color: rgba(160,150,210,0.6);
                font-size: 16px;
            }}
            QPushButton#gearBtn:hover {{
                background: rgba(255,255,255,0.05);
                color: rgba(180,170,255,0.9);
            }}
            QWidget#divider {{ background: rgba(255,255,255,0.07); }}
            QTextEdit#response {{
                background: transparent;
                border: none;
                color: #c8c0f5;
                font-size: {fs}px;
                font-family: {mono};
                selection-background-color: #7c6af7;
            }}
            QWidget#termContainer {{
                background: {TERM_BG_DEFAULT};
                border-radius: 8px;
                border: 1px solid rgba(124,106,247,0.15);
            }}
            QScrollBar:vertical {{
                background: transparent; width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(124,106,247,0.4);
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QLabel#hint {{
                color: rgba(150,140,200,0.35);
                font-size: 11px;
                font-family: 'Noto Sans',sans-serif;
                padding-top: 2px;
            }}
            /* settings */
            QWidget#settingsPanel {{
                background: rgba(14,13,20,0.6);
                border-top: 1px solid rgba(255,255,255,0.07);
                border-radius: 0 0 14px 14px;
            }}
            QLabel#settingsTitle {{
                color: rgba(180,170,255,0.5);
                font-size:10px; font-family:monospace; letter-spacing:2px;
            }}
            QLabel#settingsSection {{
                color: rgba(150,140,200,0.4);
                font-size:10px; font-family:monospace; letter-spacing:1px;
            }}
            QPushButton#settingsClose {{
                background:transparent; border:none;
                color: rgba(200,180,255,0.4); font-size:14px;
            }}
            QPushButton#settingsClose:hover {{ color:#e06c6c; }}
            QWidget#settingsPanel QLabel {{ color:rgba(180,170,255,0.7); font-size:12px; }}
            QComboBox#settingsCombo {{
                background: rgba(124,106,247,0.12);
                border: 1px solid rgba(124,106,247,0.25);
                border-radius:5px; color:#c8c0f5; font-size:12px;
                padding:2px 8px; min-width:140px;
            }}
            QComboBox#settingsCombo QAbstractItemView {{
                background:rgba(22,20,32,0.97);
                border:1px solid rgba(124,106,247,0.3);
                color:#c8c0f5;
                selection-background-color:rgba(124,106,247,0.35);
            }}
            QLineEdit#settingsInput {{
                background:rgba(255,255,255,0.05);
                border:1px solid rgba(255,255,255,0.1);
                border-radius:5px; color:#c8c0f5;
                font-size:12px; font-family:monospace;
                padding:4px 8px; min-height:28px;
            }}
            QPushButton#toolsBtn {{
                background:rgba(124,106,247,0.10);
                border:1px solid rgba(124,106,247,0.2);
                border-radius:5px; color:rgba(180,170,255,0.7);
                font-size:11px; padding:3px 10px;
            }}
            QPushButton#toolsBtn:checked {{
                background:rgba(124,106,247,0.30);
                border-color:rgba(124,106,247,0.6); color:#c8c0f5;
            }}
            QPushButton#settingsBrowse {{
                background:rgba(255,255,255,0.06);
                border:1px solid rgba(255,255,255,0.1);
                border-radius:5px; color:rgba(180,170,255,0.7);
                font-size:11px; padding:3px 10px;
            }}
            QPushButton#settingsBrowse:hover {{
                background:rgba(255,255,255,0.10); color:#c8c0f5;
            }}
            QFrame#settingsDivider {{ color:rgba(255,255,255,0.07); }}
            QPushButton#agentSwitchBtn {{
                background:rgba(255,200,50,0.10);
                border:1px solid rgba(255,200,50,0.25);
                border-radius:6px; color:rgba(255,210,80,0.85);
                font-size:12px; padding:4px 14px;
            }}
            QPushButton#agentSwitchBtn:hover {{ background:rgba(255,200,50,0.20); }}
            QPushButton#saveBtn {{
                background:rgba(124,106,247,0.25);
                border:1px solid rgba(124,106,247,0.5);
                border-radius:6px; color:#c8c0f5;
                font-size:12px; padding:4px 18px;
            }}
            QPushButton#saveBtn:hover {{ background:rgba(124,106,247,0.40); }}
        """)

    # ── paint (glow shadow) ───────────────────────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for i in range(10, 0, -1):
            color = QColor(80, 60, 200, max(0, 4 - abs(i - 5)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            r = QPainterPath()
            r.addRoundedRect(4 - i, 4 - i,
                             self.width() - 8 + i * 2,
                             self.height() - 8 + i * 2,
                             16 + i, 16 + i)
            painter.drawPath(r)

    # ── Toggle show/hide ──────────────────────────────────────────────────────

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
        elif self._term_widget:
            self._term_widget.setFocus()

    def _hide_window(self):
        if self._worker:
            self._worker.stop()
        self._destroy_terminal()
        QApplication.quit()

    # ── Quick mode ────────────────────────────────────────────────────────────

    def _expand_response(self):
        if self._expanded:
            return
        self._expanded = True
        self._divider.show()
        self._response.show()
        self._set_window_size(WINDOW_W_QUICK, WINDOW_H_QUICK_X)

    def _collapse_response(self):
        self._expanded = False
        self._response.clear()
        self._response.hide()
        self._divider.hide()
        self._spinner.setText("")
        self._spin_timer.stop()
        self._set_window_size(WINDOW_W_QUICK, WINDOW_H_QUICK)

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

        # Hide quick-mode widgets
        self._input.hide()
        self._model_picker.hide()
        self._hint.hide()
        self._collapse_response()
        self._response.hide()

        # Show agent widgets
        self._divider.show()
        self._agent_hint.show()
        self._icon.setText("⚡")
        self._close_settings()

        # Create & attach terminal widget
        self._create_terminal()

    def _enter_quick_mode(self):
        if self._mode == "quick":
            return
        self._destroy_terminal()
        self._mode = "quick"
        self._mode_btn.setText("⚡ Agent")
        self._mode_btn.setProperty("mode", "")
        self._mode_btn.style().polish(self._mode_btn)

        self._term_container.hide()
        self._agent_hint.hide()
        self._divider.hide()

        self._input.show()
        self._model_picker.show()
        self._hint.show()
        self._icon.setText("⌘")
        self._input.setPlaceholderText("Ask anything…")
        self._set_window_size(WINDOW_W_QUICK, WINDOW_H_QUICK)
        self._input.setFocus()

    def _switch_to_agent_from_settings(self):
        self._close_settings()
        self._enter_agent_mode()

    # ── Terminal lifecycle ────────────────────────────────────────────────────

    def _create_terminal(self):
        """Build TerminalWidget, start PTY, resize window to fit."""
        self._destroy_terminal()

        cols = self._cfg.get("terminal_cols", 118)
        rows = self._cfg.get("terminal_rows", 34)
        ff   = self._cfg.get("font_family", "JetBrains Mono")
        fs   = self._cfg.get("font_size", 13)

        term = TerminalWidget(cols, rows, ff, fs, parent=self._term_container)
        self._term_layout.addWidget(term)
        self._term_container.show()
        self._term_widget = term

        # Window size = terminal pixel size + card chrome
        # chrome: left(20)+right(20) margins + top(16)+hdr(40)+sp(10)+div(1)+sp(10) + sp(10)+hint(15)+bot(16)
        win_w = term.width()  + CARD_MARGIN_H
        win_h = term.height() + CARD_MARGIN_V
        self._set_window_size(win_w, win_h)

        # Start PTY
        pi_bin = self._cfg.get("pi_bin", "") or find_pi_binary()
        cwd    = self._cfg.get("agent_cwd", "~")
        w = PtyWorker(pi_bin, self._current_model, cwd, cols, rows)
        w.output.connect(term.feed)
        w.finished.connect(self._on_pty_done)
        w.start()
        self._pty_worker = w

        term.attach_pty(w)
        term.setFocus()

    def _destroy_terminal(self):
        if self._pty_worker:
            self._pty_worker.stop()
            self._pty_worker.wait(3000)
            self._pty_worker = None
        if self._term_widget:
            self._term_layout.removeWidget(self._term_widget)
            self._term_widget.deleteLater()
            self._term_widget = None

    def _on_pty_done(self):
        """PTY process exited — show a brief overlay message in the terminal."""
        if self._term_widget:
            self._term_widget.feed(
                b"\r\n\x1b[38;5;240m[pi session ended - ctrl+n to restart]\x1b[0m\r\n"
            )

    def _restart_session(self):
        """ctrl+n: destroy and recreate the terminal + PTY."""
        self._create_terminal()

    # ── Quick-mode submission ─────────────────────────────────────────────────

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
        tools  = "read"

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
        self._insert_html(
            f'<span style="color:#6b5fbf;font-size:12px;font-style:italic;">'
            f'{html.escape(text).replace(chr(10), "<br>")}</span>'
        )

    def _on_chunk(self, text: str):
        if self._in_thinking:
            self._in_thinking = False
            self._insert_html(
                '<br><span style="color:rgba(124,106,247,0.3);">──────────────────</span><br>'
            )
        self._insert_html(
            f'<span style="color:#c8c0f5;font-size:14px;">'
            f'{html.escape(text).replace(chr(10), "<br>")}</span>'
        )

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


    # ── Settings ──────────────────────────────────────────────────────────────

    def _toggle_settings(self):
        if self._settings_open:
            self._close_settings()
        else:
            self._open_settings()

    def _open_settings(self):
        self._settings_open = True
        self._settings_panel.deleteLater()
        self._settings_panel = SettingsPanel(self._cfg)
        self._settings_panel.setObjectName("settingsPanel")
        self._settings_panel.saved.connect(self._on_settings_saved)
        self._settings_panel.switch_agent.connect(self._switch_to_agent_from_settings)
        self._settings_panel.closed.connect(self._close_settings)
        self._card.layout().addWidget(self._settings_panel)
        self._apply_styles()
        self._settings_panel.show()
        # Let Qt compute the natural height before we measure it
        self._settings_panel.adjustSize()
        self._resize_for_content()

    def _close_settings(self):
        if not self._settings_open:
            return
        self._settings_open = False
        self._settings_panel.hide()
        self._resize_for_content()

    def _set_window_size(self, w: int, h: int):
        self.setFixedWidth(w)
        self.setFixedHeight(h)
        self._center_on_screen()

    def _settings_height(self) -> int:
        """Actual height the settings panel needs, measured after adjustSize()."""
        if not self._settings_open:
            return 0
        return self._settings_panel.sizeHint().height() + 8  # +8 breathing room

    def _resize_for_content(self):
        extra = self._settings_height()
        w_open = self._settings_open
        if self._mode == "agent" and self._term_widget:
            base_w = self._term_widget.width()  + CARD_MARGIN_H
            base_h = self._term_widget.height() + CARD_MARGIN_V
            self._set_window_size(base_w, base_h + extra)
        elif self._expanded:
            w = WINDOW_W_SETTINGS if w_open else WINDOW_W_QUICK
            self._set_window_size(w, WINDOW_H_QUICK_X + extra)
        else:
            w = WINDOW_W_SETTINGS if w_open else WINDOW_W_QUICK
            self._set_window_size(w, WINDOW_H_QUICK + extra)

    def _on_settings_saved(self, new_cfg: dict):
        global AVAILABLE_MODELS
        self._cfg           = new_cfg
        self._current_model = new_cfg.get("model", self._current_model)
        AVAILABLE_MODELS = load_pi_models()
        save_config(self._cfg)
        self._apply_styles()
        self._close_settings()
        # Rebuild model picker with refreshed list
        self._model_picker.blockSignals(True)
        self._model_picker.clear()
        for label, _ in AVAILABLE_MODELS:
            self._model_picker.addItem(label)
        cur = self._current_model
        for idx, (_, mid) in enumerate(AVAILABLE_MODELS):
            if mid == cur:
                self._model_picker.setCurrentIndex(idx)
                break
        self._model_picker.blockSignals(False)
        # Recreate terminal if in agent mode (new font/size/cols may apply)
        if self._mode == "agent":
            self._create_terminal()

    # ── Key events ────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        if key == Qt.Key_Escape:
            self._hide_window()
            return

        if self._mode == "agent":
            # Agent-mode window-level shortcuts (not forwarded to terminal)
            if key == Qt.Key_Q and mods == Qt.ControlModifier:
                self._enter_quick_mode()
                return
            if key == Qt.Key_N and mods == Qt.ControlModifier:
                self._restart_session()
                return
            if key == Qt.Key_L and mods == Qt.ControlModifier:
                # Clear screen — send Ctrl+L to terminal
                if self._term_widget:
                    self._term_widget._write(b"\x0c")
                return
            # Everything else → terminal widget
            if self._term_widget:
                self._term_widget.keyPressEvent(event)
            return

        # Quick mode — no extra shortcuts
        super().keyPressEvent(event)

# ─── Toggle helper ────────────────────────────────────────────────────────────

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("pi-spotlight")
    app.setQuitOnLastWindowClosed(True)

    win = SpotlightWindow()
    win._show_window()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
