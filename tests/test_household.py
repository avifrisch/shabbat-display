import copy
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402


class HouseholdCase(unittest.TestCase):
    """Runs with household.json and manage-key.txt in a temporary folder, and restores CONFIG,
    the store and the on-demand cache afterwards."""

    def setUp(self):
        self._config = copy.deepcopy(server.CONFIG)
        self._data = dict(server.store.data)
        server._cache.clear()
        self._dir = tempfile.TemporaryDirectory()
        self._patches = [
            mock.patch.object(server, "HOUSEHOLD_FILE", os.path.join(self._dir.name, "household.json")),
            mock.patch.object(server, "KEY_FILE", os.path.join(self._dir.name, "manage-key.txt")),
        ]
        for p in self._patches:
            p.start()
        server._household_cache = None
        server._household_mtime = None
        server.seen.clear()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._dir.cleanup()
        server._household_cache = None
        server._household_mtime = None
        server.seen.clear()
        server.CONFIG.clear()
        server.CONFIG.update(self._config)
        server.store.data = self._data
        server._cache.clear()


class HouseholdTests(HouseholdCase):
    def test_migration_matches_todays_display(self):
        h = server.household()
        self.assertEqual(h["sports"]["mlb"], {"on": True, "teams": [{"id": 147, "abbr": "NYY", "name": "New York Yankees"}], "favorite": 147})
        self.assertEqual(h["business"]["watchlist"], [])
        self.assertTrue(all(not h["sports"][k]["on"] for k in server.LEAGUES))
        self.assertEqual([r["scene"] for r in h["default_rotation"]],
                         ["shul", "yankees", "mlb", "news", "israel", "business"])
        self.assertEqual(h["default_rotation"][0]["seconds"], 30)
        self.assertNotIn("agenda", [r["scene"] for r in h["default_rotation"]])
        rot = h["screens"]["DESKTOP-H72VKDJ"]["rotation"]
        self.assertEqual(rot[0], {"scene": "agenda", "seconds": 25, "on": True})
        self.assertEqual(rot[1:], h["default_rotation"])
        self.assertTrue(os.path.exists(server.HOUSEHOLD_FILE))

    def test_reload_on_change(self):
        h = server.household()
        h["business"]["watchlist"] = [{"symbol": "AAPL", "name": "Apple Inc."}]
        server.save_household(h)
        self.assertEqual(server.household()["business"]["watchlist"][0]["symbol"], "AAPL")

    def test_corrupt_household_keeps_last_good(self):
        server.household()
        with open(server.HOUSEHOLD_FILE, "w") as f:
            f.write('{"version": 1, "spo')
        os.utime(server.HOUSEHOLD_FILE, (time.time() + 5, time.time() + 5))
        logged = []
        with mock.patch.object(server, "log", logged.append):
            self.assertTrue(server.household()["sports"]["mlb"]["on"])
        self.assertTrue(any("household.json" in m for m in logged))

    def test_manage_key_created_once(self):
        k = server.manage_key()
        self.assertGreaterEqual(len(k), 30)
        self.assertEqual(server.manage_key(), k)

    def test_nyt_cookie_household_overrides_settings(self):
        server.CONFIG["nyt_cookie"] = "from-settings"
        self.assertEqual(server.nyt_cookie(), "from-settings")
        h = server.household()
        h["secrets"]["nyt_cookie"] = "from-app"
        server.save_household(h)
        self.assertEqual(server.nyt_cookie(), "from-app")

    def test_older_file_gets_missing_leagues(self):
        server.household()
        h = server.household()
        del h["sports"]["nhl"]
        del h["business"]
        server.save_household(h)
        h = server.household()
        self.assertFalse(h["sports"]["nhl"]["on"])
        self.assertTrue(h["business"]["on"])


if __name__ == "__main__":
    unittest.main()
