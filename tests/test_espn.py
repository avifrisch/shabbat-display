import json
import os
import sys
import unittest
from datetime import date, datetime
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import server  # noqa: E402
from test_household import HouseholdCase  # noqa: E402


def espn_event(state="pre", short="Sat, November 7th at 7:30 PM EST", period=0, clock="0:00", name=None,
               away=("NYK", 18, "Knicks", None, None), home=("BOS", 2, "Celtics", None, None), date_="2026-11-08T00:30Z",
               eid="401"):
    """An event in the shape of ESPN's scoreboard: (abbr, id, short name, score, linescores) per side."""
    def side(where, t):
        abbr, tid, short_name, score, lines = t
        c = {"homeAway": where, "team": {"id": str(tid) if tid is not None else None, "abbreviation": abbr,
                                        "shortDisplayName": short_name, "displayName": "Full " + short_name},
             "records": [{"summary": "4-4"}]}
        if score is not None:
            c["score"] = score
        if lines is not None:
            c["linescores"] = [{"value": float(v)} for v in lines]
        return c
    return {"id": eid, "date": date_,
            "status": {"period": period, "displayClock": clock,
                       "type": {"state": state, "name": name or {"pre": "STATUS_SCHEDULED", "in": "STATUS_IN_PROGRESS",
                                                                 "post": "STATUS_FINAL"}[state], "shortDetail": short}},
            "competitions": [{"venue": {"fullName": "Madison Square Garden"},
                              "competitors": [side("home", home), side("away", away)]}]}


def espn_standings():
    def entry(tid, abbr, w, l, otl, pts):
        return {"team": {"id": str(tid), "abbreviation": abbr, "shortDisplayName": abbr.title()},
                "stats": [{"name": "wins", "displayValue": str(w)}, {"name": "losses", "displayValue": str(l)},
                          {"name": "otLosses", "displayValue": str(otl)}, {"name": "points", "displayValue": str(pts)}]}
    return {"name": "National Hockey League", "children": [
        {"name": "Eastern Conference", "standings": {"entries": [entry(1, "BOS", 10, 5, 2, 22), entry(18, "NYR", 9, 6, 1, 19)]}},
        {"name": "Western Conference", "standings": {"entries": [entry(30, "COL", 12, 3, 3, 27)]}}]}


class EspnNormTests(unittest.TestCase):
    def test_norm_espn_live_game(self):
        g = server.norm_espn_game(espn_event(state="in", short="Q3 4:12", period=3, clock="4:12",
                                             away=("NYK", 18, "Knicks", "88", [30, 28, 30]),
                                             home=("BOS", 2, "Celtics", "80", [20, 30, 30])), {18})
        self.assertEqual((g["state"], g["detail"], g["away"]["score"], g["away"]["lines"], g["chosen"]),
                         ("Live", "Q3 4:12", 88, [30, 28, 30], True))
        self.assertEqual((g["home"]["abbr"], g["home"]["name"], g["home"]["full"], g["home"]["record"], g["venue"]),
                         ("BOS", "Celtics", "Full Celtics", "4-4", "Madison Square Garden"))
        self.assertEqual((g["period"], g["clock"], g["id"]), (3, "4:12", "401"))

    def test_score_object_form(self):
        ev = espn_event(state="post", away=("NYK", 18, "Knicks", {"value": 102.0, "displayValue": "102"}, []),
                        home=("BOS", 2, "Celtics", "99", []))
        self.assertEqual(server.norm_espn_game(ev, set())["away"]["score"], 102)

    def test_schedule_form_status_and_record(self):
        ev = espn_event(state="post")
        co = ev["competitions"][0]
        co["status"] = ev.pop("status")
        for c in co["competitors"]:
            c["record"] = [{"displayValue": "0-1"}]
            del c["records"]
        g = server.norm_espn_game(ev, set())
        self.assertEqual((g["state"], g["away"]["record"]), ("Final", "0-1"))

    def test_norm_espn_game_tolerates_missing_fields(self):
        ev = espn_event(state="pre", away=("TBD", None, "TBD", None, None), home=("BOS", 2, "Celtics", None, None))
        del ev["competitions"][0]["venue"]
        ev["status"]["type"]["name"] = "STATUS_POSTPONED"
        g = server.norm_espn_game(ev, set())
        self.assertEqual((g["state"], g["away"]["score"], g["away"]["lines"], g["venue"], g["away"]["id"]),
                         ("Off", None, [], None, None))
        self.assertEqual(server.norm_espn_game({"id": "1"}, set())["state"], "Preview")

    def test_in_season_by_days(self):
        self.assertTrue(server.espn_in_season(["2026-11-05T07:00Z", "2027-04-11T07:00Z"], date(2026, 11, 7)))
        self.assertFalse(server.espn_in_season(["2026-10-31T07:00Z"], date(2026, 11, 7)))

    def test_in_season_by_weeks_skips_off_season(self):
        cal = [{"label": "Regular Season", "entries": [{"startDate": "2026-11-04T08:00Z", "endDate": "2026-11-11T07:59Z"}]},
               {"label": "Off Season", "entries": [{"startDate": "2027-02-16T08:00Z", "endDate": "2027-07-31T07:59Z"}]}]
        self.assertTrue(server.espn_in_season(cal, date(2026, 11, 7)))
        self.assertFalse(server.espn_in_season(cal, date(2027, 3, 1)))

    def test_standings_pick_favorites_group(self):
        st = server.norm_espn_standings(espn_standings(), "hockey", favorite=18)
        self.assertEqual(st["cols"], ["W", "L", "OTL", "PTS"])
        self.assertEqual(st["group"], "Eastern Conference")
        self.assertEqual(next(r for r in st["rows"] if r["is_team"])["abbr"], "NYR")
        self.assertEqual(st["rows"][0]["vals"], ["10", "5", "2", "22"])
        self.assertEqual(server.norm_espn_standings(espn_standings(), "hockey", favorite=None)["group"], "Eastern Conference")
        self.assertIsNone(server.norm_espn_standings({}, "hockey", favorite=None))


