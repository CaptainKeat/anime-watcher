from pathlib import Path
import shutil
import unittest
import uuid

from anime_watcher.ass_renderer import ASS_FONTPROVIDER_DIRECTWRITE, LibassRenderer, capped_ass_frame_size


class LibassRendererTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ".runtime" / f"ass-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_large_tv_frames_are_bounded_without_changing_aspect_ratio(self):
        self.assertEqual(capped_ass_frame_size(3840, 2160), (1920, 1080))
        self.assertEqual(capped_ass_frame_size(1280, 720), (1280, 720))

    def test_renders_animated_ass_inside_a_transparent_bitmap(self):
        subtitle = self.root / "animated.ass"
        subtitle.write_text(
            """[Script Info]
ScriptType: v4.00+
PlayResX: 640
PlayResY: 360

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,34,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,20,20,24,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{\\move(80,180,480,180,0,4000)}{\\k40}Full {\\k40}ASS
""",
            encoding="utf-8",
        )
        with LibassRenderer(subtitle) as renderer:
            self.assertIn(ASS_FONTPROVIDER_DIRECTWRITE, renderer.available_font_providers())
            first = renderer.render(250, 640, 360)
            second = renderer.render(3000, 640, 360)
        self.assertTrue(first.changed)
        self.assertIsNotNone(first.bitmap)
        self.assertTrue(second.changed)
        self.assertIsNotNone(second.bitmap)
        self.assertNotEqual(first.bitmap.x, second.bitmap.x)
        self.assertGreater(max(first.bitmap.rgba[3::4]), 0)


if __name__ == "__main__":
    unittest.main()
