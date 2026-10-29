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

    def tearDown(self):
        server.CONFIG.clear()
        server.CONFIG.update(self._config)
        server.store.data = self._data
        server._cache.clear()


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

    def test_nyt_short_article_marked_truncated(self):
        page = "<article>" + ("<p>%s</p>" % ("x" * 60)) * 3 + "</article>"
        with mock.patch.object(server, "http_get_with", return_value=page):
            j = server.article_json(NYT_LINK)
        self.assertTrue(j["ok"])
        self.assertTrue(j["truncated"])

    def test_secret_not_in_error(self):
        with mock.patch.object(server, "http_get_with", side_effect=OSError("boom secret123")):
            j = server.article_json(NYT_LINK)
        self.assertNotIn("secret123", json.dumps(j))

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

    def test_unknown_game_is_404(self):
        # statsapi answers 200 with no gameData for an id that doesn't exist
        with mock.patch.object(server, "get_json", return_value={"gamePk": 1, "liveData": {}}):
            code, _ = server.game_route("id=1")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
