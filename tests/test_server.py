import copy
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402


def fixture(name):
    with open(os.path.join(ROOT, "tests", "fixtures", name), encoding="utf-8") as f:
        return f.read()


NYT_LINK = "https://www.nytimes.com/2026/10/29/a.html"


class Isolated(unittest.TestCase):
    """Restores CONFIG, the store and the on-demand cache after each test."""

    def setUp(self):
        self._config = copy.deepcopy(server.CONFIG)
        self._data = dict(server.store.data)
        server._cache.clear()
        # never touch the real household.json or access code
        import tempfile
        self._hdir = tempfile.TemporaryDirectory()
        self._hpatches = [mock.patch.object(server, "HOUSEHOLD_FILE", os.path.join(self._hdir.name, "household.json")),
                          mock.patch.object(server, "KEY_FILE", os.path.join(self._hdir.name, "manage-key.txt"))]
        for p in self._hpatches:
            p.start()
        server._household_cache = None
        server._household_mtime = None

    def tearDown(self):
        for p in self._hpatches:
            p.stop()
        self._hdir.cleanup()
        server._household_cache = None
        server._household_mtime = None
        server.CONFIG.clear()
        server.CONFIG.update(self._config)
        server.store.data = self._data
        server._cache.clear()


class SettingsTests(Isolated):
    def test_launcher_settings_are_not_reported_as_unknown(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"server_url": "http://x:8765", "screensaver_minutes": 30, "screensaver_lock": False,
                           "screensaver_screens": "external", "keep_pc_awake": True, "screen_name": "Den",
                           "made_up": 1}, f)
            logged = []
            with mock.patch.object(server, "SETTINGS_FILE", path), mock.patch.object(server, "log", logged.append):
                server.load_settings()
        self.assertEqual(logged, ["settings.json: unknown setting 'made_up' ignored"])


class CacheTests(Isolated):
    def test_expired_entries_are_dropped(self):
        with mock.patch.object(server.time, "time", return_value=1000.0):
            server.cached("old", 10, lambda: 1)
        with mock.patch.object(server.time, "time", return_value=2000.0):
            server.cached("new", 10, lambda: 2)
        self.assertNotIn("old", server._cache)
        self.assertIn("new", server._cache)

    def test_ttl_can_depend_on_the_value(self):
        calls = []
        load = lambda: calls.append(1) or {"ok": False}  # noqa: E731
        ttl = lambda v: 60 if not v["ok"] else 600  # noqa: E731
        for t in (1000.0, 1059.0, 1061.0):
            with mock.patch.object(server.time, "time", return_value=t):
                server.cached("k", ttl, load)
        self.assertEqual(len(calls), 2)  # refetched once the 60 s were up


