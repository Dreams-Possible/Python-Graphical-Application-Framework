"""主题选择和令牌完整性，不创建窗口、不依赖系统主题。"""

import unittest

from src.shared.paths import resource_path
from src.shared.theme import PALETTES, STYLE, effective_theme


class ThemeTests(unittest.TestCase):
    def test_follow_system_and_explicit_override(self):
        self.assertEqual(effective_theme("system", True), "dark")
        self.assertEqual(effective_theme("system", False), "light")
        self.assertEqual(effective_theme("light", True), "light")
        self.assertEqual(effective_theme("dark", False), "dark")
        with self.assertRaises(ValueError):
            effective_theme("unknown", False)

    def test_palettes_cover_styles_and_icons_exist(self):
        self.assertEqual(PALETTES["light"].keys(), PALETTES["dark"].keys())
        for name, colors in PALETTES.items():
            icons = {key: resource_path(f"icons/{key}-{name}.svg") for key in ("chevron", "check", "up")}
            self.assertTrue(all(path.is_file() for path in icons.values()))
            style = STYLE.substitute(colors, **{key: path.as_posix() for key, path in icons.items()})
            self.assertNotIn("$", style)
            self.assertIn(colors["surface"], style)
            self.assertNotEqual(colors["text"], colors["surface"])
