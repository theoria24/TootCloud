"""Unit tests for emoji_utils module."""

import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the project root is on the path so ``import emoji_utils`` works when
# tests are run from within the ``tests/`` directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

import emoji_utils


class TestEmojiToTwemojiStem(unittest.TestCase):
    """Tests for :func:`emoji_utils.emoji_to_twemoji_stem`."""

    def test_simple_emoji(self):
        # 😂 is U+1F602 → "1f602"
        self.assertEqual(emoji_utils.emoji_to_twemoji_stem("😂"), "1f602")

    def test_emoji_with_fe0f(self):
        # ❤️ is U+2764 U+FE0F → "2764-fe0f"
        self.assertEqual(emoji_utils.emoji_to_twemoji_stem("❤️"), "2764-fe0f")

    def test_flag_sequence(self):
        # 🇯🇵 is U+1F1EF U+1F1F5 → "1f1ef-1f1f5"
        self.assertEqual(emoji_utils.emoji_to_twemoji_stem("🇯🇵"), "1f1ef-1f1f5")

    def test_zwj_sequence(self):
        # 👨‍👩‍👧 family ZWJ sequence
        result = emoji_utils.emoji_to_twemoji_stem("👨‍👩‍👧")
        # Must contain ZWJ codepoint 200d
        self.assertIn("200d", result)


class TestFindTwemojiSvg(unittest.TestCase):
    """Tests for :func:`emoji_utils.find_twemoji_svg` (with mock filesystem)."""

    def _make_fs(self, *svgs):
        """Return a fake assets_path whose SVG files are given by *svgs*."""

        class FakePath:
            def __init__(self, name, existing):
                self._name = name
                self._existing = existing

            def __truediv__(self, other):
                return FakePath(other, self._existing)

            def exists(self):
                return self._name in self._existing

            def __str__(self):
                return self._name

        return FakePath("root", set(svgs))

    def test_finds_file_with_fe0f(self):
        # ❤️ → "2764-fe0f.svg" exists → returned
        assets = self._make_fs("2764-fe0f.svg")
        result = emoji_utils.find_twemoji_svg("❤️", assets)
        self.assertIsNotNone(result)
        self.assertEqual(str(result), "2764-fe0f.svg")

    def test_fallback_without_fe0f(self):
        # ❤️ → "2764-fe0f.svg" absent, "2764.svg" present → fallback used
        assets = self._make_fs("2764.svg")
        result = emoji_utils.find_twemoji_svg("❤️", assets)
        self.assertIsNotNone(result)
        self.assertEqual(str(result), "2764.svg")

    def test_returns_none_when_missing(self):
        assets = self._make_fs()  # empty directory
        result = emoji_utils.find_twemoji_svg("😂", assets)
        self.assertIsNone(result)

    def test_no_fe0f_emoji_found_directly(self):
        # 😂 has no FE0F, so only one lookup is done
        assets = self._make_fs("1f602.svg")
        result = emoji_utils.find_twemoji_svg("😂", assets)
        self.assertIsNotNone(result)
        self.assertEqual(str(result), "1f602.svg")


class TestPlaceholderHelpers(unittest.TestCase):
    """Tests for placeholder creation and detection."""

    def test_make_placeholder_format(self):
        self.assertEqual(emoji_utils.make_placeholder(0), "_e0")
        self.assertEqual(emoji_utils.make_placeholder(12), "_e12")
        self.assertEqual(emoji_utils.make_placeholder(49), "_e49")

    def test_is_placeholder_true(self):
        for i in range(50):
            self.assertTrue(emoji_utils.is_placeholder(f"_e{i}"))

    def test_is_placeholder_false(self):
        self.assertFalse(emoji_utils.is_placeholder("hello"))
        self.assertFalse(emoji_utils.is_placeholder("_eX"))
        self.assertFalse(emoji_utils.is_placeholder("__EMOJI_0__"))
        self.assertFalse(emoji_utils.is_placeholder("e0"))
        self.assertFalse(emoji_utils.is_placeholder(""))


class TestBuildPlaceholderMap(unittest.TestCase):
    """Tests for :func:`emoji_utils.build_placeholder_map`."""

    def test_roundtrip(self):
        emoji_freqs = {"😂": 5, "🎉": 3, "❤️": 7}
        ph_to_emoji, ph_freqs = emoji_utils.build_placeholder_map(emoji_freqs)

        # All emoji should appear exactly once as a value
        self.assertEqual(set(ph_to_emoji.values()), set(emoji_freqs.keys()))

        # Frequencies should be preserved
        for ph, emoji_str in ph_to_emoji.items():
            self.assertEqual(ph_freqs[ph], emoji_freqs[emoji_str])

        # All placeholder keys should match the expected pattern
        for ph in ph_to_emoji:
            self.assertTrue(emoji_utils.is_placeholder(ph))

    def test_sorted_by_frequency(self):
        emoji_freqs = {"😂": 5, "🎉": 3, "❤️": 7}
        ph_to_emoji, _ = emoji_utils.build_placeholder_map(emoji_freqs)

        # The most frequent emoji should be _e0
        self.assertEqual(ph_to_emoji["_e0"], "❤️")

    def test_max_count_limit(self):
        emoji_freqs = {chr(0x1F600 + i): i + 1 for i in range(10)}
        ph_to_emoji, _ = emoji_utils.build_placeholder_map(emoji_freqs, max_count=3)
        self.assertEqual(len(ph_to_emoji), 3)

    def test_empty_input(self):
        ph_to_emoji, ph_freqs = emoji_utils.build_placeholder_map({})
        self.assertEqual(ph_to_emoji, {})
        self.assertEqual(ph_freqs, {})