class ArticleTests(Isolated):
    def setUp(self):
        super().setUp()
        server.store.data["nyt"] = {"items": [{"title": "T", "summary": "S", "time": None,
                                               "link": NYT_LINK, "source": "nyt"}]}
        server.CONFIG["nyt_cookie"] = "secret123"

    def test_unknown_url_rejected(self):
        with self.assertRaises(LookupError):
            server.article_json("https://evil.example/x")

    def test_cookie_only_for_nytimes(self):
        self.assertEqual(server.article_headers("https://www.nytimes.com/a")["Cookie"], "NYT-S=secret123")
        self.assertNotIn("Cookie", server.article_headers("https://www.cnn.com/a"))
        self.assertNotIn("Cookie", server.article_headers("https://nytimes.com.evil.example/a"))

    def test_whole_cookie_header_sent_as_is(self):
        server.CONFIG["nyt_cookie"] = "NYT-S=abc; nyt-a=def"
        self.assertEqual(server.article_headers("https://www.nytimes.com/a")["Cookie"], "NYT-S=abc; nyt-a=def")

    def test_extract_paragraphs(self):
        # only the article body: not the script, nav, header, figure caption, aside or footer
        paras = server.extract_article(fixture("article_nyt.html"))
        self.assertEqual(len(paras), 2)
        self.assertTrue(paras[0].startswith("A slow-moving storm"))
        self.assertTrue(paras[1].startswith("The National Weather Service"))

    def test_no_paragraphs_falls_back(self):
        with mock.patch.object(server, "http_get_with", return_value=fixture("article_redirect.html")):
            j = server.article_json(NYT_LINK)
        self.assertFalse(j["ok"])
        self.assertEqual(j["summary"], "S")
        self.assertEqual(j["message"], "The full article couldn't be loaded.")

    def test_secret_not_in_error(self):
        with mock.patch.object(server, "http_get_with", side_effect=OSError("boom secret123")):
            j = server.article_json(NYT_LINK)
        self.assertNotIn("secret123", json.dumps(j))

    def test_cookie_dropped_on_redirect_off_nytimes(self):
        handler = server.CookieSafeRedirect()
        req = server.urllib.request.Request(NYT_LINK, headers={"Cookie": "NYT-S=secret123"})
        away = handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/b")
        self.assertNotIn("Cookie", away.headers)
        plain = handler.redirect_request(req, None, 302, "Found", {}, "http://www.nytimes.com/b")
        self.assertNotIn("Cookie", plain.headers)
        home = handler.redirect_request(req, None, 302, "Found", {}, "https://www.nytimes.com/b")
        self.assertEqual(home.headers.get("Cookie"), "NYT-S=secret123")

    def test_nyt_failure_hints_at_cookie(self):
        with mock.patch.object(server, "http_get_with", side_effect=OSError("HTTP Error 403")):
            j = server.article_json(NYT_LINK)
        self.assertFalse(j["ok"])
        self.assertIn("nyt_cookie", j["hint"])

    def test_failed_article_retried_after_a_minute(self):
        calls = []

        def fail(*a, **k):
            calls.append(1)
            raise OSError("down")
        with mock.patch.object(server, "http_get_with", side_effect=fail):
            for t in (1000.0, 1030.0, 1065.0):
                with mock.patch.object(server.time, "time", return_value=t):
                    server.article_json(NYT_LINK)
        self.assertEqual(len(calls), 2)

    def test_short_free_nyt_piece_not_marked_truncated(self):
        page = "<article>" + ("<p>%s</p>" % ("x" * 60)) * 3 + "</article>"
        with mock.patch.object(server, "http_get_with", return_value=page):
            self.assertFalse(server.article_json(NYT_LINK)["truncated"])

    def test_paywalled_nyt_piece_marked_truncated(self):
        page = ('<script type="application/ld+json">{"isAccessibleForFree":false}</script>'
                "<article>" + ("<p>%s</p>" % ("x" * 60)) * 3 + "</article>")
        with mock.patch.object(server, "http_get_with", return_value=page):
            self.assertTrue(server.article_json(NYT_LINK)["truncated"])

    def test_only_http_links_are_fetched(self):
        server.store.data["cnn"] = {"items": [{"title": "T", "summary": "", "link": "file:///etc/passwd", "source": "cnn"}]}
        with self.assertRaises(LookupError):
            server.article_json("file:///etc/passwd")

    def test_google_news_links_not_fetched(self):
        link = "https://news.google.com/rss/articles/CBMiabc"
        server.store.data["toi"] = {"items": [{"title": "T", "summary": "S", "link": link, "source": "toi"}]}
        with mock.patch.object(server, "http_get_with") as get:
            j = server.article_json(link)
        get.assert_not_called()
        self.assertFalse(j["ok"])
        self.assertEqual(j["message"], "The full article couldn't be loaded.")

    def test_route_404_for_unknown_url(self):
        code, body = server.article_route("url=https%3A%2F%2Fevil.example%2Fx")
        self.assertEqual(code, 404)
        self.assertFalse(json.loads(body)["ok"])


