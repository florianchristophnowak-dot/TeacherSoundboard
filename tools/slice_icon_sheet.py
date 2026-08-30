#!/usr/bin/env python3
"""Schneidet ein generiertes Symbolblatt in einzelne Icon-Dateien.

Erwartet wird ein Blatt mit einem regelmäßigen Raster quadratischer Kacheln:
je Kachel eine flächige Hintergrundfarbe, darauf ein einfarbiges Motiv.

Das Werkzeug
  * erkennt die Rasterlinien selbst (auch bei leicht ungleichmäßigem Raster),
  * trennt das Motiv über einen Alphakanal vom Kachelhintergrund,
  * bringt alle Motive auf dieselbe optische Größe,
  * schreibt sie als transparente PNGs nach ``assets/icons/<icon_key>.png``.

Die Kachelfarbe wird bewusst nicht mitgespeichert: Sie kommt in der App aus der
Palette, damit Auswahlzustand, helle und dunkle Umgebung steuerbar bleiben.

Beispiele
---------
    python tools/slice_icon_sheet.py blatt.png
    python tools/slice_icon_sheet.py nachzuegler.png --grid 1x1 --keys pen
    python tools/slice_icon_sheet.py blatt.png --grid 4x4 --preview build/preview
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - nur bei fehlender Entwicklungsumgebung
    print("Pillow fehlt. Installation: pip install -r requirements-dev.txt", file=sys.stderr)
    raise

# Lesereihenfolge des Standardblatts (4 Spalten x 4 Zeilen).
DEFAULT_KEYS = [
    "plenum", "individual", "partner", "group",
    "presentation", "stations", "phase-placeholder", "clear",
    "binder", "book", "workbook", "worksheet",
    "pen", "tablet", "headphones", "material-placeholder",
]

# Nur für die Vorschau: So werden die Kacheln später in der App eingefärbt.
PREVIEW_COLORS = {
    "plenum": "#2563eb", "individual": "#7c3aed", "partner": "#0d9488",
    "group": "#16a34a", "presentation": "#c026d3", "stations": "#0891b2",
    "binder": "#ea580c", "book": "#dc2626", "workbook": "#d97706",
    "worksheet": "#64748b", "pen": "#e11d48", "tablet": "#334155",
    "headphones": "#b45309", "phase-placeholder": "#3f4854",
    "material-placeholder": "#3f4854", "clear": "#7f1d1d",
}
FALLBACK_COLOR = "#3f4854"

DETECT_MAX_SIDE = 512
CHANGE_THRESHOLD = 40      # Summe der Kanalunterschiede, ab der ein Pixel als "anders" gilt
MIN_BORDER_SHARE = 0.60    # Anteil der Linien, der sich an einer echten Rasterkante ändern muss
MARGIN_LUMINANCE = 232
MARGIN_MAX_SHARE = 0.25


@dataclass
class TileReport:
    key: str
    box: tuple[int, int, int, int]
    background: str
    coverage: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class SheetReport:
    source: str
    grid: str
    cuts_x: list[int]
    cuts_y: list[int]
    tiles: list[TileReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "grid": self.grid,
            "cuts_x": self.cuts_x,
            "cuts_y": self.cuts_y,
            "warnings": self.warnings,
            "tiles": [
                {
                    "key": tile.key,
                    "box": list(tile.box),
                    "background": tile.background,
                    "coverage": round(tile.coverage, 4),
                    "warnings": tile.warnings,
                }
                for tile in self.tiles
            ],
        }


# ---------------------------------------------------------------- Hilfsformeln
def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _smoothstep(low: float, high: float, value: float) -> float:
    if high <= low:
        return 1.0 if value >= high else 0.0
    t = _clamp((value - low) / (high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def _parse_color(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        raise ValueError(f"Ungültige Farbe: {value}")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


# ------------------------------------------------------------ Rand und Raster
def trim_uniform_margin(image: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
    """Entfernt einen hellen, gleichmäßigen Rand um das Raster (z. B. weißes Blatt)."""
    width, height = image.size
    pixels = image.load()
    max_x = int(width * MARGIN_MAX_SHARE)
    max_y = int(height * MARGIN_MAX_SHARE)

    def row_is_margin(y: int) -> bool:
        return all(
            sum(pixels[x, y]) / 3.0 >= MARGIN_LUMINANCE
            for x in range(0, width, max(1, width // 64))
        )

    def col_is_margin(x: int) -> bool:
        return all(
            sum(pixels[x, y]) / 3.0 >= MARGIN_LUMINANCE
            for y in range(0, height, max(1, height // 64))
        )

    left = 0
    while left < max_x and col_is_margin(left):
        left += 1
    right = width
    while right > width - max_x and col_is_margin(right - 1):
        right -= 1
    top = 0
    while top < max_y and row_is_margin(top):
        top += 1
    bottom = height
    while bottom > height - max_y and row_is_margin(bottom - 1):
        bottom -= 1

    if left >= right or top >= bottom:
        return image, (0, 0)
    if (left, top, right, bottom) == (0, 0, width, height):
        return image, (0, 0)
    return image.crop((left, top, right, bottom)), (left, top)


def _change_profile(image: Image.Image, axis: str, sample_step: int = 1) -> list[float]:
    """Anteil der Bildzeilen (bzw. -spalten), in denen sich die Farbe zum Nachbarn ändert.

    Eine echte Rasterkante trennt zwei Kacheln über die gesamte Bildhöhe, ändert also
    nahezu jede Zeile. Eine Motivkante ändert nur die Zeilen ihrer eigenen Kachel.
    Der Anteil unterscheidet beides zuverlässig - anders als die reine Farbdistanz,
    denn Weiß gegen Farbe springt stärker als zwei benachbarte Kachelfarben.
    """
    width, height = image.size
    raw = image.tobytes()
    stride = width * 3
    profile: list[float] = []

    if axis == "x":
        lines = range(0, height, sample_step)
        divisor = float(len(lines)) or 1.0
        for x in range(width - 1):
            changed = 0
            for y in lines:
                base = y * stride + x * 3
                if (
                    abs(raw[base] - raw[base + 3])
                    + abs(raw[base + 1] - raw[base + 4])
                    + abs(raw[base + 2] - raw[base + 5])
                ) > CHANGE_THRESHOLD:
                    changed += 1
            profile.append(changed / divisor)
    else:
        lines = range(0, width, sample_step)
        divisor = float(len(lines)) or 1.0
        for y in range(height - 1):
            changed = 0
            row = y * stride
            for x in lines:
                base = row + x * 3
                if (
                    abs(raw[base] - raw[base + stride])
                    + abs(raw[base + 1] - raw[base + stride + 1])
                    + abs(raw[base + 2] - raw[base + stride + 2])
                ) > CHANGE_THRESHOLD:
                    changed += 1
            profile.append(changed / divisor)
    return profile


def _pick_peaks(profile: list[float], count: int, span: int) -> list[int]:
    if count <= 0:
        return []
    tile = span / float(count + 1)
    min_separation = max(2, int(tile * 0.55))
    order = sorted(range(len(profile)), key=lambda i: profile[i], reverse=True)
    chosen: list[int] = []
    for index in order:
        if len(chosen) >= count:
            break
        if profile[index] < MIN_BORDER_SHARE:
            break
        if all(abs(index - other) >= min_separation for other in chosen):
            chosen.append(index)
    return sorted(chosen)


def _complete_grid(found: list[int], count: int, span: int) -> list[int]:
    """Ergänzt fehlende Trennlinien über ein Ausgleichsraster durch die gefundenen."""
    tile = span / float(count + 1)
    even = [int(round(tile * (i + 1))) for i in range(count)]
    slots: dict[int, int] = {}
    for position in found:
        index = min(count - 1, max(0, int(round(position / tile)) - 1))
        slots.setdefault(index, position)
    if len(slots) == count:
        return [slots[i] for i in range(count)]
    if not slots:
        return even

    indices = [index + 1 for index in slots]
    positions = [slots[index] for index in slots]
    size = len(indices)
    if size == 1:
        slope = tile
        offset = positions[0] - slope * indices[0]
    else:
        mean_index = sum(indices) / size
        mean_position = sum(positions) / size
        denominator = sum((index - mean_index) ** 2 for index in indices)
        slope = (
            sum((i - mean_index) * (p - mean_position) for i, p in zip(indices, positions)) / denominator
            if denominator
            else tile
        )
        offset = mean_position - slope * mean_index
    return [
        slots[i] if i in slots else int(round(offset + slope * (i + 1)))
        for i in range(count)
    ]


def _line_change_share(image: Image.Image, axis: str, position: int, sample_step: int = 4) -> float:
    """Anteil der Bildlinien, die genau an dieser Trennlinie die Farbe wechseln."""
    width, height = image.size
    raw = image.tobytes()
    stride = width * 3
    changed = 0
    if axis == "x":
        lines = range(0, height, sample_step)
        for y in lines:
            base = y * stride + (position - 1) * 3
            if (
                abs(raw[base] - raw[base + 3])
                + abs(raw[base + 1] - raw[base + 4])
                + abs(raw[base + 2] - raw[base + 5])
            ) > CHANGE_THRESHOLD:
                changed += 1
    else:
        lines = range(0, width, sample_step)
        row = (position - 1) * stride
        for x in lines:
            base = row + x * 3
            if (
                abs(raw[base] - raw[base + stride])
                + abs(raw[base + 1] - raw[base + stride + 1])
                + abs(raw[base + 2] - raw[base + stride + 2])
            ) > CHANGE_THRESHOLD:
                changed += 1
    return changed / float(len(lines) or 1)


def _refine_cut(image: Image.Image, axis: str, approximate: int, radius: int) -> int:
    """Sucht die exakte Trennlinie in voller Auflösung um die grobe Position herum."""
    limit = (image.width if axis == "x" else image.height) - 1
    best, best_share = approximate, -1.0
    for position in range(max(1, approximate - radius), min(limit, approximate + radius) + 1):
        share = _line_change_share(image, axis, position)
        if share > best_share:
            best, best_share = position, share
    return best


def detect_cuts(image: Image.Image, columns: int, rows: int) -> tuple[list[int], list[int], list[str]]:
    """Findet die inneren Trennlinien des Rasters; fällt auf gleichmäßige Teilung zurück."""
    width, height = image.size
    scale = min(1.0, DETECT_MAX_SIDE / float(max(width, height)))
    small = image if scale >= 1.0 else image.resize(
        (max(8, int(width * scale)), max(8, int(height * scale))), Image.Resampling.NEAREST
    )
    small_width, small_height = small.size
    warnings: list[str] = []

    def resolve(axis: str, count: int, small_span: int, full_span: int) -> list[int]:
        if count <= 0:
            return []
        even = [int(round(full_span * (i + 1) / (count + 1))) for i in range(count)]
        step = max(1, (small_height if axis == "x" else small_width) // 160)
        peaks = _pick_peaks(_change_profile(small, axis, step), count, small_span)
        factor = full_span / float(small_span)
        found = sorted(int(round((peak + 1) * factor)) for peak in peaks)
        if not found:
            warnings.append(f"Raster in Richtung {axis} nicht erkannt, gleichmäßige Teilung verwendet.")
            return even
        if len(found) < count:
            warnings.append(
                f"Nur {len(found)} von {count} Trennlinien ({axis}) erkannt, "
                "übrige aus dem Raster ergänzt."
            )
        radius = max(2, int(round(factor)) + 1)
        refined = [_refine_cut(image, axis, cut, radius) for cut in _complete_grid(found, count, full_span)]

        tolerance = (full_span / float(count + 1)) * 0.35
        unordered = any(refined[i] >= refined[i + 1] for i in range(count - 1))
        if unordered or any(abs(refined[i] - even[i]) > tolerance for i in range(count)):
            warnings.append(f"Trennlinien ({axis}) unplausibel, gleichmäßige Teilung verwendet.")
            return even
        return refined

    cuts_x = resolve("x", columns - 1, small_width, width)
    cuts_y = resolve("y", rows - 1, small_height, height)
    return cuts_x, cuts_y, warnings


def tile_boxes(
    size: tuple[int, int],
    cuts_x: list[int],
    cuts_y: list[int],
    inset: float,
) -> list[tuple[int, int, int, int]]:
    width, height = size
    xs = [0, *cuts_x, width]
    ys = [0, *cuts_y, height]
    boxes: list[tuple[int, int, int, int]] = []
    for row in range(len(ys) - 1):
        for column in range(len(xs) - 1):
            left, right = xs[column], xs[column + 1]
            top, bottom = ys[row], ys[row + 1]
            pad_x = int(round((right - left) * inset))
            pad_y = int(round((bottom - top) * inset))
            boxes.append((left + pad_x, top + pad_y, right - pad_x, bottom - pad_y))
    return boxes


# ------------------------------------------------------------- Motivfreistellung
def _background_color(tile: Image.Image) -> tuple[int, int, int]:
    """Häufigste Farbe im Ring zwischen 6 % und 16 % der Kachelkante.

    Der Ring liegt innerhalb eines möglichen andersfarbigen Stegs zwischen den
    Kacheln und zugleich außerhalb des Motivs, das nur die mittleren rund 70 %
    einnimmt. Der äußerste Rand taugt dafür nicht, weil ein weißer Steg dort
    sonst als Kachelfarbe gelten würde.
    """
    width, height = tile.size
    edge = min(width, height)
    outer = max(1, int(edge * 0.06))
    inner = max(outer + 1, int(edge * 0.16))
    pixels = tile.load()
    counts: dict[tuple[int, int, int], int] = {}
    step = max(1, edge // 96)
    for y in range(0, height, step):
        for x in range(0, width, step):
            distance = min(x, y, width - 1 - x, height - 1 - y)
            if not (outer <= distance < inner):
                continue
            red, green, blue = pixels[x, y][:3]
            key = (red // 8 * 8, green // 8 * 8, blue // 8 * 8)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return (0, 0, 0)
    return max(counts.items(), key=lambda item: item[1])[0]


def _trim_to_background(
    tile: Image.Image,
    background: tuple[int, int, int],
    tolerance: int = 60,
    max_share: float = 0.18,
) -> Image.Image:
    """Schneidet einen andersfarbigen Steg am Kachelrand weg (z. B. weiße Trennlinie)."""
    width, height = tile.size
    pixels = tile.load()

    def matches(x: int, y: int) -> bool:
        red, green, blue = pixels[x, y][:3]
        return (
            abs(red - background[0]) + abs(green - background[1]) + abs(blue - background[2])
        ) <= tolerance

    def row_is_background(y: int) -> bool:
        step = max(1, width // 32)
        sampled = range(0, width, step)
        hits = sum(1 for x in sampled if matches(x, y))
        return hits >= len(sampled) * 0.5

    def column_is_background(x: int) -> bool:
        step = max(1, height // 32)
        sampled = range(0, height, step)
        hits = sum(1 for y in sampled if matches(x, y))
        return hits >= len(sampled) * 0.5

    limit_x = int(width * max_share)
    limit_y = int(height * max_share)
    left = 0
    while left < limit_x and not column_is_background(left):
        left += 1
    right = width
    while right > width - limit_x and not column_is_background(right - 1):
        right -= 1
    top = 0
    while top < limit_y and not row_is_background(top):
        top += 1
    bottom = height
    while bottom > height - limit_y and not row_is_background(bottom - 1):
        bottom -= 1

    if left >= right or top >= bottom:
        return tile
    return tile.crop((left, top, right, bottom))


def extract_glyph(
    tile: Image.Image,
    low: float,
    high: float,
    glyph_color: tuple[int, int, int] | None,
) -> tuple[Image.Image, tuple[int, int, int], float]:
    """Erzeugt aus einer Kachel ein freigestelltes Motiv mit Alphakanal."""
    tile = tile.convert("RGB")
    background = _background_color(tile)
    tile = _trim_to_background(tile, background)
    width, height = tile.size
    raw = tile.tobytes()
    output = bytearray(width * height * 4)
    cache: dict[tuple[int, int, int], tuple[int, int, int, int]] = {}
    opaque = 0

    for index in range(0, len(raw), 3):
        pixel = (raw[index], raw[index + 1], raw[index + 2])
        resolved = cache.get(pixel)
        if resolved is None:
            distance = math.sqrt(
                (pixel[0] - background[0]) ** 2
                + (pixel[1] - background[1]) ** 2
                + (pixel[2] - background[2]) ** 2
            ) / 441.673
            alpha = _smoothstep(low, high, distance)
            value = int(round(alpha * 255))
            if value <= 0:
                resolved = (0, 0, 0, 0)
            elif glyph_color is not None:
                resolved = (glyph_color[0], glyph_color[1], glyph_color[2], value)
            else:
                # Mischfarben am Motivrand um den Hintergrundanteil bereinigen.
                resolved = (
                    *(
                        int(_clamp(background[i] + (channel - background[i]) / max(alpha, 0.25), 0, 255))
                        for i, channel in enumerate(pixel)
                    ),
                    value,
                )
            cache[pixel] = resolved
        if resolved[3] >= 128:
            opaque += 1
        target = index // 3 * 4
        output[target:target + 4] = bytes(resolved)

    glyph = Image.frombytes("RGBA", (width, height), bytes(output))
    coverage = opaque / float(width * height)
    return glyph, background, coverage


def normalize_glyph(glyph: Image.Image, size: int, content_scale: float) -> Image.Image:
    """Zentriert das Motiv seitenverhältnistreu auf einer quadratischen Fläche."""
    box = glyph.getbbox()
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if box is None:
        return canvas
    cropped = glyph.crop(box)
    target = max(1, int(round(size * content_scale)))
    ratio = min(target / cropped.width, target / cropped.height)
    new_size = (max(1, int(round(cropped.width * ratio))), max(1, int(round(cropped.height * ratio))))
    resized = cropped.resize(new_size, Image.Resampling.LANCZOS)
    canvas.paste(resized, ((size - new_size[0]) // 2, (size - new_size[1]) // 2), resized)
    return canvas


# --------------------------------------------------------------------- Ablauf
def slice_sheet(
    sheet_path: Path,
    out_dir: Path,
    keys: list[str],
    columns: int,
    rows: int,
    size: int = 512,
    inset: float = 0.02,
    content_scale: float = 0.72,
    low: float = 0.10,
    high: float = 0.30,
    glyph_color: tuple[int, int, int] | None = (255, 255, 255),
    preview_dir: Path | None = None,
) -> SheetReport:
    if len(keys) != columns * rows:
        raise ValueError(f"{columns}x{rows} Raster braucht {columns * rows} Namen, {len(keys)} übergeben.")

    sheet = Image.open(sheet_path).convert("RGB")
    sheet, offset = trim_uniform_margin(sheet)
    cuts_x, cuts_y, warnings = detect_cuts(sheet, columns, rows)
    report = SheetReport(str(sheet_path), f"{columns}x{rows}", cuts_x, cuts_y, warnings=warnings)
    if offset != (0, 0):
        report.warnings.append(f"Gleichmäßiger heller Rand entfernt (Versatz {offset[0]}/{offset[1]} px).")

    out_dir.mkdir(parents=True, exist_ok=True)
    boxes = tile_boxes(sheet.size, cuts_x, cuts_y, inset)
    glyphs: list[Image.Image] = []

    for key, box in zip(keys, boxes):
        tile = sheet.crop(box)
        glyph, background, coverage = extract_glyph(tile, low, high, glyph_color)
        normalized = normalize_glyph(glyph, size, content_scale)
        normalized.save(out_dir / f"{key}.png")
        glyphs.append(normalized)

        tile_report = TileReport(key, box, _hex(background), coverage)
        if coverage < 0.02:
            tile_report.warnings.append("Fast kein Motiv erkannt - Kachel prüfen.")
        elif coverage > 0.55:
            tile_report.warnings.append("Sehr großer Motivanteil - Hintergrund evtl. nicht flächig.")
        report.tiles.append(tile_report)

    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        _write_cut_preview(sheet, cuts_x, cuts_y, preview_dir / "preview-cuts.png")
        _write_icon_preview(glyphs, keys, columns, preview_dir / "preview-icons.png")

    (out_dir / "sheet-report.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def _write_cut_preview(sheet: Image.Image, cuts_x: list[int], cuts_y: list[int], path: Path) -> None:
    preview = sheet.copy().convert("RGB")
    draw = ImageDraw.Draw(preview)
    width, height = preview.size
    for x in cuts_x:
        draw.line([(x, 0), (x, height)], fill=(255, 0, 0), width=max(1, width // 400))
    for y in cuts_y:
        draw.line([(0, y), (width, y)], fill=(255, 0, 0), width=max(1, height // 400))
    preview.save(path)


def _write_icon_preview(glyphs: list[Image.Image], keys: list[str], columns: int, path: Path) -> None:
    if not glyphs:
        return
    cell = 200
    gap = 10
    rows = math.ceil(len(glyphs) / columns)
    canvas = Image.new(
        "RGB",
        (columns * cell + (columns + 1) * gap, rows * cell + (rows + 1) * gap),
        (18, 21, 26),
    )
    for index, (key, glyph) in enumerate(zip(keys, glyphs)):
        column, row = index % columns, index // columns
        x = gap + column * (cell + gap)
        y = gap + row * (cell + gap)
        tile = Image.new("RGBA", (cell, cell), _parse_color(PREVIEW_COLORS.get(key, FALLBACK_COLOR)) + (255,))
        scaled = glyph.resize((cell, cell), Image.Resampling.LANCZOS)
        tile.alpha_composite(scaled)
        canvas.paste(tile.convert("RGB"), (x, y))
    canvas.save(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Symbolblatt in einzelne Icons zerlegen.")
    parser.add_argument("sheet", type=Path, help="Bilddatei mit dem Symbolraster")
    parser.add_argument("--out", type=Path, default=Path("assets/icons"), help="Zielordner")
    parser.add_argument("--grid", default="4x4", help="Raster als SPALTENxZEILEN, z. B. 4x4")
    parser.add_argument("--keys", default="", help="Kommagetrennte Namen in Lesereihenfolge")
    parser.add_argument("--size", type=int, default=512, help="Kantenlänge der Ausgabedateien")
    parser.add_argument("--inset", type=float, default=0.02, help="Sicherheitsabstand je Kachelkante")
    parser.add_argument("--content-scale", type=float, default=0.72, help="Motivgröße auf der Kachel")
    parser.add_argument("--low", type=float, default=0.10, help="Freistellung: untere Schwelle")
    parser.add_argument("--high", type=float, default=0.30, help="Freistellung: obere Schwelle")
    parser.add_argument("--keep-color", action="store_true", help="Originalfarben des Motivs behalten")
    parser.add_argument("--preview", type=Path, default=None, help="Ordner für Kontrollbilder")
    args = parser.parse_args(argv)

    try:
        columns, rows = (int(part) for part in args.grid.lower().split("x", 1))
    except ValueError:
        parser.error("--grid erwartet das Format SPALTENxZEILEN, z. B. 4x4")

    keys = [key.strip() for key in args.keys.split(",") if key.strip()] if args.keys else list(DEFAULT_KEYS)
    if len(keys) != columns * rows:
        parser.error(f"{columns}x{rows} Raster braucht {columns * rows} Namen, {len(keys)} vorhanden.")

    report = slice_sheet(
        args.sheet, args.out, keys, columns, rows,
        size=args.size, inset=args.inset, content_scale=args.content_scale,
        low=args.low, high=args.high,
        glyph_color=None if args.keep_color else (255, 255, 255),
        preview_dir=args.preview,
    )

    for warning in report.warnings:
        print(f"Hinweis: {warning}")
    for tile in report.tiles:
        flags = ("  <- " + "; ".join(tile.warnings)) if tile.warnings else ""
        print(f"{tile.key:22s} Hintergrund {tile.background}  Motivanteil {tile.coverage:5.1%}{flags}")
    print(f"\n{len(report.tiles)} Symbole geschrieben nach {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
