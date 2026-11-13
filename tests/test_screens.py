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

    def test_preview_shows_the_screen_without_checking_in(self):
        server.store.data["agenda"] = {"days": []}
        s = json.loads(server.state_json("DESKTOP-H72VKDJ", preview=True))
        self.assertIn("agenda", [r["scene"] for r in s["config"]["rotation"]])
        self.assertIn("agenda", s["data"])
        self.assertNotIn("DESKTOP-H72VKDJ", server.seen)
        json.loads(server.state_json("Somewhere New", preview=True))
        self.assertNotIn("Somewhere New", server.household()["screens"])
        self.assertNotIn("Somewhere New", server.seen)

    def test_state_route_passes_preview(self):
        code, j = self.get("/api/state?screen=Kitchen%20iPad&preview=1")
        self.assertEqual((code, j["config"]["screen"]), (200, "Kitchen iPad"))
        self.assertNotIn("Kitchen iPad", server.seen)
        self.assertNotIn("Kitchen iPad", server.household()["screens"])

    def test_sports_config_for_leagues_switched_on(self):
        h = server.household()
        h["sports"]["nba"] = {"on": True, "teams": [{"id": 18, "abbr": "NY", "name": "New York Knicks"}], "favorite": 18}
        server.save_household(h)
        sp = json.loads(server.state_json(None))["config"]["sports"]
        self.assertEqual(sp["nba"], {"name": "NBA", "favorite_abbr": "NY", "favorite_name": "New York Knicks", "teams": [18]})
        self.assertIn("mlb", sp)
        self.assertNotIn("nhl", sp)

    def test_launcher_first_checkin_echoes_its_own_settings(self):
        code, j = self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&shabbat=1")
        self.assertEqual(code, 200)
        self.assertEqual((j["mode"], j["saver"], j["saved"]), ("saver", {"minutes": 10, "lock": True, "shabbat": True}, False))
        self.assertTrue(server.household()["screens"]["Ariela"]["launcher"])
        self.assertTrue(server.seen["Ariela"]["launcher"])

    def test_old_launcher_awake_means_shabbat(self):
        j = self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&screens=external&awake=1")[1]
        self.assertEqual(j["saver"], {"minutes": 10, "lock": True, "shabbat": True})

    def test_old_keep_awake_becomes_shabbat(self):
        h = server.household()
        h["screens"]["Acer"] = dict(server._new_screen(), saver={"minutes": 15, "lock": False, "screens": "external", "keep_awake": True})
        server.save_household(h)
        self.assertEqual(server.household()["screens"]["Acer"]["saver"], {"minutes": 15, "lock": False, "shabbat": True})

    def test_save_screen_off_and_shabbat(self):
        code, _ = self.call("POST", "/api/manage/screen", {"name": "Acer", "mode": "off", "saver": {"minutes": 12, "lock": True, "shabbat": True}})
        self.assertEqual(code, 200)
        s = server.household()["screens"]["Acer"]
        self.assertEqual((s["mode"], s["saver"]), ("off", {"minutes": 12, "lock": True, "shabbat": True}))

    def test_announce_switch_reaches_the_launcher(self):
        get = lambda: self.get("/api/screen-settings?screen=Acer&mode=always")[1]["announce"]
        self.assertTrue(get())  # on until switched off in the app
        body = {"name": "Acer", "mode": "always", "saver": {"minutes": 10}}
        self.assertEqual(self.call("POST", "/api/manage/screen", {**body, "announce": False})[0], 200)
        self.assertFalse(get())
        self.call("POST", "/api/manage/screen", body)  # an older app: left as it was
        self.assertFalse(get())
        self.assertEqual(self.call("POST", "/api/manage/screen", {**body, "announce": "no"})[0], 400)
        h = server.household()
        h["screens"]["Acer"]["announce"] = "x"  # a hand-edited file
        server.save_household(h)
        self.assertTrue(server.household()["screens"]["Acer"]["announce"])

    def test_save_screen_rejects_bad_minutes(self):
        for m in (0, 241, 1.5, True):
            self.assertEqual(self.call("POST", "/api/manage/screen", {"name": "Acer", "mode": "saver", "saver": {"minutes": m}})[0], 400, m)

    def test_holy_spans_from_calendar(self):
        items = [{"category": "havdalah", "date": "2026-11-07T17:25:00-05:00"},
                 {"category": "candles", "date": "2026-11-13T16:17:00-05:00"},
                 {"category": "havdalah", "date": "2026-11-14T17:20:00-05:00"},
                 {"category": "candles", "date": "2026-11-20T16:12:00-05:00"},   # Erev Yom Tov
                 {"category": "candles", "date": "2026-11-21T17:16:00-05:00"},   # second day
                 {"category": "havdalah", "date": "2026-11-22T17:15:00-05:00"}]
        n = server.parse_dt("2026-11-10T09:00:00-05:00")
        self.assertEqual(server.holy_spans(items, n), [
            {"start": "2026-11-13T16:17:00-05:00", "end": "2026-11-14T17:20:00-05:00"},
            {"start": "2026-11-20T16:12:00-05:00", "end": "2026-11-22T17:15:00-05:00"}])
        self.assertEqual(len(server.holy_spans(items, server.parse_dt("2026-11-14T18:00:00-05:00"))), 1)

    def test_screen_settings_carries_holy_spans(self):
        server.store.data["calendar"] = {"items": [{"category": "candles", "date": "2099-01-02T16:00:00-05:00"},
                                                   {"category": "havdalah", "date": "2099-01-03T17:00:00-05:00"}]}
        j = self.get("/api/screen-settings?screen=Ariela&mode=saver")[1]
        self.assertEqual(j["holy"], [{"start": "2099-01-02T16:00:00-05:00", "end": "2099-01-03T17:00:00-05:00"}])

    def test_saved_settings_win_over_local(self):
        self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&shabbat=0")
        h = server.household()
        h["screens"]["Ariela"].update(saved=True, mode="always")
        server.save_household(h)
        self.assertEqual(self.get("/api/screen-settings?screen=Ariela&mode=saver&minutes=10&lock=1&shabbat=0")[1]["mode"],
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
