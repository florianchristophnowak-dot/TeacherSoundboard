import json
import os
import math
import random
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import Qt, QPoint, QPointF, QUrl, QRectF, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import (
    QAction, QPixmap, QGuiApplication, QPainter, QPen, QBrush,
    QRadialGradient, QColor, QFont, QPainterPath, QTransform, QKeySequence, QShortcut
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QLabel,
    QMenu, QHBoxLayout, QVBoxLayout, QMessageBox, QDialog, QGridLayout,
    QLineEdit, QPushButton, QFrame, QSlider, QComboBox, QSpinBox, QCheckBox,
    QGroupBox, QKeySequenceEdit, QToolTip
)

from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PyQt6.QtMultimediaWidgets import QVideoWidget


APP_NAME = "Teacher Soundboard"
VERSION = "v4.2.0"
CONFIG_FILE = "soundboard_config.json"

DEFAULT_BUTTONS = 6
MAX_BUTTONS = 8

# Layout / sizing
SPACING = 10
MARGIN = 10  # transparent "handle" area around coins (easier right-click + drag)

# Visual coin diameter range
MIN_COIN = 44
MAX_COIN = 92

# playful size multipliers for up to 8 coins (first 6 match previous feel)
SIZE_MULT = [1.00, 0.88, 1.12, 0.82, 1.06, 0.93, 1.10, 0.86]

SNAP_THRESHOLD_PX = 80

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".wmv", ".mkv", ".webm"}

CLIP_CUSTOM_IMAGES_TO_CIRCLE = True

# Default hotkeys for buttons (F1-F8 as default, easily reachable)
DEFAULT_HOTKEYS = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]

# Try to import pynput for global hotkeys (cross-platform)
GLOBAL_HOTKEYS_AVAILABLE = False
try:
    from pynput import keyboard as pynput_keyboard
    GLOBAL_HOTKEYS_AVAILABLE = True
except ImportError:
    pass


def get_config_path() -> Path:
    if os.name == "nt":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        cfg_dir = Path(root) / "TeacherSoundboard"
    else:
        cfg_dir = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "TeacherSoundboard"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / CONFIG_FILE


@dataclass
class ButtonConfig:
    media_path: str = ""
    image_path: str = ""
    hotkey: str = ""  # e.g. "F1", "ctrl+1", "alt+shift+a"


@dataclass
class AppConfig:
    dock_edge: str = "top"  # left/right/top/bottom
    volume: float = 0.75    # 0.0 .. 1.0
    video_mode: str = "fullscreen_burst"  # large | fullscreen | fullscreen_burst
    burst_seconds: float = 1.6
    visible_buttons: int = DEFAULT_BUTTONS
    audio_device: str = ""  # empty = system default, else device description
    global_hotkeys_enabled: bool = True  # enable/disable global hotkeys
    stop_hotkey: str = "Escape"  # global hotkey to stop playback
    buttons: list = None


# ---------------- Global Hotkey Manager ----------------
class GlobalHotkeyManager:
    """Cross-platform global hotkey manager using pynput."""
    
    def __init__(self):
        self.listener: Optional[pynput_keyboard.GlobalHotKeys] = None
        self.callbacks: dict[str, Callable] = {}
        self.enabled = False
        self._pending_restart = False
    
    def _normalize_hotkey(self, hotkey: str) -> str:
        """Normalize hotkey string for pynput format."""
        if not hotkey:
            return ""
        
        hotkey = hotkey.strip().lower()
        
        # Map Qt-style modifiers to pynput style
        replacements = [
            ("ctrl+", "<ctrl>+"),
            ("control+", "<ctrl>+"),
            ("alt+", "<alt>+"),
            ("shift+", "<shift>+"),
            ("meta+", "<cmd>+"),
            ("win+", "<cmd>+"),
            ("cmd+", "<cmd>+"),
        ]
        
        for old, new in replacements:
            hotkey = hotkey.replace(old, new)
        
        # Handle function keys
        for i in range(1, 13):
            if hotkey == f"f{i}" or hotkey.endswith(f"+f{i}"):
                hotkey = hotkey.replace(f"f{i}", f"<f{i}>")
        
        # Handle special keys
        special_keys = {
            "escape": "<esc>",
            "esc": "<esc>",
            "space": "<space>",
            "enter": "<enter>",
            "return": "<enter>",
            "tab": "<tab>",
            "backspace": "<backspace>",
            "delete": "<delete>",
            "del": "<delete>",
            "home": "<home>",
            "end": "<end>",
            "pageup": "<page_up>",
            "pagedown": "<page_down>",
            "up": "<up>",
            "down": "<down>",
            "left": "<left>",
            "right": "<right>",
        }
        
        for old, new in special_keys.items():
            if hotkey == old or hotkey.endswith(f"+{old}"):
                hotkey = hotkey.replace(old, new)
        
        return hotkey
    
    def register(self, hotkey: str, callback: Callable) -> bool:
        """Register a hotkey with its callback."""
        if not GLOBAL_HOTKEYS_AVAILABLE:
            return False
        
        normalized = self._normalize_hotkey(hotkey)
        if not normalized:
            return False
        
        self.callbacks[normalized] = callback
        self._pending_restart = True
        return True
    
    def unregister(self, hotkey: str) -> bool:
        """Unregister a hotkey."""
        normalized = self._normalize_hotkey(hotkey)
        if normalized in self.callbacks:
            del self.callbacks[normalized]
            self._pending_restart = True
            return True
        return False
    
    def clear_all(self):
        """Clear all registered hotkeys."""
        self.callbacks.clear()
        self._pending_restart = True
    
    def start(self):
        """Start listening for global hotkeys."""
        if not GLOBAL_HOTKEYS_AVAILABLE or not self.callbacks:
            return
        
        self.stop()
        
        try:
            self.listener = pynput_keyboard.GlobalHotKeys(self.callbacks)
            self.listener.start()
            self.enabled = True
            self._pending_restart = False
        except Exception as e:
            print(f"Failed to start global hotkeys: {e}")
            self.enabled = False
    
    def stop(self):
        """Stop listening for global hotkeys."""
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None
        self.enabled = False
    
    def restart_if_needed(self):
        """Restart listener if there are pending changes."""
        if self._pending_restart and self.callbacks:
            self.start()


