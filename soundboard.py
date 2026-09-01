from __future__ import annotations

import ctypes
import json
import os
import math
import platform
import random
import struct
import sys
import tempfile
import threading
import traceback
import wave
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import (
    PYQT_VERSION_STR, QT_VERSION_STR, QEvent, QLockFile, QPoint, QPointF,
    QRectF, QTimer, QUrl, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QPixmap, QGuiApplication, QPainter, QPen, QBrush,
    QRadialGradient, QColor, QFont, QPainterPath, QTransform, QKeySequence,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QLabel,
    QMenu, QHBoxLayout, QVBoxLayout, QMessageBox, QDialog, QGridLayout,
    QLineEdit, QPushButton, QFrame, QSlider, QComboBox, QSpinBox, QCheckBox,
    QGroupBox, QScrollArea
)

from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PyQt6.QtMultimediaWidgets import QVideoWidget

from classroom_modules import (
    CatalogEditorDialog, ClassroomPanel, IconPickerPopup, PhaseTimer,
    TimerControlPopup, VisualItem, asset_icon_dir, default_material_items,
    default_phase_items, paint_action_icon, parse_visual_items,
)


APP_NAME = "Teacher Soundboard"
VERSION = "v4.5.0"
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

# Try to import pynput for global hotkeys. Importing it can fail for reasons
# other than a missing package (for example an unavailable platform backend),
# so the app must remain usable without it.
GLOBAL_HOTKEYS_AVAILABLE = False
GLOBAL_HOTKEYS_ERROR = ""
pynput_keyboard = None
try:
    from pynput import keyboard as pynput_keyboard
    GLOBAL_HOTKEYS_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on the host platform
    GLOBAL_HOTKEYS_ERROR = str(exc)