class TestExtractEmojiFrequencies(unittest.TestCase):
    """Tests for :func:`emoji_utils.extract_emoji_frequencies`."""

    def test_counts_emoji(self):
        text = "Hello 😂 world 😂 test 🎉"
        freqs = emoji_utils.extract_emoji_frequencies(text)
        self.assertEqual(freqs["😂"], 2)
        self.assertEqual(freqs["🎉"], 1)

    def test_no_emoji(self):
        freqs = emoji_utils.extract_emoji_frequencies("no emoji here")
        self.assertEqual(freqs, {})

    def test_only_emoji(self):
        freqs = emoji_utils.extract_emoji_frequencies("😂😂😂")
        self.assertEqual(freqs["😂"], 3)


class TestStripEmoji(unittest.TestCase):
    """Tests for :func:`emoji_utils.strip_emoji`."""

    def test_strips_emoji(self):
        result = emoji_utils.strip_emoji("Hello 😂 world 🎉")
        self.assertNotIn("😂", result)
        self.assertNotIn("🎉", result)
        self.assertIn("Hello", result)
        self.assertIn("world", result)

    def test_no_emoji_unchanged(self):
        text = "no emoji here"
        self.assertEqual(emoji_utils.strip_emoji(text), text)


class TestCompositeEmoji(unittest.TestCase):
    """Tests for :func:`emoji_utils.composite_emoji`."""

    def _make_fake_emoji_img(self, size=32):
        img = MagicMock(spec=["rotate", "size"])
        img.size = (size, size)

        def rotate_side_effect(angle, expand=False):
            return img

        img.rotate.side_effect = rotate_side_effect
        return img

    def test_composites_horizontal(self):
        """Emoji placed at correct pixel position for horizontal orientation."""
        from PIL import Image

        bg = Image.new("RGB", (200, 200), "white")
        placeholder_to_emoji = {"_e0": "😂"}

        fake_emoji = Image.new("RGBA", (30, 30), (255, 0, 0, 255))

        layout = [
            (("_e0", 1.0), 30, (10, 20), None, "white"),
        ]

        with patch.object(emoji_utils, "render_twemoji", return_value=fake_emoji):
            result = emoji_utils.composite_emoji(
                bg, layout, placeholder_to_emoji
            )

        # Result should be RGB
        self.assertEqual(result.mode, "RGB")
        # position=(row=10, col=20) maps to Pillow (x=20, y=10).
        # The fake emoji is 30×30 solid red; check a pixel near the centre.
        pixel = result.getpixel((35, 25))
        self.assertEqual(pixel[:3], (255, 0, 0))

    def test_skips_non_placeholders(self):
        """Normal words should not be composited."""
        from PIL import Image

        bg = Image.new("RGB", (200, 200), "white")
        placeholder_to_emoji = {"_e0": "😂"}

        layout = [
            (("hello", 1.0), 30, (10, 20), None, "red"),
        ]

        with patch.object(emoji_utils, "render_twemoji") as mock_render:
            emoji_utils.composite_emoji(bg, layout, placeholder_to_emoji)
            mock_render.assert_not_called()

    def test_rotated_emoji(self):
        """ROTATE_90 orientation should rotate the emoji image."""
        from PIL import Image

        bg = Image.new("RGB", (200, 200), "white")
        placeholder_to_emoji = {"_e0": "😂"}

        # Asymmetric emoji to detect rotation
        fake_emoji = Image.new("RGBA", (30, 30), (0, 255, 0, 255))

        layout = [
            (("_e0", 1.0), 30, (10, 20), Image.ROTATE_90, "white"),
        ]

        rotated_calls = []

        original_rotate = fake_emoji.rotate

        def record_rotate(angle, **kwargs):
            rotated_calls.append(angle)
            return original_rotate(angle, **kwargs)

        fake_emoji.rotate = record_rotate

        with patch.object(emoji_utils, "render_twemoji", return_value=fake_emoji):
            emoji_utils.composite_emoji(bg, layout, placeholder_to_emoji)

        self.assertEqual(rotated_calls, [90])

    def test_missing_svg_is_skipped(self):
        """If render_twemoji returns None the placeholder is silently skipped."""
        from PIL import Image

        bg = Image.new("RGB", (200, 200), "white")
        placeholder_to_emoji = {"_e0": "😂"}

        layout = [
            (("_e0", 1.0), 30, (10, 20), None, "white"),
        ]

        with patch.object(emoji_utils, "render_twemoji", return_value=None):
            result = emoji_utils.composite_emoji(bg, layout, placeholder_to_emoji)

        # Background should be unchanged (white)
        pixel = result.getpixel((20, 10))
        self.assertEqual(pixel[:3], (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