# ---------------- Video Overlay (Safety) ----------------
class VideoOverlay(QWidget):
    closeRequested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.video = QVideoWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._burst_timer = QTimer(self)
        self._burst_timer.setSingleShot(True)
        self._burst_timer.timeout.connect(self._end_burst_to_large)

        self._current_screen_geom = None
        self.video.installEventFilter(self)

    def set_player(self, player: QMediaPlayer):
        player.setVideoOutput(self.video)

    def show_video(self, screen_geom, mode: str, burst_seconds: float = 1.6):
        self._current_screen_geom = screen_geom
        mode = (mode or "large").lower().strip()
        if mode not in ("large", "fullscreen", "fullscreen_burst"):
            mode = "large"

        self._burst_timer.stop()

        if mode == "fullscreen":
            self._show_fullscreen_on_geom(screen_geom)
            return

        if mode == "fullscreen_burst":
            self._show_fullscreen_on_geom(screen_geom)
            ms = max(200, int(burst_seconds * 1000))
            self._burst_timer.start(ms)
            return

        self._show_large_on_geom(screen_geom)

    def hide_video(self):
        self._burst_timer.stop()
        self.showNormal()
        self.hide()

    def _show_fullscreen_on_geom(self, g):
        self._burst_timer.stop()
        self.showNormal()
        self.setGeometry(g)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.showFullScreen()

    def _show_large_on_geom(self, g):
        self._burst_timer.stop()
        self.showNormal()

        max_w = int(g.width() * 0.75)
        max_h = int(g.height() * 0.75)

        w = min(max_w, 1280)
        h = int(w * 9 / 16)
        if h > max_h:
            h = max_h
            w = int(h * 16 / 9)

        x = g.left() + (g.width() - w) // 2
        y = g.top() + (g.height() - h) // 2

        self.setGeometry(x, y, w, h)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _end_burst_to_large(self):
        if not self._current_screen_geom:
            return
        self._show_large_on_geom(self._current_screen_geom)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Backspace):
            self.closeRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.video and event.type() == event.Type.MouseButtonPress:
            self.closeRequested.emit()
            return True
        return super().eventFilter(obj, event)


# ---------------- Coin Rendering ----------------
def _pick_comic_font(size_px: int) -> QFont:
    candidates = ["Comic Sans MS", "Segoe Print", "Arial Rounded MT Bold", "Segoe UI", "Arial"]
    f = QFont(candidates[0])
    f.setBold(True)
    f.setPointSizeF(max(10.0, size_px * 0.42))
    return f


def make_coin_pixmap(size: int, number: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    rng = random.Random(1337 + number)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(1.5, 1.5, size - 3.0, size - 3.0)
    center = rect.center()

    palettes = [
        (QColor(240, 205, 90), QColor(170, 120, 20)),
        (QColor(210, 210, 220), QColor(120, 120, 130)),
        (QColor(200, 140, 90), QColor(120, 70, 35)),
    ]
    base_c, edge_c = palettes[(number - 1) % len(palettes)]

    grad = QRadialGradient(
        center,
        rect.width() * 0.60,
        center - QPointF(rect.width() * 0.18, rect.height() * 0.22)
    )
    grad.setColorAt(0.00, QColor(min(base_c.red()+35,255), min(base_c.green()+35,255), min(base_c.blue()+35,255)))
    grad.setColorAt(0.45, base_c)
    grad.setColorAt(1.00, edge_c)

    p.setBrush(QBrush(grad))
    p.setPen(QPen(edge_c, max(2.0, size * 0.04)))
    p.drawEllipse(rect)

    inner = rect.adjusted(size*0.10, size*0.10, -size*0.10, -size*0.10)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255,255,255,120), max(1.0, size*0.018)))
    p.drawEllipse(inner)

    dot_r = max(1.2, size * 0.018)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(255, 255, 255, 120)))
    dot_count = 18
    for i in range(dot_count):
        ang = (i / dot_count) * 2 * math.pi
        rr = rect.width() * 0.45
        x = center.x() + math.cos(ang) * rr
        y = center.y() + math.sin(ang) * rr
        p.drawEllipse(QRectF(x - dot_r, y - dot_r, dot_r*2, dot_r*2))

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 140), max(2.0, size*0.03), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    arc_rect = rect.adjusted(size*0.08, size*0.08, -size*0.08, -size*0.08)
    p.drawArc(arc_rect, int(30 * 16), int(110 * 16))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(0, 0, 0, 18)))
    for _ in range(18):
        r = rng.uniform(size*0.01, size*0.02)
        x = rng.uniform(inner.left(), inner.right())
        y = rng.uniform(inner.top(), inner.bottom())
        p.drawEllipse(QRectF(x - r, y - r, r*2, r*2))

    num_text = str(number)
    font = _pick_comic_font(size)
    p.setFont(font)

    path = QPainterPath()
    metrics = p.fontMetrics()
    tw = metrics.horizontalAdvance(num_text)
    th = metrics.height()
    tx = center.x() - tw / 2
    ty = center.y() + th / 4
    path.addText(tx, ty, font, num_text)

    angle = rng.uniform(-8.0, 8.0)
    t = QTransform()
    t.translate(center.x(), center.y())
    t.rotate(angle)
    t.translate(-center.x(), -center.y())
    path = t.map(path)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(0, 0, 0, 90)))
    p.drawPath(path.translated(size*0.02, size*0.02))

    p.setBrush(QBrush(QColor(255, 255, 255)))
    p.drawPath(path)

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0), max(2.0, size*0.05), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)

    p.end()
    return pm


def short_path(p: str, max_len: int = 55) -> str:
    if not p:
        return ""
    s = str(p)
    if len(s) <= max_len:
        return s
    keep = max_len - 5
    left = keep // 2
    right = keep - left
    return s[:left] + " … " + s[-right:]


