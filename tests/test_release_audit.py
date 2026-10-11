import tempfile
import unittest
import zipfile
import json
from unittest.mock import patch
from pathlib import Path

from release_audit import _scan_text, audit_archive, audit_source


class ReleaseAuditTests(unittest.TestCase):
    def test_text_scan_finds_personal_email_user_path_identity_and_secret(self):
        text = "\n".join([
            "person" + "@gmail.com",
            "C:\\Users" + "\\someone\\private.txt",
            "local-machine-name",
            "ghp_" + ("A" * 40),
        ])
        findings = _scan_text("sample", text, {"local-machine-name"})
        self.assertTrue(any("email address" in item for item in findings))
        self.assertTrue(any("Windows user path" in item for item in findings))
        self.assertTrue(any("local identity" in item for item in findings))
        self.assertTrue(any("GitHub token" in item for item in findings))

    def test_text_scan_allows_github_noreply_identity(self):
        self.assertEqual(_scan_text("sample", "132614303+CaptainKeat@users.noreply.github.com", set()), [])

    def test_archive_name_scan_ignores_qt_high_dpi_suffix(self):
        qt_asset = "checkbox-indicator" + "@" + "2x.png"
        findings = _scan_text("archive", qt_asset, set(), scan_email=False)
        self.assertEqual(findings, [])

    def test_archive_name_scan_still_finds_identity_and_secret(self):
        text = "local-machine-name/ghp_" + ("A" * 40)
        findings = _scan_text("archive", text, {"local-machine-name"}, scan_email=False)
        self.assertTrue(any("local identity" in item for item in findings))
        self.assertTrue(any("GitHub token" in item for item in findings))

    def test_archive_rejects_media_and_wrong_root_before_executable_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("wrong-root/private.mkv", b"media")
            result = audit_archive(archive_path)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("incorrect root" in item for item in result["findings"]))
            self.assertTrue(any("media file" in item for item in result["findings"]))

    def test_runtime_caches_and_database_sidecars_are_rejected_from_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root/'.test-tmp'/'receipt.json', root/'cache'/'artwork.img', root/'.cache'/'artwork.img', root/'library.db-wal', root/'library.sqlite3-shm', root/'.env.local']
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text('{}')
            with patch('release_audit._prospective_files', return_value=paths): result = audit_source(root)
            self.assertEqual(result['status'], 'failed')
            for path in paths: self.assertTrue(any(str(path.relative_to(root)) in finding for finding in result['findings']))

    def test_runtime_caches_and_database_sidecars_are_rejected_from_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.zip'
            entries = ['Anime Watcher/.test-tmp/receipt.json', 'Anime Watcher/_internal/cache/thumbnail.img', 'Anime Watcher/library.db-wal']
            with zipfile.ZipFile(path, 'w') as archive:
                for entry in entries: archive.writestr(entry, '{}')
            result = audit_archive(path)
            for entry in entries: self.assertTrue(any(entry in finding for finding in result['findings']))

    def test_renamed_cookie_exports_are_rejected_without_printing_cookie_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exports = {'renamed.txt': '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tfixture-private-value\n',
                       'renamed.json': json.dumps([dict(domain='.youtube.com', name='SID', value='fixture-private-value')])}
            paths = []
            for name, text in exports.items():
                source = root/name; source.write_text(text); paths.append(source)
            with patch('release_audit._prospective_files', return_value=paths): result = audit_source(root)
            self.assertEqual(sum('cookie export' in finding for finding in result['findings']), 2)
            path = root/'bad.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                for name, text in exports.items(): archive.writestr('Anime Watcher/'+name, text)
            result = audit_archive(path)
            self.assertEqual(sum('cookie export' in finding for finding in result['findings']), 2)
            self.assertNotIn('fixture-private-value', json.dumps(result))

    def test_encrypted_credentials_are_rejected_even_in_renamed_files(self):
        fixture = 'AQAAANCMnd8BFdERjHoAwE/' + 'A'*80
        findings = _scan_text('renamed.json', fixture, set())
        self.assertTrue(any('encrypted Windows credential' in finding for finding in findings))
        self.assertNotIn(fixture, json.dumps(findings))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.zip'
            with zipfile.ZipFile(path, 'w') as archive: archive.writestr('Anime Watcher/renamed.txt', fixture)
            result = audit_archive(path)
            self.assertTrue(any('encrypted Windows credential' in finding for finding in result['findings']))
            self.assertNotIn(fixture, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