class FetchLeagueTests(HouseholdCase):
    def nba_on(self, teams=(), fav=None):
        h = server.household()
        h["sports"]["nba"] = {"on": True, "teams": [{"id": i, "abbr": "X", "name": "X"} for i in teams], "favorite": fav}
        server.save_household(h)

    def test_league_off_makes_no_requests(self):
        with mock.patch.object(server, "http_get", side_effect=AssertionError("fetched")):
            self.assertEqual(server.fetch_league("nba"), {"off": True})

    def test_espn_requests_use_own_user_agent(self):
        seen = []

        def fake(url, accept="*/*", timeout=20, ua=server.UA):
            seen.append(ua)
            return json.dumps({"events": [], "leagues": [{"calendar": []}]})
        self.nba_on()
        with mock.patch.object(server, "http_get", fake):
            server.fetch_league("nba")
        self.assertTrue(seen and all(u == server.OWN_UA for u in seen))

    def test_fetch_league_puts_chosen_teams_first(self):
        board = {"leagues": [{"calendar": ["2026-11-07T07:00Z"]}], "events": [
            espn_event(state="post", away=("IND", 11, "Pacers", "102", [1]), home=("DEN", 7, "Nuggets", "114", [1]), eid="1"),
            espn_event(state="in", short="Q2 1:00", away=("NYK", 18, "Knicks", "50", [1]), home=("BOS", 2, "Celtics", "48", [1]), eid="2")]}
        sched = {"events": [espn_event(state="post", away=("NYK", 18, "Knicks", "99", [1]), home=("MIA", 14, "Heat", "90", [1]),
                                       date_="2026-11-05T00:30Z", eid="0"),
                            dict(board["events"][1])]}

        def fake(url, accept="*/*", timeout=20, ua=server.UA):
            if "/scoreboard" in url:
                return json.dumps(board)
            if "/teams/18/schedule" in url:
                return json.dumps(sched)
            if "/standings" in url:
                return json.dumps({})
            return json.dumps({"articles": [{"headline": "Knicks win", "description": "d", "published": "2026-11-07T07:03:36Z",
                                             "links": {"web": {"href": "https://www.espn.com/nba/story/_/id/1"}}}]})
        self.nba_on([18], 18)
        with mock.patch.object(server, "http_get", fake), \
                mock.patch.object(server, "now", return_value=datetime(2026, 11, 7, 20, 0).astimezone()):
            v = server.fetch_league("nba")
        self.assertTrue(v["on"] and v["in_season"])
        self.assertEqual([g["id"] for g in v["scores"]["games"]], ["2", "1"])
        self.assertEqual(v["team"]["live"]["id"], "2")
        self.assertEqual(v["team"]["last"]["id"], "0")
        self.assertEqual(v["news"]["items"][0]["link"], "https://www.espn.com/nba/story/_/id/1")
        self.assertIsNone(v["standings"])

    def test_poll_seconds(self):
        self.assertEqual(server.league_poll_seconds("nba"), 600)
        self.nba_on([18], 18)
        server.store.data["sport_nba"] = {"on": True, "in_season": True, "team": {"live": {"id": "2"}}, "scores": {"games": []}}
        self.assertEqual(server.league_poll_seconds("nba"), 30)
        server.store.data["sport_nba"] = {"on": True, "in_season": False, "team": None, "scores": {"games": []}}
        self.assertEqual(server.league_poll_seconds("nba"), 3600)

    def test_every_league_has_a_source(self):
        keys = [k for k, _, _ in server.SOURCES]
        for k in server.LEAGUES:
            self.assertIn("sport_" + k, keys)

    def test_espn_news_links_open_in_the_reader(self):
        server.store.data["sport_nba"] = {"on": True, "news": {"items": [{"title": "T", "link": "https://www.espn.com/x"}]},
                                          "team_news": {"items": []}}
        item = server.feed_item_for("https://www.espn.com/x")
        self.assertEqual(item["title"], "T")


if __name__ == "__main__":
    unittest.main()