# ---------------- Hotkey Edit Widget ----------------
class HotkeyEdit(QLineEdit):
    """Custom widget for capturing keyboard shortcuts."""
    
    hotkeyChanged = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Klicken und Taste drücken...")
        self._recording = False
        self.setStyleSheet("""
            QLineEdit {
                background: #f5f5f5;
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 4px 8px;
            }
            QLineEdit:focus {
                background: #fff8e0;
                border-color: #f0a030;
            }
        """)
    
    def mousePressEvent(self, event):
        self._recording = True
        self.setStyleSheet("""
            QLineEdit {
                background: #fff8e0;
                border: 2px solid #f0a030;
                border-radius: 3px;
                padding: 4px 8px;
            }
        """)
        self.setFocus()
        super().mousePressEvent(event)
    
    def keyPressEvent(self, event):
        if not self._recording:
            super().keyPressEvent(event)
            return
        
        key = event.key()
        
        # Ignore pure modifier keys
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        
        # Clear on Backspace/Delete
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and not event.modifiers():
            self.setText("")
            self._recording = False
            self._reset_style()
            self.hotkeyChanged.emit("")
            return
        
        # Build hotkey string
        parts = []
        mods = event.modifiers()
        
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("Meta")
        
        # Get key name
        key_seq = QKeySequence(key)
        key_str = key_seq.toString()
        
        if key_str:
            parts.append(key_str)
            hotkey = "+".join(parts)
            self.setText(hotkey)
            self._recording = False
            self._reset_style()
            self.hotkeyChanged.emit(hotkey)
    
    def _reset_style(self):
        self.setStyleSheet("""
            QLineEdit {
                background: #f5f5f5;
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 4px 8px;
            }
            QLineEdit:focus {
                background: #fff8e0;
                border-color: #f0a030;
            }
        """)
    
    def focusOutEvent(self, event):
        self._recording = False
        self._reset_style()
        super().focusOutEvent(event)
    
    def setHotkey(self, hotkey: str):
        self.setText(hotkey or "")


