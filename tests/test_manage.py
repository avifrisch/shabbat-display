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
                                                 "saver": {"minutes": 15, "lock": True, "shabbat": True}})
        s = server.household()["screens"]["Ariela"]
        self.assertTrue(s["saved"])
        self.assertEqual(s["mode"], "saver")
        self.assertEqual(s["saver"]["minutes"], 15)

    def test_bad_screen_settings_are_400(self):
        self.assertEqual(self.call("POST", "/api/manage/screen", {"name": "Ariela", "mode": "blink", "saver": {}})[0], 400)
        self.assertEqual(self.call("POST", "/api/manage/screen", {"name": "Ariela", "mode": "saver",
                                                                  "saver": {"minutes": 0, "lock": True, "shabbat": False}})[0], 400)

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

    def test_lists_need_the_key_and_are_changed(self):
        import tempfile
        from unittest import mock
        folder = tempfile.mkdtemp()
        a = server.ASSISTANT
        with mock.patch.object(a.shopping, "path", folder + "/shopping.json"), mock.patch.object(a.usuals, "path", folder + "/usuals.json"):
            self.assertEqual(self.call("GET", "/api/manage/lists", key=None)[0], 401)
            status, state = self.call("POST", "/api/manage/lists", {"op": "create_list", "name": "Kids", "kind": "todo"})
            self.assertEqual((status, [(one["name"], one["kind"]) for one in state["lists"]]),
                             (200, [("Shopping", "shopping"), ("Kids", "todo")]))
            self.call("POST", "/api/manage/lists", {"op": "add_item", "list": state["lists"][1]["id"], "text": "Set the table"})
            status, state = self.call("GET", "/api/manage/lists")
            self.assertEqual((status, state["lists"][1]["items"], state["sets"][0]["name"]), (200, ["Set the table"], "Usuals"))
            status, out = self.call("POST", "/api/manage/lists", {"op": "delete_list", "list": "main"})
            self.assertEqual((status, out["error"]), (400, "The main list can't be deleted."))
            shown = self.get("/api/state")[1]["data"]["shopping"]
            self.assertEqual(shown, {"items": [], "lists": [{"name": "Kids", "kind": "todo", "items": ["Set the table"]}]})

    def voice_files(self):
        """The assistant's count file and the device list in the temp folder."""
        return (mock.patch.object(server.ASSISTANT.budget, "path", os.path.join(self._dir.name, "budget.json")),
                mock.patch.object(server.PUSH_DEVICES, "path", os.path.join(self._dir.name, "devices.json")))

    def test_voice_settings_from_the_app_win_and_stay_secret(self):
        budget, devices = self.voice_files()
        server.CONFIG.update(anthropic_api_key="", assistant_monthly_usd=5.0, announce_push_url="https://ntfy.sh/from-settings")
        with budget, devices:
            self.assertEqual(self.call("GET", "/api/manage/voice", key=None)[0], 401)
            status, v = self.call("GET", "/api/manage/voice")
            self.assertEqual((status, v["key_set"], v["monthly_usd"], v["daily_requests"], v["ntfy_set"], v["spent_usd"]),
                             (200, False, 5.0, 300, True, 0.0))
            status, v = self.call("POST", "/api/manage/voice", {"op": "set_key", "key": "sk-ant-secret789"})
            self.assertEqual((status, v["key_set"]), (200, True))
            self.assertEqual(server._assistant_settings()["api_key"], "sk-ant-secret789")
            v = self.call("POST", "/api/manage/voice", {"op": "set_limits", "monthly_usd": 2.5, "daily_requests": 40})[1]
            self.assertEqual((v["monthly_usd"], v["daily_requests"]), (2.5, 40))
            self.assertEqual(server._assistant_settings()["monthly_usd"], 2.5)
            v = self.call("POST", "/api/manage/voice", {"op": "set_ntfy", "url": ""})[1]   # cleared in the app wins
            self.assertFalse(v["ntfy_set"])
            self.call("POST", "/api/manage/voice", {"op": "set_menuapp", "url": "https://example.com/inbox/secret321"})
            for path in ("/api/manage/voice", "/api/manage/household", "/api/manage/status"):
                text = json.dumps(self.call("GET", path)[1])
                for secret in ("secret789", "secret321", "from-settings"):
                    self.assertNotIn(secret, text)
            self.assertNotIn("secret789", self.get("/api/state")[1].__repr__())

    def test_voice_bad_values_are_sentences(self):
        budget, devices = self.voice_files()
        with budget, devices:
            for body, start in (({"op": "set_key", "key": "hello"}, "That doesn't look like a Claude API key"),
                                ({"op": "set_limits", "monthly_usd": 500, "daily_requests": 40}, "The monthly limit"),
                                ({"op": "set_limits", "monthly_usd": 5, "daily_requests": 1.5}, "The daily limit"),
                                ({"op": "set_ntfy", "url": "http://ntfy.sh/x"}, "The address starts with https://"),
                                ({"op": "set_push", "key_file": "k.p8", "key_id": "A B", "team_id": "T1", "critical": False}, "The key ID"),
                                ({"op": "forget_device", "id": "nope"}, "That device isn't"),
                                ({"op": "announce", "text": "  "}, "Type what to announce"),
                                ({"op": "dance"}, "The display server doesn't know")):
                status, out = self.call("POST", "/api/manage/voice", body)
                self.assertEqual(status, 400, body)
                self.assertTrue(out["error"].startswith(start), out)

    def test_voice_push_key_devices_and_announce(self):
        budget, devices = self.voice_files()
        sent = []
        with budget, devices, mock.patch.object(server, "_push_announcement", lambda text, origin="", device="": sent.append((text, origin))):
            token = "ab" * 32
            self.assertTrue(server.PUSH_DEVICES.register(token, "Kitchen iPad", "production"))
            v = self.call("POST", "/api/manage/voice", {"op": "set_push", "key_file": "missing.p8", "key_id": "FZ5YNX7JN6",
                                                         "team_id": "TEAM123456", "critical": False})[1]
            self.assertEqual((v["push"]["ready"], v["push"]["key_found"], v["push"]["key_id"]), (True, False, "FZ5YNX7JN6"))
            self.assertEqual([(d["screen"], d["env"], d["id"]) for d in v["devices"]], [("Kitchen iPad", "production", token[:12])])
            self.assertNotIn(token, json.dumps(v))

            status, v = self.call("POST", "/api/manage/voice", {"op": "announce", "text": "Dinner is  ready"})
            self.assertEqual((status, sent, v["note"]), (200, [("Dinner is ready", "Display Manager")],
                                                        "It is on the displays now and was sent to the phones and tablets."))
            self.assertEqual([i["text"] for i in server.ASSISTANT.announcements.since(0)["items"]][-1], "Dinner is ready")
            with mock.patch.object(server, "is_holy", lambda n=None: True):
                status, out = self.call("POST", "/api/manage/voice", {"op": "announce", "text": "Dinner"})
            self.assertEqual((status, out["error"], len(sent)), (403, "Nothing is announced on Shabbat or Yom Tov.", 1))

            v = self.call("POST", "/api/manage/voice", {"op": "forget_device", "id": token[:12]})[1]
            self.assertEqual((v["devices"], server.PUSH_DEVICES.all()), ([], {}))

    def test_voice_values_in_a_damaged_household_are_dropped(self):
        h = server._fill_household({"voice": {"assistant_monthly_usd": "lots", "apns_critical": 1, "apns_key_id": "K1"},
                                    "secrets": {"anthropic_api_key": 7}})
        self.assertEqual((h["voice"]["assistant_monthly_usd"], h["voice"]["apns_critical"], h["voice"]["apns_key_id"],
                          h["secrets"]["anthropic_api_key"]), (None, None, "K1", None))

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


