import json
import tempfile
import unittest
from pathlib import Path

import soundboard


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


if __name__ == "__main__":
    unittest.main()
