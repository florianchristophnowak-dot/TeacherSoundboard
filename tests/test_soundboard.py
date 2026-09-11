import ast
import json
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QPointF

import classroom_modules
import companion
import soundboard
from classroom_modules import (
    PhaseTimer, build_panel_layout, default_material_items, default_phase_items,
)


class ConfigTests(unittest.TestCase):
    def test_platform_config_directories(self):
        home = Path("/Users/test")
        self.assertEqual(
            soundboard.platform_config_dir("darwin", {}, home),
            home / "Library" / "Application Support" / "TeacherSoundboard",
        )
        self.assertEqual(
            soundboard.platform_config_dir("win32", {"APPDATA": "C:/Users/test/AppData/Roaming"}, home),
            Path("C:/Users/test/AppData/Roaming") / "TeacherSoundboard",
        )
        self.assertEqual(
            soundboard.platform_config_dir("linux", {"XDG_CONFIG_HOME": "/tmp/config"}, home),
            Path("/tmp/config") / "TeacherSoundboard",
        )
        self.assertEqual(
            soundboard.platform_config_dir(
                "darwin",
                {"TEACHER_SOUNDBOARD_CONFIG_DIR": "/tmp/isolated-config"},
                home,
            ),
            Path("/tmp/isolated-config"),
        )

    def test_config_is_clamped_and_unknown_button_fields_are_ignored(self):
        config = soundboard.parse_config({
            "dock_edge": "somewhere",
            "volume": 50,
            "visible_buttons": -5,
            "buttons": [{"media_path": "sound.mp3", "future_field": True}],
        })
        self.assertEqual(config.dock_edge, "top")
        self.assertEqual(config.volume, 1.0)
        self.assertEqual(config.visible_buttons, 1)
        self.assertEqual(config.buttons[0].media_path, "sound.mp3")
        self.assertEqual(config.buttons[0].hotkey, "F1")
        self.assertEqual(len(config.buttons), soundboard.MAX_BUTTONS)

    def test_explicitly_cleared_hotkey_stays_cleared(self):
        config = soundboard.parse_config({"buttons": [{"hotkey": ""}]})
        self.assertEqual(config.buttons[0].hotkey, "")
        self.assertEqual(config.buttons[1].hotkey, "F2")

    def test_invalid_values_fall_back_without_crashing(self):
        config = soundboard.parse_config({
            "volume": "NaN",
            "visible_buttons": object(),
            "buttons": "not-a-list",
            "global_hotkeys_enabled": "false",
        })
        self.assertEqual(config.volume, 0.75)
        self.assertEqual(config.visible_buttons, soundboard.DEFAULT_BUTTONS)
        self.assertTrue(config.global_hotkeys_enabled)

    def test_atomic_json_write_replaces_complete_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text("old", encoding="utf-8")
            soundboard.atomic_write_json(path, {"value": "ä"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": "ä"})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_old_config_keeps_classroom_modules_optional(self):
        config = soundboard.parse_config({"visible_buttons": 4})
        self.assertTrue(config.show_soundboard)
        self.assertFalse(config.show_phase)
        self.assertFalse(config.show_materials)
        self.assertFalse(config.show_timer)
        self.assertGreaterEqual(len(config.phase_items), 4)
        self.assertGreaterEqual(len(config.material_items), 4)

    def test_custom_catalogs_and_selections_are_parsed_safely(self):
        config = soundboard.parse_config({
            "phase_items": [
                {"item_id": "custom-phase", "name": "Eigene Methode", "image_path": "/tmp/icon.png"},
            ],
            "material_items": [
                {"item_id": "custom-material", "name": "Eigenes Material", "icon_key": "generic"},
            ],
            "selected_phase_id": "custom-phase",
            "selected_material_ids": ["missing", "custom-material", "custom-material"],
            "timer_presets": [5, 8, 10, 10, -3, "bad"],
        })
        self.assertEqual(config.selected_phase_id, "custom-phase")
        self.assertEqual(config.selected_material_ids, ["custom-material"])
        self.assertEqual(config.timer_presets, [5, 8, 10])


class PhaseTimerTests(unittest.TestCase):
    def test_minute_display_uses_ceiling_without_exposing_seconds(self):
        now = [100.0]
        timer = PhaseTimer(lambda: now[0])
        timer.start(8)
        self.assertEqual(timer.total_minutes(), 8)
        self.assertEqual(timer.remaining_minutes(), 8)
        now[0] += 60.1
        self.assertEqual(timer.remaining_minutes(), 7)
        now[0] += 419.9
        self.assertEqual(timer.remaining_minutes(), 0)
        self.assertEqual(timer.progress(), 0.0)

    def test_pause_resume_and_extension_do_not_drift(self):
        now = [0.0]
        timer = PhaseTimer(lambda: now[0])
        timer.start(5)
        now[0] = 30.0
        timer.pause()
        paused = timer.remaining_seconds()
        now[0] = 300.0
        self.assertEqual(timer.remaining_seconds(), paused)
        timer.add_minutes(1)
        self.assertEqual(timer.total_minutes(), 6)
        timer.resume()
        now[0] += paused + 60.0
        self.assertEqual(timer.remaining_minutes(), 0)


class HotkeyTests(unittest.TestCase):
    def test_hotkeys_are_normalized_for_pynput(self):
        manager = soundboard.GlobalHotkeyManager()
        self.assertEqual(manager._normalize_hotkey("Ctrl+Shift+F8"), "<ctrl>+<shift>+<f8>")
        self.assertEqual(manager._normalize_hotkey("Escape"), "<esc>")

    def test_duplicate_hotkeys_are_rejected(self):
        manager = soundboard.GlobalHotkeyManager()
        first = manager.register("F1", lambda: None)
        second = manager.register("f1", lambda: None)
        if soundboard.GLOBAL_HOTKEYS_AVAILABLE:
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertIn("Doppelt", manager.last_error)
        else:
            self.assertFalse(first)
            self.assertFalse(second)


class PanelLayoutTests(unittest.TestCase):
    """Die Panelgeometrie wird ohne Fenster berechnet und ist daher prüfbar."""

    def layout(self, **overrides):
        options = dict(
            unit=64,
            show_phase=True,
            show_materials=True,
            show_timer=True,
            phase_item=default_phase_items()[2],
            material_items=default_material_items()[:3],
        )
        options.update(overrides)
        return build_panel_layout(**options)

    def kinds(self, layout):
        return [region.kind for region in layout.regions]

    def test_each_module_contributes_its_own_regions(self):
        layout = self.layout()
        self.assertEqual(self.kinds(layout), [
            "phase", "material", "material", "material",
            "timer", "timer-minus", "timer-toggle", "timer-plus",
        ])

    def test_everything_is_flush_with_the_right_edge(self):
        # Das Panel klebt an der Bildschirmkante, also enden alle Elemente an
        # derselben rechten Kante statt mittig zu schweben.
        layout = self.layout(material_items=default_material_items()[:4])
        edges = {round(region.tile.right(), 3) for region in layout.regions
                 if region.kind in ("phase", "timer")}
        rows = {}
        for region in layout.regions:
            if region.kind == "material":
                rows.setdefault(round(region.tile.top(), 3), []).append(region.tile.right())
        edges.update(round(max(right), 3) for right in rows.values())
        edges.add(round(layout.grip.right(), 3))
        edges.add(round(max(r.tile.right() for r in layout.regions
                            if r.kind == "timer-plus"), 3))
        self.assertEqual(len(edges), 1, f"unterschiedliche rechte Kanten: {sorted(edges)}")
        self.assertLess(layout.width - edges.pop(), layout.unit * 0.2)

    def test_an_odd_material_sits_on_the_right_of_its_row(self):
        layout = self.layout(material_items=default_material_items()[:3])
        rows = {}
        for region in layout.regions:
            if region.kind == "material":
                rows.setdefault(round(region.tile.top(), 3), []).append(region.tile)
        last_row = rows[max(rows)]
        self.assertEqual(len(last_row), 1)
        full_row = rows[min(rows)]
        self.assertAlmostEqual(last_row[0].right(), max(t.right() for t in full_row), places=3)

    def test_the_panel_carries_no_text_at_all(self):
        layout = self.layout()
        for region in layout.regions:
            self.assertFalse(hasattr(region, "label"), "Beschriftungen sind nicht erwünscht")
        self.assertFalse(hasattr(layout, "headings"))

    def test_groups_are_separated_by_spacing_alone(self):
        # Ohne Karte und ohne Linien muss allein der Abstand die drei Gruppen
        # trennen: zwischen ihnen deutlich mehr Luft als innerhalb.
        layout = self.layout(material_items=default_material_items()[:4])
        materials = [r for r in layout.regions if r.kind == "material"]
        phase = next(r for r in layout.regions if r.kind == "phase")
        timer = next(r for r in layout.regions if r.kind == "timer")

        within = materials[2].rect.top() - materials[0].rect.bottom()
        between = min(
            materials[0].rect.top() - phase.rect.bottom(),
            timer.rect.top() - materials[-1].rect.bottom(),
        )
        self.assertGreater(between, within * 2)

    def test_modules_can_be_switched_off_individually(self):
        only_timer = self.layout(show_phase=False, show_materials=False)
        self.assertEqual(self.kinds(only_timer),
                         ["timer", "timer-minus", "timer-toggle", "timer-plus"])

        without_timer = self.layout(show_timer=False)
        self.assertEqual(self.kinds(without_timer), ["phase", "material", "material", "material"])
        self.assertLess(without_timer.height, self.layout().height)

        empty = self.layout(show_phase=False, show_materials=False, show_timer=False)
        self.assertEqual(empty.regions, [])

    def test_empty_selections_stay_clickable_as_placeholders(self):
        layout = self.layout(phase_item=None, material_items=[])
        icon_keys = [region.item.icon_key for region in layout.regions if region.item]
        self.assertEqual(icon_keys, ["phase-placeholder", "material-placeholder"])

    def test_regions_neither_overlap_nor_leave_the_panel(self):
        layout = self.layout(material_items=default_material_items())
        for region in layout.regions:
            self.assertGreaterEqual(region.rect.left(), 0)
            self.assertLessEqual(region.rect.right(), layout.width)
            self.assertLessEqual(region.rect.bottom(), layout.height)
        for index, region in enumerate(layout.regions):
            for other in layout.regions[index + 1:]:
                self.assertTrue(
                    region.rect.intersected(other.rect).isEmpty(),
                    f"{region.kind} überlappt {other.kind}",
                )

    def test_material_is_laid_out_in_two_columns(self):
        layout = self.layout(material_items=default_material_items()[:4])
        tops = {region.tile.top() for region in layout.regions if region.kind == "material"}
        self.assertEqual(len(tops), 2, "vier Materialien gehören in zwei Reihen")

    def test_hit_testing_finds_the_region_under_the_pointer(self):
        layout = self.layout()
        for region in layout.regions:
            self.assertIs(layout.region_at(region.rect.center()), region)
        self.assertIsNone(layout.region_at(QPointF(layout.width + 10, 10)))

    def test_start_and_pause_is_the_largest_control(self):
        layout = self.layout()
        sizes = {
            region.kind: region.tile.width()
            for region in layout.regions if region.kind.startswith("timer-")
        }
        self.assertGreater(sizes["timer-toggle"], sizes["timer-minus"])
        self.assertEqual(sizes["timer-minus"], sizes["timer-plus"])

    def test_more_materials_make_the_panel_taller(self):
        short = self.layout(material_items=default_material_items()[:1])
        tall = self.layout(material_items=default_material_items())
        self.assertGreater(tall.height, short.height)
        self.assertEqual(tall.width, short.width)


class TimerDisplayTests(unittest.TestCase):
    def test_a_coarse_clock_does_not_add_a_phantom_minute(self):
        # Unter Windows löst time.monotonic nur rund 15 ms auf, zwei kurz
        # aufeinanderfolgende Abfragen liefern also denselben Wert. Der Rest
        # ist dann (t + 300.0) - t und das ergibt in Gleitkomma bei manchen
        # Uhrwerten einen Hauch mehr als 300 Sekunden; ohne Toleranz macht
        # ceil daraus 6 statt 5 Minuten.
        tick = 524202.22506058164
        self.assertGreater(
            (tick + 300.0) - tick, 300.0,
            "Uhrwert ohne Rundungsüberschuss - der Test prüft dann nichts mehr",
        )

        timer = PhaseTimer(lambda: tick)
        timer.start(5)
        self.assertEqual(timer.remaining_minutes(), 5)
        self.assertEqual(timer.total_minutes(), 5)

    def test_minutes_can_be_taken_off_a_running_timer(self):
        now = [0.0]
        timer = PhaseTimer(lambda: now[0])
        timer.start(10)
        now[0] = 60.0
        timer.add_minutes(-3)
        self.assertAlmostEqual(timer.remaining_seconds(), 360.0)
        self.assertEqual(timer.total_minutes(), 7)
        self.assertTrue(timer.running)

    def test_taking_off_more_than_is_left_ends_the_timer(self):
        now = [0.0]
        timer = PhaseTimer(lambda: now[0])
        timer.start(5)
        timer.add_minutes(-99)
        self.assertEqual(timer.remaining_seconds(), 0.0)
        self.assertFalse(timer.running)
        self.assertFalse(timer.paused)

    def test_a_paused_timer_stays_paused_when_minutes_are_added(self):
        now = [0.0]
        timer = PhaseTimer(lambda: now[0])
        timer.start(5)
        now[0] = 60.0
        timer.pause()
        timer.add_minutes(2)
        self.assertTrue(timer.paused)
        self.assertFalse(timer.running)
        now[0] = 5000.0
        self.assertAlmostEqual(timer.remaining_seconds(), 360.0)

    def test_nothing_happens_without_a_timer_when_minutes_are_taken_off(self):
        timer = PhaseTimer(lambda: 0.0)
        timer.add_minutes(-5)
        self.assertFalse(timer.has_value())


class PanelConfigTests(unittest.TestCase):
    def test_panel_settings_have_defaults_and_are_clamped(self):
        self.assertAlmostEqual(soundboard.parse_config({}).panel_y_ratio, 0.08)
        self.assertEqual(soundboard.parse_config({"panel_y_ratio": 4.2}).panel_y_ratio, 1.0)
        self.assertAlmostEqual(
            soundboard.parse_config({"panel_y_ratio": 0.5}).panel_y_ratio, 0.5
        )
        # Die frühere Beschriftungs-Einstellung darf einen alten Stand nicht stören.
        self.assertAlmostEqual(
            soundboard.parse_config({"panel_show_labels": True, "panel_y_ratio": 0.3}).panel_y_ratio,
            0.3,
        )

    def test_timer_sound_path_survives_a_round_trip(self):
        self.assertEqual(soundboard.parse_config({}).timer_sound_path, "")
        self.assertEqual(soundboard.parse_config({"timer_sound_path": None}).timer_sound_path, "")
        kept = soundboard.parse_config({"timer_sound_path": "/tmp/gong.mp3"})
        self.assertEqual(kept.timer_sound_path, "/tmp/gong.mp3")


class BoiteTileTests(unittest.TestCase):
    """Die Kachel für Boîte à Oublis im Unterrichtspanel."""

    def layout(self, **overrides):
        options = dict(
            unit=64,
            show_phase=True,
            show_materials=True,
            show_timer=True,
            phase_item=default_phase_items()[2],
            material_items=default_material_items()[:2],
        )
        options.update(overrides)
        return build_panel_layout(**options)

    def kinds(self, layout):
        return [region.kind for region in layout.regions]

    def test_the_tile_is_off_unless_it_is_switched_on(self):
        self.assertNotIn("boite", self.kinds(self.layout()))
        self.assertIn("boite", self.kinds(self.layout(show_boite=True)))

    def test_the_tile_stands_at_the_top_and_ends_at_the_same_edge(self):
        layout = self.layout(show_boite=True)
        self.assertEqual(self.kinds(layout)[0], "boite")
        boite = layout.regions[0]
        phase = next(r for r in layout.regions if r.kind == "phase")
        self.assertAlmostEqual(boite.tile.right(), phase.tile.right(), places=3)
        self.assertAlmostEqual(boite.tile.width(), phase.tile.width(), places=3)
        self.assertLess(boite.rect.bottom(), phase.rect.top())

    def test_the_tile_carries_its_state_and_no_text(self):
        layout = self.layout(show_boite=True, boite_state="live", boite_level=3)
        boite = layout.regions[0]
        self.assertEqual(boite.state, "live")
        self.assertEqual(boite.level, 3)
        self.assertIsNone(boite.item)
        self.assertFalse(hasattr(boite, "label"), "Beschriftungen sind nicht erwünscht")

    def test_the_tile_alone_is_enough_for_a_panel(self):
        layout = self.layout(
            show_phase=False, show_materials=False, show_timer=False, show_boite=True
        )
        self.assertEqual(self.kinds(layout), ["boite"])
        self.assertGreater(layout.height, 0)

    def test_the_tile_can_be_hit_and_does_not_overlap(self):
        layout = self.layout(show_boite=True)
        boite = layout.regions[0]
        self.assertIs(layout.region_at(boite.rect.center()), boite)
        for other in layout.regions[1:]:
            self.assertTrue(boite.rect.intersected(other.rect).isEmpty())

    def test_every_state_of_the_status_has_a_drawing(self):
        # Was der Zustandsbericht liefern kann, muss die Kachel auch zeichnen.
        states = set()
        for connected, active, blank in [
            (False, False, False), (True, False, False), (True, True, False), (True, True, True),
        ]:
            states.add(companion.BoiteStatus(
                connected=connected, active=active, blank=blank
            ).tile_state())
        self.assertEqual(states, set(classroom_modules.BOITE_COLORS))


class CompanionConfigTests(unittest.TestCase):
    def test_the_connection_is_off_in_a_fresh_configuration(self):
        config = soundboard.parse_config({})
        self.assertFalse(config.show_boite)
        self.assertFalse(config.companion.enabled)
        self.assertEqual(config.companion.app_path, "")
        self.assertEqual(config.companion.presets, [])

    def test_an_older_configuration_keeps_working(self):
        config = soundboard.parse_config({"visible_buttons": 4, "show_timer": True})
        self.assertFalse(config.show_boite)
        self.assertFalse(config.companion.enabled)
        self.assertTrue(config.show_timer)

    def test_the_connection_survives_a_round_trip(self):
        stored = {
            "show_boite": True,
            "companion": {
                "enabled": True,
                "app_path": "/tmp/dist/boite-a-oublis.html",
                "tokens": ["abc"],
                "scene_map": {"Partnergespräch": "phase-partner"},
                "hotkeys": {"blank": "ctrl+alt+b"},
                "presets": [{
                    "preset_id": "p1", "name": "Am Markt", "target_kind": "bank",
                    "target_id": "bnk_1", "target_title": "Au marché", "target_group": "9b",
                    "level": 3, "phase_id": "phase-partner",
                    "material_ids": ["material-book"], "timer_minutes": 8,
                    "timer_autostart": True, "missing": False,
                }],
            },
        }
        config = soundboard.parse_config(stored)
        self.assertTrue(config.show_boite)
        self.assertEqual(config.companion.to_dict()["presets"], stored["companion"]["presets"])
        self.assertEqual(config.companion.tokens, ["abc"])
        self.assertEqual(config.companion.hotkeys, {"blank": "ctrl+alt+b"})

    def test_a_damaged_connection_block_does_not_stop_the_program(self):
        for broken in ("kaputt", 42, [], {"presets": "nein", "tokens": 5}):
            config = soundboard.parse_config({"companion": broken})
            self.assertFalse(config.companion.enabled)
            self.assertEqual(config.companion.presets, [])

    def test_companion_hotkeys_are_empty_by_default(self):
        # Leer heißt: Es kann nichts mit den Klang- und Stopp-Hotkeys kollidieren.
        config = soundboard.parse_config({})
        self.assertEqual(config.companion.hotkeys, {})
        for action in companion.HOTKEY_KEYS:
            self.assertEqual(config.companion.hotkeys.get(action, ""), "")


class PresetTriggerTests(unittest.TestCase):
    """Ein Preset wirkt nur, wenn die Lehrkraft es ausdrücklich startet."""

    @staticmethod
    def callers_of(method: str) -> set[str]:
        source = Path(soundboard.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and getattr(inner.func, "attr", "") == method:
                    found.add(node.name)
        return found

    def test_the_lesson_part_is_applied_only_after_an_explicit_preset(self):
        # Eine Wortbank zu öffnen darf Timer und Material nicht verändern:
        # Der Unterrichtsteil hängt allein an der Antwort auf "preset.start".
        # (check_companion_module ist der Selbsttest, kein Weg im Betrieb.)
        self.assertEqual(
            self.callers_of("_apply_preset_locally"),
            {"_on_companion_result", "check_companion_module"},
        )

    def test_only_one_place_asks_boite_to_open_a_preset(self):
        source = Path(soundboard.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        senders = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call) or not inner.args:
                    continue
                first = inner.args[0]
                if isinstance(first, ast.Constant) and first.value == "preset.start":
                    senders.add(node.name)
        self.assertEqual(senders, {"start_boite_preset"})

    def test_a_status_report_carries_no_lesson_settings(self):
        # Was Boîte à Oublis zurückmeldet, kann gar keine Sozialform, kein
        # Material und keinen Timer enthalten.
        status = companion.parse_status({
            "kind": "bank", "active": True, "title": "Au marché",
            "phase_id": "phase-group", "timer_minutes": 20,
            "material_ids": ["material-book"],
        })
        self.assertFalse(hasattr(status, "phase_id"))
        self.assertFalse(hasattr(status, "timer_minutes"))
        self.assertFalse(hasattr(status, "material_ids"))


class BarLayoutTests(unittest.TestCase):
    def test_modules_no_longer_share_the_sound_bar(self):
        source = Path(soundboard.__file__).read_text(encoding="utf-8")
        # Die Randleiste trägt nur noch Klänge und den Griff; alles Weitere
        # steht im Panel und darf die Münzgröße nicht mehr schrumpfen lassen.
        self.assertNotIn('slots.append(("phase"', source)
        self.assertNotIn('slots.extend([("timer-total"', source)



if __name__ == "__main__":
    unittest.main()