# ---------------- Manager UI ----------------
class ManageDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.host = parent

        self.setWindowTitle(f"{APP_NAME} – Verwaltung ({VERSION})")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(1200, 700)

        root = QVBoxLayout(self)

        header = QLabel("Medien, Button-Bilder, Hotkeys, Lautstärke & Audio-Ausgabe")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(header)

        tip = QLabel("Tipp: Wenn du nichts hörst, prüfe auch Windows → Lautstärkemixer (App evtl. stumm).")
        tip.setStyleSheet("color: #444;")
        root.addWidget(tip)

        sub = QLabel("Menü: Rechtsklick auf Münze (oder STRG+Rechtsklick). Drag: ALT+Ziehen.")
        sub.setStyleSheet("color: #666;")
        root.addWidget(sub)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        # ---- Global Settings Row 1 ----
        global_row = QHBoxLayout()
        root.addLayout(global_row)

        # volume
        global_row.addWidget(QLabel("App-Lautstärke:"))
        self.vol_label = QLabel("")
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setSingleStep(1)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        global_row.addWidget(self.vol_slider, 1)
        global_row.addWidget(self.vol_label)

        global_row.addSpacing(18)

        # output device
        global_row.addWidget(QLabel("Audio-Ausgabe:"))
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        global_row.addWidget(self.device_combo)

        global_row.addSpacing(18)

        # video mode
        global_row.addWidget(QLabel("Videoanzeige:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Großes Fenster", "large")
        self.mode_combo.addItem("Vollbild", "fullscreen")
        self.mode_combo.addItem("Kurzer Vollbild-Start (danach groß)", "fullscreen_burst")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        global_row.addWidget(self.mode_combo)

        global_row.addSpacing(18)

        # visible buttons
        global_row.addWidget(QLabel("Buttons anzeigen:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, MAX_BUTTONS)
        self.count_spin.valueChanged.connect(self._on_count_changed)
        global_row.addWidget(self.count_spin)

        global_row.addStretch(1)

        # ---- Hotkey Settings Row ----
        hotkey_group = QGroupBox("Tastenkombinationen (Hotkeys)")
        hotkey_layout = QHBoxLayout(hotkey_group)
        root.addWidget(hotkey_group)
        
        # Global hotkeys checkbox
        self.global_hotkeys_check = QCheckBox("Globale Hotkeys aktivieren")
        self.global_hotkeys_check.setToolTip(
            "Wenn aktiviert, funktionieren Hotkeys auch wenn andere Programme im Fokus sind.\n"
            "Erfordert 'pynput' Library (pip install pynput)."
        )
        self.global_hotkeys_check.stateChanged.connect(self._on_global_hotkeys_changed)
        hotkey_layout.addWidget(self.global_hotkeys_check)
        
        if not GLOBAL_HOTKEYS_AVAILABLE:
            self.global_hotkeys_check.setEnabled(False)
            self.global_hotkeys_check.setToolTip("Globale Hotkeys nicht verfügbar. Installiere pynput: pip install pynput")
        
        hotkey_layout.addSpacing(20)
        
        # Stop hotkey
        hotkey_layout.addWidget(QLabel("Stopp-Hotkey:"))
        self.stop_hotkey_edit = HotkeyEdit()
        self.stop_hotkey_edit.setFixedWidth(120)
        self.stop_hotkey_edit.hotkeyChanged.connect(self._on_stop_hotkey_changed)
        hotkey_layout.addWidget(self.stop_hotkey_edit)
        
        hotkey_layout.addSpacing(20)
        
        # Reset to defaults
        btn_reset_hotkeys = QPushButton("Standard-Hotkeys (F1-F8)")
        btn_reset_hotkeys.clicked.connect(self._reset_hotkeys_to_default)
        hotkey_layout.addWidget(btn_reset_hotkeys)
        
        hotkey_layout.addStretch(1)

        # ---- Hotkey info label ----
        hotkey_info = QLabel(
            "📌 Tastenkombinationen: Klicke in ein Hotkey-Feld und drücke die gewünschte Taste(n). "
            "Backspace/Entf löscht. Lokale Hotkeys (1-8) funktionieren immer wenn Soundboard fokussiert."
        )
        hotkey_info.setStyleSheet("color: #666; font-size: 11px;")
        hotkey_info.setWordWrap(True)
        root.addWidget(hotkey_info)

        line2 = QFrame(); line2.setFrameShape(QFrame.Shape.HLine); line2.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line2)

        # ---- Button Grid ----
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        root.addLayout(grid)

        grid.addWidget(QLabel("Nr."), 0, 0)
        grid.addWidget(QLabel("Vorschau"), 0, 1)
        grid.addWidget(QLabel("Medien (Audio/Video)"), 0, 2)
        grid.addWidget(QLabel("Button-Bild (PNG/JPG)"), 0, 3)
        grid.addWidget(QLabel("Hotkey"), 0, 4)
        grid.addWidget(QLabel("Status"), 0, 5)
        grid.addWidget(QLabel("Aktionen"), 0, 6)

        self.preview_labels = []
        self.media_edits = []
        self.image_edits = []
        self.hotkey_edits = []
        self.status_labels = []

        for i in range(MAX_BUTTONS):
            row = i + 1

            num = QLabel(str(i + 1))
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num.setStyleSheet("font-size: 16px; font-weight: 700;")
            grid.addWidget(num, row, 0)

            prev = QLabel()
            prev.setFixedSize(72, 72)
            prev.setScaledContents(True)
            grid.addWidget(prev, row, 1)
            self.preview_labels.append(prev)

            media_edit = QLineEdit(); media_edit.setReadOnly(True)
            img_edit = QLineEdit(); img_edit.setReadOnly(True)
            grid.addWidget(media_edit, row, 2); grid.addWidget(img_edit, row, 3)
            self.media_edits.append(media_edit); self.image_edits.append(img_edit)

            # Hotkey edit
            hotkey_edit = HotkeyEdit()
            hotkey_edit.setFixedWidth(100)
            idx = i  # capture index
            hotkey_edit.hotkeyChanged.connect(lambda hk, ix=idx: self._on_button_hotkey_changed(ix, hk))
            grid.addWidget(hotkey_edit, row, 4)
            self.hotkey_edits.append(hotkey_edit)

            status = QLabel("")
            grid.addWidget(status, row, 5)
            self.status_labels.append(status)

            actions = QWidget()
            h = QHBoxLayout(actions)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)

            b_media = QPushButton("Medien…")
            b_media.clicked.connect(lambda checked=False, ix=i: self.host.assign_media(ix, refresh=True))
            h.addWidget(b_media)

            b_img = QPushButton("Bild…")
            b_img.clicked.connect(lambda checked=False, ix=i: self.host.assign_image(ix, refresh=True))
            h.addWidget(b_img)

            b_reset_img = QPushButton("Bild ⟲")
            b_reset_img.setToolTip("Button-Bild zurücksetzen (Münze)")
            b_reset_img.clicked.connect(lambda checked=False, ix=i: self.host.clear_image(ix, refresh=True))
            h.addWidget(b_reset_img)

            b_clear = QPushButton("Alles ✕")
            b_clear.setToolTip("Alle Zuweisungen löschen")
            b_clear.clicked.connect(lambda checked=False, ix=i: self.host.clear_assignments(ix, refresh=True))
            h.addWidget(b_clear)

            b_test = QPushButton("▶")
            b_test.setToolTip("Test abspielen")
            b_test.clicked.connect(lambda checked=False, ix=i: self.host.on_coin_clicked(ix))
            h.addWidget(b_test)

            grid.addWidget(actions, row, 6)

        footer = QHBoxLayout()
        root.addLayout(footer)

        self.btn_close = QPushButton("Schließen")
        self.btn_close.clicked.connect(self.accept)
        footer.addStretch(1)
        footer.addWidget(self.btn_close)

        self.refresh()

    def refresh(self):
        v = int(round(self.host.cfg.volume * 100))
        self.vol_slider.blockSignals(True)
        self.vol_slider.setValue(max(0, min(100, v)))
        self.vol_slider.blockSignals(False)
        self.vol_label.setText(f"{self.vol_slider.value()}%")

        # device list
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("Standard (Windows/System)", "")
        devices = self.host.list_audio_devices()
        for d in devices:
            self.device_combo.addItem(d, d)
        current = self.host.cfg.audio_device or ""
        ix = self.device_combo.findData(current)
        if ix < 0:
            ix = 0
        self.device_combo.setCurrentIndex(ix)
        self.device_combo.blockSignals(False)

        # mode
        mode = (self.host.cfg.video_mode or "large").lower().strip()
        ix2 = self.mode_combo.findData(mode)
        self.mode_combo.blockSignals(True)
        if ix2 >= 0:
            self.mode_combo.setCurrentIndex(ix2)
        self.mode_combo.blockSignals(False)

        # count
        self.count_spin.blockSignals(True)
        self.count_spin.setValue(int(self.host.cfg.visible_buttons))
        self.count_spin.blockSignals(False)

        # Global hotkeys
        self.global_hotkeys_check.blockSignals(True)
        self.global_hotkeys_check.setChecked(self.host.cfg.global_hotkeys_enabled)
        self.global_hotkeys_check.blockSignals(False)
        
        # Stop hotkey
        self.stop_hotkey_edit.setHotkey(self.host.cfg.stop_hotkey)

        vis = int(self.host.cfg.visible_buttons)

        for i in range(MAX_BUTTONS):
            cfg = self.host.cfg.buttons[i]
            self.media_edits[i].setText(short_path(cfg.media_path))
            self.image_edits[i].setText(short_path(cfg.image_path))
            self.hotkey_edits[i].setHotkey(cfg.hotkey)
            self.preview_labels[i].setPixmap(self.host.render_coin_preview(i, 72))

            if i < vis:
                self.status_labels[i].setText("sichtbar")
                self.status_labels[i].setStyleSheet("color: #1b6; font-weight: 700;")
            else:
                self.status_labels[i].setText("versteckt")
                self.status_labels[i].setStyleSheet("color: #888;")

    def _on_volume_changed(self, value: int):
        self.vol_label.setText(f"{value}%")
        self.host.set_volume(value / 100.0)

    def _on_device_changed(self, _):
        dev = self.device_combo.currentData()
        self.host.set_audio_device(dev or "")

    def _on_mode_changed(self, _):
        mode = self.mode_combo.currentData()
        if mode:
            self.host.set_video_mode(mode)

    def _on_count_changed(self, value: int):
        self.host.set_visible_buttons(int(value))

    def _on_global_hotkeys_changed(self, state):
        self.host.set_global_hotkeys_enabled(state == Qt.CheckState.Checked.value)

    def _on_stop_hotkey_changed(self, hotkey: str):
        self.host.set_stop_hotkey(hotkey)

    def _on_button_hotkey_changed(self, index: int, hotkey: str):
        self.host.set_button_hotkey(index, hotkey)

    def _reset_hotkeys_to_default(self):
        for i in range(MAX_BUTTONS):
            self.host.set_button_hotkey(i, DEFAULT_HOTKEYS[i] if i < len(DEFAULT_HOTKEYS) else "")
        self.host.set_stop_hotkey("Escape")
        self.refresh()


# ---------------- Custom painted coin bar ----------------
class CoinBar(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for i in range(self.host.visible_count()):
            coin = self.host.coin_rect(i)
            pm = self.host.coin_pixmap(i, int(coin.width()))
            p.drawPixmap(int(round(coin.x())), int(round(coin.y())), pm)

            if self.host.current_index == i and self.host.player.playbackState().name == "PlayingState":
                ring = QRectF(coin).adjusted(-3, -3, 3, 3)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(0, 200, 255, 200), 4))
                p.drawEllipse(ring)

        p.end()

    def mousePressEvent(self, event):
        gp = event.globalPosition().toPoint()
        lp = event.position().toPoint()

        if event.button() == Qt.MouseButton.RightButton and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.host.open_window_menu(gp)
            return

        if event.button() == Qt.MouseButton.RightButton:
            idx = self.host.hit_test(lp)
            if idx is None:
                self.host.open_window_menu(gp)
            else:
                self.host.open_coin_menu(idx, gp)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.host.start_drag(gp)
                event.accept()
                return

            idx = self.host.hit_test(lp)
            if idx is None:
                self.host.start_drag(gp)
            else:
                self.host.on_coin_clicked(idx)
            event.accept()

    def mouseMoveEvent(self, event):
        self.host.drag_move(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.host.end_drag()
            event.accept()


# ---------------- Main Window ----------------
class SoundboardWindow(QMainWindow):
    # Signal for thread-safe hotkey triggering
    hotkeyTriggered = pyqtSignal(int)
    stopTriggered = pyqtSignal()
    
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._dragging = False
        self._drag_offset = QPoint(0, 0)

        self.config_path = get_config_path()
        self.cfg = self.load_config()

        self.current_index: int | None = None
        self.current_is_video = False

        self.coin_sizes = [64] * MAX_BUTTONS
        self.slot_size = 72

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)

        # Apply device + volume right away
        self.apply_audio_device()
        self.apply_volume_to_audio()

        self.player.mediaStatusChanged.connect(self.on_media_status)
        self.player.errorOccurred.connect(self.on_media_error)

        self.video_overlay = VideoOverlay()
        self.video_overlay.set_player(self.player)
        self.video_overlay.closeRequested.connect(self.stop_playback)

        self.bar = CoinBar(self)
        self.setCentralWidget(self.bar)

        self.manager_dialog: ManageDialog | None = None

        # Global hotkey manager
        self.hotkey_manager = GlobalHotkeyManager()
        self.hotkeyTriggered.connect(self._on_hotkey_triggered)
        self.stopTriggered.connect(self.stop_playback)
        
        # Setup hotkeys
        self._setup_global_hotkeys()

        self.apply_dock_edge(self.cfg.dock_edge, snap_now=False)
        self.snap_to_edge(self.cfg.dock_edge)

    def _setup_global_hotkeys(self):
        """Setup global hotkeys from config."""
        if not GLOBAL_HOTKEYS_AVAILABLE or not self.cfg.global_hotkeys_enabled:
            self.hotkey_manager.stop()
            return
        
        self.hotkey_manager.clear_all()
        
        # Register button hotkeys
        for i, btn_cfg in enumerate(self.cfg.buttons):
            if btn_cfg.hotkey:
                idx = i  # capture index
                self.hotkey_manager.register(
                    btn_cfg.hotkey,
                    lambda ix=idx: self.hotkeyTriggered.emit(ix)
                )
        
        # Register stop hotkey
        if self.cfg.stop_hotkey:
            self.hotkey_manager.register(
                self.cfg.stop_hotkey,
                lambda: self.stopTriggered.emit()
            )
        
        self.hotkey_manager.start()

    def _on_hotkey_triggered(self, index: int):
        """Handle hotkey trigger (thread-safe via signal)."""
        if 0 <= index < self.visible_count():
            self.on_coin_clicked(index)

    def set_global_hotkeys_enabled(self, enabled: bool):
        """Enable or disable global hotkeys."""
        self.cfg.global_hotkeys_enabled = enabled
        self.save_config()
        self._setup_global_hotkeys()

    def set_stop_hotkey(self, hotkey: str):
        """Set the stop playback hotkey."""
        self.cfg.stop_hotkey = hotkey
        self.save_config()
        self._setup_global_hotkeys()

    def set_button_hotkey(self, index: int, hotkey: str):
        """Set hotkey for a specific button."""
        if 0 <= index < MAX_BUTTONS:
            self.cfg.buttons[index].hotkey = hotkey
            self.save_config()
            self._setup_global_hotkeys()

    # ---- audio devices
    def list_audio_devices(self) -> list[str]:
        try:
            return [d.description() for d in QMediaDevices.audioOutputs()]
        except Exception:
            return []

    def apply_audio_device(self):
        try:
            wanted = (self.cfg.audio_device or "").strip()
            if not wanted:
                self.audio.setDevice(QMediaDevices.defaultAudioOutput())
                return
            for d in QMediaDevices.audioOutputs():
                if d.description() == wanted:
                    self.audio.setDevice(d)
                    return
            self.audio.setDevice(QMediaDevices.defaultAudioOutput())
        except Exception:
            pass

    def set_audio_device(self, desc: str):
        self.cfg.audio_device = (desc or "").strip()
        self.apply_audio_device()
        self.save_config()
        if self.manager_dialog:
            self.manager_dialog.refresh()

    # ---- helpers
    def visible_count(self) -> int:
        try:
            n = int(self.cfg.visible_buttons)
        except Exception:
            n = DEFAULT_BUTTONS
        return max(1, min(MAX_BUTTONS, n))

    # ---- Drag helpers
    def start_drag(self, global_pos: QPoint):
        self._dragging = True
        self._drag_offset = global_pos - self.frameGeometry().topLeft()

    def drag_move(self, global_pos: QPoint):
        if not self._dragging:
            return
        self.move(global_pos - self._drag_offset)

    def end_drag(self):
        if not self._dragging:
            return
        self._dragging = False
        edge = self.nearest_edge()
        if edge:
            self.apply_dock_edge(edge, snap_now=True)

    # ---- Config
    def load_config(self) -> AppConfig:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))

                buttons = []
                for i, b in enumerate(data.get("buttons", [])):
                    btn = ButtonConfig(**b)
                    # Set default hotkey if not present
                    if not btn.hotkey and i < len(DEFAULT_HOTKEYS):
                        btn.hotkey = DEFAULT_HOTKEYS[i]
                    buttons.append(btn)
                
                while len(buttons) < MAX_BUTTONS:
                    idx = len(buttons)
                    btn = ButtonConfig()
                    if idx < len(DEFAULT_HOTKEYS):
                        btn.hotkey = DEFAULT_HOTKEYS[idx]
                    buttons.append(btn)
                buttons = buttons[:MAX_BUTTONS]

                dock_edge = (data.get("dock_edge", "top") or "top").lower().strip()
                if dock_edge not in ("left", "right", "top", "bottom"):
                    dock_edge = "top"

                volume = float(data.get("volume", 0.75))
                volume = max(0.0, min(1.0, volume))

                video_mode = (data.get("video_mode", "fullscreen_burst") or "fullscreen_burst").lower().strip()
                if video_mode not in ("large", "fullscreen", "fullscreen_burst"):
                    video_mode = "fullscreen_burst"

                burst = float(data.get("burst_seconds", 1.6))
                burst = max(0.2, min(10.0, burst))

                vis = int(data.get("visible_buttons", DEFAULT_BUTTONS))
                vis = max(1, min(MAX_BUTTONS, vis))

                audio_dev = str(data.get("audio_device", "") or "")
                
                global_hotkeys = data.get("global_hotkeys_enabled", True)
                stop_hotkey = data.get("stop_hotkey", "Escape")

                return AppConfig(
                    dock_edge=dock_edge,
                    volume=volume,
                    video_mode=video_mode,
                    burst_seconds=burst,
                    visible_buttons=vis,
                    audio_device=audio_dev,
                    global_hotkeys_enabled=global_hotkeys,
                    stop_hotkey=stop_hotkey,
                    buttons=buttons
                )
            except Exception:
                pass

        # Default config with default hotkeys
        buttons = []
        for i in range(MAX_BUTTONS):
            btn = ButtonConfig()
            if i < len(DEFAULT_HOTKEYS):
                btn.hotkey = DEFAULT_HOTKEYS[i]
            buttons.append(btn)
        
        return AppConfig(
            dock_edge="top",
            volume=0.75,
            video_mode="fullscreen_burst",
            burst_seconds=1.6,
            visible_buttons=DEFAULT_BUTTONS,
            audio_device="",
            global_hotkeys_enabled=True,
            stop_hotkey="Escape",
            buttons=buttons
        )

    def save_config(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "dock_edge": self.cfg.dock_edge,
            "volume": self.cfg.volume,
            "video_mode": self.cfg.video_mode,
            "burst_seconds": self.cfg.burst_seconds,
            "visible_buttons": self.visible_count(),
            "audio_device": self.cfg.audio_device,
            "global_hotkeys_enabled": self.cfg.global_hotkeys_enabled,
            "stop_hotkey": self.cfg.stop_hotkey,
            "buttons": [asdict(b) for b in self.cfg.buttons],
        }
        self.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_visible_buttons(self, n: int):
        n = max(1, min(MAX_BUTTONS, int(n)))
        self.cfg.visible_buttons = n
        self.save_config()

        self.compute_sizes_for_edge(self.cfg.dock_edge)
        self.set_window_size_for_edge(self.cfg.dock_edge)
        self.bar.update()
        self.snap_to_edge(self.cfg.dock_edge)

        if self.manager_dialog:
            self.manager_dialog.refresh()

    # ---- Volume
    def apply_volume_to_audio(self):
        try:
            self.audio.setMuted(False)
        except Exception:
            pass
        self.audio.setVolume(float(self.cfg.volume))

    def set_volume(self, vol: float):
        self.cfg.volume = max(0.0, min(1.0, float(vol)))
        self.apply_volume_to_audio()
        self.save_config()
        if self.manager_dialog:
            self.manager_dialog.refresh()

    # ---- Video settings
    def set_video_mode(self, mode: str):
        mode = (mode or "large").lower().strip()
        if mode not in ("large", "fullscreen", "fullscreen_burst"):
            mode = "large"
        self.cfg.video_mode = mode
        self.save_config()
        if self.manager_dialog:
            self.manager_dialog.refresh()

    # ---- Sizes
    def compute_sizes_for_edge(self, edge: str):
        screen = self.current_screen()
        g = screen.availableGeometry()
        n = self.visible_count()

        available = g.height() if edge in ("left", "right") else g.width()
        total_spacing = SPACING * (n - 1)
        available -= (MARGIN * 2 + total_spacing)

        mult = SIZE_MULT[:n]
        mult_sum = sum(mult) or 1.0
        base = available / mult_sum
        base = max(MIN_COIN, min(MAX_COIN, base))

        sizes = []
        for m in mult:
            s = int(round(base * m))
            s = max(MIN_COIN, min(MAX_COIN, s))
            sizes.append(s)

        while len(sizes) < MAX_BUTTONS:
            sizes.append(max(MIN_COIN, min(MAX_COIN, int(round(base)))))

        self.coin_sizes = sizes
        self.slot_size = max(sizes[:n])

    def set_window_size_for_edge(self, edge: str):
        n = self.visible_count()
        total_spacing = SPACING * (n - 1)
        total_margin = MARGIN * 2

        if edge in ("left", "right"):
            w = self.slot_size + total_margin
            h = n * self.slot_size + total_spacing + total_margin
        else:
            w = n * self.slot_size + total_spacing + total_margin
            h = self.slot_size + total_margin

        self.setFixedSize(int(w), int(h))

    # ---- Geometry helpers
    def slot_rect(self, index: int) -> QRectF:
        edge = self.cfg.dock_edge
        s = self.slot_size
        step = s + SPACING
        if edge in ("left", "right"):
            return QRectF(MARGIN, MARGIN + index * step, s, s)
        return QRectF(MARGIN + index * step, MARGIN, s, s)

    def coin_rect(self, index: int) -> QRectF:
        slot = self.slot_rect(index)
        edge = self.cfg.dock_edge
        coin = self.coin_sizes[index] if index < len(self.coin_sizes) else self.slot_size
        coin = max(10, min(self.slot_size, coin))

        x = slot.x() + (slot.width() - coin) / 2.0
        y = slot.y() + (slot.height() - coin) / 2.0

        if edge == "top":
            y = slot.y()
        elif edge == "bottom":
            y = slot.y() + slot.height() - coin
        elif edge == "left":
            x = slot.x()
        elif edge == "right":
            x = slot.x() + slot.width() - coin

        return QRectF(x, y, coin, coin)

    def hit_test(self, local_pos: QPoint) -> int | None:
        for i in range(self.visible_count()):
            r = self.coin_rect(i)
            cx = r.x() + r.width() / 2.0
            cy = r.y() + r.height() / 2.0
            dx = local_pos.x() + 0.5 - cx
            dy = local_pos.y() + 0.5 - cy
            rr = (min(r.width(), r.height()) / 2.0 - 1.5) ** 2
            if (dx * dx + dy * dy) <= rr:
                return i
        return None

    # ---- Coin images
    def clip_circle(self, pm: QPixmap, size: int) -> QPixmap:
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(QRectF(0, 0, size, size))
        p.setClipPath(path)
        sx = (pm.width() - size) / 2.0
        sy = (pm.height() - size) / 2.0
        p.drawPixmap(QPointF(-sx, -sy), pm)
        p.end()
        return out

    def coin_pixmap(self, index: int, size: int) -> QPixmap:
        cfg = self.cfg.buttons[index]
        if cfg.image_path and Path(cfg.image_path).exists():
            pm = QPixmap(cfg.image_path)
            if not pm.isNull():
                pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                if CLIP_CUSTOM_IMAGES_TO_CIRCLE:
                    pm = self.clip_circle(pm, size)
                return pm
        return make_coin_pixmap(size, index + 1)

    def render_coin_preview(self, index: int, slot: int) -> QPixmap:
        pm = QPixmap(slot, slot)
        pm.fill(Qt.GlobalColor.transparent)

        coin = min(slot, max(10, int(round(slot * (self.coin_sizes[index] / max(self.slot_size, 1))))))
        x = (slot - coin) / 2.0
        y = (slot - coin) / 2.0
        edge = self.cfg.dock_edge
        if edge == "top":
            y = 0.0
        elif edge == "bottom":
            y = slot - coin
        elif edge == "left":
            x = 0.0
        elif edge == "right":
            x = slot - coin

        coin_pm = self.coin_pixmap(index, coin)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPixmap(int(round(x)), int(round(y)), coin_pm)
        p.end()
        return pm

    # ---- Manager
    def open_manager(self):
        if self.manager_dialog is None:
            self.manager_dialog = ManageDialog(self)
        self.manager_dialog.refresh()
        self.manager_dialog.show()
        self.manager_dialog.raise_()
        self.manager_dialog.activateWindow()

    # ---- Menus
    def add_dock_submenu(self, menu: QMenu):
        dock_menu = menu.addMenu("Andocken")
        for edge, label in [("top", "Oben"), ("bottom", "Unten"), ("left", "Links"), ("right", "Rechts")]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.cfg.dock_edge == edge)
            act.triggered.connect(lambda checked=False, e=edge: self.apply_dock_edge(e))
            dock_menu.addAction(act)

    def add_video_submenu(self, menu: QMenu):
        video_menu = menu.addMenu("Videoanzeige")
        for mode, label in [("large", "Großes Fenster"), ("fullscreen", "Vollbild"), ("fullscreen_burst", "Kurzer Vollbild-Start (danach groß)")]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.cfg.video_mode == mode)
            act.triggered.connect(lambda checked=False, m=mode: self.set_video_mode(m))
            video_menu.addAction(act)

    def add_volume_submenu(self, menu: QMenu):
        vol_menu = menu.addMenu("Lautstärke")
        for pct in [0, 25, 50, 75, 100]:
            act = QAction(f"{pct}%", self)
            act.triggered.connect(lambda checked=False, p=pct: self.set_volume(p / 100.0))
            vol_menu.addAction(act)

    def open_window_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #222; color: #eee; }")
        self.add_dock_submenu(menu)
        self.add_video_submenu(menu)
        self.add_volume_submenu(menu)

        act_manage = QAction("Verwalten… (Ctrl+M)", self)
        act_manage.triggered.connect(self.open_manager)
        menu.addAction(act_manage)

        menu.addSeparator()
        act_quit = QAction("Beenden", self)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_quit)

        menu.exec(global_pos)

    def open_coin_menu(self, index: int, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #222; color: #eee; }")
        
        hotkey = self.cfg.buttons[index].hotkey or f"Taste {index+1}"

        act_media = QAction(f"Medien für {index+1} zuweisen…", self)
        act_img = QAction(f"Button-Bild für {index+1} zuweisen…", self)
        act_clear_img = QAction("Button-Bild zurück (Münze)", self)
        act_clear = QAction("Zuweisungen löschen", self)

        act_media.triggered.connect(lambda: self.assign_media(index, refresh=True))
        act_img.triggered.connect(lambda: self.assign_image(index, refresh=True))
        act_clear_img.triggered.connect(lambda: self.clear_image(index, refresh=True))
        act_clear.triggered.connect(lambda: self.clear_assignments(index, refresh=True))

        menu.addAction(act_media)
        menu.addAction(act_img)
        menu.addAction(act_clear_img)
        menu.addSeparator()
        
        # Show current hotkey
        act_hotkey_info = QAction(f"⌨ Hotkey: {hotkey}", self)
        act_hotkey_info.setEnabled(False)
        menu.addAction(act_hotkey_info)
        
        menu.addSeparator()
        menu.addAction(act_clear)

        menu.addSeparator()
        self.add_dock_submenu(menu)
        self.add_video_submenu(menu)
        self.add_volume_submenu(menu)

        act_manage = QAction("Verwalten… (Ctrl+M)", self)
        act_manage.triggered.connect(self.open_manager)
        menu.addAction(act_manage)

        menu.addSeparator()
        act_quit = QAction("Beenden", self)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_quit)

        menu.exec(global_pos)

    # ---- Assignments
    def assign_media(self, index: int, refresh: bool = False):
        filt = "Medien (*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.mp4 *.mov *.m4v *.avi *.wmv *.mkv *.webm)"
        path, _ = QFileDialog.getOpenFileName(self, "Medien-Datei auswählen", str(Path.home()), filt)
        if path:
            self.cfg.buttons[index].media_path = path
            self.save_config()
            if refresh and self.manager_dialog:
                self.manager_dialog.refresh()

    def assign_image(self, index: int, refresh: bool = False):
        filt = "Bilder (*.png *.jpg *.jpeg)"
        path, _ = QFileDialog.getOpenFileName(self, "Button-Bild auswählen", str(Path.home()), filt)
        if path:
            self.cfg.buttons[index].image_path = path
            self.save_config()
            self.bar.update()
            if refresh and self.manager_dialog:
                self.manager_dialog.refresh()

    def clear_image(self, index: int, refresh: bool = False):
        self.cfg.buttons[index].image_path = ""
        self.save_config()
        self.bar.update()
        if refresh and self.manager_dialog:
            self.manager_dialog.refresh()

    def clear_assignments(self, index: int, refresh: bool = False):
        hotkey = self.cfg.buttons[index].hotkey  # preserve hotkey
        self.cfg.buttons[index] = ButtonConfig(hotkey=hotkey)
        self.save_config()
        self.bar.update()
        if refresh and self.manager_dialog:
            self.manager_dialog.refresh()

    # ---- Playback
    def on_coin_clicked(self, index: int):
        cfg = self.cfg.buttons[index]
        if not cfg.media_path or not Path(cfg.media_path).exists():
            QMessageBox.information(self, "Keine Datei", "Für diese Münze ist keine Medien-Datei zugewiesen.")
            return

        if self.current_index == index and self.player.playbackState().name == "PlayingState":
            self.stop_playback()
            self.bar.update()
            return

        self.stop_playback()

        # Ensure audio settings are applied before playing (helps on some Windows setups)
        self.apply_audio_device()
        self.apply_volume_to_audio()

        path = Path(cfg.media_path)
        self.current_is_video = path.suffix.lower() in VIDEO_EXT
        self.current_index = index

        self.player.setSource(QUrl.fromLocalFile(str(path)))
        if self.current_is_video:
            screen = self.current_screen()
            g = screen.availableGeometry()
            self.video_overlay.show_video(g, self.cfg.video_mode, self.cfg.burst_seconds)
        else:
            self.video_overlay.hide_video()

        self.player.play()
        self.bar.update()

    def stop_playback(self):
        self.player.stop()
        self.video_overlay.hide_video()
        self.current_index = None
        self.current_is_video = False
        self.bar.update()

    def on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            err = self.player.errorString() or "Unbekannter Fehler (Codec/Datei)."
            QMessageBox.warning(self, "Medien-Fehler", err)
            self.stop_playback()
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop_playback()

    def on_media_error(self, error, error_string):
        msg = error_string or self.player.errorString()
        if msg:
            QMessageBox.warning(self, "Wiedergabe-Fehler", msg)
        self.stop_playback()

    # ---- Docking / Snapping
    def apply_dock_edge(self, edge: str, snap_now=True):
        edge = (edge or "top").lower().strip()
        if edge not in ("left", "right", "top", "bottom"):
            edge = "top"

        self.cfg.dock_edge = edge
        self.save_config()

        self.compute_sizes_for_edge(edge)
        self.set_window_size_for_edge(edge)
        self.bar.update()

        if snap_now:
            self.snap_to_edge(edge)

        if self.manager_dialog:
            self.manager_dialog.refresh()

    def snap_to_edge(self, edge: str):
        screen = self.current_screen()
        g = screen.availableGeometry()

        w, h = self.width(), self.height()
        x, y = self.x(), self.y()

        if edge == "left":
            x = g.left()
            y = max(g.top(), min(y, g.bottom() - h + 1))
        elif edge == "right":
            x = g.right() - w + 1
            y = max(g.top(), min(y, g.bottom() - h + 1))
        elif edge == "top":
            y = g.top()
            x = max(g.left(), min(x, g.right() - w + 1))
        else:  # bottom
            y = g.bottom() - h + 1
            x = max(g.left(), min(x, g.right() - w + 1))

        self.move(x, y)

    def current_screen(self):
        center = self.frameGeometry().center()
        scr = QGuiApplication.screenAt(center)
        return scr if scr else QGuiApplication.primaryScreen()

    def nearest_edge(self):
        screen = self.current_screen()
        g = screen.availableGeometry()
        w, h = self.width(), self.height()
        x, y = self.x(), self.y()

        d_left = abs(x - g.left())
        d_right = abs((x + w) - (g.right() + 1))
        d_top = abs(y - g.top())
        d_bottom = abs((y + h) - (g.bottom() + 1))

        dmin = min(d_left, d_right, d_top, d_bottom)
        if dmin > SNAP_THRESHOLD_PX:
            return None

        if dmin == d_left:
            return "left"
        if dmin == d_right:
            return "right"
        if dmin == d_top:
            return "top"
        return "bottom"

    def keyPressEvent(self, event):
        # Ctrl+M opens manager
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_M:
            self.open_manager()
            return

        # Docking shortcuts
        if event.key() in (Qt.Key.Key_T, Qt.Key.Key_Up):
            self.apply_dock_edge("top"); return
        if event.key() in (Qt.Key.Key_B, Qt.Key.Key_Down):
            self.apply_dock_edge("bottom"); return
        if event.key() in (Qt.Key.Key_L, Qt.Key.Key_Left):
            self.apply_dock_edge("left"); return
        if event.key() in (Qt.Key.Key_R, Qt.Key.Key_Right):
            self.apply_dock_edge("right"); return

        # Number keys 1-8 for quick access (local hotkeys, always work when focused)
        if Qt.Key.Key_1 <= event.key() <= Qt.Key.Key_8:
            ix = event.key() - Qt.Key.Key_1
            if 0 <= ix < self.visible_count():
                self.on_coin_clicked(ix)
            return
        
        # Escape/Space to stop
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.stop_playback()
            return
        
        # S for stop
        if event.key() == Qt.Key.Key_S:
            self.stop_playback()
            return

    def closeEvent(self, event):
        """Clean up when closing."""
        self.hotkey_manager.stop()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = SoundboardWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
