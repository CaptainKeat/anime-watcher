from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from anime_watcher.subtitles import (
    attach_subtitle_file,
    find_sidecar_subtitles,
    generate_english_subtitles,
    load_subtitle_file,
    subtitle_text_at,
    subtitle_texts_at,
)


class SubtitleTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        self.runtime.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.runtime, ignore_errors=True)

    def test_loads_srt_and_finds_active_text(self):
        path = self.runtime / "episode.en.srt"
        path.write_text(
            "1\n00:00:01,250 --> 00:00:03,000\nHello &amp; welcome.\n\n"
            "2\n00:00:04,000 --> 00:00:05,500\nSecond line\n",
            encoding="utf-8",
        )
        cues = load_subtitle_file(path)
        self.assertEqual(len(cues), 2)
        self.assertEqual(subtitle_text_at(cues, 1500), "Hello & welcome.")
        self.assertEqual(subtitle_text_at(cues, 3500), "")

    def test_loads_webvtt(self):
        path = self.runtime / "episode.vtt"
        path.write_text("WEBVTT\n\n00:01.000 --> 00:02.500\nA VTT caption\n", encoding="utf-8")
        cues = load_subtitle_file(path)
        self.assertEqual(subtitle_text_at(cues, 1200), "A VTT caption")

    def test_loads_basic_ass_and_removes_style_tags(self):
        path = self.runtime / "episode.ass"
        path.write_text(
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,{\\i1}Hello\\Nthere\n",
            encoding="utf-8",
        )
        cues = load_subtitle_file(path)
        self.assertEqual(subtitle_text_at(cues, 2500), "Hello\nthere")

    def test_loads_ssa_alignment_and_overlapping_dialogue(self):
        path = self.runtime / "episode.ssa"
        path.write_text(
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,{\\an8}Top sign\n"
            "Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,Spoken line\n",
            encoding="utf-8",
        )
        cues = load_subtitle_file(path)
        self.assertEqual(subtitle_texts_at(cues, 2500), [("top", "Top sign"), ("bottom", "Spoken line")])

    def test_discovers_english_sidecar_first(self):
        video = self.runtime / "Show - S01E01.mkv"
        video.write_bytes(b"video")
        plain = self.runtime / "Show - S01E01.srt"
        english = self.runtime / "Show - S01E01.en.srt"
        unrelated = self.runtime / "Other Show.srt"
        for subtitle in (plain, english, unrelated):
            subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\nText\n", encoding="utf-8")
        self.assertEqual(find_sidecar_subtitles(video), [english, plain])

    def test_attaches_subtitle_beside_video(self):
        video = self.runtime / "Show - S01E01.mkv"
        source = self.runtime / "downloaded English.srt"
        video.write_bytes(b"video")
        source.write_text("1\n00:00:01,000 --> 00:00:02,000\nText\n", encoding="utf-8")
        attached = attach_subtitle_file(video, source)
        self.assertEqual(attached.name, "Show - S01E01.en.srt")
        self.assertTrue(attached.is_file())

    @patch("anime_watcher.subtitles.find_ffmpeg", return_value="ffmpeg.exe")
    @patch("anime_watcher.subtitles.subprocess.run")
    def test_generation_preserves_multi_part_english_filename(self, run, _find_ffmpeg):
        video = self.runtime / "Show - S01E01.mkv"
        cli = self.runtime / "whisper-cli.exe"
        model = self.runtime / "ggml-small.bin"
        output = self.runtime / "Show - S01E01.generated.en.srt"
        for path in (video, cli, model):
            path.write_bytes(b"test")

        def simulate(command, **_kwargs):
            if command[0] == "ffmpeg.exe":
                Path(command[-1]).write_bytes(b"wave")
            else:
                output_base = Path(command[command.index("-of") + 1])
                Path(f"{output_base}.srt").write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nEnglish\n",
                    encoding="utf-8",
                )
            return SimpleNamespace(returncode=0, stderr="", stdout="")

        run.side_effect = simulate
        generated = generate_english_subtitles(video, output, cli, model)
        self.assertEqual(generated, output.resolve())
        self.assertTrue(output.is_file())
        self.assertFalse(list(self.runtime.glob("*.whisper.wav")))


if __name__ == "__main__":
    unittest.main()
