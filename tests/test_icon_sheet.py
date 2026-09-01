import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None
    ImageDraw = None


def _load_slicer():
    spec = importlib.util.spec_from_file_location(
        "slice_icon_sheet", REPO_ROOT / "tools" / "slice_icon_sheet.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TILE_COLORS = [
    "#2563eb", "#7c3aed", "#0d9488", "#16a34a",
    "#c026d3", "#0891b2", "#3f4854", "#7f1d1d",
    "#ea580c", "#dc2626", "#d97706", "#64748b",
    "#e11d48", "#334155", "#b45309", "#3f4854",
]


def build_sheet(
    path: Path,
    columns: int = 4,
    rows: int = 4,
    tile: int = 200,
    margin: int = 37,
    jitter: tuple[int, ...] = (0, 9, -7, 0, 5),
    gutter: int = 0,
) -> None:
    """Baut ein Testblatt mit hellem Rand und leicht ungleichmäßigem Raster."""
    xs = [margin]
    for column in range(columns):
        xs.append(xs[-1] + tile + (jitter[column % len(jitter)] if column < columns - 1 else 0))
    ys = [margin]
    for row in range(rows):
        ys.append(ys[-1] + tile + (jitter[(row + 2) % len(jitter)] if row < rows - 1 else 0))

    image = Image.new("RGB", (xs[-1] + margin, ys[-1] + margin), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            left, right = xs[column], xs[column + 1]
            top, bottom = ys[row], ys[row + 1]
            if gutter:
                # Weißer Steg zwischen den Kacheln, wie ihn Bildmodelle gern einziehen.
                left, top = left + gutter, top + gutter
                right, bottom = right - gutter, bottom - gutter
            draw.rectangle([left, top, right - 1, bottom - 1], fill=TILE_COLORS[index])
            width = right - left
            height = bottom - top
            # Motiv: weiße Form in den mittleren 60 % der Kachel, je Kachel anders.
            pad_x = int(width * 0.20)
            pad_y = int(height * 0.20)
            shape = [left + pad_x, top + pad_y, right - pad_x, bottom - pad_y]
            if index % 3 == 0:
                draw.ellipse(shape, fill="white")
            elif index % 3 == 1:
                draw.rectangle(shape, fill="white")
            else:
                draw.polygon(
                    [
                        ((shape[0] + shape[2]) // 2, shape[1]),
                        (shape[2], shape[3]),
                        (shape[0], shape[3]),
                    ],
                    fill="white",
                )
    image.save(path)


@unittest.skipIf(Image is None, "Pillow ist nicht installiert")
class IconSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slicer = _load_slicer()

    def test_sheet_is_split_into_named_transparent_icons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "sheet.png"
            build_sheet(sheet)
            out = root / "icons"

            report = self.slicer.slice_sheet(
                sheet, out, list(self.slicer.DEFAULT_KEYS), 4, 4, size=128
            )

            self.assertEqual(len(report.tiles), 16)
            for key in self.slicer.DEFAULT_KEYS:
                icon = out / f"{key}.png"
                self.assertTrue(icon.is_file(), f"{key}.png fehlt")
                with Image.open(icon) as image:
                    self.assertEqual(image.mode, "RGBA")
                    self.assertEqual(image.size, (128, 128))
                    # Ecken bleiben transparent, das Motiv sitzt in der Mitte.
                    self.assertEqual(image.getpixel((0, 0))[3], 0)
                    self.assertGreater(image.getpixel((64, 64))[3], 200)

    def test_detected_backgrounds_match_the_generated_tiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "sheet.png"
            build_sheet(sheet)

            report = self.slicer.slice_sheet(
                sheet, root / "icons", list(self.slicer.DEFAULT_KEYS), 4, 4, size=64
            )

            for tile, expected in zip(report.tiles, TILE_COLORS):
                detected = self.slicer._parse_color(tile.background)
                wanted = self.slicer._parse_color(expected)
                distance = max(abs(a - b) for a, b in zip(detected, wanted))
                self.assertLessEqual(distance, 10, f"{tile.key}: {tile.background} statt {expected}")
                self.assertEqual(tile.warnings, [], f"{tile.key}: {tile.warnings}")

    def test_uneven_grid_is_detected_instead_of_split_evenly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "sheet.png"
            build_sheet(sheet)

            report = self.slicer.slice_sheet(
                sheet, root / "icons", list(self.slicer.DEFAULT_KEYS), 4, 4, size=64
            )

            self.assertEqual(report.warnings, [
                "Gleichmäßiger heller Rand entfernt (Versatz 37/37 px)."
            ])
            # Der Versatz aus build_sheet muss sich in den Schnittlinien wiederfinden.
            self.assertEqual(len(report.cuts_x), 3)
            for cut, expected in zip(report.cuts_x, (200, 409, 602)):
                self.assertLessEqual(abs(cut - expected), 6, f"Schnitt {cut} statt {expected}")

    def test_white_gutters_do_not_end_up_in_the_icons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "sheet.png"
            build_sheet(sheet, gutter=7)
            out = root / "icons"

            report = self.slicer.slice_sheet(
                sheet, out, list(self.slicer.DEFAULT_KEYS), 4, 4, size=128
            )

            for tile, expected in zip(report.tiles, TILE_COLORS):
                detected = self.slicer._parse_color(tile.background)
                wanted = self.slicer._parse_color(expected)
                distance = max(abs(a - b) for a, b in zip(detected, wanted))
                self.assertLessEqual(distance, 10, f"{tile.key}: Steg als Kachelfarbe erkannt")
                # Ohne Stegabschnitt läge der Motivanteil bei über der Hälfte der Kachel.
                self.assertLess(tile.coverage, 0.45, f"{tile.key}: Steg im Motiv gelandet")
            with Image.open(out / "plenum.png") as image:
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                self.assertGreater(image.getpixel((64, 64))[3], 200)

    def test_a_large_motif_does_not_get_mistaken_for_the_background(self):
        # Ein Motiv, das bis in den Randstreifen reicht, während der flächige
        # Hintergrund leicht rauscht: Ohne Bündelung benachbarter Farbtöne
        # gewinnt das reine Weiß gegen den über viele Stufen verteilten Ton.
        import random

        random.seed(11)
        tile = Image.new("RGB", (512, 512), (215, 120, 10))
        pixels = tile.load()
        for y in range(512):
            for x in range(512):
                red, green, blue = pixels[x, y]
                # Pro Kanal unabhängig, wie bei erzeugten Bildern: der Farbton
                # verteilt sich dadurch über mehrere feine Stufen.
                pixels[x, y] = (
                    red + random.randint(-5, 5),
                    green + random.randint(-5, 5),
                    blue + random.randint(-5, 5),
                )
        # Das Motiv ragt in den Randstreifen, beherrscht ihn aber nicht: gut ein
        # Viertel weiß, wie beim Arbeitsheft des echten Blatts. Ohne Bündelung
        # gewinnt dieses eine reine Weiß gegen den fein verteilten Orangeton.
        ImageDraw.Draw(tile).rounded_rectangle([66, 66, 445, 445], radius=18, fill="white")

        background = self.slicer._background_color(tile)
        self.assertLess(
            max(abs(a - b) for a, b in zip(background, (215, 120, 10))), 12,
            f"Hintergrund als {background} erkannt statt als Orange",
        )

    def test_single_icon_can_be_replaced_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "single.png"
            build_sheet(sheet, columns=1, rows=1, margin=0)

            report = self.slicer.slice_sheet(sheet, root / "icons", ["pen"], 1, 1, size=96)

            self.assertEqual([tile.key for tile in report.tiles], ["pen"])
            self.assertTrue((root / "icons" / "pen.png").is_file())


if __name__ == "__main__":
    unittest.main()
