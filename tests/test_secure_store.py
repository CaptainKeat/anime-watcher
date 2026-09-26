import sys
import unittest

from anime_watcher.secure_store import protect_secret, unprotect_secret


@unittest.skipUnless(sys.platform == "win32", "Windows DPAPI test")
class SecureStoreTests(unittest.TestCase):
    def test_dpapi_round_trip_does_not_store_plain_text(self):
        value = "test-token-that-must-not-be-plain"
        protected = protect_secret(value)
        self.assertNotIn(value, protected)
        self.assertEqual(unprotect_secret(protected), value)


if __name__ == "__main__":
    unittest.main()