def platform_config_dir(
    platform_name: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the native per-user configuration directory for a platform."""
    platform_name = platform_name or sys.platform
    environ = environ if environ is not None else os.environ
    home = home or Path.home()

    override = environ.get("TEACHER_SOUNDBOARD_CONFIG_DIR")
    if override:
        return Path(override)

    if platform_name.startswith("win"):
        root = environ.get("APPDATA")
        return Path(root) / "TeacherSoundboard" if root else home / "AppData" / "Roaming" / "TeacherSoundboard"
    if platform_name == "darwin":
        return home / "Library" / "Application Support" / "TeacherSoundboard"

    root = environ.get("XDG_CONFIG_HOME")
    return Path(root) / "TeacherSoundboard" if root else home / ".config" / "TeacherSoundboard"


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically so an interrupted save cannot corrupt config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def get_config_path() -> Path:
    cfg_dir = platform_config_dir()
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Starting without persistent settings is preferable to crashing when a
        # profile directory is temporarily unavailable or read-only.
        cfg_dir = Path(tempfile.gettempdir()) / "TeacherSoundboard"
        cfg_dir.mkdir(parents=True, exist_ok=True)

    config_path = cfg_dir / CONFIG_FILE

    # v4.2 stored macOS settings under ~/.config. Copy them once to the native
    # Application Support location without deleting the old file.
    if sys.platform == "darwin" and not config_path.exists():
        legacy = Path.home() / ".config" / "TeacherSoundboard" / CONFIG_FILE
        if legacy.is_file():
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    atomic_write_json(config_path, data)
            except (OSError, ValueError, TypeError):
                pass

    return config_path


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
    audio_device_id: str = ""  # stable OS device id; description is migration fallback
    global_hotkeys_enabled: bool = True  # enable/disable global hotkeys
    stop_hotkey: str = "Escape"  # global hotkey to stop playback
    buttons: list[ButtonConfig] = field(default_factory=list)
    show_soundboard: bool = True
    show_phase: bool = False
    show_materials: bool = False
    show_timer: bool = False
    phase_items: list[VisualItem] = field(default_factory=default_phase_items)
    material_items: list[VisualItem] = field(default_factory=default_material_items)
    selected_phase_id: str = ""
    selected_material_ids: list[str] = field(default_factory=list)
    timer_presets: list[int] = field(default_factory=lambda: [5, 8, 10])
    timer_default_minutes: int = 5
    timer_sound_path: str = ""   # Klang, wenn die Zeit abgelaufen ist
    panel_y_ratio: float = 0.08   # senkrechte Lage des Panels am rechten Rand
    panel_show_labels: bool = False   # ausdrücklich gewünscht: rein bildlich


def default_buttons() -> list[ButtonConfig]:
    return [ButtonConfig(hotkey=DEFAULT_HOTKEYS[i]) for i in range(MAX_BUTTONS)]


def _bounded_float(value, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(minimum, min(maximum, parsed))


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, parsed))


def parse_config(data) -> AppConfig:
    """Parse settings defensively and preserve explicitly cleared hotkeys."""
    if not isinstance(data, dict):
        return AppConfig(buttons=default_buttons())

    raw_buttons = data.get("buttons")
    raw_buttons = raw_buttons if isinstance(raw_buttons, list) else []
    buttons: list[ButtonConfig] = []
    for index in range(MAX_BUTTONS):
        raw = raw_buttons[index] if index < len(raw_buttons) and isinstance(raw_buttons[index], dict) else {}
        default_hotkey = DEFAULT_HOTKEYS[index]
        hotkey = raw.get("hotkey", default_hotkey)
        buttons.append(ButtonConfig(
            media_path=str(raw.get("media_path") or ""),
            image_path=str(raw.get("image_path") or ""),
            hotkey=str(hotkey or ""),
        ))

    dock_edge = str(data.get("dock_edge") or "top").lower().strip()
    if dock_edge not in ("left", "right", "top", "bottom"):
        dock_edge = "top"

    video_mode = str(data.get("video_mode") or "fullscreen_burst").lower().strip()
    if video_mode not in ("large", "fullscreen", "fullscreen_burst"):
        video_mode = "fullscreen_burst"

    enabled = data.get("global_hotkeys_enabled", True)
    if not isinstance(enabled, bool):
        enabled = True

    stop_hotkey = data.get("stop_hotkey", "Escape")
    stop_hotkey = str(stop_hotkey or "")

    def config_bool(key: str, default: bool) -> bool:
        value = data.get(key, default)
        return value if isinstance(value, bool) else default

    phase_items = parse_visual_items(data.get("phase_items"), default_phase_items)
    material_items = parse_visual_items(data.get("material_items"), default_material_items)
    phase_ids = {item.item_id for item in phase_items}
    material_ids = {item.item_id for item in material_items}

    selected_phase_id = str(data.get("selected_phase_id") or "")
    if selected_phase_id not in phase_ids:
        selected_phase_id = ""

    raw_material_ids = data.get("selected_material_ids")
    if not isinstance(raw_material_ids, list):
        raw_material_ids = []
    selected_material_ids = []
    for item_id in raw_material_ids:
        item_id = str(item_id)
        if item_id in material_ids and item_id not in selected_material_ids:
            selected_material_ids.append(item_id)

    raw_presets = data.get("timer_presets", [5, 8, 10])
    presets = []
    if isinstance(raw_presets, list):
        for value in raw_presets:
            try:
                parsed = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if 1 <= parsed <= 999 and parsed not in presets:
                presets.append(parsed)
    if not presets:
        presets = [5, 8, 10]
    presets = presets[:6]

    return AppConfig(
        dock_edge=dock_edge,
        volume=_bounded_float(data.get("volume"), 0.75, 0.0, 1.0),
        video_mode=video_mode,
        burst_seconds=_bounded_float(data.get("burst_seconds"), 1.6, 0.2, 10.0),
        visible_buttons=_bounded_int(data.get("visible_buttons"), DEFAULT_BUTTONS, 1, MAX_BUTTONS),
        audio_device=str(data.get("audio_device") or ""),
        audio_device_id=str(data.get("audio_device_id") or ""),
        global_hotkeys_enabled=enabled,
        stop_hotkey=stop_hotkey,
        buttons=buttons,
        show_soundboard=config_bool("show_soundboard", True),
        show_phase=config_bool("show_phase", False),
        show_materials=config_bool("show_materials", False),
        show_timer=config_bool("show_timer", False),
        phase_items=phase_items,
        material_items=material_items,
        selected_phase_id=selected_phase_id,
        selected_material_ids=selected_material_ids,
        timer_presets=presets,
        timer_default_minutes=_bounded_int(data.get("timer_default_minutes"), 5, 1, 999),
        timer_sound_path=str(data.get("timer_sound_path") or ""),
        panel_y_ratio=_bounded_float(data.get("panel_y_ratio"), 0.08, 0.0, 1.0),
        panel_show_labels=config_bool("panel_show_labels", False),
    )


def macos_accessibility_trusted() -> bool | None:
    """Return whether macOS allows keyboard monitoring, or None if unknown."""
    if sys.platform != "darwin":
        return True
    try:  # pragma: no cover - only available on macOS
        framework = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        framework.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(framework.AXIsProcessTrusted())
    except Exception:
        return None


# ---------------- Global Hotkey Manager ----------------
class GlobalHotkeyManager:
    """Cross-platform global hotkey manager using pynput."""
    
    def __init__(self):
        self.listener = None
        self.callbacks: dict[str, Callable] = {}
        self.enabled = False
        self._pending_restart = False
        self.last_error = GLOBAL_HOTKEYS_ERROR
    
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

        if normalized in self.callbacks:
            self.last_error = f"Doppelt vergebener Hotkey: {hotkey}"
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
    
    def start(self) -> bool:
        """Start listening for global hotkeys."""
        if not GLOBAL_HOTKEYS_AVAILABLE or not self.callbacks:
            self.enabled = False
            if not GLOBAL_HOTKEYS_AVAILABLE and not self.last_error:
                self.last_error = "Die globale Hotkey-Komponente ist nicht verfügbar."
            return False
        
        self.stop()
        
        try:
            self.listener = pynput_keyboard.GlobalHotKeys(self.callbacks)
            self.listener.start()
            self.enabled = True
            self._pending_restart = False
            self.last_error = ""
            return True
        except Exception as e:
            self.last_error = str(e)
            print(f"Failed to start global hotkeys: {e}", file=sys.stderr)
            self.enabled = False
            self.listener = None
            return False
    
    def stop(self):
        """Stop listening for global hotkeys."""
        listener = self.listener
        self.listener = None
        if listener:
            try:
                listener.stop()
                if listener is not threading.current_thread():
                    listener.join(timeout=0.75)
            except Exception:
                pass
        self.enabled = False
    
    def restart_if_needed(self):
        """Restart listener if there are pending changes."""
        if self._pending_restart:
            if self.callbacks:
                self.start()
            else:
                self.stop()


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

        self._current_screen = None
        self.video.installEventFilter(self)

    def set_player(self, player: QMediaPlayer):
        player.setVideoOutput(self.video)

    def show_video(self, screen, mode: str, burst_seconds: float = 1.6):
        self._current_screen = screen
        mode = (mode or "large").lower().strip()
        if mode not in ("large", "fullscreen", "fullscreen_burst"):
            mode = "large"

        self._burst_timer.stop()

        if mode == "fullscreen":
            self._show_fullscreen_on_screen(screen)
            return

        if mode == "fullscreen_burst":
            self._show_fullscreen_on_screen(screen)
            ms = max(200, int(burst_seconds * 1000))
            self._burst_timer.start(ms)
            return

        self._show_large_on_screen(screen)

    def hide_video(self):
        self._burst_timer.stop()
        self.hide()
        self.setWindowState(Qt.WindowState.WindowNoState)

    def _place_on_screen(self, screen):
        if screen is None:
            return
        # Force creation of a native handle before assigning a monitor. This is
        # considerably more reliable than geometry-only placement on macOS.
        self.winId()
        handle = self.windowHandle()
        if handle and handle.screen() is not screen:
            handle.setScreen(screen)

    def _show_fullscreen_on_screen(self, screen):
        self._burst_timer.stop()
        self.hide()
        self.setWindowState(Qt.WindowState.WindowNoState)
        self._place_on_screen(screen)
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _show_large_on_screen(self, screen):
        self._burst_timer.stop()
        self.hide()
        self.setWindowState(Qt.WindowState.WindowNoState)
        self._place_on_screen(screen)
        g = screen.availableGeometry()

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
        if not self._current_screen:
            return
        self._show_large_on_screen(self._current_screen)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Backspace):
            self.closeRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.video and event.type() == QEvent.Type.MouseButtonPress:
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


def ui_modifier_label() -> str:
    return "Cmd" if sys.platform == "darwin" else "Strg"


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
            # Qt maps the macOS Command key to ControlModifier.
            parts.append("Cmd" if sys.platform == "darwin" else "Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            # Conversely, the physical macOS Control key is MetaModifier.
            parts.append("Ctrl" if sys.platform == "darwin" else "Meta")
        
        # Get key name
        key_seq = QKeySequence(key)
        key_str = key_seq.toString(QKeySequence.SequenceFormat.PortableText)
        
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
        available = parent.current_screen().availableGeometry()
        self.resize(
            max(760, min(1200, available.width() - 60)),
            max(560, min(700, available.height() - 60)),
        )

        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll)
        root = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        header = QLabel("Medien, Button-Bilder, Hotkeys, Lautstärke & Audio-Ausgabe")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(header)

        tip = QLabel("Tipp: Wenn du nichts hörst, prüfe die Systemlautstärke und das unten gewählte Ausgabegerät.")
        tip.setStyleSheet("color: #444;")
        root.addWidget(tip)

        sub = QLabel(
            f"Menü: Rechtsklick auf Münze (oder {ui_modifier_label()}+Rechtsklick). "
            "Verschieben: ALT+Ziehen."
        )
        sub.setStyleSheet("color: #666;")
        root.addWidget(sub)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
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
            "Unter macOS muss Teacher Soundboard zusätzlich unter Datenschutz & Sicherheit → "
            "Bedienungshilfen erlaubt werden."
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

        self.hotkey_status_label = QLabel("")
        self.hotkey_status_label.setWordWrap(True)
        hotkey_layout.addWidget(self.hotkey_status_label, 1)

        hotkey_layout.addStretch(1)

        # ---- Hotkey info label ----
        hotkey_info = QLabel(
            "📌 Tastenkombinationen: Klicke in ein Hotkey-Feld und drücke die gewünschte Taste(n). "
            "Backspace/Entf löscht. Lokale Hotkeys (1-8) funktionieren immer wenn Soundboard fokussiert."
        )
        hotkey_info.setStyleSheet("color: #666; font-size: 11px;")
        hotkey_info.setWordWrap(True)
        root.addWidget(hotkey_info)

        # ---- Integrated classroom modules ----
        classroom_group = QGroupBox("Optionale Unterrichtsmodule (Panel am rechten Rand)")
        classroom_box = QVBoxLayout(classroom_group)
        classroom_layout = QHBoxLayout()
        classroom_box.addLayout(classroom_layout)
        self.module_checks: dict[str, QCheckBox] = {}
        for key, label in [
            ("soundboard", "Soundboard-Leiste"),
            ("phase", "Methode/Sozialform"),
            ("materials", "Material"),
            ("timer", "Timer"),
        ]:
            checkbox = QCheckBox(label)
            checkbox.stateChanged.connect(
                lambda state, module=key: self._on_module_changed(module, state)
            )
            classroom_layout.addWidget(checkbox)
            self.module_checks[key] = checkbox

        self.panel_labels_check = QCheckBox("Beschriftung")
        self.panel_labels_check.setToolTip(
            "Blendet Überschriften und Namen im Panel ein oder aus."
        )
        self.panel_labels_check.stateChanged.connect(self._on_panel_labels_changed)
        classroom_layout.addWidget(self.panel_labels_check)

        classroom_layout.addSpacing(12)
        phase_catalog = QPushButton("Methoden/Sozialformen bearbeiten…")
        phase_catalog.clicked.connect(lambda: self.host.open_catalog_editor("phase"))
        classroom_layout.addWidget(phase_catalog)
        material_catalog = QPushButton("Materialien bearbeiten…")
        material_catalog.clicked.connect(lambda: self.host.open_catalog_editor("materials"))
        classroom_layout.addWidget(material_catalog)
        classroom_layout.addStretch(1)

        sound_row = QHBoxLayout()
        sound_row.addWidget(QLabel("Klang am Ende des Timers:"))
        self.timer_sound_label = QLabel()
        self.timer_sound_label.setMinimumWidth(220)
        sound_row.addWidget(self.timer_sound_label, 1)
        choose_sound = QPushButton("Audiodatei wählen…")
        choose_sound.clicked.connect(self.host.assign_timer_sound)
        sound_row.addWidget(choose_sound)
        self.test_sound_button = QPushButton("Anhören")
        self.test_sound_button.clicked.connect(self.host.play_timer_sound)
        sound_row.addWidget(self.test_sound_button)
        self.clear_sound_button = QPushButton("Entfernen")
        self.clear_sound_button.clicked.connect(self.host.clear_timer_sound)
        sound_row.addWidget(self.clear_sound_button)
        classroom_box.addLayout(sound_row)
        root.addWidget(classroom_group)

        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
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

            media_edit = QLineEdit()
            media_edit.setReadOnly(True)
            img_edit = QLineEdit()
            img_edit.setReadOnly(True)
            grid.addWidget(media_edit, row, 2)
            grid.addWidget(img_edit, row, 3)
            self.media_edits.append(media_edit)
            self.image_edits.append(img_edit)

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
        outer.addLayout(footer)

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
        self.device_combo.addItem("Standard (System)", "")
        devices = self.host.list_audio_devices()
        for device_id, description in devices:
            self.device_combo.addItem(description, device_id)
        current = self.host.cfg.audio_device_id or ""
        ix = self.device_combo.findData(current)
        if ix < 0 and self.host.cfg.audio_device:
            ix = self.device_combo.findText(self.host.cfg.audio_device)
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

        module_values = {
            "soundboard": self.host.cfg.show_soundboard,
            "phase": self.host.cfg.show_phase,
            "materials": self.host.cfg.show_materials,
            "timer": self.host.cfg.show_timer,
        }
        for key, checkbox in self.module_checks.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(module_values[key])
            checkbox.blockSignals(False)

        self.panel_labels_check.blockSignals(True)
        self.panel_labels_check.setChecked(self.host.cfg.panel_show_labels)
        self.panel_labels_check.blockSignals(False)

        sound_name = self.host.timer_sound_name()
        error = self.host.timer_sound_error
        if error:
            self.timer_sound_label.setText(error)
            self.timer_sound_label.setStyleSheet("color: #9a4d00; font-weight: 600;")
        elif sound_name:
            self.timer_sound_label.setText(sound_name)
            self.timer_sound_label.setStyleSheet("color: #176b35; font-weight: 600;")
        else:
            self.timer_sound_label.setText("kein Klang – der Ring wird nur rot")
            self.timer_sound_label.setStyleSheet("color: #666;")
        self.test_sound_button.setEnabled(bool(sound_name))
        self.clear_sound_button.setEnabled(bool(sound_name))

        # Global hotkeys
        self.global_hotkeys_check.blockSignals(True)
        self.global_hotkeys_check.setChecked(self.host.cfg.global_hotkeys_enabled)
        self.global_hotkeys_check.blockSignals(False)
        status_text, status_ok = self.host.global_hotkey_status()
        self.hotkey_status_label.setText(status_text)
        self.hotkey_status_label.setStyleSheet(
            "color: #176b35; font-weight: 600;" if status_ok else "color: #9a4d00; font-weight: 600;"
        )
        
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
        device_id = self.device_combo.currentData()
        description = "" if not device_id else self.device_combo.currentText()
        self.host.set_audio_device(device_id or "", description)

    def _on_mode_changed(self, _):
        mode = self.mode_combo.currentData()
        if mode:
            self.host.set_video_mode(mode)

    def _on_count_changed(self, value: int):
        self.host.set_visible_buttons(int(value))

    def _on_module_changed(self, module: str, state):
        self.host.set_module_visible(module, state == Qt.CheckState.Checked.value)

    def _on_panel_labels_changed(self, state):
        self.host.set_panel_labels(state == Qt.CheckState.Checked.value)

    def _on_global_hotkeys_changed(self, state):
        self.host.set_global_hotkeys_enabled(state == Qt.CheckState.Checked.value)

    def _on_stop_hotkey_changed(self, hotkey: str):
        self.host.set_stop_hotkey(hotkey)

    def _on_button_hotkey_changed(self, index: int, hotkey: str):
        self.host.set_button_hotkey(index, hotkey)

    def _reset_hotkeys_to_default(self):
        self.host.reset_hotkeys_to_default()
        self.refresh()


# ---------------- Custom painted modular classroom bar ----------------
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

        if self.host.cfg.show_soundboard:
            for i in range(self.host.visible_count()):
                coin = self.host.coin_rect(i)
                pm = self.host.coin_pixmap(i, int(coin.width()))
                p.drawPixmap(int(round(coin.x())), int(round(coin.y())), pm)

                if (
                    self.host.current_index == i
                    and self.host.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                ):
                    ring = QRectF(coin).adjusted(-3, -3, 3, 3)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor(0, 200, 255, 200), 4))
                    p.drawEllipse(ring)

        self.host.paint_classroom_modules(p)

        p.end()

    def mousePressEvent(self, event):
        gp = event.globalPosition().toPoint()
        lp = event.position().toPoint()

        shortcut_modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        if event.button() == Qt.MouseButton.RightButton and (event.modifiers() & shortcut_modifiers):
            self.host.open_window_menu(gp)
            return

        if event.button() == Qt.MouseButton.RightButton:
            target = self.host.hit_target(lp)
            if target and target[0] == "sound":
                self.host.open_coin_menu(int(target[1]), gp)
            else:
                self.host.open_window_menu(gp)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.host.start_drag(gp)
                event.accept()
                return

            target = self.host.hit_target(lp)
            if target is None:
                self.host.start_drag(gp)
            else:
                self.host.activate_target(target, gp)
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
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._dragging = False
        self._drag_offset = QPoint(0, 0)

        self.config_path = get_config_path()
        self.last_config_error = ""
        self.cfg = self.load_config()

        self.phase_timer = PhaseTimer()
        self._module_tick = QTimer(self)
        self._module_tick.setInterval(200)
        self._module_tick.timeout.connect(self._on_module_tick)
        self._picker_popup: IconPickerPopup | None = None
        self._timer_popup: TimerControlPopup | None = None
        self._catalog_dialogs: dict[str, CatalogEditorDialog] = {}

        self.current_index: int | None = None
        self.current_is_video = False
        self._handling_media_error = False

        self.coin_sizes = [64] * MAX_BUTTONS
        self.slot_size = 72

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)

        # Eigener Player, damit der Timerklang eine laufende Wiedergabe nicht
        # abbricht und umgekehrt nicht von ihr abgeschnitten wird.
        self.timer_player = QMediaPlayer(self)
        self.timer_audio = QAudioOutput(self)
        self.timer_player.setAudioOutput(self.timer_audio)
        self.timer_player.errorOccurred.connect(self._on_timer_sound_error)
        self.timer_sound_error = ""
        self._timer_sound_fired = False

        self.media_devices = QMediaDevices(self)
        self.media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)

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

        self.panel = ClassroomPanel(self)

        self.manager_dialog: ManageDialog | None = None

        # Global hotkey manager
        self.hotkey_manager = GlobalHotkeyManager()
        self.hotkeyTriggered.connect(self._on_hotkey_triggered)
        self.stopTriggered.connect(self.stop_playback)
        
        # Setup hotkeys
        self._setup_global_hotkeys()

        self.apply_dock_edge(self.cfg.dock_edge, snap_now=False)
        self.snap_to_edge(self.cfg.dock_edge)

        app = QApplication.instance()
        if app:
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._schedule_reposition)
            for screen in app.screens():
                screen.availableGeometryChanged.connect(self._schedule_reposition)
        QTimer.singleShot(0, self._attach_window_screen_signal)
        self.panel.relayout()

    def _setup_global_hotkeys(self):
        """Setup global hotkeys from config."""
        self.hotkey_manager.stop()
        self.hotkey_manager.clear_all()
        self.hotkey_manager.last_error = ""

        if not self.cfg.global_hotkeys_enabled:
            return
        if not GLOBAL_HOTKEYS_AVAILABLE:
            self.hotkey_manager.last_error = GLOBAL_HOTKEYS_ERROR or "Hotkey-Komponente nicht verfügbar."
            return
        if macos_accessibility_trusted() is False:
            self.hotkey_manager.last_error = (
                "macOS blockiert globale Hotkeys. Erlaube Teacher Soundboard unter "
                "Datenschutz & Sicherheit → Bedienungshilfen."
            )
            self.hotkey_manager.stop()
            return

        registration_error = ""

        # Register button hotkeys
        for i, btn_cfg in enumerate(self.cfg.buttons[:self.visible_count()]):
            if btn_cfg.hotkey:
                idx = i  # capture index
                registered = self.hotkey_manager.register(
                    btn_cfg.hotkey,
                    lambda ix=idx: self.hotkeyTriggered.emit(ix)
                )
                if not registered:
                    registration_error = self.hotkey_manager.last_error
        
        # Register stop hotkey
        if self.cfg.stop_hotkey:
            registered = self.hotkey_manager.register(
                self.cfg.stop_hotkey,
                lambda: self.stopTriggered.emit()
            )
            if not registered:
                registration_error = self.hotkey_manager.last_error
        
        started = self.hotkey_manager.start()
        if started and registration_error:
            self.hotkey_manager.last_error = registration_error

    def global_hotkey_status(self) -> tuple[str, bool]:
        if not self.cfg.global_hotkeys_enabled:
            return "Globale Hotkeys sind deaktiviert; lokale Tasten funktionieren weiterhin.", True
        if not self.hotkey_manager.callbacks and not self.hotkey_manager.last_error:
            return "Es sind keine globalen Hotkeys konfiguriert.", True
        if self.hotkey_manager.enabled and not self.hotkey_manager.last_error:
            return "Globale Hotkeys sind aktiv.", True
        if self.hotkey_manager.enabled:
            return f"Globale Hotkeys sind teilweise aktiv. {self.hotkey_manager.last_error}", False
        detail = self.hotkey_manager.last_error or "Globale Hotkeys konnten nicht gestartet werden."
        return detail, False

    def _on_hotkey_triggered(self, index: int):
        """Handle hotkey trigger (thread-safe via signal)."""
        if 0 <= index < self.visible_count():
            self.on_coin_clicked(index)

    def set_global_hotkeys_enabled(self, enabled: bool):
        """Enable or disable global hotkeys."""
        self.cfg.global_hotkeys_enabled = enabled
        self.save_config()
        self._setup_global_hotkeys()
        if enabled and macos_accessibility_trusted() is False:
            QMessageBox.information(
                self,
                "macOS-Freigabe erforderlich",
                "Damit globale Hotkeys funktionieren, öffne Systemeinstellungen → Datenschutz & "
                "Sicherheit → Bedienungshilfen und erlaube dort Teacher Soundboard.\n\n"
                "Die App bleibt auch ohne diese Freigabe vollständig per Mausklick und mit lokalen "
                "Tasten bedienbar.",
            )
        if self.manager_dialog:
            self.manager_dialog.refresh()

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

    def reset_hotkeys_to_default(self):
        for index, hotkey in enumerate(DEFAULT_HOTKEYS):
            self.cfg.buttons[index].hotkey = hotkey
        self.cfg.stop_hotkey = "Escape"
        self.save_config()
        self._setup_global_hotkeys()

    # ---- audio devices
    @staticmethod
    def _audio_device_id(device) -> str:
        try:
            raw = bytes(device.id())
            if raw:
                return raw.hex()
        except Exception:
            pass
        return f"description:{device.description()}"

    def list_audio_devices(self) -> list[tuple[str, str]]:
        try:
            return [(self._audio_device_id(device), device.description()) for device in QMediaDevices.audioOutputs()]
        except Exception:
            return []

    def _selected_audio_device(self):
        """Eingestelltes Ausgabegerät, sonst das Standardgerät des Systems."""
        wanted_id = (self.cfg.audio_device_id or "").strip()
        wanted_description = (self.cfg.audio_device or "").strip()
        if wanted_id or wanted_description:
            for device in QMediaDevices.audioOutputs():
                device_id = self._audio_device_id(device)
                if (wanted_id and device_id == wanted_id) or (
                    not wanted_id and wanted_description and device.description() == wanted_description
                ):
                    self.cfg.audio_device_id = device_id
                    self.cfg.audio_device = device.description()
                    return device
        return QMediaDevices.defaultAudioOutput()

    def apply_audio_device(self):
        try:
            device = self._selected_audio_device()
            self.audio.setDevice(device)
            self.timer_audio.setDevice(device)
        except Exception:
            pass

    def set_audio_device(self, device_id: str, description: str = ""):
        self.cfg.audio_device_id = (device_id or "").strip()
        self.cfg.audio_device = (description or "").strip()
        self.apply_audio_device()
        self.save_config()
        if self.manager_dialog:
            self.manager_dialog.refresh()

    def _on_audio_outputs_changed(self):
        self.apply_audio_device()
        if self.manager_dialog:
            self.manager_dialog.refresh()

    # ---- helpers
    def visible_count(self) -> int:
        try:
            n = int(self.cfg.visible_buttons)
        except Exception:
            n = DEFAULT_BUTTONS
        return max(1, min(MAX_BUTTONS, n))

    def _attach_window_screen_signal(self):
        handle = self.windowHandle()
        if handle:
            handle.screenChanged.connect(self._schedule_reposition)

    def _on_screen_added(self, screen):
        screen.availableGeometryChanged.connect(self._schedule_reposition)
        self._schedule_reposition()

    def _schedule_reposition(self, *_args):
        QTimer.singleShot(0, self._reposition_after_screen_change)

    def _reposition_after_screen_change(self):
        if not self.isVisible():
            return
        self.compute_sizes_for_edge(self.cfg.dock_edge)
        self.set_window_size_for_edge(self.cfg.dock_edge)
        self.snap_to_edge(self.cfg.dock_edge)
        self.panel.relayout()

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
                return parse_config(data)
            except (OSError, ValueError, TypeError) as exc:
                print(f"Could not read config: {exc}", file=sys.stderr)

        return parse_config({})

    def save_config(self):
        data = {
            "dock_edge": self.cfg.dock_edge,
            "volume": self.cfg.volume,
            "video_mode": self.cfg.video_mode,
            "burst_seconds": self.cfg.burst_seconds,
            "visible_buttons": self.visible_count(),
            "audio_device": self.cfg.audio_device,
            "audio_device_id": self.cfg.audio_device_id,
            "global_hotkeys_enabled": self.cfg.global_hotkeys_enabled,
            "stop_hotkey": self.cfg.stop_hotkey,
            "buttons": [asdict(b) for b in self.cfg.buttons],
            "show_soundboard": self.cfg.show_soundboard,
            "show_phase": self.cfg.show_phase,
            "show_materials": self.cfg.show_materials,
            "show_timer": self.cfg.show_timer,
            "phase_items": [item.to_dict() for item in self.cfg.phase_items],
            "material_items": [item.to_dict() for item in self.cfg.material_items],
            "selected_phase_id": self.cfg.selected_phase_id,
            "selected_material_ids": list(self.cfg.selected_material_ids),
            "timer_presets": list(self.cfg.timer_presets),
            "timer_default_minutes": self.cfg.timer_default_minutes,
            "timer_sound_path": self.cfg.timer_sound_path,
            "panel_y_ratio": self.cfg.panel_y_ratio,
            "panel_show_labels": self.cfg.panel_show_labels,
        }
        try:
            atomic_write_json(self.config_path, data)
            self.last_config_error = ""
        except OSError as exc:
            self.last_config_error = str(exc)
            print(f"Could not save config: {exc}", file=sys.stderr)

    def set_visible_buttons(self, n: int):
        n = max(1, min(MAX_BUTTONS, int(n)))
        self.cfg.visible_buttons = n
        self.save_config()

        self.compute_sizes_for_edge(self.cfg.dock_edge)
        self.set_window_size_for_edge(self.cfg.dock_edge)
        self.bar.update()
        self.snap_to_edge(self.cfg.dock_edge)
        self._setup_global_hotkeys()

        if self.manager_dialog:
            self.manager_dialog.refresh()

    # ---- Volume
    def apply_volume_to_audio(self):
        for output in (self.audio, self.timer_audio):
            try:
                output.setMuted(False)
            except Exception:
                pass
            output.setVolume(float(self.cfg.volume))

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
    def selected_phase_item(self) -> VisualItem | None:
        for item in self.cfg.phase_items:
            if item.item_id == self.cfg.selected_phase_id:
                return item
        return None

    def selected_material_items(self) -> list[VisualItem]:
        by_id = {item.item_id: item for item in self.cfg.material_items}
        return [by_id[item_id] for item_id in self.cfg.selected_material_ids if item_id in by_id]

    def display_slots(self) -> list[tuple[str, object]]:
        """Belegung der Randleiste. Sozialform, Material und Timer stehen im Panel."""
        slots: list[tuple[str, object]] = []
        if self.cfg.show_soundboard:
            slots.extend(("sound", index) for index in range(self.visible_count()))
        # A language-independent handle remains available even if every module is hidden.
        slots.append(("handle", None))
        return slots

    def compute_sizes_for_edge(self, edge: str):
        screen = self.current_screen()
        g = screen.availableGeometry()
        slot_count = max(1, len(self.display_slots()))

        available = g.height() if edge in ("left", "right") else g.width()
        total_spacing = SPACING * (slot_count - 1)
        available -= (MARGIN * 2 + total_spacing)

        self.slot_size = max(34, min(MAX_COIN, int(available / slot_count)))
        sizes = []
        min_mult, max_mult = min(SIZE_MULT), max(SIZE_MULT)
        for multiplier in SIZE_MULT:
            relative = (multiplier - min_mult) / max(0.01, max_mult - min_mult)
            factor = 0.76 + relative * 0.24
            sizes.append(max(30, min(self.slot_size, int(round(self.slot_size * factor)))))

        while len(sizes) < MAX_BUTTONS:
            sizes.append(self.slot_size)

        self.coin_sizes = sizes

    def set_window_size_for_edge(self, edge: str):
        slot_count = max(1, len(self.display_slots()))
        total_spacing = SPACING * (slot_count - 1)
        total_margin = MARGIN * 2

        if edge in ("left", "right"):
            w = self.slot_size + total_margin
            h = slot_count * self.slot_size + total_spacing + total_margin
        else:
            w = slot_count * self.slot_size + total_spacing + total_margin
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

    def hit_target(self, local_pos: QPoint) -> tuple[str, object] | None:
        for slot_index, target in enumerate(self.display_slots()):
            rect = self.coin_rect(int(target[1])) if target[0] == "sound" else self.slot_rect(slot_index)
            if target[0] == "sound":
                cx, cy = rect.center().x(), rect.center().y()
                dx = local_pos.x() + 0.5 - cx
                dy = local_pos.y() + 0.5 - cy
                if dx*dx + dy*dy <= (min(rect.width(), rect.height())/2.0 - 1.5)**2:
                    return target
            elif rect.contains(QPointF(local_pos)):
                return target
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

    # ---- Randleiste
    def paint_classroom_modules(self, painter: QPainter) -> None:
        """Zeichnet den Griff der Randleiste; die Module leben im Panel."""
        for slot_index, (kind, _payload) in enumerate(self.display_slots()):
            if kind != "handle":
                continue
            rect = self.slot_rect(slot_index)
            inset = rect.width() * 0.15
            inner = rect.adjusted(inset, inset, -inset, -inset)
            painter.setPen(QPen(QColor(255, 255, 255, 70), max(1.0, rect.width()*0.025)))
            painter.setBrush(QBrush(QColor(28, 33, 39, 218)))
            painter.drawRoundedRect(inner, inner.width()*0.25, inner.height()*0.25)
            paint_action_icon(painter, inner.adjusted(5, 5, -5, -5), "menu")

    def _refresh_views(self) -> None:
        """Zeichnet Randleiste und Panel neu, ohne die Anordnung zu ändern."""
        self.bar.update()
        self.panel.relayout()

    def _refresh_module_layout(self, persist: bool = True) -> None:
        if persist:
            self.save_config()
        self.compute_sizes_for_edge(self.cfg.dock_edge)
        self.set_window_size_for_edge(self.cfg.dock_edge)
        self.bar.update()
        if self.isVisible():
            self.snap_to_edge(self.cfg.dock_edge)
        self.panel.relayout()
        if self.manager_dialog:
            self.manager_dialog.refresh()

    def set_module_visible(self, module: str, visible: bool) -> None:
        field_name = {
            "soundboard": "show_soundboard",
            "phase": "show_phase",
            "materials": "show_materials",
            "timer": "show_timer",
        }.get(module)
        if not field_name:
            return
        setattr(self.cfg, field_name, bool(visible))
        self._refresh_module_layout()

    def set_panel_labels(self, visible: bool) -> None:
        self.cfg.panel_show_labels = bool(visible)
        self._refresh_module_layout()

    def activate_target(self, target: tuple[str, object], global_pos: QPoint) -> None:
        kind, payload = target
        if kind == "sound":
            self.on_coin_clicked(int(payload))
        elif kind == "handle":
            self.open_window_menu(global_pos)

    def _position_popup(self, popup: QDialog, global_pos: QPoint) -> None:
        popup.adjustSize()
        screen = QGuiApplication.screenAt(global_pos) or self.current_screen()
        available = screen.availableGeometry()
        x = max(available.left(), min(global_pos.x() + 6, available.right() - popup.width() + 1))
        y = max(available.top(), min(global_pos.y() + 6, available.bottom() - popup.height() + 1))
        popup.move(x, y)

    def open_phase_picker(self, global_pos: QPoint) -> None:
        popup = IconPickerPopup(
            self.cfg.phase_items,
            {self.cfg.selected_phase_id} if self.cfg.selected_phase_id else set(),
            multi_select=False,
            parent=self,
        )
        popup.itemToggled.connect(self.set_selected_phase)
        popup.cleared.connect(lambda: self.set_selected_phase(""))
        self._picker_popup = popup
        self._position_popup(popup, global_pos)
        popup.show()

    def open_material_picker(self, global_pos: QPoint) -> None:
        popup = IconPickerPopup(
            self.cfg.material_items,
            set(self.cfg.selected_material_ids),
            multi_select=True,
            parent=self,
        )
        popup.itemToggled.connect(self.toggle_selected_material)
        popup.cleared.connect(self.clear_selected_materials)
        self._picker_popup = popup
        self._position_popup(popup, global_pos)
        popup.show()

    def set_selected_phase(self, item_id: str) -> None:
        valid_ids = {item.item_id for item in self.cfg.phase_items}
        self.cfg.selected_phase_id = item_id if item_id in valid_ids else ""
        self.save_config()
        self._refresh_views()

    def toggle_selected_material(self, item_id: str) -> None:
        valid_ids = {item.item_id for item in self.cfg.material_items}
        if item_id not in valid_ids:
            return
        if item_id in self.cfg.selected_material_ids:
            self.cfg.selected_material_ids.remove(item_id)
        else:
            self.cfg.selected_material_ids.append(item_id)
        self._refresh_module_layout()

    def clear_selected_materials(self) -> None:
        self.cfg.selected_material_ids = []
        self._refresh_module_layout()

    def open_timer_controls(self, global_pos: QPoint) -> None:
        popup = TimerControlPopup(
            self.cfg.timer_presets,
            self.phase_timer.total_minutes() or self.cfg.timer_default_minutes,
            self.phase_timer.running,
            parent=self,
        )
        popup.startRequested.connect(self.start_phase_timer)
        popup.resetRequested.connect(self.reset_phase_timer)
        popup.clearRequested.connect(self.clear_phase_timer)
        popup.soundRequested.connect(self.assign_timer_sound)
        self._timer_popup = popup
        self._position_popup(popup, global_pos)
        popup.show()

    def start_phase_timer(self, minutes: int) -> None:
        minutes = max(1, min(999, int(minutes)))
        self.cfg.timer_default_minutes = minutes
        self.save_config()
        self.phase_timer.start(minutes)
        self._timer_sound_fired = False
        self._module_tick.start()
        self._refresh_views()

    def toggle_phase_timer(self) -> None:
        if not self.phase_timer.has_value():
            self.start_phase_timer(self.cfg.timer_default_minutes)
            return
        if self.phase_timer.remaining_seconds() <= 0:
            # Abgelaufen: Pause umschalten würde nichts bewirken.
            self.reset_phase_timer()
            return
        self.phase_timer.toggle_pause()
        if self.phase_timer.running:
            self._module_tick.start()
        self._refresh_views()

    def reset_phase_timer(self) -> None:
        if not self.phase_timer.has_value():
            self.start_phase_timer(self.cfg.timer_default_minutes)
            return
        self.phase_timer.reset()
        self._timer_sound_fired = False
        self._module_tick.start()
        self._refresh_views()

    def adjust_phase_timer(self, delta: int) -> None:
        """Ändert die laufende Zeit oder, ohne laufenden Timer, die Startdauer."""
        if self.phase_timer.has_value():
            self.phase_timer.add_minutes(delta)
            if self.phase_timer.remaining_seconds() > 0:
                self._timer_sound_fired = False
            if self.phase_timer.running:
                self._module_tick.start()
        else:
            minutes = _bounded_int(self.cfg.timer_default_minutes + delta, 5, 1, 999)
            self.cfg.timer_default_minutes = minutes
            self.save_config()
        self._refresh_views()

    def add_phase_minutes(self, minutes: int) -> None:
        self.phase_timer.add_minutes(minutes)
        if self.phase_timer.running:
            self._module_tick.start()
        self._refresh_views()

    def clear_phase_timer(self) -> None:
        self.phase_timer.clear()
        self._timer_sound_fired = False
        self._release_timer_sound()
        self._module_tick.stop()
        self._refresh_views()

    def _on_module_tick(self) -> None:
        remaining = self.phase_timer.remaining_seconds()
        if remaining > 0:
            self._timer_sound_fired = False
        elif self.phase_timer.has_value() and not self._timer_sound_fired:
            # Genau einmal je abgelaufenem Timer, nicht bei jedem Takt.
            self._timer_sound_fired = True
            self.play_timer_sound()
        self.panel.update()
        if not self.phase_timer.running:
            self._module_tick.stop()
            self.panel.relayout()

    # ---- Klang am Ende des Timers
    def timer_sound_name(self) -> str:
        path = (self.cfg.timer_sound_path or "").strip()
        return Path(path).name if path else ""

    def _release_timer_sound(self) -> None:
        """Stoppt die Wiedergabe und gibt insbesondere unter Windows die Audiodatei frei."""
        self.timer_player.stop()
        self.timer_player.setSource(QUrl())

    def play_timer_sound(self) -> bool:
        # Die vorige Quelle zuerst lösen: Windows hält die Datei sonst nach stop()
        # weiterhin geöffnet, auch wenn der nächste konfigurierte Pfad ungültig ist.
        self._release_timer_sound()
        path = (self.cfg.timer_sound_path or "").strip()
        if not path:
            return False
        source = Path(path)
        if not source.is_file():
            self.timer_sound_error = f"Datei nicht gefunden: {path}"
            return False
        self.timer_sound_error = ""
        self.timer_player.setSource(QUrl.fromLocalFile(str(source)))
        self.timer_player.play()
        return True

    def _on_timer_sound_error(self, error, error_string: str = ""):
        if error == QMediaPlayer.Error.NoError:
            return
        self.timer_sound_error = error_string or "Klang konnte nicht abgespielt werden."
        print(f"Timer sound error: {self.timer_sound_error}", file=sys.stderr)

    def assign_timer_sound(self) -> None:
        filt = "Audio (*.mp3 *.wav *.ogg *.flac *.m4a *.aac)"
        start = str(Path(self.cfg.timer_sound_path).parent) if self.cfg.timer_sound_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Klang für das Timer-Ende wählen", start, filt)
        if not path:
            return
        self.cfg.timer_sound_path = path
        self.timer_sound_error = ""
        self.save_config()
        self.play_timer_sound()
        if self.manager_dialog:
            self.manager_dialog.refresh()

    def clear_timer_sound(self) -> None:
        self.cfg.timer_sound_path = ""
        self.timer_sound_error = ""
        self._release_timer_sound()
        self.save_config()
        if self.manager_dialog:
            self.manager_dialog.refresh()

    def open_catalog_editor(self, catalog: str) -> None:
        if catalog == "phase":
            title = "Methoden und Sozialformen"
            items = self.cfg.phase_items
            defaults = default_phase_items
        elif catalog == "materials":
            title = "Materialien"
            items = self.cfg.material_items
            defaults = default_material_items
        else:
            return

        existing = self._catalog_dialogs.get(catalog)
        if existing and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        dialog = CatalogEditorDialog(
            title,
            items,
            self.config_path.parent / "icons",
            defaults,
            lambda changed_items, kind=catalog: self._catalog_changed(kind, changed_items),
            parent=self,
        )
        self._catalog_dialogs[catalog] = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _catalog_changed(self, catalog: str, items: list[VisualItem]) -> None:
        if catalog == "phase":
            self.cfg.phase_items = items
            valid_ids = {item.item_id for item in items}
            if self.cfg.selected_phase_id not in valid_ids:
                self.cfg.selected_phase_id = ""
        else:
            self.cfg.material_items = items
            valid_ids = {item.item_id for item in items}
            self.cfg.selected_material_ids = [
                item_id for item_id in self.cfg.selected_material_ids if item_id in valid_ids
            ]
        self._refresh_module_layout()

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

    def add_modules_submenu(self, menu: QMenu):
        module_menu = menu.addMenu("Anzeige")
        modules = [
            ("soundboard", "Soundboard-Leiste", self.cfg.show_soundboard),
            ("phase", "Methode/Sozialform", self.cfg.show_phase),
            ("materials", "Material", self.cfg.show_materials),
            ("timer", "Timer", self.cfg.show_timer),
        ]
        for key, label, visible in modules:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(visible)
            action.triggered.connect(
                lambda checked=False, module=key: self.set_module_visible(module, checked)
            )
            module_menu.addAction(action)

        module_menu.addSeparator()
        labels = QAction("Beschriftung im Panel", self)
        labels.setCheckable(True)
        labels.setChecked(self.cfg.panel_show_labels)
        labels.triggered.connect(self.set_panel_labels)
        module_menu.addAction(labels)

    def open_window_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #222; color: #eee; }")
        self.add_dock_submenu(menu)
        self.add_video_submenu(menu)
        self.add_volume_submenu(menu)
        self.add_modules_submenu(menu)

        act_manage = QAction(f"Verwalten… ({ui_modifier_label()}+M)", self)
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
        self.add_modules_submenu(menu)

        act_manage = QAction(f"Verwalten… ({ui_modifier_label()}+M)", self)
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
        if not 0 <= index < min(MAX_BUTTONS, len(self.cfg.buttons)):
            return
        cfg = self.cfg.buttons[index]
        if not cfg.media_path:
            QMessageBox.information(self, "Keine Datei", "Für diese Münze ist keine Medien-Datei zugewiesen.")
            return

        path = Path(cfg.media_path)
        if not path.is_file():
            QMessageBox.warning(
                self,
                "Datei nicht gefunden",
                "Die zugewiesene Datei wurde verschoben, umbenannt oder gelöscht.\n\n"
                f"{cfg.media_path}",
            )
            return

        if (
            self.current_index == index
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            self.stop_playback()
            self.bar.update()
            return

        self.stop_playback()

        # Ensure audio settings are applied before playing (helps on some Windows setups)
        self.apply_audio_device()
        self.apply_volume_to_audio()

        self._handling_media_error = False
        self.current_is_video = path.suffix.lower() in VIDEO_EXT
        self.current_index = index

        self.player.setSource(QUrl.fromLocalFile(str(path)))
        if self.current_is_video:
            screen = self.current_screen()
            self.video_overlay.show_video(screen, self.cfg.video_mode, self.cfg.burst_seconds)
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
            self._report_media_error("Medien-Fehler", err)
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop_playback()

    def on_media_error(self, error, error_string):
        if error == QMediaPlayer.Error.NoError:
            return
        msg = error_string or self.player.errorString()
        self._report_media_error("Wiedergabe-Fehler", msg or "Die Datei konnte nicht wiedergegeben werden.")

    def _report_media_error(self, title: str, message: str):
        if self._handling_media_error:
            return
        self._handling_media_error = True
        self.stop_playback()
        QMessageBox.warning(
            self,
            title,
            f"{message}\n\nTipp: MP3/WAV für Audio und MP4 (H.264/AAC) für Video sind "
            "unter Windows und macOS am zuverlässigsten.",
        )

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
        # Ctrl/Cmd+M opens manager
        shortcut_modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        if event.modifiers() & shortcut_modifiers and event.key() == Qt.Key.Key_M:
            self.open_manager()
            return

        # Docking shortcuts
        if event.key() in (Qt.Key.Key_T, Qt.Key.Key_Up):
            self.apply_dock_edge("top")
            return
        if event.key() in (Qt.Key.Key_B, Qt.Key.Key_Down):
            self.apply_dock_edge("bottom")
            return
        if event.key() in (Qt.Key.Key_L, Qt.Key.Key_Left):
            self.apply_dock_edge("left")
            return
        if event.key() in (Qt.Key.Key_R, Qt.Key.Key_Right):
            self.apply_dock_edge("right")
            return

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
        self._module_tick.stop()
        self.hotkey_manager.stop()
        self.player.stop()
        self._release_timer_sound()
        self.video_overlay.close()
        self.panel.close()
        if self._picker_popup:
            self._picker_popup.close()
        if self._timer_popup:
            self._timer_popup.close()
        for dialog in self._catalog_dialogs.values():
            dialog.close()
        if self.manager_dialog:
            self.manager_dialog.close()
        super().closeEvent(event)


def write_crash_log(exc_type, exc_value, exc_traceback) -> None:
    """Persist otherwise invisible errors from windowed packaged builds."""
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    try:
        log_path = get_config_path().with_name("TeacherSoundboard-crash.log")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + "=" * 72 + "\n")
            handle.write(f"{APP_NAME} {VERSION} | {platform.platform()}\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=handle)
    except OSError:
        pass


def install_exception_handler():
    def handle_exception(exc_type, exc_value, exc_traceback):
        write_crash_log(exc_type, exc_value, exc_traceback)
        app = QApplication.instance()
        if app:
            QMessageBox.critical(
                None,
                "Unerwarteter Fehler",
                "Teacher Soundboard hat einen unerwarteten Fehler erkannt. Die App kann neu gestartet "
                "werden; Details wurden in TeacherSoundboard-crash.log im Einstellungsordner gespeichert.",
            )

    sys.excepthook = handle_exception


def run_self_test(app: QApplication) -> int:
    """Exercise imports and critical runtime objects in packaged CI builds."""
    window = None
    previous_config_dir = os.environ.get("TEACHER_SOUNDBOARD_CONFIG_DIR")
    try:
        config = parse_config({
            "volume": "not-a-number",
            "visible_buttons": 99,
            "buttons": [{"hotkey": ""}],
        })
        assert config.volume == 0.75
        assert config.visible_buttons == MAX_BUTTONS
        assert config.buttons[0].hotkey == ""
        assert GlobalHotkeyManager()._normalize_hotkey("Ctrl+F1") == "<ctrl>+<f1>"
        if sys.platform in ("win32", "darwin") and not GLOBAL_HOTKEYS_AVAILABLE:
            raise RuntimeError(f"Global hotkey backend failed to import: {GLOBAL_HOTKEYS_ERROR}")

        with tempfile.TemporaryDirectory(prefix="teachersoundboard-self-test-") as temp_dir:
            os.environ["TEACHER_SOUNDBOARD_CONFIG_DIR"] = temp_dir
            atomic_write_json(
                Path(temp_dir) / CONFIG_FILE,
                {"global_hotkeys_enabled": False},
            )
            window = SoundboardWindow()
            window.cfg.show_phase = True
            window.cfg.show_materials = True
            window.cfg.show_timer = True
            window.cfg.selected_phase_id = window.cfg.phase_items[0].item_id
            window.cfg.selected_material_ids = [window.cfg.material_items[0].item_id]
            window.start_phase_timer(5)
            window._refresh_module_layout(persist=False)
            window.show()
            app.processEvents()
            if not window.isVisible():
                raise RuntimeError("Main window did not become visible")
            slot_kinds = {kind for kind, _payload in window.display_slots()}
            if slot_kinds != {"sound", "handle"}:
                raise RuntimeError(f"Unexpected bar layout: {sorted(slot_kinds)}")
            preview = window.bar.grab()
            if preview.isNull():
                raise RuntimeError("Sound bar did not render")

            app.processEvents()
            panel_layout = window.panel.layout_data
            if panel_layout is None:
                raise RuntimeError("Classroom panel was not laid out")
            panel_kinds = {region.kind for region in panel_layout.regions}
            expected_kinds = {
                "phase", "material", "timer", "timer-minus", "timer-toggle", "timer-plus",
            }
            if panel_kinds != expected_kinds:
                raise RuntimeError(f"Classroom modules missing from panel: {sorted(panel_kinds)}")
            if any(region.label for region in panel_layout.regions):
                raise RuntimeError("Panel shows labels although they are switched off")
            if not window.panel.isVisible():
                raise RuntimeError("Classroom panel did not become visible")
            panel_preview = window.panel.grab()
            if panel_preview.isNull():
                raise RuntimeError("Classroom panel did not render")

            # Klang am Ende des Timers: Zuweisung, Auslösen und Neustart prüfen.
            beep = Path(temp_dir) / "timer-end.wav"
            with wave.open(str(beep), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(8000)
                handle.writeframes(b"".join(
                    struct.pack("<h", int(9000 * math.sin(index * 0.7)))
                    for index in range(1200)
                ))
            window.cfg.timer_sound_path = str(beep)
            window.phase_timer._paused_remaining = 0.0
            window.phase_timer.running = False
            window._timer_sound_fired = False
            window._on_module_tick()
            if not window._timer_sound_fired:
                raise RuntimeError("Timer sound was not triggered when the time ran out")
            if not window.play_timer_sound():
                raise RuntimeError("Timer sound could not be started")
            window.cfg.timer_sound_path = str(Path(temp_dir) / "missing.wav")
            if window.play_timer_sound() or not window.timer_sound_error:
                raise RuntimeError("Missing timer sound was not reported")
            window.clear_timer_sound()
            if not window.timer_player.source().isEmpty():
                raise RuntimeError("Timer sound source was not released")

            window.start_phase_timer(5)
            window.phase_timer._paused_remaining = 0.0
            window.phase_timer.running = False
            window.toggle_phase_timer()
            if window.phase_timer.remaining_minutes() != 5:
                raise RuntimeError("An expired timer did not restart on play")

            window.audio.setVolume(0.5)
            media_player_available = window.player.isAvailable()
            window.close()
            window.deleteLater()
            window = None
            app.processEvents()

        if sys.platform in ("win32", "darwin") and not media_player_available:
            raise RuntimeError("Qt Multimedia backend is unavailable in this package")

        print(json.dumps({
            "status": "ok",
            "platform": sys.platform,
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "pyqt": PYQT_VERSION_STR,
            "qt": QT_VERSION_STR,
            "main_window_created": True,
            "media_player_available": media_player_available,
            "global_hotkeys_imported": GLOBAL_HOTKEYS_AVAILABLE,
            "classroom_modules_rendered": True,
            "bundled_icons": len(list(asset_icon_dir().glob("*.png"))),
        }))
        return 0
    except Exception:
        details = traceback.format_exc()
        print(details, file=sys.stderr)
        diagnostic_path = os.environ.get("TEACHER_SOUNDBOARD_SELF_TEST_LOG")
        if diagnostic_path:
            try:
                Path(diagnostic_path).write_text(details, encoding="utf-8")
            except OSError:
                pass
        return 1
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            app.processEvents()
        if previous_config_dir is None:
            os.environ.pop("TEACHER_SOUNDBOARD_CONFIG_DIR", None)
        else:
            os.environ["TEACHER_SOUNDBOARD_CONFIG_DIR"] = previous_config_dir


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION.removeprefix("v"))
    app.setOrganizationName("Florian Nowak")

    if "--self-test" in sys.argv:
        return run_self_test(app)

    install_exception_handler()

    lock_path = get_config_path().with_name("TeacherSoundboard.lock")
    instance_lock = QLockFile(str(lock_path))
    instance_lock.setStaleLockTime(5_000)
    if not instance_lock.tryLock(250):
        QMessageBox.information(
            None,
            "Teacher Soundboard läuft bereits",
            "Es ist bereits eine Instanz geöffnet. Du findest sie am Bildschirmrand oder in der Taskleiste.",
        )
        return 0

    try:
        win = SoundboardWindow()
        app.aboutToQuit.connect(win.hotkey_manager.stop)
        app.aboutToQuit.connect(win.player.stop)
        win.show()
        return app.exec()
    except Exception:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        write_crash_log(exc_type, exc_value, exc_traceback)
        QMessageBox.critical(
            None,
            "Start fehlgeschlagen",
            "Teacher Soundboard konnte nicht gestartet werden. Details stehen in "
            "TeacherSoundboard-crash.log im Einstellungsordner.",
        )
        return 1
    finally:
        instance_lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
