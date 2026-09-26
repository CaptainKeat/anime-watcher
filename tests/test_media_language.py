import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from anime_watcher.media_language import classify_streams, probe_embedded_language


class MediaLanguageTests(unittest.TestCase):
    def test_english_audio_is_dub(self):
        self.assertEqual(
            classify_streams([{"codec_type": "audio", "tags": {"language": "eng"}}]),
            "Dub",
        )

    def test_japanese_audio_is_sub(self):
        self.assertEqual(
            classify_streams([{"codec_type": "audio", "tags": {"language": "jpn"}}]),
            "Sub",
        )

    def test_english_subtitle_without_tagged_audio_is_sub(self):
        self.assertEqual(
            classify_streams([
                {"codec_type": "audio", "tags": {"language": "und"}},
                {"codec_type": "subtitle", "tags": {"language": "eng"}},
            ]),
            "Sub",
        )

    def test_untagged_streams_stay_unknown(self):
        self.assertEqual(
            classify_streams([{"codec_type": "audio", "tags": {"language": "und"}}]),
            "Unknown",
        )

    @patch("anime_watcher.media_language.subprocess.run")
    @patch("anime_watcher.media_language.shutil.which", return_value="ffprobe")
    @patch.object(Path, "is_file", return_value=True)
    def test_probe_reads_ffprobe_json(self, _is_file, _which, run):
        run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({"streams": [{"codec_type": "audio", "tags": {"language": "eng"}}]}),
        )
        self.assertEqual(probe_embedded_language("episode.mp4"), "Dub")


if __name__ == "__main__":
    unittest.main()
