from __future__ import annotations

import math
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
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


# Aufrunden mit Toleranz. Eine Restzeit entsteht als Differenz zweier
# Uhrabfragen; liefern beide denselben Wert, ergibt (t + 300.0) - t in
# Gleitkomma nicht immer genau 300, sondern gelegentlich einen Hauch mehr.
# Ohne Toleranz macht ceil daraus eine ganze Minute zu viel. Unter Windows
# fällt das auf, weil time.monotonic dort nur rund 15 ms auflöst und zwei
# kurz aufeinanderfolgende Abfragen deshalb oft gleich ausfallen.
_CEIL_TOLERANCE = 1e-9


def _ceil_units(value: float, unit: float = 1.0) -> int:
    return int(math.ceil(value / unit - _CEIL_TOLERANCE))


class PhaseTimer:
    """Driftfester Phasentimer."""

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
        """Verlängert oder verkürzt die laufende Zeit um die angegebenen Minuten."""
        seconds = float(minutes) * 60.0
        if seconds == 0:
            return
        if self.total_seconds <= 0:
            if seconds > 0:
                self.start(minutes)
            return

        was_running = self.running
        remaining = max(0.0, self.remaining_seconds() + seconds)
        self.total_seconds = max(remaining, self.total_seconds + seconds)
        if remaining <= 0:
            self.running = False
            self.paused = False
            self._paused_remaining = 0.0
            self._deadline = self._clock()
            return

        self._paused_remaining = remaining
        if was_running:
            self._deadline = self._clock() + remaining
            self.running = True
            self.paused = False
        else:
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
        return _ceil_units(remaining, 60.0) if remaining > 0 else 0

    def total_minutes(self) -> int:
        return _ceil_units(self.total_seconds, 60.0) if self.total_seconds > 0 else 0

    def progress(self) -> float:
        if self.total_seconds <= 0:
            return 0.0
        return max(0.0, min(1.0, self.remaining_seconds() / self.total_seconds))

    def has_value(self) -> bool:
        return self.total_seconds > 0


# Kachelfarben der mitgelieferten Symbole. Gleiche wahrgenommene Helligkeit,
# damit die Reihe als ein System wirkt; kühle Töne für Sozialformen, warme für
# Material. Das Motiv ist immer weiß.
_TILE_COLORS = {
    "plenum": QColor("#2563eb"),
    "individual": QColor("#7c3aed"),
    "partner": QColor("#0d9488"),
    "group": QColor("#16a34a"),
    "presentation": QColor("#c026d3"),
    "stations": QColor("#0891b2"),
    "binder": QColor("#ea580c"),
    "book": QColor("#dc2626"),
    "workbook": QColor("#d97706"),
    "worksheet": QColor("#64748b"),
    "pen": QColor("#e11d48"),
    "tablet": QColor("#4c6382"),
    "headphones": QColor("#b45309"),
    "phase-placeholder": QColor("#3f4854"),
    "material-placeholder": QColor("#3f4854"),
    "generic": QColor("#475569"),
    "clear": QColor("#7f1d1d"),
}
_INK = QColor("#ffffff")

_GLYPH_CACHE: dict[str, QPixmap | None] = {}


def asset_icon_dir() -> Path:
    """Ordner der mitgelieferten Symbole, auch im gepackten Programm."""
    bundle = getattr(sys, "_MEIPASS", None)
    root = Path(bundle) if bundle else Path(__file__).resolve().parent
    return root / "assets" / "icons"


def glyph_pixmap(icon_key: str) -> QPixmap | None:
    """Mitgeliefertes Symbol (weißes Motiv auf transparentem Grund) oder None."""
    if icon_key in _GLYPH_CACHE:
        return _GLYPH_CACHE[icon_key]
    pixmap = None
    path = asset_icon_dir() / f"{icon_key}.png"
    if path.is_file():
        loaded = QPixmap(str(path))
        if not loaded.isNull():
            pixmap = loaded
    _GLYPH_CACHE[icon_key] = pixmap
    return pixmap


def clear_glyph_cache() -> None:
    _GLYPH_CACHE.clear()


