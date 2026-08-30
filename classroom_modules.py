from __future__ import annotations

import math
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
    QToolButton, QVBoxLayout,
)


@dataclass
class VisualItem:
    """One configurable, language-independent symbol in the classroom bar."""

    item_id: str
    name: str
    icon_key: str = "generic"
    image_path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "icon_key": self.icon_key,
            "image_path": self.image_path,
        }


def default_phase_items() -> list[VisualItem]:
    return [
        VisualItem("phase-plenum", "Plenum", "plenum"),
        VisualItem("phase-individual", "Einzelarbeit", "individual"),
        VisualItem("phase-partner", "Partnerarbeit", "partner"),
        VisualItem("phase-group", "Gruppenarbeit", "group"),
        VisualItem("phase-presentation", "Präsentation", "presentation"),
        VisualItem("phase-stations", "Stationenarbeit", "stations"),
    ]


def default_material_items() -> list[VisualItem]:
    return [
        VisualItem("material-binder", "Hefter", "binder"),
        VisualItem("material-book", "Buch", "book"),
        VisualItem("material-workbook", "Arbeitsheft", "workbook"),
        VisualItem("material-sheet", "Arbeitsblatt", "worksheet"),
        VisualItem("material-pen", "Stift", "pen"),
        VisualItem("material-tablet", "Tablet/Computer", "tablet"),
        VisualItem("material-headphones", "Kopfhörer", "headphones"),
    ]


def parse_visual_items(raw, defaults: Callable[[], list[VisualItem]]) -> list[VisualItem]:
    if raw is None:
        return defaults()
    if not isinstance(raw, list):
        return defaults()

    parsed: list[VisualItem] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("item_id") or "").strip()
        if not item_id or item_id in seen:
            item_id = f"custom-{uuid.uuid4().hex}"
        seen.add(item_id)
        parsed.append(VisualItem(
            item_id=item_id,
            name=str(entry.get("name") or "Eigenes Symbol").strip() or "Eigenes Symbol",
            icon_key=str(entry.get("icon_key") or "generic").strip() or "generic",
            image_path=str(entry.get("image_path") or ""),
        ))
    return parsed


class PhaseTimer:
    """Drift-resistant phase timer whose public display is minute-only."""

    def __init__(self, clock: Callable[[], float] | None = None):
        self._clock = clock or time.monotonic
        self.total_seconds = 0.0
        self._deadline = 0.0
        self._paused_remaining = 0.0
        self.running = False
        self.paused = False

    def start(self, minutes: int | float) -> None:
        minutes = max(1.0, min(999.0, float(minutes)))
        self.total_seconds = minutes * 60.0
        self._paused_remaining = self.total_seconds
        self._deadline = self._clock() + self.total_seconds
        self.running = True
        self.paused = False

    def pause(self) -> None:
        if not self.running or self.paused:
            return
        self._paused_remaining = self.remaining_seconds()
        self.running = False
        self.paused = self._paused_remaining > 0

    def resume(self) -> None:
        if not self.paused or self._paused_remaining <= 0:
            return
        self._deadline = self._clock() + self._paused_remaining
        self.running = True
        self.paused = False

    def toggle_pause(self) -> None:
        if self.running:
            self.pause()
        elif self.paused:
            self.resume()

    def reset(self) -> None:
        if self.total_seconds <= 0:
            return
        self._paused_remaining = self.total_seconds
        self._deadline = self._clock() + self.total_seconds
        self.running = True
        self.paused = False

    def clear(self) -> None:
        self.total_seconds = 0.0
        self._deadline = 0.0
        self._paused_remaining = 0.0
        self.running = False
        self.paused = False

    def add_minutes(self, minutes: int | float) -> None:
        seconds = max(0.0, float(minutes) * 60.0)
        if seconds <= 0:
            return
        if self.total_seconds <= 0:
            self.start(minutes)
            return
        self.total_seconds += seconds
        if self.running:
            self._deadline += seconds
        else:
            self._paused_remaining += seconds
            if self._paused_remaining > 0:
                self.paused = True

    def remaining_seconds(self) -> float:
        if self.running:
            remaining = max(0.0, self._deadline - self._clock())
            if remaining <= 0:
                self.running = False
                self.paused = False
                self._paused_remaining = 0.0
            return remaining
        return max(0.0, self._paused_remaining)

    def remaining_minutes(self) -> int:
        remaining = self.remaining_seconds()
        return int(math.ceil(remaining / 60.0)) if remaining > 0 else 0

    def total_minutes(self) -> int:
        return int(math.ceil(self.total_seconds / 60.0)) if self.total_seconds > 0 else 0

    def progress(self) -> float:
        if self.total_seconds <= 0:
            return 0.0
        return max(0.0, min(1.0, self.remaining_seconds() / self.total_seconds))

    def has_value(self) -> bool:
        return self.total_seconds > 0