class GameTests(Isolated):
    def test_final_box(self):
        b = server.norm_boxscore(json.loads(fixture("game_final.json")))
        self.assertEqual(b["state"], "Final")
        self.assertGreaterEqual(len(b["innings"]), 9)
        self.assertEqual(sum(i["away"] or 0 for i in b["innings"]), b["away"]["r"])
        self.assertGreaterEqual(len(b["away"]["batters"]), 9)
        self.assertTrue(any(p["note"] == "W" for p in b["away"]["pitchers"] + b["home"]["pitchers"]))
        self.assertTrue(b["away"]["is_team"] or b["home"]["is_team"])

    def test_final_box_summary(self):
        b = server.norm_boxscore(json.loads(fixture("game_final.json")))
        self.assertEqual(b["decisions"]["l"], "Fried (1-1)")
        self.assertEqual(len(b["homers"]), 2)
        self.assertRegex(b["homers"][0], r"^\S.* \(\d+\)$")
        self.assertEqual(b["away"]["batters"][0]["pos"], b["away"]["batters"][0]["pos"].upper())

    def test_preview_game_has_probables(self):
        b = server.norm_boxscore(json.loads(fixture("game_preview.json")))
        self.assertEqual(b["state"], "Preview")
        self.assertEqual(b["away"]["batters"], [])
        self.assertIn("probable", b["home"])

    def test_game_route_rejects_non_numeric(self):
        self.assertIsNone(server.game_id_from_query("id=12ab"))
        self.assertIsNone(server.game_id_from_query(""))
        self.assertEqual(server.game_id_from_query("id=778899"), 778899)

    def test_game_route_rejects_non_ascii_digits(self):
        self.assertIsNone(server.game_id_from_query("id=%C2%B2"))          # superscript two
        self.assertIsNone(server.game_id_from_query("id=%D9%A1%D9%A2"))    # Arabic-Indic digits

    def test_postponed_game_is_off(self):
        feed = json.loads(fixture("game_preview.json"))
        feed["gameData"]["status"]["detailedState"] = "Postponed"
        b = server.norm_boxscore(feed)
        self.assertEqual(b["state"], "Off")
        self.assertEqual(b["detail"], "Postponed")

    def test_parse_error_is_not_reported_as_missing_game(self):
        # a change in MLB's format must show up as an error, not as "no such game"
        with mock.patch.object(server, "get_json", return_value={"gamePk": 5}), \
                mock.patch.object(server, "norm_boxscore", side_effect=KeyError("seasonStats")):
            code, _ = server.game_route("id=5")
        self.assertEqual(code, 503)

    def test_unknown_game_is_404(self):
        # statsapi answers 200 with no gameData for an id that doesn't exist
        with mock.patch.object(server, "get_json", return_value={"gamePk": 1, "liveData": {}}):
            code, _ = server.game_route("id=1")
        self.assertEqual(code, 404)


START = "2026-10-29T16:00"  # the current hour in the openmeteo.json fixture


def build(aq=True, nws=True):
    return server.build_forecast(json.loads(fixture("openmeteo.json")),
                                 json.loads(fixture("airquality.json")) if aq else None,
                                 json.loads(fixture("nws_forecast.json")) if nws else None,
                                 start=START)