def tile_color(icon_key: str) -> QColor:
    return _TILE_COLORS.get(icon_key, _TILE_COLORS["generic"])


def _fit_square(rect: QRectF, pixmap: QPixmap) -> QRectF:
    """Zielrechteck, das das Bild seitenverhältnistreu in rect zentriert."""
    if pixmap.width() <= 0 or pixmap.height() <= 0:
        return rect
    ratio = min(rect.width() / pixmap.width(), rect.height() / pixmap.height())
    width = pixmap.width() * ratio
    height = pixmap.height() * ratio
    return QRectF(
        rect.center().x() - width / 2.0,
        rect.center().y() - height / 2.0,
        width,
        height,
    )


def _person(p: QPainter, x: float, y: float, scale: float, color: QColor) -> None:
    pen = QPen(color, max(1.8, scale * 0.09), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(QBrush(color))
    p.drawEllipse(QRectF(x - scale * 0.12, y - scale * 0.42, scale * 0.24, scale * 0.24))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(int(x), int(y - scale * 0.14), int(x), int(y + scale * 0.22))
    p.drawArc(QRectF(x - scale * 0.26, y + scale * 0.02, scale * 0.52, scale * 0.42), 10 * 16, 160 * 16)


def _rounded_background(p: QPainter, rect: QRectF, fill: QColor, selected: bool = False) -> QRectF:
    """Flächige Kachel ohne Umrandung; nur die Auswahl bekommt einen Ring."""
    inset = max(0.5, rect.width() * 0.02)
    inner = rect.adjusted(inset, inset, -inset, -inset)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(fill))
    p.drawRoundedRect(inner, inner.width() * 0.22, inner.height() * 0.22)
    if selected:
        p.setPen(QPen(QColor("#ffffff"), max(2.0, rect.width() * 0.05)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(inner.adjusted(1, 1, -1, -1), inner.width() * 0.20, inner.height() * 0.20)
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
    """Zeichnet eine Symbolkachel: eigenes Bild, mitgeliefertes Symbol oder Vektor-Rückfall."""
    inner = _rounded_background(p, rect, tile_color(item.icon_key), selected)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    image_path = Path(item.image_path) if item.image_path else None
    if image_path and image_path.is_file():
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            target = inner.adjusted(
                inner.width()*0.10, inner.height()*0.10,
                -inner.width()*0.10, -inner.height()*0.10,
            )
            p.drawPixmap(_fit_square(target, pixmap), pixmap, QRectF(pixmap.rect()))
            return

    # Die mitgelieferten Dateien tragen ihren Rand bereits in sich.
    glyph = glyph_pixmap(item.icon_key)
    if glyph is not None:
        p.drawPixmap(_fit_square(inner, glyph), glyph, QRectF(glyph.rect()))
        return

    _draw_builtin(p, inner.adjusted(inner.width()*0.13, inner.height()*0.13, -inner.width()*0.13, -inner.height()*0.13), item.icon_key, _INK)


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
        radius = s * 0.25
        p.drawArc(QRectF(cx - radius, cy - radius, radius*2, radius*2), 60*16, 280*16)
        # Pfeilspitze am Ende des Bogens, tangential in Laufrichtung.
        angle = math.radians(340)
        px_, py_ = cx + radius*math.cos(angle), cy - radius*math.sin(angle)
        dx, dy = -math.sin(angle), -math.cos(angle)
        tip = QPointF(px_ + dx*s*0.17, py_ + dy*s*0.17)
        head = QPainterPath()
        head.moveTo(tip)
        head.lineTo(px_ - dy*s*0.11, py_ + dx*s*0.11)
        head.lineTo(px_ + dy*s*0.11, py_ - dx*s*0.11)
        head.closeSubpath()
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(head)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif action == "plus":
        p.drawLine(int(cx - s*0.22), int(cy), int(cx + s*0.22), int(cy))
        p.drawLine(int(cx), int(cy - s*0.22), int(cx), int(cy + s*0.22))
    elif action == "minus":
        p.drawLine(int(cx - s*0.22), int(cy), int(cx + s*0.22), int(cy))
    elif action == "sound":
        body = QPainterPath()
        body.moveTo(cx - s*0.28, cy - s*0.11)
        body.lineTo(cx - s*0.16, cy - s*0.11)
        body.lineTo(cx - s*0.02, cy - s*0.26)
        body.lineTo(cx - s*0.02, cy + s*0.26)
        body.lineTo(cx - s*0.16, cy + s*0.11)
        body.lineTo(cx - s*0.28, cy + s*0.11)
        body.closeSubpath()
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(body)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, max(1.6, s*0.06), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for radius in (0.16, 0.28):
            p.drawArc(
                QRectF(cx + s*0.02 - s*radius, cy - s*radius, s*radius*2, s*radius*2),
                -55*16, 110*16,
            )
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


TIMER_IDLE = QColor("#5d6874")
TIMER_PAUSED = QColor("#eda34d")
TIMER_DONE = QColor("#df5d67")
TIMER_SPENT = QColor("#39424f")   # bereits verstrichener Teil des Kreises


def timer_arc_color(progress: float) -> QColor:
    if progress > 0.20:
        return QColor("#63c6a0")
    return QColor("#eda34d") if progress > 0 else QColor("#df5d67")


def paint_timer_disc(
    p: QPainter,
    rect: QRectF,
    progress: float,
    state: str,
) -> None:
    """Restzeit als schrumpfender Kreisausschnitt. state: running | paused | idle | done.

    Bewusst ohne Ziffern: Der Ausschnitt zeigt die verbleibende Zeit als Fläche
    und ist damit auch aus der letzten Reihe ablesbar.
    """
    disc = rect.adjusted(1, 1, -1, -1)
    p.setPen(Qt.PenStyle.NoPen)

    if state == "idle":
        p.setBrush(QBrush(TIMER_IDLE))
        p.drawEllipse(disc)
        return
    if state == "done":
        p.setBrush(QBrush(TIMER_DONE))
        p.drawEllipse(disc)
        return

    # Dunkle Scheibe als verbrauchte Zeit, darauf der farbige Rest.
    p.setBrush(QBrush(TIMER_SPENT))
    p.drawEllipse(disc)
    p.setBrush(QBrush(TIMER_PAUSED if state == "paused" else timer_arc_color(progress)))
    span = max(0, min(360 * 16, int(round(360 * 16 * progress))))
    if span > 0:
        p.drawPie(disc, 90 * 16, -span)


# ---------------- Unterrichtspanel am rechten Bildschirmrand ----------------
PANEL_MIN_UNIT = 36
PANEL_MAX_UNIT = 96
PANEL_MATERIAL_COLUMNS = 2


@dataclass
class PanelRegion:
    """Ein anklickbarer Bereich des Panels."""

    kind: str                                    # phase | material | timer | timer-*
    rect: QRectF                                 # Klickfläche
    tile: QRectF                                 # Zeichenfläche für Symbol, Scheibe oder Taste
    item: VisualItem | None = None
    action: str = ""                             # Symbol der Schaltflächen


@dataclass
class PanelLayout:
    width: int
    height: int
    unit: int
    grip: QRectF
    regions: list[PanelRegion] = field(default_factory=list)

    def region_at(self, point: QPointF) -> PanelRegion | None:
        for region in self.regions:
            if region.rect.contains(point):
                return region
        return None


def build_panel_layout(
    unit: int,
    show_phase: bool,
    show_materials: bool,
    show_timer: bool,
    phase_item: VisualItem | None,
    material_items: list[VisualItem],
) -> PanelLayout:
    """Berechnet die Panelgeometrie ohne Fenster - dadurch für sich testbar.

    Das Panel bleibt frei von Schrift; alles steht rechtsbündig, also zur
    Bildschirmkante hin, an der das Panel klebt.
    """
    unit = max(PANEL_MIN_UNIT, int(unit))
    pad = round(unit * 0.14)
    gap = round(unit * 0.38)          # Gruppen trennt allein der Abstand
    row_gap = round(unit * 0.13)
    big = round(unit * 1.50)
    small = unit
    dial = round(unit * 1.90)
    button = round(unit * 0.62)
    toggle = round(unit * 0.86)       # Start/Pause ist das Hauptbedienelement
    button_gap = round(unit * 0.16)
    grip_height = round(unit * 0.24)
    columns = PANEL_MATERIAL_COLUMNS

    phase_display = phase_item or VisualItem(
        "phase-placeholder", "", "phase-placeholder"
    )
    material_display = material_items or [
        VisualItem("material-placeholder", "", "material-placeholder")
    ]

    button_row = 2 * button + toggle + 2 * button_gap
    content_width = max(
        big,
        columns * small + (columns - 1) * row_gap,
        dial,
        button_row if show_timer else 0,
    )
    width = pad * 2 + content_width
    right = float(pad + content_width)          # alles endet an dieser Kante

    layout = PanelLayout(width=width, height=0, unit=unit, grip=QRectF())
    grip_width = round(unit * 0.62)
    layout.grip = QRectF(
        right - grip_width, pad * 0.55, grip_width, max(3.0, grip_height * 0.28)
    )

    y = float(pad + grip_height)
    first_section = True

    def open_section() -> None:
        nonlocal y, first_section
        if not first_section:
            y += gap
        first_section = False

    if show_phase:
        open_section()
        tile = QRectF(right - big, y, big, big)
        layout.regions.append(PanelRegion("phase", QRectF(tile), tile, phase_display))
        y += big

    if show_materials:
        open_section()
        for index in range(0, len(material_display), columns):
            row_items = material_display[index:index + columns]
            row_width = len(row_items) * small + (len(row_items) - 1) * row_gap
            x = right - row_width
            for item in row_items:
                tile = QRectF(x, y, small, small)
                layout.regions.append(PanelRegion("material", QRectF(tile), tile, item))
                x += small + row_gap
            y += small
            if index + columns < len(material_display):
                y += row_gap

    if show_timer:
        open_section()
        ring = QRectF(right - dial, y, dial, dial)
        layout.regions.append(PanelRegion("timer", QRectF(ring), ring))
        y += dial + row_gap

        x = right - button_row
        for kind, action, size in (
            ("timer-minus", "minus", button),
            ("timer-toggle", "play", toggle),
            ("timer-plus", "plus", button),
        ):
            tile = QRectF(x, y + (toggle - size) / 2.0, size, size)
            layout.regions.append(PanelRegion(kind, QRectF(tile), tile, None, action))
            x += size + button_gap
        y += toggle

    layout.height = int(round(y + pad))
    return layout


class ClassroomPanel(QWidget):
    """Frei am rechten Bildschirmrand verschiebbares Anzeigefeld.

    Zeigt Sozialform, Material und Timer groß genug, um bis in die letzte Reihe
    lesbar zu sein. Jeder der drei Abschnitte lässt sich einzeln zuschalten.
    Ohne Beschriftung bleibt es rein bildlich, wie für die Klasse vorgesehen.
    """

    def __init__(self, host):
        # Kein Qt.Tool: macOS blendet Werkzeugfenster aus, sobald eine andere
        # Anwendung aktiv wird - das Panel soll aber gerade dann sichtbar sein.
        # Das Elternfenster verhindert einen zweiten Eintrag in der Taskleiste.
        super().__init__(
            host,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.host = host
        self.layout_data: PanelLayout | None = None
        self._drag_grab = 0
        self._dragging = False
        self._hovered: str = ""

    # ---- Geometrie
    def has_content(self) -> bool:
        cfg = self.host.cfg
        return bool(cfg.show_phase or cfg.show_materials or cfg.show_timer)

    def unit_for_screen(self) -> int:
        available = self.host.current_screen().availableGeometry()
        return max(44, min(PANEL_MAX_UNIT, int(available.height() * 0.062)))

    def relayout(self, reposition: bool = True) -> None:
        if not self.has_content():
            self.layout_data = None
            self.hide()
            return

        cfg = self.host.cfg
        timer = self.host.phase_timer
        available = self.host.current_screen().availableGeometry()
        unit = self.unit_for_screen()

        # Bei vielen Materialien darf das Panel nicht über den Bildschirm
        # hinauswachsen: notfalls kleiner rechnen, bis es passt.
        while True:
            layout = build_panel_layout(
                unit,
                cfg.show_phase,
                cfg.show_materials,
                cfg.show_timer,
                self.host.selected_phase_item(),
                self.host.selected_material_items(),
            )
            if layout.height <= available.height() or unit <= PANEL_MIN_UNIT:
                break
            unit = max(PANEL_MIN_UNIT, int(unit * 0.9))

        self.layout_data = layout
        self.setFixedSize(self.layout_data.width, self.layout_data.height)
        if reposition:
            self.apply_position()
        if not self.isVisible():
            self.show()
        self.update()

    def apply_position(self) -> None:
        available = self.host.current_screen().availableGeometry()
        ratio = max(0.0, min(1.0, float(self.host.cfg.panel_y_ratio)))
        span = max(0, available.height() - self.height())
        self.move(
            available.right() - self.width() + 1,
            available.top() + int(round(ratio * span)),
        )

    def _store_position(self) -> None:
        available = self.host.current_screen().availableGeometry()
        span = max(1, available.height() - self.height())
        ratio = (self.y() - available.top()) / float(span)
        self.host.cfg.panel_y_ratio = max(0.0, min(1.0, ratio))
        self.host.save_config()

    # ---- Zeichnen
    def timer_state(self) -> str:
        timer = self.host.phase_timer
        if not timer.has_value():
            return "idle"
        if timer.remaining_seconds() <= 0:
            return "done"
        return "running" if timer.running else "paused"

    def paintEvent(self, event):
        if self.layout_data is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Bewusst ohne Hintergrundkarte: es stehen nur die Symbole im Bild.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(125, 134, 146, 190)))
        grip = self.layout_data.grip
        painter.drawRoundedRect(grip, grip.height() / 2.0, grip.height() / 2.0)

        state = self.timer_state()
        for region in self.layout_data.regions:
            self._paint_hover(painter, region)
            if region.kind == "timer":
                paint_timer_disc(painter, region.tile, self.host.phase_timer.progress(), state)
            elif region.kind.startswith("timer-"):
                self._paint_button(painter, region, state)
            elif region.item is not None:
                paint_visual_item(painter, region.tile, region.item)

        painter.end()

    def _paint_hover(self, painter: QPainter, region: PanelRegion) -> None:
        """Zeigt die Schaltfläche unter dem Zeiger als dünnen Ring."""
        if self._hovered != self._region_key(region):
            return
        tile = region.tile.adjusted(-2, -2, 2, 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 205), max(1.6, tile.width() * 0.035)))
        if region.kind == "timer" or region.kind.startswith("timer-"):
            painter.drawEllipse(tile)
        else:
            painter.drawRoundedRect(tile, tile.width() * 0.24, tile.height() * 0.24)

    def _paint_button(self, painter: QPainter, region: PanelRegion, state: str) -> None:
        action = region.action
        if region.kind == "timer-toggle":
            action = "pause" if state == "running" else "play"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(TIMER_IDLE))
        painter.drawEllipse(region.tile)
        inset = region.tile.width() * 0.26
        paint_action_icon(
            painter, region.tile.adjusted(inset, inset, -inset, -inset), action, QColor("#ffffff")
        )

    @staticmethod
    def _region_key(region: PanelRegion) -> str:
        return f"{region.kind}:{region.item.item_id if region.item else ''}"

    # ---- Eingaben
    def mousePressEvent(self, event):
        if self.layout_data is None:
            return
        global_pos = event.globalPosition().toPoint()
        if event.button() == Qt.MouseButton.RightButton:
            self.host.open_window_menu(global_pos)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        region = self.layout_data.region_at(event.position())
        if region is None or event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._dragging = True
            self._drag_grab = global_pos.y() - self.y()
            event.accept()
            return

        if region.kind == "phase":
            self.host.open_phase_picker(global_pos)
        elif region.kind == "material":
            self.host.open_material_picker(global_pos)
        elif region.kind == "timer":
            self.host.open_timer_controls(global_pos)
        elif region.kind == "timer-toggle":
            self.host.toggle_phase_timer()
        elif region.kind == "timer-minus":
            self.host.adjust_phase_timer(-1)
        elif region.kind == "timer-plus":
            self.host.adjust_phase_timer(1)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            available = self.host.current_screen().availableGeometry()
            target = event.globalPosition().toPoint().y() - self._drag_grab
            lowest = available.bottom() - self.height() + 1
            self.move(self.x(), max(available.top(), min(target, lowest)))
            event.accept()
            return
        if self.layout_data is not None:
            region = self.layout_data.region_at(event.position())
            key = self._region_key(region) if region else ""
            if key != self._hovered:
                self._hovered = key
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.OpenHandCursor
                )
                self.update()

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._store_position()
            event.accept()

    def leaveEvent(self, event):
        if self._hovered:
            self._hovered = ""
            self.update()
        super().leaveEvent(event)


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
    """Auswahl der Dauer. Pause, Neustart und Minuten liegen im Panel selbst."""

    startRequested = pyqtSignal(int)
    resetRequested = pyqtSignal()
    clearRequested = pyqtSignal()
    soundRequested = pyqtSignal()

    def __init__(self, presets: list[int], current_minutes: int, is_running: bool, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(
            "QDialog { background: #20252b; border: 1px solid #59616b; border-radius: 8px; }"
            "QPushButton, QToolButton, QSpinBox { background: #353c44; color: white; border: 0; "
            "border-radius: 8px; padding: 7px; font-size: 17px; font-weight: 700; }"
            "QPushButton:hover, QToolButton:hover { background: #46505c; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        durations = QHBoxLayout()
        durations.setSpacing(6)
        for minutes in presets:
            button = QPushButton(str(minutes))
            button.setToolTip(f"{minutes} Minuten starten")
            button.setFixedSize(54, 48)
            button.clicked.connect(lambda checked=False, value=minutes: self._start(value))
            durations.addWidget(button)
        root.addLayout(durations)

        custom = QHBoxLayout()
        custom.setSpacing(6)
        # Eigene Tasten statt der Pfeile des Zahlenfelds: die zeichnet Qt je
        # nach Plattform unterschiedlich groß, teils gar nicht sichtbar.
        self.custom_minutes = QSpinBox()
        self.custom_minutes.setRange(1, 999)
        self.custom_minutes.setValue(max(1, current_minutes or (presets[0] if presets else 5)))
        self.custom_minutes.setToolTip("Eigene Minutenzahl")
        self.custom_minutes.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.custom_minutes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.custom_minutes.setFixedSize(72, 48)

        less = self._action_button("minus", "Eine Minute weniger")
        less.clicked.connect(self.custom_minutes.stepDown)
        custom.addWidget(less)
        custom.addWidget(self.custom_minutes)
        more = self._action_button("plus", "Eine Minute mehr")
        more.clicked.connect(self.custom_minutes.stepUp)
        custom.addWidget(more)

        play = self._action_button("play", "Mit dieser Dauer starten")
        play.clicked.connect(lambda: self._start(self.custom_minutes.value()))
        custom.addWidget(play)
        root.addLayout(custom)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        reset = self._action_button("reset", "Von vorn beginnen")
        reset.setEnabled(is_running)
        reset.clicked.connect(self._reset)
        actions.addWidget(reset)

        clear = QToolButton()
        clear.setIcon(QIcon(render_visual_item(VisualItem("clear", "", "clear"), 48)))
        clear.setIconSize(QSize(40, 40))
        clear.setFixedSize(54, 48)
        clear.setToolTip("Timer löschen")
        clear.clicked.connect(self._clear)
        actions.addWidget(clear)

        sound = self._action_button("sound", "Klang am Ende des Timers festlegen")
        sound.clicked.connect(self._sound)
        actions.addWidget(sound)
        root.addLayout(actions)

    @staticmethod
    def _action_button(action: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(QIcon(render_action_icon(action, 48, QColor("#ffffff"))))
        button.setIconSize(QSize(38, 38))
        button.setFixedSize(54, 48)
        button.setToolTip(tooltip)
        return button

    def _start(self, minutes: int) -> None:
        self.startRequested.emit(minutes)
        self.accept()

    def _reset(self) -> None:
        self.resetRequested.emit()
        self.accept()

    def _clear(self) -> None:
        self.clearRequested.emit()
        self.accept()

    def _sound(self) -> None:
        self.soundRequested.emit()
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