_PALETTES = {
    "plenum": (QColor("#f2c45e"), QColor("#5d4315")),
    "individual": (QColor("#9fc9e8"), QColor("#183f5b")),
    "partner": (QColor("#efad81"), QColor("#653217")),
    "group": (QColor("#9fd3b6"), QColor("#174b33")),
    "presentation": (QColor("#c5b3e6"), QColor("#412c68")),
    "stations": (QColor("#e7a9c0"), QColor("#63243d")),
    "binder": (QColor("#f1c86d"), QColor("#5c431a")),
    "book": (QColor("#9fc9e8"), QColor("#183f5b")),
    "workbook": (QColor("#b7b0e7"), QColor("#363064")),
    "worksheet": (QColor("#efefef"), QColor("#3f4650")),
    "pen": (QColor("#efad81"), QColor("#653217")),
    "tablet": (QColor("#9fd3b6"), QColor("#174b33")),
    "headphones": (QColor("#e7a9c0"), QColor("#63243d")),
    "phase-placeholder": (QColor("#f2c45e"), QColor("#5d4315")),
    "material-placeholder": (QColor("#9fc9e8"), QColor("#183f5b")),
    "generic": (QColor("#d7d9dc"), QColor("#31353a")),
    "clear": (QColor("#e2e2e2"), QColor("#8c2731")),
}


