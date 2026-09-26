import unittest

from anime_watcher.keybindings import duplicate_keybindings, merged_keybindings


class KeybindingTests(unittest.TestCase):
    def test_saved_binding_overrides_default_without_removing_new_actions(self):
        bindings = merged_keybindings({"play_pause": "K"})
        self.assertEqual(bindings["play_pause"], "K")
        self.assertEqual(bindings["seek_back"], "Left")
        self.assertIn("picture_in_picture", bindings)

    def test_duplicate_shortcuts_are_case_insensitive(self):
        self.assertEqual(duplicate_keybindings({"one": "F", "two": "f", "three": "P"}), {"f"})


if __name__ == "__main__":
    unittest.main()