NBA_TEAMS = [{"id": 18, "abbr": "NY", "name": "New York Knicks"}, {"id": 17, "abbr": "BKN", "name": "Brooklyn Nets"},
             {"id": 2, "abbr": "BOS", "name": "Boston Celtics"}]


class TeamSearchTests(ManageCase):
    def test_team_search(self):
        with mock.patch.object(server, "league_teams", return_value=sorted(NBA_TEAMS, key=lambda t: t["name"])):
            self.assertEqual([t["id"] for t in server.team_search("nba", "kni")], [18])
            self.assertEqual([t["id"] for t in server.team_search("nba", "n")], [17, 18])
            self.assertEqual([t["id"] for t in server.team_search("nba", "BOS")], [2])
            self.assertEqual(len(server.team_search("nba", "")), 3)
            code, j = self.call("GET", "/api/manage/teams?league=nba&q=kni")
        self.assertEqual((code, j["teams"][0]["name"]), (200, "New York Knicks"))
        self.assertEqual(self.call("GET", "/api/manage/teams?league=xfl&q=a")[0], 400)

    def test_league_teams_from_espn(self):
        body = {"sports": [{"leagues": [{"teams": [{"team": {"id": "18", "abbreviation": "NY", "displayName": "New York Knicks"}},
                                                   {"team": {"id": "2", "abbreviation": "BOS", "displayName": "Boston Celtics"}}]}]}]}
        with mock.patch.object(server, "espn_json", return_value=body):
            self.assertEqual(server.league_teams("nba"), [{"id": 2, "abbr": "BOS", "name": "Boston Celtics"},
                                                          {"id": 18, "abbr": "NY", "name": "New York Knicks"}])

    def test_league_teams_for_mlb(self):
        body = {"teams": [{"id": 147, "abbreviation": "NYY", "name": "New York Yankees"}]}
        with mock.patch.object(server, "get_json", return_value=body):
            self.assertEqual(server.league_teams("mlb"), [{"id": 147, "abbr": "NYY", "name": "New York Yankees"}])


if __name__ == "__main__":
    unittest.main()
