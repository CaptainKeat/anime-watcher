import tempfile
import unittest
import zipfile
from pathlib import Path

from release_audit import _scan_text, audit_archive


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


if __name__ == "__main__":
    unittest.main()
