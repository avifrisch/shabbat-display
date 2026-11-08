"""Fixes from the final review: a damaged household.json, settings that arrive late, NYT sign-out."""
import glob
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import server  # noqa: E402
from test_manage import ManageCase  # noqa: E402


class DamagedHouseholdTests(ManageCase):
    def damage(self, text):
        with open(server.HOUSEHOLD_FILE, "w", encoding="utf-8") as f:
            f.write(text)
        server._household_cache = None
        server._household_mtime = None

    def test_unreadable_file_is_kept_aside_not_overwritten(self):
        self.damage("")
        logged = []
        with mock.patch.object(server, "log", logged.append):
            h = server.household()
            self.assertTrue(h["sports"]["mlb"]["on"])
            server.check_in("Den", True, {"mode": "always", "saver": server.default_saver()})
        self.assertTrue(glob.glob(server.HOUSEHOLD_FILE + ".bad-*"))
        self.assertTrue(any("defaults" in m for m in logged))
        self.assertTrue(any(".bad-" in m for m in logged))

    def test_backup_is_used_when_the_file_is_damaged(self):
        h = server.household()
        h["business"]["watchlist"] = [{"symbol": "AAPL", "name": "Apple Inc."}]
        server.save_household(h)
        self.assertTrue(os.path.exists(server.HOUSEHOLD_FILE + ".bak"))
        self.damage('{"version": 1, "spo')
        with mock.patch.object(server, "log", lambda m: None):
            self.assertEqual(server.household()["business"]["watchlist"][0]["symbol"], "AAPL")

    def test_wrong_shapes_are_repaired(self):
        h = server.default_household()
        h["screens"] = None
        h["default_rotation"] = [{"scene": "news"}, {"scene": "shul", "seconds": 30, "on": True}, "junk"]
        h["sports"]["nba"] = {"on": True, "teams": [{"abbr": "NY"}, {"id": 18, "abbr": "NY", "name": "Knicks"}], "favorite": 18}
        self.damage(json.dumps(h))
        with mock.patch.object(server, "log", lambda m: None):
            s = json.loads(server.state_json("Den"))
        self.assertEqual(s["config"]["rotation"], [{"scene": "shul", "seconds": 30}])
        self.assertEqual(s["config"]["sports"]["nba"]["teams"], [18])

    def test_bad_screen_entry_is_repaired(self):
        h = server.default_household()
        h["screens"] = {"Den": {"rotation": [{"scene": "news", "on": True}]}, "Junk": "x"}
        self.damage(json.dumps(h))
        with mock.patch.object(server, "log", lambda m: None):
            s = json.loads(server.state_json("Den"))
        self.assertEqual(s["config"]["rotation"][0]["scene"], "shul")  # nothing usable left: house rotation
        self.assertEqual(server.household()["screens"]["Den"]["mode"], "always")

    def test_state_never_fails(self):
        with mock.patch.object(server, "household", side_effect=RuntimeError("boom")), \
                mock.patch.object(server, "log", lambda m: None):
            code, j = self.get("/api/state?screen=Den")
        self.assertEqual(code, 200)
        self.assertIn("data", j)

    def test_unexpected_manage_error_is_json(self):
        code, j = self.call("POST", "/api/manage/business", {"on": True, "watchlist": [], "news": ["x"]})
        self.assertIn(code, (400, 500))
        self.assertFalse(j["ok"])


class ChangesArriveQuicklyTests(ManageCase):
    def test_switched_off_league_checks_every_minute(self):
        self.assertEqual(server.league_poll_seconds("nba"), 60)

    def test_saving_wakes_the_sources(self):
        server.WAKE.clear()
        self.call("POST", "/api/manage/business", {"on": True, "watchlist": [{"symbol": "AAPL", "name": "Apple"}], "news": {}})
        self.assertTrue(server.WAKE["markets"].is_set())
        self.call("POST", "/api/manage/sports", {"nba": {"on": True, "teams": [], "favorite": None},
                                                 "mlb": {"on": True, "teams": [{"id": 147, "abbr": "NYY", "name": "Yankees"}], "favorite": 147}})
        self.assertTrue(server.WAKE["sport_nba"].is_set())
        self.assertTrue(server.WAKE["team"].is_set())

    def test_run_source_wakes_early(self):
        import threading
        calls = []
        done = threading.Event()

        def fn():
            calls.append(1)
            if len(calls) == 2:
                done.set()
            return {}
        server.WAKE.clear()
        with mock.patch.object(server.store, "set", lambda k, v: None):
            threading.Thread(target=server.run_source, args=("wake_test", fn, 3600), daemon=True).start()
            for _ in range(50):
                if calls:
                    break
                done.wait(0.05)
            server.wake("wake_test")
            self.assertTrue(done.wait(3))


class NytSignOutTests(ManageCase):
    def test_sign_out_wins_over_settings(self):
        server.CONFIG["nyt_cookie"] = "from-settings"
        self.call("POST", "/api/manage/nyt", {"cookie": "abc"})
        j = self.call("POST", "/api/manage/nyt", {"cookie": ""})[1]
        self.assertFalse(j["nyt_signed_in"])
        self.assertEqual(server.nyt_cookie(), "")

    def test_never_set_in_app_uses_settings(self):
        server.CONFIG["nyt_cookie"] = "from-settings"
        self.assertEqual(server.nyt_cookie(), "from-settings")


if __name__ == "__main__":
    unittest.main()
