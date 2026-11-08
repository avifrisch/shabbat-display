import json
import os
import sys
import threading
import unittest
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_household import HouseholdCase  # noqa: E402


class ManageCase(HouseholdCase):
    """The real request handler on a free local port, with household files in a temp folder."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method, path, body=None, key="valid"):
        headers = {}
        if key == "valid":
            key = server.manage_key()
        if key is not None:
            headers["X-Manage-Key"] = key
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = server.urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with server.urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except server.urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def get(self, path):
        return self.call("GET", path, key=None)


class ManageTests(ManageCase):
    def test_no_key_is_401(self):
        self.assertEqual(self.call("GET", "/api/manage/status", key=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/manage/status", key="wrong")[0], 401)
        self.assertEqual(self.call("POST", "/api/manage/nyt", {"cookie": "x"}, key=None)[0], 401)

    def test_status_lists_feeds_and_screens(self):
        server.store.meta["weather"] = {"updated": 1, "ok": True, "error": None}
        code, j = self.call("GET", "/api/manage/status")
        self.assertEqual(code, 200)
        self.assertIn("weather", j["feeds"])
        self.assertIn("DESKTOP-H72VKDJ", [s["name"] for s in j["screens"]])

    def test_switching_a_league_on_adds_its_pair(self):
        self.call("POST", "/api/manage/rotation", {"screen": "Kitchen", "rotation": [{"scene": "news", "seconds": 30, "on": True}]})
        code, _ = self.call("POST", "/api/manage/sports",
                            {"nba": {"on": True, "teams": [{"id": 18, "abbr": "NY", "name": "New York Knicks"}], "favorite": 18}})
        self.assertEqual(code, 200)
        h = server.household()
        names = [r["scene"] for r in h["default_rotation"]]
        self.assertLess(names.index("nba_team"), names.index("business"))
        kitchen = {r["scene"]: r["on"] for r in h["screens"]["Kitchen"]["rotation"]}
        self.assertEqual((kitchen["nba_team"], kitchen["nba"]), (False, False))
        self.assertEqual(h["sports"]["nba"]["favorite"], 18)

    def test_favorite_must_be_a_chosen_team(self):
        code, j = self.call("POST", "/api/manage/sports", {"nba": {"on": True, "teams": [], "favorite": 18}})
        self.assertEqual(code, 400)

    def test_bad_rotation_is_400(self):
        code, j = self.call("POST", "/api/manage/rotation", {"screen": None, "rotation": [{"scene": "nope", "seconds": 30, "on": True}]})
        self.assertEqual(code, 400)
        self.assertIn("nope", j["error"])
        code, _ = self.call("POST", "/api/manage/rotation", {"screen": None, "rotation": [{"scene": "news", "seconds": 2, "on": True}]})
        self.assertEqual(code, 400)

    def test_screen_rotation_back_to_default(self):
        self.call("POST", "/api/manage/rotation", {"screen": "Kitchen", "rotation": [{"scene": "news", "seconds": 30, "on": True}]})
        self.call("POST", "/api/manage/rotation", {"screen": "Kitchen", "rotation": None})
        self.assertIsNone(server.household()["screens"]["Kitchen"]["rotation"])

    def test_bad_ticker_is_400(self):
        self.assertEqual(self.call("POST", "/api/manage/business",
                                   {"on": True, "watchlist": [{"symbol": "AAPL; rm", "name": "x"}], "news": {}})[0], 400)

    def test_business_saved(self):
        code, _ = self.call("POST", "/api/manage/business",
                            {"on": True, "watchlist": [{"symbol": "BRK.B", "name": "Berkshire Hathaway"}], "news": {"biz_cnbc": False}})
        self.assertEqual(code, 200)
        b = server.household()["business"]
        self.assertEqual(b["watchlist"][0]["symbol"], "BRK.B")
        self.assertEqual(b["news"], {"biz_nyt": True, "biz_cnbc": False})

    def test_screen_save_marks_saved(self):
        self.call("POST", "/api/manage/screen", {"name": "Ariela", "mode": "saver",
                                                 "saver": {"minutes": 15, "lock": True, "screens": "external", "keep_awake": True}})
        s = server.household()["screens"]["Ariela"]
        self.assertTrue(s["saved"])
        self.assertEqual(s["mode"], "saver")
        self.assertEqual(s["saver"]["minutes"], 15)

    def test_bad_screen_settings_are_400(self):
        self.assertEqual(self.call("POST", "/api/manage/screen", {"name": "Ariela", "mode": "blink", "saver": {}})[0], 400)
        self.assertEqual(self.call("POST", "/api/manage/screen", {"name": "Ariela", "mode": "saver",
                                                                  "saver": {"minutes": 0, "lock": True, "screens": "all", "keep_awake": False}})[0], 400)

    def test_bad_json_is_400(self):
        req = server.urllib.request.Request(self.base + "/api/manage/sports", data=b"{nope",
                                            headers={"X-Manage-Key": server.manage_key()}, method="POST")
        with self.assertRaises(server.urllib.error.HTTPError) as e:
            server.urllib.request.urlopen(req, timeout=10)
        self.assertEqual(e.exception.code, 400)
        e.exception.close()

    def test_manage_responses_never_contain_secrets(self):
        server.CONFIG["agenda_ics"] = ["https://example.com/feed/secret456.ics"]
        self.call("POST", "/api/manage/nyt", {"cookie": "secret123"})
        bodies = [json.dumps(self.call("GET", p)[1]) for p in
                  ("/api/manage/status", "/api/manage/household", "/api/manage/log?lines=500")]
        for b in bodies:
            for s in ("secret123", "secret456", server.manage_key()):
                self.assertNotIn(s, b)
        j = self.call("GET", "/api/manage/household")[1]
        self.assertTrue(j["nyt_signed_in"])
        self.assertTrue(j["agenda_set"])
        self.assertNotIn("secrets", j)

    def test_nyt_sign_out(self):
        self.call("POST", "/api/manage/nyt", {"cookie": "abc"})
        self.assertEqual(self.call("POST", "/api/manage/nyt", {"cookie": ""})[1]["nyt_signed_in"], False)
        self.assertEqual(server.nyt_cookie(), server.CONFIG["nyt_cookie"])

    def test_household_lists_scenes(self):
        j = self.call("GET", "/api/manage/household")[1]
        scenes = [s["scene"] for s in j["scenes"]]
        self.assertIn("business", scenes)
        self.assertIn("nba_team", scenes)
        self.assertEqual(j["leagues"]["nba"], "NBA")

    def test_log_tail(self):
        with mock.patch.object(server, "LOG_FILE", os.path.join(self._dir.name, "server.log")):
            with open(server.LOG_FILE, "w", encoding="utf-8") as f:
                f.write("".join(f"line {i}\n" for i in range(300)))
            j = self.call("GET", "/api/manage/log?lines=5")[1]
        self.assertEqual(j["lines"], [f"line {i}" for i in range(295, 300)])

    def test_shul_status_flags_unreadable_bulletin(self):
        server.store.data["shul"] = {"bulletin": {"file": "7Nov-ChayeiSarah.pdf", "shabbat": "2026-11-07", "times": None},
                                     "chart": None, "calendars": []}
        with mock.patch.object(server, "now", return_value=datetime(2026, 11, 6, 14, 0).astimezone()):
            st = server.shul_status()
        self.assertIsNone(st["bulletin"]["rows"])
        self.assertTrue(st["bulletin"]["this_shabbat"])
        self.assertIn("couldn't be read", st["problem"])

    def test_shul_status_all_good(self):
        server.store.data["shul"] = {
            "bulletin": {"file": "7Nov-ChayeiSarah.pdf", "shabbat": "2026-11-07", "times": {"rows": [{}] * 24, "notes": []}},
            "chart": {"file": "Nov1-weeklydavening.png", "week_of": "2026-11-01"},
            "calendars": [{"file": "November2026.jpg"}]}
        with mock.patch.object(server, "now", return_value=datetime(2026, 11, 6, 14, 0).astimezone()):
            st = server.shul_status()
        self.assertEqual(st["bulletin"]["rows"], 24)
        self.assertTrue(st["chart"]["this_week"])
        self.assertTrue(st["calendars"][0]["this_month"])
        self.assertIsNone(st["problem"])


if __name__ == "__main__":
    unittest.main()
