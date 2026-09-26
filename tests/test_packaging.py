import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class WindowsPackagingTests(unittest.TestCase):
    def test_build_uses_a_sanitized_native_dll_search_path(self):
        script = (PROJECT_ROOT / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("$SafePath", script)
        self.assertIn('$env:PATH = $SafePath -join ";"', script)
        self.assertIn("$env:PATH = $OriginalPath", script)

    def test_build_rejects_foreign_icu_and_exception_dialogs(self):
        script = (PROJECT_ROOT / "build.ps1").read_text(encoding="utf-8")
        self.assertIn('Test-Path "$InternalRoot\\icuuc.dll"', script)
        self.assertIn('*Unhandled exception*', script)
        self.assertIn("Packaged application exited during its startup smoke test", script)

    def test_build_bundles_the_isolated_libass_runtime(self):
        script = (PROJECT_ROOT / "build.ps1").read_text(encoding="utf-8")
        self.assertIn('third_party\\libass\\bin;libass', script)
        runtime = PROJECT_ROOT / "third_party" / "libass" / "bin"
        self.assertTrue((runtime / "libass-9.dll").is_file())
        self.assertTrue((runtime / "libharfbuzz-0.dll").is_file())
        self.assertFalse((runtime / "Qt6Core.dll").exists())


if __name__ == "__main__":
    unittest.main()
