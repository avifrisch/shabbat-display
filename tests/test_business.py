import json
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import server  # noqa: E402
from test_household import HouseholdCase  # noqa: E402


def local(*a):
    return datetime(*a).astimezone()


class BusinessTests(HouseholdCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(server, "SEC_FILE", os.path.join(self._dir.name, "sec-tickers.json"))
        p.start()
        self.addCleanup(p.stop)

    def watch(self, *syms):
        h = server.household()
        h["business"]["watchlist"] = [{"symbol": s, "name": s + " Inc."} for s in syms]
        server.save_household(h)

    def test_cnbc_numbers(self):
        body = json.dumps({"FormattedQuoteResult": {"FormattedQuote": [
            {"symbol": ".SPX", "shortName": "S&P 500", "last": "7,376.86", "change": "+23.13", "change_pct": "+0.31%",
             "last_time": "2026-11-06", "code": 0},
            {"symbol": "AAPL", "shortName": "AAPL", "last": "342.37", "change": "-1.80", "change_pct": "-0.52%", "code": 0},
            {"symbol": "ZZZZ", "code": 1}]}})
        with mock.patch.object(server, "http_get", return_value=body) as g:
            q = server.cnbc_quotes([".SPX", "AAPL", "ZZZZ"])
        self.assertEqual((q[".SPX"]["last"], q[".SPX"]["change"], q[".SPX"]["pct"]), (7376.86, 23.13, 0.31))
        self.assertEqual(q["AAPL"]["change"], -1.80)
        self.assertNotIn("ZZZZ", q)
        self.assertEqual(g.call_args.kwargs.get("ua"), server.OWN_UA)
        self.assertIn(".SPX%7CAAPL%7CZZZZ", g.call_args.args[0])

    def test_yahoo_quote(self):
        body = json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": 110.0, "chartPreviousClose": 100.0,
                                                          "shortName": "Berkshire", "regularMarketTime": 1794001029}}]}})
        with mock.patch.object(server, "http_get", return_value=body) as g:
            q = server.yahoo_quote("BRK.B")
        self.assertEqual((q["last"], q["change"], q["pct"]), (110.0, 10.0, 10.0))
        self.assertIn("/BRK-B?", g.call_args.args[0])

    def test_fetch_markets_shape(self):
        self.watch("AAPL")
        quotes = {".SPX": {"last": 1.0, "change": 0.1, "pct": 1.0, "name": "S&P 500", "time": None},
                  ".DJI": {"last": 2.0, "change": -0.1, "pct": -1.0, "name": "DJIA", "time": None},
                  ".IXIC": {"last": 3.0, "change": 0.0, "pct": 0.0, "name": "NASDAQ", "time": None},
                  "AAPL": {"last": 4.0, "change": 0.2, "pct": 5.0, "name": "AAPL", "time": None}}
        with mock.patch.object(server, "cnbc_quotes", return_value=quotes), \
                mock.patch.object(server, "now", return_value=local(2026, 11, 9, 10, 0)):
            m = server.fetch_markets()
        self.assertEqual([i["name"] for i in m["indices"]], ["S&P 500", "Dow Jones", "Nasdaq"])
        self.assertEqual(m["watch"], [{"symbol": "AAPL", "name": "AAPL Inc.", "last": 4.0, "change": 0.2, "pct": 5.0}])
        self.assertEqual((m["source"], m["market"], m["missing"]), ("CNBC", "open", []))
        self.assertIsNone(m["last_trade"])
        quotes[".SPX"]["time"] = "2026-11-06"
        quotes["AAPL"]["time"] = "2026-11-06T19:59:00-05:00"
        with mock.patch.object(server, "cnbc_quotes", return_value=quotes):
            self.assertEqual(server.fetch_markets()["last_trade"], "2026-11-06")

    def test_missing_symbols_fall_back_to_yahoo(self):
        self.watch("AAPL")
        with mock.patch.object(server, "cnbc_quotes", return_value={}), \
                mock.patch.object(server, "yahoo_quote",
                                  return_value={"last": 10.0, "change": 1.0, "pct": 11.1, "name": "X", "time": None}):
            m = server.fetch_markets()
        self.assertEqual(m["source"], "Yahoo")
        self.assertEqual(m["watch"][0]["symbol"], "AAPL")

    def test_everything_failing_raises(self):
        self.watch("AAPL")
        with mock.patch.object(server, "cnbc_quotes", side_effect=OSError("down")), \
                mock.patch.object(server, "yahoo_quote", side_effect=OSError("down")):
            with self.assertRaises(Exception):
                server.fetch_markets()

    def test_market_wait(self):
        mon_open = local(2026, 11, 9, 10, 0)
        self.assertEqual(server.market_wait(mon_open, None), 300)
        after = local(2026, 11, 9, 16, 30)
        self.assertEqual(server.market_wait(after, local(2026, 11, 9, 15, 58)), 300)
        w = server.market_wait(after, local(2026, 11, 9, 16, 6))
        self.assertEqual(w, int((local(2026, 11, 10, 9, 30) - after).total_seconds()) + 60)
        sat = local(2026, 11, 7, 12, 0)
        self.assertEqual(server.market_wait(sat, None), int((local(2026, 11, 9, 9, 30) - sat).total_seconds()) + 60)
        early = local(2026, 11, 9, 7, 0)
        self.assertEqual(server.market_wait(early, local(2026, 11, 6, 16, 6)), int((local(2026, 11, 9, 9, 30) - early).total_seconds()) + 60)

    def test_sec_only_gets_the_email(self):
        seen = []

        def fake(url, accept="*/*", timeout=20, ua=server.UA):
            seen.append((url, ua))
            return json.dumps({"0": {"ticker": "AAPL", "title": "Apple Inc."}, "1": {"ticker": "APLE", "title": "Apple Hospitality REIT"}})
        with mock.patch.object(server, "http_get", fake):
            res = server.stock_search("apple")
            self.assertEqual(res[0]["symbol"], "AAPL")
            self.assertEqual(server.stock_search("aple")[0]["symbol"], "APLE")  # exact ticker first
        self.assertEqual(len(seen), 1)  # cached in sec-tickers.json after the first search
        self.assertTrue(all(url.startswith("https://www.sec.gov/") for url, ua in seen if "frischa@" in ua))
        with open(os.path.join(server.HERE, "server.py"), encoding="utf-8") as f:
            self.assertEqual(f.read().count("frischa@avifrischlaw.com"), 1)

    def test_sec_failure_returns_empty(self):
        with mock.patch.object(server, "http_get", side_effect=OSError("down")):
            self.assertEqual(server.stock_search("apple"), [])

    def test_business_off(self):
        h = server.household()
        h["business"]["on"] = False
        server.save_household(h)
        self.assertEqual(server.fetch_markets(), {"off": True})

    def test_business_feeds_use_own_user_agent_and_open_in_reader(self):
        self.assertIn("biz_nyt", server.ARTICLE_FEEDS)
        self.assertIn("biz_cnbc", server.ARTICLE_FEEDS)
        rss = "<rss><channel><item><title>Stocks rise</title><link>https://www.cnbc.com/a.html</link></item></channel></rss>"
        with mock.patch.object(server, "http_get", return_value=rss) as g:
            v = {k: fn for k, fn, _ in server.SOURCES}["biz_cnbc"]()
        self.assertEqual(v["items"][0]["title"], "Stocks rise")
        self.assertEqual(g.call_args.kwargs.get("ua"), server.OWN_UA)


if __name__ == "__main__":
    unittest.main()
