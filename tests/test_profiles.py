from pathlib import Path
import shutil
import unittest
import uuid

from anime_watcher.profiles import DEFAULT_PROFILE_ID, ProfileManager


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Path(__file__).parent / ".runtime" / str(uuid.uuid4())
        self.runtime.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.runtime, ignore_errors=True)

    def test_default_profile_preserves_original_database_path(self):
        manager = ProfileManager(self.runtime)
        self.assertEqual(manager.active.id, DEFAULT_PROFILE_ID)
        self.assertEqual(manager.database_path(), self.runtime / "library.db")

    def test_profiles_persist_and_receive_isolated_database_paths(self):
        manager = ProfileManager(self.runtime)
        created = manager.create("Guest")
        manager.set_active(created.id)
        self.assertEqual(manager.database_path(), self.runtime / "profiles" / created.id / "library.db")
        reloaded = ProfileManager(self.runtime)
        self.assertEqual(reloaded.active.name, "Guest")
        self.assertEqual(len(reloaded.profiles()), 2)

    def test_duplicate_names_are_rejected(self):
        manager = ProfileManager(self.runtime)
        manager.create("Guest")
        with self.assertRaises(ValueError):
            manager.create("guest")


if __name__ == "__main__":
    unittest.main()
