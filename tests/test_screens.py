import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import server  # noqa: E402
from test_manage import ManageCase  # noqa: E402


class ScreenTests(ManageCase):
    def test_unknown_screen_registers_with_house_default(self):
        s = json.loads(server.state_json("Kitchen iPad"))
        self.assertEqual([r["scene"] for r in s["config"]["rotation"]][:2], ["shul", "yankees"])
        self.assertEqual(s["config"]["screen"], "Kitchen iPad")
        self.assertIn("Kitchen iPad", server.household()["screens"])
        self.assertIn("Kitchen iPad", server.seen)

    def test_switched_off_scenes_are_left_out(self):
        h = server.household()
        h["screens"]["Den"] = dict(server._new_screen(), rotation=[{"scene": "news", "seconds": 20, "on": True},
                                                                   {"scene": "shul", "seconds": 30, "on": False}])
        server.save_household(h)
        s = json.loads(server.state_json("Den"))
        self.assertEqual(s["config"]["rotation"], [{"scene": "news", "seconds": 20}])

    def test_agenda_only_on_screens_that_have_it(self):
        server.store.data["agenda"] = {"days": [{"date": "2026-11-09", "events": [{"title": "Smith deposition"}]}]}
        self.assertNotIn("agenda", json.loads(server.state_json("Kitchen iPad"))["data"])
        self.assertNotIn("agenda", json.loads(server.state_json(None))["data"])
        self.assertIn("agenda", json.loads(server.state_json("DESKTOP-H72VKDJ"))["data"])
        self.assertIn("agenda", server.store.data)  # only left out of the answer

    def test_invalid_screen_name_gets_default_and_is_not_stored(self):
        for bad in ("../x", "x" * 300, "<script>", "\U0001F600", ""):
            s = json.loads(server.state_json(bad))
            self.assertIsNone(s["config"]["screen"])
            self.assertNotIn(bad, server.household()["screens"])
            self.assertNotIn(bad, server.seen)

    def test_state_route_passes_the_screen(self):
        code, j = self.get("/api/state?screen=Kitchen%20iPad")
        self.assertEqual(code, 200)
        self.assertEqual(j["config"]["screen"], "Kitchen iPad")

    def test_sports_config_for_leagues_switched_on(self):
        h = server.household()
        h["sports"]["nba"] = {"on": True, "teams": [{"id": 18, "abbr": "NY", "name": "New York Knicks"}], "favorite": 18}
        server.save_household(h)
        sp = json.loads(server.state_json(None))["config"]["sports"]
        self.assertEqual(sp["nba"], {"name": "NBA", "favorite_abbr": "NY", "favorite_name": "New York Knicks", "teams": [18]})
        self.assertIn("mlb", sp)
        self.assertNotIn("nhl", sp)

    def test_launcher_first_checkin_echoes_its_own_settings(self):
        code, j = self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&screens=external&awake=1")
        self.assertEqual(code, 200)
        self.assertEqual((j["mode"], j["saver"]["screens"], j["saver"]["keep_awake"], j["saved"]),
                         ("saver", "external", True, False))
        self.assertTrue(server.household()["screens"]["Ariela"]["launcher"])
        self.assertTrue(server.seen["Ariela"]["launcher"])

    def test_saved_settings_win_over_local(self):
        self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&screens=all&awake=0")
        h = server.household()
        h["screens"]["Ariela"].update(saved=True, mode="always")
        server.save_household(h)
        self.assertEqual(self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&screens=all&awake=0")[1]["mode"],
                         "always")

    def test_bad_screen_settings_query(self):
        self.assertEqual(self.get("/api/screen-settings?screen=..%2Fx&mode=saver")[0], 400)
        code, j = self.get("/api/screen-settings?screen=Den&mode=saver&minutes=lots")
        self.assertEqual(code, 200)
        self.assertEqual(j["saver"]["minutes"], 10)

    def test_screen_settings_has_nothing_secret(self):
        server.CONFIG["agenda_ics"] = ["https://example.com/secret456.ics"]
        code, j = self.get("/api/screen-settings?screen=Ariela&mode=always")
        self.assertNotIn("secret456", json.dumps(j))
        self.assertNotIn("rotation", j)


if __name__ == "__main__":
    unittest.main()
