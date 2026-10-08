import hashlib
import io
import inspect
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from anime_watcher.updater import (
    ReleaseAsset,
    ReleaseInfo,
    _extract_verified_archive,
    _helper_script,
    fetch_latest_release,
    is_newer_version,
    stage_update,
    version_tuple,
)
from anime_watcher.qt_ui import AnimeWatcherWindow


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = io.BytesIO(content)

    def read(self, size=-1):
        return self.content.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def release_payload(version="1.2.0", digest="a" * 64, size=10):
    return {
        "tag_name": f"v{version}", "name": f"Anime Watcher v{version}",
        "body": "Fixes", "published_at": "2026-10-08T00:00:00Z",
        "html_url": f"https://github.com/CaptainKeat/anime-watcher/releases/tag/v{version}",
        "draft": False, "prerelease": False,
        "assets": [{
            "name": f"Anime-Watcher-v{version}-Windows.zip", "size": size,
            "digest": f"sha256:{digest}",
            "browser_download_url": f"https://github.com/CaptainKeat/anime-watcher/releases/download/v{version}/Anime-Watcher-v{version}-Windows.zip",
        }],
    }


class UpdaterTests(unittest.TestCase):
    def test_versions_are_strict_and_compared_numerically(self):
        self.assertEqual(version_tuple("v1.10.2"), (1, 10, 2))
        self.assertTrue(is_newer_version("1.10.0", "1.9.9"))
        self.assertFalse(is_newer_version("1.0.1", "1.0.1"))
        with self.assertRaises(ValueError):
            version_tuple("latest")

    def test_latest_release_requires_exact_official_asset_and_digest(self):
        payload = release_payload()
        release = fetch_latest_release(lambda *_args, **_kwargs: FakeResponse(json.dumps(payload).encode()))
        self.assertEqual(release.version, "1.2.0")
        self.assertEqual(release.asset.sha256, "a" * 64)
        payload["assets"][0]["digest"] = None
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            fetch_latest_release(lambda *_args, **_kwargs: FakeResponse(json.dumps(payload).encode()))

    def test_archive_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "bad")
            with self.assertRaisesRegex(ValueError, "unsafe path"):
                _extract_verified_archive(archive_path, Path(directory) / "out")
            self.assertFalse((Path(directory) / "outside.txt").exists())

    def test_verified_package_is_staged_beside_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root / "Anime Watcher"
            (install / "_internal").mkdir(parents=True)
            (install / "Anime Watcher.exe").write_bytes(b"old")
            memory = io.BytesIO()
            with zipfile.ZipFile(memory, "w") as archive:
                archive.writestr("Anime Watcher/Anime Watcher.exe", b"new")
                archive.writestr("Anime Watcher/_internal/runtime.dll", b"runtime")
            content = memory.getvalue()
            digest = hashlib.sha256(content).hexdigest()
            release = ReleaseInfo(
                "1.2.0", "v1.2.0", "Anime Watcher v1.2.0", "", "", "",
                ReleaseAsset("Anime-Watcher-v1.2.0-Windows.zip", "https://github.com/CaptainKeat/anime-watcher/releases/download/v1.2.0/Anime-Watcher-v1.2.0-Windows.zip", len(content), digest),
            )
            progress = []
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local")}), patch("anime_watcher.updater.uuid.uuid4") as unique:
                unique.side_effect = [type("U", (), {"hex": "a" * 32})(), type("U", (), {"hex": "b" * 32})(), type("U", (), {"hex": "c" * 32})()]
                staged = stage_update(release, install, lambda done, total: progress.append((done, total)), lambda *_args, **_kwargs: FakeResponse(content))
            self.assertEqual(staged.payload_root.parent, install.parent)
            self.assertEqual((staged.payload_root / "Anime Watcher.exe").read_bytes(), b"new")
            self.assertEqual(progress[-1], (len(content), len(content)))

    def test_bad_download_digest_never_stages_a_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root / "Anime Watcher"
            install.mkdir()
            (install / "Anime Watcher.exe").write_bytes(b"old")
            content = b"not the promised archive"
            release = ReleaseInfo(
                "1.2.0", "v1.2.0", "Anime Watcher v1.2.0", "", "", "",
                ReleaseAsset("Anime-Watcher-v1.2.0-Windows.zip", "https://github.com/CaptainKeat/anime-watcher/releases/download/v1.2.0/Anime-Watcher-v1.2.0-Windows.zip", len(content), "0" * 64),
            )
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local")}):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    stage_update(release, install, open_url=lambda *_args, **_kwargs: FakeResponse(content))
            self.assertEqual([item.name for item in root.iterdir() if ".update-" in item.name], [])

    def test_helper_waits_for_exit_and_keeps_rollback_path(self):
        script = _helper_script()
        self.assertIn("Get-Process -Id $ParentPid -ErrorAction SilentlyContinue", script)
        self.assertIn("Wait-Process -Id $ParentPid -Timeout 120", script)
        self.assertIn("Move-Item -LiteralPath $Target -Destination $Backup", script)
        self.assertIn("Move-Item -LiteralPath $Backup -Destination $Target", script)
        self.assertIn("Start-Process -FilePath (Join-Path $Target \"Anime Watcher.exe\")", script)

    def test_settings_exposes_manual_and_automatic_verified_updates(self):
        settings = inspect.getsource(AnimeWatcherWindow.show_settings)
        startup = inspect.getsource(AnimeWatcherWindow.__init__)
        install = inspect.getsource(AnimeWatcherWindow._confirm_staged_app_update)
        self.assertIn('QLabel("Application updates")', settings)
        self.assertIn("Check automatically at startup and every 6 hours", settings)
        self.assertIn("GitHub's SHA-256 digest", settings)
        self.assertIn("self._auto_check_for_app_update", startup)
        self.assertIn("launch_staged_update", install)


if __name__ == "__main__":
    unittest.main()
