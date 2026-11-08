import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import server  # noqa: E402
from test_household import HouseholdCase  # noqa: E402

METS = {"teams": [{"id": 121, "abbreviation": "NYM", "teamName": "Mets", "name": "New York Mets",
                   "division": {"id": 204, "name": "National League East"}, "league": {"id": 104}}]}


def fake_get_json(url, accept="application/json"):
    if "/teams/121" in url:
        return METS
    raise AssertionError("unexpected request " + url)


class MlbHouseholdTests(HouseholdCase):
    def choose_mets(self):
        h = server.household()
        h["sports"]["mlb"]["favorite"] = 121
        h["sports"]["mlb"]["teams"] = [{"id": 121, "abbr": "NYM", "name": "New York Mets"}]
        server.save_household(h)

    def test_favorite_comes_from_household(self):
        self.choose_mets()
        with mock.patch.object(server, "get_json", fake_get_json):
            fav = server.mlb_favorite()
        self.assertEqual((fav["id"], fav["division_id"], fav["league_id"], fav["abbr"]), (121, 204, 104, "NYM"))
        self.assertEqual(fav["division_name"], "NL East")

    def test_yankees_need_no_lookup(self):
        with mock.patch.object(server, "get_json", side_effect=AssertionError("fetched")):
            fav = server.mlb_favorite()
        self.assertEqual((fav["id"], fav["division_id"], fav["division_name"]), (147, 201, "AL East"))

    def test_lookup_failure_falls_back_to_yankees(self):
        self.choose_mets()
        with mock.patch.object(server, "get_json", side_effect=OSError("down")):
            self.assertEqual(server.mlb_favorite()["id"], 147)

    def test_state_config_follows_favorite(self):
        self.choose_mets()
        with mock.patch.object(server, "get_json", fake_get_json):
            cfg = json.loads(server.state_json(None))["config"]
        self.assertEqual((cfg["team_abbr"], cfg["division_name"]), ("NYM", "NL East"))

    def test_mlb_off(self):
        h = server.household()
        h["sports"]["mlb"]["on"] = False
        server.save_household(h)
        with mock.patch.object(server, "get_json", side_effect=AssertionError("fetched")):
            self.assertEqual(server.fetch_team(), {"off": True})


if __name__ == "__main__":
    unittest.main()