class ForecastTests(Isolated):
    def test_aqi_word(self):
        self.assertEqual(server.aqi_word(32), "Good")
        self.assertEqual(server.aqi_word(50), "Good")
        self.assertEqual(server.aqi_word(51), "Moderate")
        self.assertEqual(server.aqi_word(301), "Hazardous")
        self.assertEqual(server.aqi_word(None), "")

    def test_pressure_trend(self):
        self.assertEqual(server.pressure_trend([1015.0, 1014.6, 1014.2, 1013.9]), "falling")
        self.assertEqual(server.pressure_trend([1013.0, 1013.4, 1013.8, 1014.0]), "rising")
        self.assertEqual(server.pressure_trend([1015.0, 1015.1, 1015.0, 1015.2]), "steady")
        self.assertEqual(server.pressure_trend([1015.0]), "steady")

    def test_build_forecast_shape(self):
        f = build()
        self.assertEqual(len(f["hours"]), 48)
        self.assertEqual(f["hours"][0]["time"], START)
        self.assertEqual(len(f["days"]), 7)
        self.assertGreaterEqual(len(f["periods"]), 10)
        self.assertEqual(f["now"]["aqi"], 69)
        self.assertEqual(f["now"]["aqi_word"], "Moderate")
        self.assertIn(f["now"]["pressure_trend"], ("rising", "falling", "steady"))
        self.assertLess(abs(f["now"]["pressure_inhg"] - 30), 1.5)

    def test_build_forecast_without_extras(self):
        f = build(aq=False, nws=False)
        self.assertIsNone(f["now"]["aqi"])
        self.assertEqual(f["periods"], [])

    def test_days_start_tomorrow_when_yesterday_is_included(self):
        # past_days=1 puts yesterday first in the daily and hourly data
        om = json.loads(fixture("openmeteo.json"))
        d, h = om["daily"], om["hourly"]
        for k in d:
            d[k] = [("2026-10-28" if k == "time" else d[k][0])] + d[k]
        for k in h:
            h[k] = [(f"2026-10-28T{i:02d}:00" if k == "time" else h[k][0]) for i in range(24)] + h[k]
        f = server.build_forecast(om, None, None, start="2026-10-29T01:00")
        self.assertEqual(f["days"][0]["date"], "2026-10-30")
        self.assertEqual(len(f["days"]), 7)
        self.assertEqual(f["hours"][0]["time"], "2026-10-29T01:00")

    def test_forecast_asks_for_yesterday(self):
        # so the 3-hour pressure trend works just after midnight
        urls = []
        om = json.loads(fixture("openmeteo.json"))
        with mock.patch.object(server, "get_json", side_effect=lambda u, **k: urls.append(u) or om):
            server.forecast_json()
        self.assertIn("past_days=1", urls[0])

    def test_alerts_keep_full_text(self):
        feature = {"properties": {"event": "Flood Watch", "headline": "Flood Watch until Sunday",
                                  "severity": "Moderate", "ends": None, "expires": "2026-11-01T06:00:00-04:00",
                                  "description": "* WHAT...Flooding caused by excessive rainfall.",
                                  "instruction": "Monitor later forecasts."}}
        with mock.patch.object(server, "get_json", return_value={"features": [feature]}):
            a = server.fetch_alerts()[0]
        self.assertEqual(a["description"], "* WHAT...Flooding caused by excessive rainfall.")
        self.assertEqual(a["instruction"], "Monitor later forecasts.")

    def test_candles_marked_inside_48_hours(self):
        server.store.data["calendar"] = {"items": [
            {"category": "candles", "date": "2026-10-30T17:36:00-04:00", "title": "Candle lighting"},
            {"category": "havdalah", "date": "2026-10-31T18:35:00-04:00", "title": "Havdalah"},
            {"category": "candles", "date": "2026-11-06T16:29:00-05:00", "title": "Candle lighting"}]}
        marks = build()["marks"]
        self.assertEqual([m["label"] for m in marks], ["Candles"])


class RouteTests(Isolated):
    """The real request handler, on a free local port."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def status(self, path):
        try:
            with server.urllib.request.urlopen(self.base + path, timeout=10) as r:
                return r.status
        except server.urllib.error.HTTPError as e:
            return e.code

    def test_health(self):
        self.assertEqual(self.status("/health"), 200)

    def test_bad_game_ids_are_404(self):
        self.assertEqual(self.status("/api/game?id=abc"), 404)
        self.assertEqual(self.status("/api/game?id=%C2%B2"), 404)

    def test_unknown_article_is_404(self):
        self.assertEqual(self.status("/api/article?url=https%3A%2F%2Fevil.example%2F"), 404)

    def test_state_has_no_secrets(self):
        server.CONFIG["nyt_cookie"] = "secret123"
        server.CONFIG["agenda_ics"] = ["https://example.com/feed/secret456.ics"]
        with server.urllib.request.urlopen(self.base + "/api/state", timeout=10) as r:
            body = r.read().decode()
        self.assertNotIn("secret123", body)
        self.assertNotIn("secret456", body)


if __name__ == "__main__":
    unittest.main()