def _person(p: QPainter, x: float, y: float, scale: float, color: QColor) -> None:
    pen = QPen(color, max(1.8, scale * 0.09), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(QBrush(color))
    p.drawEllipse(QRectF(x - scale * 0.12, y - scale * 0.42, scale * 0.24, scale * 0.24))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(int(x), int(y - scale * 0.14), int(x), int(y + scale * 0.22))
    p.drawArc(QRectF(x - scale * 0.26, y + scale * 0.02, scale * 0.52, scale * 0.42), 10 * 16, 160 * 16)


def _rounded_background(p: QPainter, rect: QRectF, fill: QColor, selected: bool = False) -> QRectF:
    inset = max(1.5, rect.width() * 0.055)
    inner = rect.adjusted(inset, inset, -inset, -inset)
    p.setPen(QPen(QColor(255, 255, 255, 220) if selected else fill.darker(120), max(1.5, rect.width() * 0.035)))
    p.setBrush(QBrush(fill))
    p.drawRoundedRect(inner, inner.width() * 0.22, inner.height() * 0.22)
    if selected:
        p.setPen(QPen(QColor("#ffffff"), max(2.0, rect.width() * 0.055)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(inner.adjusted(2, 2, -2, -2), inner.width() * 0.18, inner.height() * 0.18)
    return inner


def _draw_builtin(p: QPainter, rect: QRectF, key: str, color: QColor) -> None:
    cx, cy = rect.center().x(), rect.center().y()
    s = min(rect.width(), rect.height())
    pen = QPen(color, max(2.0, s * 0.055), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if key == "plenum":
        _person(p, cx, cy - s * 0.10, s * 0.42, color)
        _person(p, cx - s * 0.25, cy + s * 0.18, s * 0.30, color)
        _person(p, cx + s * 0.25, cy + s * 0.18, s * 0.30, color)
    elif key == "individual":
        _person(p, cx - s * 0.17, cy, s * 0.46, color)
        p.drawRoundedRect(QRectF(cx + s * 0.02, cy - s * 0.20, s * 0.27, s * 0.40), 3, 3)
        p.drawLine(int(cx + s * 0.08), int(cy - s * 0.08), int(cx + s * 0.23), int(cy - s * 0.08))
        p.drawLine(int(cx + s * 0.08), int(cy + s * 0.02), int(cx + s * 0.20), int(cy + s * 0.02))
    elif key == "partner":
        _person(p, cx - s * 0.22, cy + s * 0.08, s * 0.40, color)
        _person(p, cx + s * 0.22, cy + s * 0.08, s * 0.40, color)
        bubble = QRectF(cx - s * 0.14, cy - s * 0.31, s * 0.28, s * 0.19)
        p.drawRoundedRect(bubble, s * 0.06, s * 0.06)
        p.drawLine(int(cx), int(cy - s * 0.12), int(cx - s * 0.04), int(cy - s * 0.05))
    elif key == "group":
        p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 55)))
        p.drawRoundedRect(QRectF(cx - s * 0.22, cy - s * 0.10, s * 0.44, s * 0.25), 5, 5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for x, y in [(-0.24, -0.24), (0.24, -0.24), (-0.24, 0.25), (0.24, 0.25)]:
            p.setBrush(QBrush(color))
            p.drawEllipse(QRectF(cx + s*x - s*0.07, cy + s*y - s*0.07, s*0.14, s*0.14))
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif key == "presentation":
        p.drawRoundedRect(QRectF(cx - s * 0.30, cy - s * 0.27, s * 0.46, s * 0.35), 4, 4)
        p.drawLine(int(cx - s * 0.07), int(cy + s * 0.08), int(cx - s * 0.07), int(cy + s * 0.25))
        p.drawLine(int(cx - s * 0.20), int(cy + s * 0.25), int(cx + s * 0.06), int(cy + s * 0.25))
        _person(p, cx + s * 0.25, cy + s * 0.07, s * 0.35, color)
    elif key == "stations":
        points = [(cx, cy - s*0.27), (cx + s*0.27, cy), (cx, cy + s*0.27), (cx - s*0.27, cy)]
        for index, (x, y) in enumerate(points):
            nx, ny = points[(index + 1) % len(points)]
            p.drawLine(int(x), int(y), int(nx), int(ny))
            p.setBrush(QBrush(color))
            p.drawEllipse(QRectF(x - s*0.07, y - s*0.07, s*0.14, s*0.14))
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif key == "binder":
        p.drawRoundedRect(QRectF(cx - s*0.27, cy - s*0.29, s*0.54, s*0.58), 5, 5)
        p.drawLine(int(cx - s*0.11), int(cy - s*0.28), int(cx - s*0.11), int(cy + s*0.28))
        p.setBrush(QBrush(color))
        for y in (-0.13, 0.0, 0.13):
            p.drawEllipse(QRectF(cx - s*0.18, cy + s*y - s*0.025, s*0.05, s*0.05))
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif key == "book":
        path = QPainterPath()
        path.moveTo(cx, cy - s*0.22)
        path.cubicTo(cx - s*0.12, cy - s*0.30, cx - s*0.33, cy - s*0.22, cx - s*0.33, cy + s*0.22)
        path.cubicTo(cx - s*0.14, cy + s*0.17, cx - s*0.05, cy + s*0.20, cx, cy + s*0.27)
        path.cubicTo(cx + s*0.05, cy + s*0.20, cx + s*0.14, cy + s*0.17, cx + s*0.33, cy + s*0.22)
        path.cubicTo(cx + s*0.33, cy - s*0.22, cx + s*0.12, cy - s*0.30, cx, cy - s*0.22)
        p.drawPath(path)
        p.drawLine(int(cx), int(cy - s*0.20), int(cx), int(cy + s*0.24))
    elif key == "workbook":
        p.drawRoundedRect(QRectF(cx - s*0.25, cy - s*0.30, s*0.50, s*0.60), 4, 4)
        for y in (-0.18, -0.06, 0.06, 0.18):
            p.drawLine(int(cx - s*0.30), int(cy + s*y), int(cx - s*0.20), int(cy + s*y))
        p.drawLine(int(cx - s*0.10), int(cy - s*0.12), int(cx + s*0.15), int(cy - s*0.12))
        p.drawLine(int(cx - s*0.10), int(cy), int(cx + s*0.10), int(cy))
    elif key == "worksheet":
        p.drawRoundedRect(QRectF(cx - s*0.24, cy - s*0.31, s*0.48, s*0.62), 3, 3)
        for y, width in [(-0.15, 0.28), (-0.03, 0.30), (0.09, 0.23), (0.21, 0.27)]:
            p.drawLine(int(cx - s*0.14), int(cy + s*y), int(cx - s*0.14 + s*width), int(cy + s*y))
    elif key == "pen":
        p.setBrush(QBrush(color))
        path = QPainterPath()
        path.moveTo(cx - s*0.27, cy + s*0.21)
        path.lineTo(cx - s*0.18, cy - s*0.03)
        path.lineTo(cx + s*0.20, cy - s*0.28)
        path.lineTo(cx + s*0.29, cy - s*0.16)
        path.lineTo(cx - s*0.08, cy + s*0.10)
        path.closeSubpath()
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif key == "tablet":
        p.drawRoundedRect(QRectF(cx - s*0.30, cy - s*0.24, s*0.60, s*0.48), s*0.06, s*0.06)
        p.drawEllipse(QRectF(cx + s*0.20, cy - s*0.025, s*0.05, s*0.05))
    elif key == "headphones":
        p.drawArc(QRectF(cx - s*0.28, cy - s*0.28, s*0.56, s*0.56), 15*16, 150*16)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(QRectF(cx - s*0.31, cy, s*0.14, s*0.25), 4, 4)
        p.drawRoundedRect(QRectF(cx + s*0.17, cy, s*0.14, s*0.25), 4, 4)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif key == "clear":
        p.drawEllipse(QRectF(cx - s*0.26, cy - s*0.26, s*0.52, s*0.52))
        p.drawLine(int(cx - s*0.18), int(cy + s*0.18), int(cx + s*0.18), int(cy - s*0.18))
    elif key == "phase-placeholder":
        _person(p, cx - s*0.16, cy + s*0.05, s*0.38, color)
        _person(p, cx + s*0.16, cy + s*0.05, s*0.38, color)
        p.drawEllipse(QRectF(cx - s*0.07, cy - s*0.28, s*0.14, s*0.14))
    elif key == "material-placeholder":
        p.drawRoundedRect(QRectF(cx - s*0.24, cy - s*0.25, s*0.48, s*0.50), 5, 5)
        p.drawLine(int(cx - s*0.13), int(cy), int(cx + s*0.13), int(cy))
        p.drawLine(int(cx), int(cy - s*0.13), int(cx), int(cy + s*0.13))
    else:
        p.drawEllipse(QRectF(cx - s*0.08, cy - s*0.08, s*0.16, s*0.16))
        p.drawEllipse(QRectF(cx - s*0.28, cy - s*0.08, s*0.16, s*0.16))
        p.drawEllipse(QRectF(cx + s*0.12, cy - s*0.08, s*0.16, s*0.16))


def paint_visual_item(p: QPainter, rect: QRectF, item: VisualItem, selected: bool = False) -> None:
    fill, ink = _PALETTES.get(item.icon_key, _PALETTES["generic"])
    inner = _rounded_background(p, rect, fill, selected)

    image_path = Path(item.image_path) if item.image_path else None
    if image_path and image_path.is_file():
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            target = inner.adjusted(inner.width()*0.10, inner.height()*0.10, -inner.width()*0.10, -inner.height()*0.10)
            scaled = pixmap.scaled(
                int(target.width()), int(target.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = target.center().x() - scaled.width()/2
            y = target.center().y() - scaled.height()/2
            p.drawPixmap(int(x), int(y), scaled)
            return

    _draw_builtin(p, inner.adjusted(inner.width()*0.13, inner.height()*0.13, -inner.width()*0.13, -inner.height()*0.13), item.icon_key, ink)


def render_visual_item(item: VisualItem, size: int = 64, selected: bool = False) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint_visual_item(painter, QRectF(0, 0, size, size), item, selected)
    painter.end()
    return pixmap


def paint_action_icon(p: QPainter, rect: QRectF, action: str, color: QColor = QColor("#f4f4f4")) -> None:
    s = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    p.setPen(QPen(color, max(2.0, s*0.07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if action == "play":
        path = QPainterPath()
        path.moveTo(cx - s*0.16, cy - s*0.24)
        path.lineTo(cx + s*0.24, cy)
        path.lineTo(cx - s*0.16, cy + s*0.24)
        path.closeSubpath()
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
    elif action == "pause":
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(cx - s*0.20, cy - s*0.24, s*0.13, s*0.48), 2, 2)
        p.drawRoundedRect(QRectF(cx + s*0.07, cy - s*0.24, s*0.13, s*0.48), 2, 2)
    elif action == "reset":
        p.drawArc(QRectF(cx - s*0.25, cy - s*0.25, s*0.50, s*0.50), 30*16, 290*16)
        p.drawLine(int(cx - s*0.26), int(cy - s*0.02), int(cx - s*0.30), int(cy - s*0.21))
        p.drawLine(int(cx - s*0.26), int(cy - s*0.02), int(cx - s*0.08), int(cy - s*0.08))
    elif action == "plus":
        p.drawLine(int(cx - s*0.22), int(cy), int(cx + s*0.22), int(cy))
        p.drawLine(int(cx), int(cy - s*0.22), int(cx), int(cy + s*0.22))
    elif action == "menu":
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        for dx in (-0.16, 0.16):
            for dy in (-0.16, 0.16):
                p.drawEllipse(QRectF(cx + s*dx - s*0.055, cy + s*dy - s*0.055, s*0.11, s*0.11))


def render_action_icon(action: str, size: int = 42, color: QColor = QColor("#29313a")) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint_action_icon(painter, QRectF(0, 0, size, size), action, color)
    painter.end()
    return pixmap


def paint_timer_dial(
    p: QPainter,
    rect: QRectF,
    value: int,
    progress: float,
    remaining: bool,
) -> None:
    inset = rect.width() * 0.10
    inner = rect.adjusted(inset, inset, -inset, -inset)
    track = QColor(255, 255, 255, 75)
    active = QColor("#63c6a0") if progress > 0.2 else QColor("#eda34d") if progress > 0 else QColor("#df5d67")
    p.setBrush(QBrush(QColor(24, 28, 34, 218)))
    p.setPen(QPen(QColor(255, 255, 255, 60), max(1.0, rect.width()*0.025)))
    p.drawEllipse(inner)
    ring = inner.adjusted(rect.width()*0.07, rect.height()*0.07, -rect.width()*0.07, -rect.height()*0.07)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(track, max(2.0, rect.width()*0.055), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(ring, 90*16, -360*16)
    p.setPen(QPen(active if remaining else QColor("#d7dde5"), max(2.0, rect.width()*0.055), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    arc = max(0, min(360*16, int(360*16*(progress if remaining else 1.0))))
    p.drawArc(ring, 90*16, -arc)

    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(max(12, int(rect.width()*0.30)))
    p.setFont(font)
    p.setPen(QColor("#ffffff"))
    p.drawText(inner, Qt.AlignmentFlag.AlignCenter, str(max(0, int(value))))


class IconPickerPopup(QDialog):
    itemToggled = pyqtSignal(str)
    cleared = pyqtSignal()

    def __init__(
        self,
        items: Iterable[VisualItem],
        selected_ids: set[str] | None = None,
        multi_select: bool = False,
        parent=None,
    ):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.multi_select = multi_select
        self.selected_ids = selected_ids or set()
        self.items_by_id: dict[str, VisualItem] = {}
        self.buttons_by_id: dict[str, QToolButton] = {}
        self.setStyleSheet("QDialog { background: #20252b; border: 1px solid #59616b; border-radius: 8px; }")
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(6)
        all_items = list(items)
        for index, item in enumerate(all_items):
            self.items_by_id[item.item_id] = item
            button = QToolButton(self)
            button.setToolTip(item.name)
            button.setIcon(QIcon(render_visual_item(item, 64, item.item_id in self.selected_ids)))
            button.setIconSize(QSize(58, 58))
            button.setFixedSize(66, 66)
            button.setAutoRaise(True)
            button.clicked.connect(lambda checked=False, item_id=item.item_id: self._choose(item_id))
            grid.addWidget(button, index // 5, index % 5)
            self.buttons_by_id[item.item_id] = button

        clear_item = VisualItem("__clear__", "Auswahl löschen", "clear")
        clear_button = QToolButton(self)
        clear_button.setToolTip(clear_item.name)
        clear_button.setIcon(QIcon(render_visual_item(clear_item, 64)))
        clear_button.setIconSize(QSize(58, 58))
        clear_button.setFixedSize(66, 66)
        clear_button.setAutoRaise(True)
        clear_button.clicked.connect(self._clear)
        index = len(all_items)
        grid.addWidget(clear_button, index // 5, index % 5)

    def _choose(self, item_id: str) -> None:
        if self.multi_select:
            if item_id in self.selected_ids:
                self.selected_ids.remove(item_id)
            else:
                self.selected_ids.add(item_id)
            item = self.items_by_id[item_id]
            self.buttons_by_id[item_id].setIcon(
                QIcon(render_visual_item(item, 64, item_id in self.selected_ids))
            )
        self.itemToggled.emit(item_id)
        if not self.multi_select:
            self.accept()

    def _clear(self) -> None:
        self.selected_ids.clear()
        for item_id, button in self.buttons_by_id.items():
            button.setIcon(QIcon(render_visual_item(self.items_by_id[item_id], 64, False)))
        self.cleared.emit()
        if not self.multi_select:
            self.accept()


class TimerControlPopup(QDialog):
    startRequested = pyqtSignal(int)
    pauseRequested = pyqtSignal()
    resetRequested = pyqtSignal()
    addMinuteRequested = pyqtSignal()
    clearRequested = pyqtSignal()

    def __init__(self, presets: list[int], current_minutes: int, is_running: bool, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(
            "QDialog { background: #20252b; border: 1px solid #59616b; border-radius: 8px; }"
            "QPushButton, QToolButton, QSpinBox { background: #353c44; color: white; border: 0; "
            "border-radius: 6px; padding: 7px; font-weight: 700; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        durations = QHBoxLayout()
        for minutes in presets:
            button = QPushButton(str(minutes))
            button.setToolTip(f"{minutes} Minuten starten")
            button.setFixedSize(44, 40)
            button.clicked.connect(lambda checked=False, value=minutes: self._start(value))
            durations.addWidget(button)
        self.custom_minutes = QSpinBox()
        self.custom_minutes.setRange(1, 999)
        self.custom_minutes.setValue(max(1, current_minutes or presets[0] if presets else 5))
        self.custom_minutes.setToolTip("Eigene Minutenzahl")
        self.custom_minutes.setFixedSize(64, 40)
        durations.addWidget(self.custom_minutes)
        play = self._action_button("play", "Timer starten")
        play.clicked.connect(lambda: self._start(self.custom_minutes.value()))
        durations.addWidget(play)
        root.addLayout(durations)

        controls = QHBoxLayout()
        pause = self._action_button("pause" if is_running else "play", "Pause/Fortsetzen")
        pause.clicked.connect(self._pause)
        controls.addWidget(pause)
        reset = self._action_button("reset", "Neu starten")
        reset.clicked.connect(self._reset)
        controls.addWidget(reset)
        plus = self._action_button("plus", "Eine Minute hinzufügen")
        plus.clicked.connect(self._add_minute)
        controls.addWidget(plus)
        clear_item = VisualItem("clear", "Timer löschen", "clear")
        clear = QToolButton()
        clear.setIcon(QIcon(render_visual_item(clear_item, 42)))
        clear.setIconSize(QSize(36, 36))
        clear.setFixedSize(44, 40)
        clear.setToolTip("Timer löschen")
        clear.clicked.connect(self._clear)
        controls.addWidget(clear)
        root.addLayout(controls)

    @staticmethod
    def _action_button(action: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(QIcon(render_action_icon(action, 42, QColor("#ffffff"))))
        button.setIconSize(QSize(34, 34))
        button.setFixedSize(44, 40)
        button.setToolTip(tooltip)
        return button

    def _start(self, minutes: int) -> None:
        self.startRequested.emit(minutes)
        self.accept()

    def _pause(self) -> None:
        self.pauseRequested.emit()
        self.accept()

    def _reset(self) -> None:
        self.resetRequested.emit()
        self.accept()

    def _add_minute(self) -> None:
        self.addMinuteRequested.emit()
        self.accept()

    def _clear(self) -> None:
        self.clearRequested.emit()
        self.accept()


class CatalogEditorDialog(QDialog):
    """Language-bearing manager; the persistent classroom bar remains icon-only."""

    def __init__(
        self,
        title: str,
        items: list[VisualItem],
        icon_dir: Path,
        defaults: Callable[[], list[VisualItem]],
        changed: Callable[[list[VisualItem]], None],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(620, 520)
        self.items = items
        self.icon_dir = icon_dir
        self.defaults = defaults
        self.changed = changed

        root = QVBoxLayout(self)
        info = QLabel(
            "Die Bezeichnungen werden nur in der Verwaltung und als Hilfetext verwendet. "
            "In der Unterrichtsleiste erscheinen ausschließlich Symbole oder Bilder."
        )
        info.setWordWrap(True)
        root.addWidget(info)
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(54, 54))
        root.addWidget(self.list_widget, 1)

        row = QGridLayout()
        actions = [
            ("Hinzufügen…", self._add),
            ("Bezeichnung…", self._rename),
            ("Bild/Symbol austauschen…", self._replace_image),
            ("Standardbild", self._reset_image),
            ("Nach oben", lambda: self._move(-1)),
            ("Nach unten", lambda: self._move(1)),
            ("Entfernen", self._remove),
            ("Standards wiederherstellen", self._restore_defaults),
        ]
        for index, (label, callback) in enumerate(actions):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button, index // 4, index % 4)
        root.addLayout(row)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("Schließen")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)
        self.refresh()

    def refresh(self, selected_id: str | None = None) -> None:
        self.list_widget.clear()
        selected_row = 0
        for row, item in enumerate(self.items):
            entry = QListWidgetItem(QIcon(render_visual_item(item, 64)), item.name)
            entry.setData(Qt.ItemDataRole.UserRole, item.item_id)
            self.list_widget.addItem(entry)
            if item.item_id == selected_id:
                selected_row = row
        if self.items:
            self.list_widget.setCurrentRow(min(selected_row, len(self.items) - 1))

    def _current(self) -> VisualItem | None:
        row = self.list_widget.currentRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    def _notify(self, selected_id: str | None = None) -> None:
        self.changed(self.items)
        self.refresh(selected_id)

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "Eigenes Symbol", "Bezeichnung für die Verwaltung:")
        if not ok or not name.strip():
            return
        item = VisualItem(f"custom-{uuid.uuid4().hex}", name.strip(), "generic")
        self.items.append(item)
        self._notify(item.item_id)

    def _rename(self) -> None:
        item = self._current()
        if not item:
            return
        name, ok = QInputDialog.getText(self, "Bezeichnung", "Neue Bezeichnung:", text=item.name)
        if ok and name.strip():
            item.name = name.strip()
            self._notify(item.item_id)

    def _replace_image(self) -> None:
        item = self._current()
        if not item:
            return
        source, _ = QFileDialog.getOpenFileName(
            self, "Bild oder Symbol auswählen", str(Path.home()),
            "Bilder und Symbole (*.png *.jpg *.jpeg *.svg)",
        )
        if not source:
            return
        source_path = Path(source)
        self.icon_dir.mkdir(parents=True, exist_ok=True)
        destination = self.icon_dir / f"{item.item_id}-{uuid.uuid4().hex[:8]}{source_path.suffix.lower()}"
        try:
            shutil.copy2(source_path, destination)
        except OSError as exc:
            QMessageBox.warning(self, "Bild konnte nicht übernommen werden", str(exc))
            return
        item.image_path = str(destination)
        self._notify(item.item_id)

    def _reset_image(self) -> None:
        item = self._current()
        if item:
            item.image_path = ""
            self._notify(item.item_id)

    def _move(self, delta: int) -> None:
        row = self.list_widget.currentRow()
        target = row + delta
        if not (0 <= row < len(self.items) and 0 <= target < len(self.items)):
            return
        item = self.items.pop(row)
        self.items.insert(target, item)
        self._notify(item.item_id)

    def _remove(self) -> None:
        item = self._current()
        if not item:
            return
        answer = QMessageBox.question(self, "Symbol entfernen", f"„{item.name}“ wirklich entfernen?")
        if answer == QMessageBox.StandardButton.Yes:
            self.items.remove(item)
            self._notify()

    def _restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self, "Standards wiederherstellen",
            "Die aktuelle Liste wird durch die Standards ersetzt. Eigene importierte Bilddateien bleiben gespeichert.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.items[:] = self.defaults()
            self._notify()
