import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import assistant  # noqa: E402
import walmart  # noqa: E402
import server  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_household import HouseholdCase  # noqa: E402


def text(words, tokens_in=2000, tokens_out=60, stop="end_turn"):
    return {"content": [{"type": "text", "text": words}], "stop_reason": stop,
            "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}}


def tool(name, args, tokens_in=2000, tokens_out=60, call_id="toolu_1", before="One moment."):
    return {"content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                        {"type": "text", "text": before},
                        {"type": "tool_use", "id": call_id, "name": name, "input": args}],
            "stop_reason": "tool_use", "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}}


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.clock = datetime(2026, 11, 12, 9, 0)
        self.budget_file = os.path.join(self.dir.name, "assistant-budget.json")
        self.settings = {"api_key": "sk-test", "monthly_usd": 5.0, "daily_requests": 300}
        self.answers, self.sent, self.logged, self.forwarded = [], [], [], []
        self.forward_fails = False
        self.a = assistant.Assistant(lambda: self.settings,
                                     assistant.Budget(self.budget_file, now=lambda: self.clock),
                                     assistant.ShoppingList(os.path.join(self.dir.name, "shopping.json"), now=lambda: self.clock),
                                     assistant.Usuals(os.path.join(self.dir.name, "usuals.json")),
                                     post=self.post, log=self.logged.append, forward=self.forward)

    def post(self, url, headers, body):
        self.sent.append(json.loads(json.dumps(body)))  # a copy, and proof that it is JSON
        self.headers = headers
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def forward(self, items):
        if self.forward_fails:
            raise OSError("MenuApp is down")
        self.forwarded.append(list(items))

    def ask(self, words, **more):
        return self.a.handle({"text": words, **more}, facts="It is Thursday.")

    def spent(self):
        with open(self.budget_file, encoding="utf-8") as f:
            return json.load(f)


class Answers(Case):
    def test_a_plain_answer(self):
        self.answers = [text("A cup is sixteen tablespoons.")]
        status, out = self.ask("how many tablespoons in a cup")
        self.assertEqual((status, out), (200, {"ok": True, "say": "A cup is sixteen tablespoons.", "actions": []}))
        body = self.sent[0]
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertEqual(body["output_config"], {"effort": "low"})
        self.assertEqual(body["messages"], [{"role": "user", "content": "how many tablespoons in a cup"}])
        self.assertIn("It is Thursday.", body["system"])
        self.assertIn("Shopping list: empty.", body["system"])
        self.assertEqual(self.headers["x-api-key"], "sk-test")

    def test_history_and_timers_reach_claude(self):
        self.answers = [text("Four minutes.")]
        self.ask("how long is left", history=[{"q": "set a pasta timer", "a": "Done."}, {"q": "", "a": "x"}],
                 timers=[{"label": "pasta", "seconds_left": 245.7, "ringing": False}, {"label": "eggs", "seconds_left": 0, "ringing": True}])
        body = self.sent[0]
        self.assertEqual([m["content"] for m in body["messages"]], ["set a pasta timer", "Done.", "how long is left"])
        self.assertIn("Timers: pasta (4 min 5 s left); eggs (ringing now).", body["system"])

    def test_a_timer_becomes_an_action_for_the_ipad(self):
        self.answers = [tool("set_timer", {"seconds": 600, "label": "pasta"}), text("Pasta timer set for ten minutes.")]
        status, out = self.ask("set a pasta timer for ten minutes")
        self.assertEqual(out, {"ok": True, "say": "Pasta timer set for ten minutes.",
                               "actions": [{"type": "set_timer", "seconds": 600, "label": "pasta"}]})
        back = self.sent[1]["messages"]
        self.assertEqual(back[1]["content"][0]["type"], "thinking")  # Claude's own blocks go back unchanged
        self.assertEqual(back[2]["content"], [{"type": "tool_result", "tool_use_id": "toolu_1",
                                               "content": "Started: pasta, 10 min."}])

    def test_a_bad_timer_is_refused_to_claude(self):
        for seconds in (0, 90000, "600", True, None):
            self.answers = [tool("set_timer", {"seconds": seconds}), text("I can only set timers up to a day.")]
            _, out = self.ask("timer")
            self.assertEqual(out["actions"], [])
            self.assertTrue(self.sent[-1]["messages"][2]["content"][0]["is_error"])

    def test_cancel_only_when_a_timer_runs(self):
        self.answers = [tool("cancel_timer", {"label": "all"}), text("There are no timers.")]
        self.assertEqual(self.ask("stop the timer")[1]["actions"], [])
        self.answers = [tool("cancel_timer", {"label": "Pasta"}), text("Stopped.")]
        out = self.ask("stop the pasta timer", timers=[{"label": "pasta", "seconds_left": 30}])[1]
        self.assertEqual(out["actions"], [{"type": "cancel_timer", "label": "Pasta"}])

    def test_shopping_list(self):
        self.answers = [tool("add_to_shopping_list", {"items": ["Milk", " 2 dozen  eggs ", "milk", 7]}), text("Added milk and eggs.")]
        self.ask("we need milk and two dozen eggs")
        self.assertEqual([i["text"] for i in self.a.shopping.items()], ["Milk", "2 dozen eggs"])
        self.assertEqual(self.forwarded, [["Milk", "2 dozen eggs"]])
        self.assertTrue(all(i["sent"] for i in self.a.shopping.items()))

        self.answers = [tool("add_to_shopping_list", {"items": ["MILK", "butter"]}), text("Butter added; milk was already there.")]
        self.ask("milk and butter")
        self.assertIn("Added: butter. Already on the list: MILK.", self.sent[-1]["messages"][2]["content"][0]["content"])
        self.assertEqual(self.forwarded[-1], ["butter"])

        self.answers = [text("Milk, eggs and butter.")]
        self.ask("what's on the list")
        self.assertIn("Shopping list: Milk; 2 dozen eggs; butter.", self.sent[-1]["system"])

        self.answers = [tool("remove_from_shopping_list", {"items": ["eggs", "bread"]}), text("Eggs are off the list.")]
        self.ask("take eggs off")
        self.assertEqual([i["text"] for i in self.a.shopping.items()], ["Milk", "butter"])

    def test_items_wait_when_menuapp_is_down(self):
        self.forward_fails = True
        self.answers = [tool("add_to_shopping_list", {"items": ["milk"]}), text("Added milk.")]
        self.assertEqual(self.ask("milk")[1]["say"], "Added milk.")
        self.assertEqual(self.a.shopping.unsent(), ["milk"])
        self.forward_fails = False
        self.answers = [tool("add_to_shopping_list", {"items": ["eggs"]}), text("Added eggs.")]
        self.ask("eggs")
        self.assertEqual(self.forwarded, [["milk", "eggs"]])
        self.assertEqual(self.a.shopping.unsent(), [])

    def test_items_stay_unsent_while_there_is_nowhere_to_send_them(self):
        self.a.forward = lambda items: False
        self.answers = [tool("add_to_shopping_list", {"items": ["milk"]}), text("Added milk.")]
        self.ask("milk")
        self.assertEqual(self.a.shopping.unsent(), ["milk"])

    def test_refusal_unknown_tool_and_tool_loop_end(self):
        self.answers = [text("", stop="refusal")]
        self.assertEqual(self.ask("x")[1]["say"], "Sorry, I can't help with that.")
        self.answers = [tool("order_pizza", {})] * 4
        status, out = self.ask("order a pizza")
        self.assertEqual((status, out["say"], len(self.sent)), (200, "", 5))
        self.assertTrue(self.sent[-1]["messages"][-1]["content"][0]["is_error"])

    def test_what_is_refused_before_claude_is_asked(self):
        self.assertEqual(self.a.handle({"text": "hello"}, holy=True), (403, {"ok": False, "error": "holy", "say": ""}))
        self.assertEqual(self.ask("   ")[0], 400)
        self.assertEqual(self.a.handle(None)[0], 400)
        self.assertEqual(self.a.handle({"text": 5})[0], 400)
        self.settings["api_key"] = ""
        status, out = self.ask("hello")
        self.assertEqual((status, out["error"]), (503, "not_set_up"))
        self.assertEqual(self.sent, [])

    def test_claude_errors_are_sentences(self):
        self.answers = [assistant.ApiError(401, "invalid x-api-key")]
        status, out = self.ask("hello")
        self.assertEqual((status, out["error"]), (502, "claude_401"))
        self.assertIn("key was refused", out["say"])
        self.answers = [assistant.ApiError(0, "timed out")]
        self.assertEqual(self.ask("hello")[1]["say"], "I couldn't reach Claude just now.")
        self.assertNotIn("sk-test", " ".join(self.logged))


class MusicAndWalmart(Case):
    def result(self):
        return self.sent[-1]["messages"][2]["content"][0]

    def test_music_becomes_actions_for_the_ipad(self):
        self.answers = [tool("play_music", {"query": " quiet  jazz ", "kind": "radio"}), text("Putting on some quiet jazz.")]
        out = self.ask("play some quiet jazz")[1]
        self.assertEqual(out["actions"], [{"type": "play_music", "query": "quiet jazz", "kind": "any"}])
        self.answers = [tool("play_music", {"query": "Abbey Road", "kind": "album"}), text("Abbey Road.")]
        self.assertEqual(self.ask("play the album abbey road")[1]["actions"][0]["kind"], "album")
        self.answers = [tool("music_control", {"command": "next"}), text("Skipped.")]
        self.assertEqual(self.ask("skip this")[1]["actions"], [{"type": "music_control", "command": "next"}])
        for bad in (("play_music", {"query": "  "}), ("music_control", {"command": "louder"})):
            self.answers = [tool(*bad), text("Sorry.")]
            self.assertEqual(self.ask("x")[1]["actions"], [])
            self.assertTrue(self.result()["is_error"])

    def test_what_is_playing_reaches_claude(self):
        self.answers = [text("That's Abbey Road.")]
        self.ask("what is this", music={"playing": True, "title": "Come Together - The Beatles"})
        self.assertIn("Music: Come Together - The Beatles (playing).", self.sent[0]["system"])
        self.answers = [text("Nothing.")]
        self.ask("what is this", music={"playing": False, "title": ""})
        self.assertIn("Music: nothing playing.", self.sent[-1]["system"])

    def test_walmart_item_numbers(self):
        for link, want in (("https://www.walmart.com/ip/Great-Value-Whole-Milk-1-Gallon/10450114", "10450114"),
                           ("https://www.walmart.com/ip/Great-Value-Whole-Milk/10450114?athbdg=L1600&from=/search", "10450114"),
                           ("walmart.com/ip/10450114", "10450114"), (" 10450114 ", "10450114"),
                           ("https://www.walmart.com/search?q=milk", ""), ("https://evil.example/ip/x/10450114", ""),
                           ("https://www.walmart.com/ip/Milk/12", ""), ("", ""), (None, "")):
            self.assertEqual(assistant.walmart_item_id(link), want, link)

    def test_a_pasted_link_names_the_item(self):
        self.assertEqual(assistant.walmart_item_name("https://www.walmart.com/ip/Great-Value-Whole-Vitamin-D-Milk-Gallon/10450114?from=/search"),
                         "Great Value Whole Vitamin D Milk Gallon")
        self.assertEqual(assistant.walmart_item_name("https://www.walmart.com/ip/10450114"), "")
        self.assertEqual(assistant.walmart_item_name("10450114"), "")
        item = self.a.usuals.add("", "https://www.walmart.com/ip/Kedem-Grape-Juice-64-fl-oz/555666777", 3)
        self.assertEqual((item["name"], item["item_id"], item["qty"]), ("Kedem Grape Juice 64 fl oz", "555666777", 3))
        self.assertEqual(self.a.usuals.add("Grape juice", "https://www.walmart.com/ip/Kedem-Grape-Juice-64-fl-oz/555666777")["name"], "Grape juice")
        self.assertIsNone(self.a.usuals.add("", "10450114"))
        status, state = assistant.shop_change(self.a.shopping, self.a.usuals, {"op": "add_usual", "name": "", "link": ""})
        self.assertEqual(status, 400)

    def test_the_cart_link_has_only_items_with_a_product_number(self):
        u = self.a.usuals
        self.assertEqual(u.cart_url(), "")
        u.add("Milk", "https://www.walmart.com/ip/Milk/10450114", 2)
        u.add("Eggs", "", 1)
        u.add("Challah", "https://www.walmart.com/ip/Challah/555666777")
        self.assertEqual(u.cart_url(), "https://www.walmart.com/sc/cart/addToCart?items=10450114_2,555666777")
        u.add("milk", "", 3)  # the same item again: new amount, link kept
        self.assertEqual([(i["name"], i["qty"], i["item_id"]) for i in u.items()][0], ("Milk", 3, "10450114"))
        self.assertIsNone(u.add("  "))
        self.assertTrue(u.remove(u.items()[0]["id"]))
        self.assertFalse(u.remove("nope"))
        self.assertEqual(u.cart_url(), "https://www.walmart.com/sc/cart/addToCart?items=555666777")

    def test_send_the_cart_to_a_phone(self):
        self.answers = [tool("send_to_phone", {"what": "cart"}), text("Set up your usual items first.")]
        out = self.ask("reorder from walmart")[1]
        self.assertEqual(out["actions"], [{"type": "show_code", "path": "/shop", "title": "Set up your usual items"}])
        self.a.usuals.add("Milk", "10450114", 2)
        self.a.usuals.add("Eggs")
        self.answers = [tool("send_to_phone", {"what": "cart"}), text("Scan the code to open your cart.")]
        out = self.ask("reorder from walmart")[1]
        self.assertEqual(out["actions"], [{"type": "show_code", "url": "https://www.walmart.com/sc/cart/addToCart?items=10450114_2",
                                           "title": "Walmart cart"}])
        self.assertIn("Left out, no product link yet: Eggs.", self.result()["content"])
        self.assertIn("Usual Walmart items: 2 x Milk; Eggs (no product link yet).", self.sent[-1]["system"])
        self.answers = [tool("send_to_phone", {"what": "list"}), text("Scan the code.")]
        self.assertEqual(self.ask("send the list to my phone")[1]["actions"], [{"type": "show_code", "path": "/shop", "title": "Shopping list"}])

    def test_usuals_onto_the_shopping_list(self):
        self.answers = [tool("add_usuals_to_shopping_list", {}), text("There are none.")]
        self.ask("add the usuals")
        self.assertEqual(self.result()["content"], "No usual items are set up yet.")
        self.a.usuals.add("Milk", "", 2)
        self.a.usuals.add("Eggs")
        self.answers = [tool("add_usuals_to_shopping_list", {}), text("Added.")]
        self.ask("add the usuals")
        self.assertEqual([i["text"] for i in self.a.shopping.items()], ["2 x Milk", "Eggs"])

    def test_changes_from_the_phones_page(self):
        change = lambda body: assistant.shop_change(self.a.shopping, self.a.usuals, body, forward=self.forward)
        status, state = change({"op": "add_item", "text": " Paper   towels "})
        self.assertEqual((status, state["items"], self.forwarded), (200, ["Paper towels"], [["Paper towels"]]))
        self.assertEqual(change({"op": "add_item", "text": ""})[0], 400)
        self.a.shopping.add(["paper"])
        self.assertEqual(change({"op": "remove_item", "text": "paper"})[1]["items"], ["Paper towels"])  # the exact item only
        status, state = change({"op": "add_usual", "name": "Milk", "link": "https://www.walmart.com/ip/Milk/10450114", "qty": 2})
        self.assertEqual(state["cart_url"], "https://www.walmart.com/sc/cart/addToCart?items=10450114_2")
        status, state = change({"op": "add_usual", "name": "Eggs", "link": "https://www.target.com/p/eggs"})
        self.assertEqual(status, 400)
        self.assertIn("Walmart product link", state["error"])
        self.assertEqual(change({"op": "add_usual", "name": "", "link": ""})[0], 400)
        status, state = change({"op": "remove_usual", "id": self.a.usuals.items()[0]["id"]})
        self.assertEqual((state["usuals"], state["cart_url"]), ([], ""))
        for bad in (None, [], {"op": "format_disk"}, {}):
            self.assertEqual(change(bad)[0], 400)

    def test_a_damaged_usuals_file_is_an_empty_list(self):
        with open(self.a.usuals.path, "w", encoding="utf-8") as f:
            f.write('{"items": [{"id": "a", "name": "Milk", "item_id": "<script>", "qty": 99}, {"name": "no id"}, 7]}')
        self.assertEqual(self.a.usuals.items(), [{"id": "a", "name": "Milk", "item_id": "", "qty": 1}])
        with open(self.a.usuals.path, "w", encoding="utf-8") as f:
            f.write("nonsense")
        self.assertEqual(self.a.usuals.items(), [])


class Home(Case):
    HOME = {"devices": [{"name": "Ceiling lights", "room": "Kitchen", "kind": "light", "state": "on, 80%"},
                        {"name": "Lamp", "room": "Den", "kind": "light", "state": "off"},
                        {"name": "Lamp", "room": "Bedroom", "kind": "light", "state": "off"},
                        {"name": "Thermostat", "room": "Hallway", "kind": "thermostat", "state": "68 F, set to 70"},
                        {"name": "Front door", "room": "Hallway", "kind": "lock", "state": "unlocked"},
                        {"name": "Garage", "room": "Garage", "kind": "garage door", "state": "open"},
                        {"name": "Toaster", "room": "Kitchen", "kind": "rocket", "state": "?"}, "junk"],
            "scenes": ["Good Night", "", 7, "Movie time"]}

    def run_tool(self, name, args, home=HOME):
        self.answers = [tool(name, args), text("Okay.")]
        out = self.ask("home", **({"home": home} if home is not None else {}))[1]
        return out["actions"], self.sent[-1]["messages"][2]["content"][0]

    def test_devices_and_scenes_reach_claude(self):
        self.answers = [text("It's unlocked.")]
        self.ask("is the front door locked", home=self.HOME)
        system = self.sent[0]["system"]
        self.assertIn("  Kitchen: Ceiling lights (light, on, 80%).", system)
        self.assertIn("  Hallway: Thermostat (thermostat, 68 F, set to 70); Front door (lock, unlocked).", system)
        self.assertIn("Home scenes: Good Night; Movie time.", system)
        self.assertNotIn("Toaster", system)
        self.answers = [text("x")]
        self.ask("hello")
        self.assertIn("home control isn't switched on", self.sent[-1]["system"])

    def test_switching_dimming_and_the_thermostat(self):
        self.assertEqual(self.run_tool("home_set", {"device": "ceiling lights", "action": "off"})[0],
                         [{"type": "home_set", "device": "Ceiling lights", "room": "Kitchen", "action": "off"}])
        self.assertEqual(self.run_tool("home_set", {"device": "Ceiling lights", "room": "kitchen", "action": "brightness", "value": 30.4})[0][0]["value"], 30)
        self.assertEqual(self.run_tool("home_set", {"device": "Thermostat", "action": "temperature", "value": 70})[0][0],
                         {"type": "home_set", "device": "Thermostat", "room": "Hallway", "action": "temperature", "value": 70})

    def test_what_is_refused(self):
        for args, why in (({"device": "Lamp", "action": "on"}, "More than one"),
                          ({"device": "Chandelier", "action": "on"}, "No device has that name"),
                          ({"device": "Thermostat", "action": "on"}, "doesn't apply"),
                          ({"device": "Thermostat", "action": "temperature", "value": 120}, "from 50 to 90"),
                          ({"device": "Ceiling lights", "action": "brightness"}, "from 0 to 100"),
                          ({"device": "Front door", "action": "unlock"}, "Unlocking and opening"),
                          ({"device": "Garage", "action": "open"}, "Unlocking and opening"),
                          ({"device": "Front door", "action": "off"}, "doesn't apply")):
            actions, result = self.run_tool("home_set", args)
            self.assertEqual(actions, [], args)
            self.assertTrue(result["is_error"])
            self.assertIn(why, result["content"])
        self.assertEqual(self.run_tool("home_set", {"device": "Lamp", "room": "Den", "action": "on"})[0][0]["room"], "Den")

    def test_locking_and_closing_are_allowed(self):
        self.assertEqual(self.run_tool("home_set", {"device": "Front door", "action": "lock"})[0][0]["action"], "lock")
        self.assertEqual(self.run_tool("home_set", {"device": "Garage", "action": "close"})[0][0]["action"], "close")

    def test_scenes(self):
        self.assertEqual(self.run_tool("home_scene", {"name": "good night"})[0], [{"type": "home_scene", "name": "Good Night"}])
        actions, result = self.run_tool("home_scene", {"name": "Party"})
        self.assertEqual(actions, [])
        self.assertIn("Good Night; Movie time", result["content"])

    def test_without_home_control_the_tools_say_so(self):
        actions, result = self.run_tool("home_set", {"device": "Lamp", "action": "on"}, home=None)
        self.assertEqual(actions, [])
        self.assertIn("isn't switched on", result["content"])


class RemindersAnnouncementsRadio(Case):
    def run_tool(self, name, args, **body):
        self.answers = [tool(name, args), text("Okay.")]
        out = self.ask("x", **body)[1]
        return out["actions"], self.sent[-1]["messages"][2]["content"][0]

    def test_a_reminder_becomes_an_action(self):
        actions, result = self.run_tool("set_reminder", {"when": "2026-11-12T16:00", "text": " take the challah  out "})
        self.assertEqual(actions, [{"type": "set_reminder", "when": "2026-11-12T16:00", "text": "take the challah out", "repeat": "none"}])
        self.assertIn("Set for Thursday November 12 at 4:00 PM.", result["content"])
        actions, result = self.run_tool("set_reminder", {"when": "2026-11-13T07:00", "text": "wake up", "repeat": "weekdays"})
        self.assertEqual(actions[0]["repeat"], "weekdays")

    def test_bad_reminders(self):
        for args in ({"when": "2026-11-12T08:00", "text": "too late"},          # the clock says 9:00
                     {"when": "tomorrow at 4", "text": "x"}, {"when": "2026-11-13T07:00", "text": ""},
                     {"when": "2028-11-13T07:00", "text": "too far"}, {"text": "no time"}):
            actions, result = self.run_tool("set_reminder", args)
            self.assertEqual(actions, [], args)
            self.assertTrue(result["is_error"])
        self.assertEqual(self.run_tool("set_reminder", {"when": "2026-11-12T08:00", "text": "daily", "repeat": "daily"})[0][0]["repeat"], "daily")

    def test_reminders_reach_claude_and_can_be_cancelled(self):
        self.answers = [text("One.")]
        self.ask("what reminders", reminders=[{"text": "challah", "when": "2026-11-12T16:00:00", "repeat": "none"},
                                               {"text": "wake up", "when": "2026-11-13T07:00", "repeat": "weekdays"}, {"text": ""}])
        self.assertIn("Reminders: challah at 2026-11-12 16:00; wake up at 2026-11-13 07:00, weekdays.", self.sent[0]["system"])
        self.assertEqual(self.run_tool("cancel_reminder", {"text": "challah"})[0], [{"type": "cancel_reminder", "text": "challah"}])

    def test_an_announcement_reaches_the_other_screens_once_and_expires(self):
        actions, result = self.run_tool("announce", {"message": "Dinner is ready."}, screen="Kitchen iPad")
        self.assertEqual(actions, [])
        got = self.a.announcements.since(0)
        self.assertEqual(got, {"ok": True, "last": 1, "items": [{"id": 1, "text": "Dinner is ready.", "from": "Kitchen iPad"}]})
        self.assertEqual(self.a.announcements.since(1)["items"], [])
        self.clock = datetime(2026, 11, 12, 9, 3)
        self.assertEqual(self.a.announcements.since(0), {"ok": True, "last": 1, "items": []})
        self.assertTrue(self.run_tool("announce", {"message": " "})[1]["is_error"])

    def test_an_announcement_also_goes_to_the_phones_when_that_is_set_up(self):
        sent = []
        self.a.push = lambda text: sent.append(text)
        _, result = self.run_tool("announce", {"message": "Dinner is ready."})
        self.assertEqual(sent, ["Dinner is ready."])
        self.assertIn("phones and tablets", result["content"])
        self.a.push = lambda text: False
        self.assertNotIn("phones", self.run_tool("announce", {"message": "Bedtime."})[1]["content"])
        def broken(text): raise OSError("no network")
        self.a.push = broken
        self.assertNotIn("phones", self.run_tool("announce", {"message": "Bedtime."})[1]["content"])
        self.assertEqual(self.a.announcements.since(0)["last"], 3)

    def test_radio(self):
        self.assertEqual(self.run_tool("play_radio", {"station": "WNYC"})[0], [{"type": "play_radio", "station": "WNYC"}])
        self.assertTrue(self.run_tool("play_radio", {"station": ""})[1]["is_error"])


class FakeBrowser:
    """Stands in for Chrome: remembers how it was started and reports the tabs it is told to."""

    def __init__(self, pages):
        self.pages, self.started, self.closed, self.now = list(pages), [], False, 0.0

    def popen(self, args, **extra):
        self.started.append((args, extra))
        return self

    def tabs(self, port):
        url = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        return [] if url is None else [{"type": "page", "id": "T1", "url": url}]

    def sleep(self, seconds): self.now += seconds
    def clock(self): return self.now
    def wait(self, timeout=None): return 0
    def terminate(self): self.closed = True


class WalmartCartTests(Case):
    CART = "https://www.walmart.com/sc/cart/addToCart?items=10450114_2"

    def cart(self, pages, signed_in=True, find=lambda: "/usr/bin/chrome"):
        self.browser = FakeBrowser(pages)
        w = walmart.WalmartCart(os.path.join(self.dir.name, "profile"), os.path.join(self.dir.name, "walmart.json"),
                                log=self.logged.append, find=find, popen=self.browser.popen, tabs=self.browser.tabs,
                                sleep=self.browser.sleep, clock=self.browser.clock)
        if signed_in:
            w.set_signed_in(True)
        return w

    def test_the_link_is_opened_in_its_own_profile_and_the_cart_is_reached(self):
        w = self.cart([None, "https://www.walmart.com/sc/cart/addToCart?items=10450114_2", "https://www.walmart.com/shoppingcart"])
        with mock.patch.object(walmart.urllib.request, "urlopen", side_effect=OSError):
            self.assertEqual(w.add(self.CART), (True, ""))
        args = self.browser.started[0][0]
        self.assertEqual(args[0], "/usr/bin/chrome")
        self.assertIn("--user-data-dir=" + os.path.join(self.dir.name, "profile"), args)
        self.assertEqual(args[-1], self.CART)
        self.assertFalse(any("headless" in a for a in args))

    def test_what_stops_it(self):
        self.assertEqual(self.cart(["x"], signed_in=False).add(self.CART), (False, "not_signed_in"))
        self.assertEqual(self.browser.started, [])
        self.assertEqual(self.cart(["x"], find=lambda: None).add(self.CART), (False, "no_browser"))
        with mock.patch.object(walmart.urllib.request, "urlopen", side_effect=OSError):
            self.assertEqual(self.cart(["https://www.walmart.com/blocked?url=x"]).add(self.CART), (False, "blocked"))
            self.assertEqual(self.cart(["https://www.walmart.com/"]).add(self.CART, wait=5), (False, "timeout"))
            w = self.cart(["https://www.walmart.com/account/login?vid=oaoh"])
            self.assertEqual(w.add(self.CART), (False, "signin"))
            self.assertFalse(w.signed_in(), "a sign-in page means the sign-in was lost")

    def test_the_voice_tool_fills_the_cart_or_falls_back_to_the_code(self):
        self.a.usuals.add("Milk", "10450114", 2)
        self.a.usuals.add("Eggs")
        self.a.usuals.add("Challah", "555666777")
        self.a.walmart = mock.Mock()
        self.a.walmart.add.return_value = (True, "")
        self.answers = [tool("walmart_cart", {}), text("Your usual items are in the cart.")]
        out = self.ask("reorder from walmart")[1]
        self.a.walmart.add.assert_called_once_with("https://www.walmart.com/sc/cart/addToCart?items=10450114_2,555666777")
        self.assertEqual(out["actions"], [])
        result = self.sent[-1]["messages"][2]["content"][0]["content"]
        self.assertIn("In the Walmart cart now: 2 x Milk, Challah.", result)
        self.assertIn("Left out, no product link yet: Eggs.", result)

        self.a.walmart.add.reset_mock()
        self.answers = [tool("walmart_cart", {"items": ["milk"]}), text("Milk is in the cart.")]
        self.ask("add milk to my walmart cart")
        self.a.walmart.add.assert_called_once_with("https://www.walmart.com/sc/cart/addToCart?items=10450114_2")

        self.answers = [tool("walmart_cart", {"items": ["caviar"]}), text("That isn't a usual item.")]
        self.ask("add caviar to my walmart cart")
        self.assertTrue(self.sent[-1]["messages"][2]["content"][0]["is_error"])

        self.a.walmart.add.return_value = (False, "not_signed_in")
        self.answers = [tool("walmart_cart", {}), text("Walmart isn't signed in yet.")]
        out = self.ask("reorder from walmart")[1]
        self.assertEqual(out["actions"], [{"type": "show_code", "title": "Walmart cart",
                                           "url": "https://www.walmart.com/sc/cart/addToCart?items=10450114_2,555666777"}])
        self.assertIn("Someone signs in once", self.sent[-1]["messages"][2]["content"][0]["content"])

    def test_the_phone_page_can_sign_in_and_fill_the_cart(self):
        w = mock.Mock()
        w.signed_in.return_value = False
        w.open_sign_in.return_value = ""
        change = lambda body: assistant.shop_change(self.a.shopping, self.a.usuals, body, walmart=w)
        self.assertEqual(change({"op": "walmart_open_sign_in"})[0], 200)
        w.open_sign_in.assert_called_once()
        change({"op": "walmart_signed_in"})
        w.set_signed_in.assert_called_with(True)
        self.assertEqual(change({"op": "walmart_fill"})[0], 400)          # no usual item has a link
        self.a.usuals.add("Milk", "10450114")
        w.add.return_value = (True, "")
        status, state = change({"op": "walmart_fill"})
        self.assertEqual(status, 200)
        self.assertIn("in your Walmart cart", state["note"])
        w.add.return_value = (False, "blocked")
        self.assertEqual(change({"op": "walmart_fill"})[0], 502)
        self.assertEqual(assistant.shop_change(self.a.shopping, self.a.usuals, {"op": "walmart_fill"})[0], 400)

    def test_tab_reading(self):
        self.assertEqual(walmart.where([{"url": "https://www.walmart.com/cart"}]), "cart")
        self.assertEqual(walmart.where([{"url": "about:blank"}, {"url": "https://www.walmart.com/shoppingcart?x=1"}]), "cart")
        self.assertEqual(walmart.where([]), "other")
        self.assertEqual(walmart.read_tabs(1), [])


class Spending(Case):
    def test_every_answer_is_counted(self):
        self.answers = [tool("set_timer", {"seconds": 60}, tokens_in=2000, tokens_out=100),
                        text("Done.", tokens_in=2100, tokens_out=20)]
        self.ask("one minute timer")
        self.assertEqual(self.spent(), {"month": "2026-11", "usd": round((4100 * 0.10 + 120 * 0.50) / 1e6, 8),
                                        "day": "2026-11-12", "requests": 2})

    def test_cost(self):
        self.assertAlmostEqual(assistant.cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000}), 0.60)
        self.assertAlmostEqual(assistant.cost_usd({"input_tokens": 10, "cache_creation_input_tokens": 20,
                                                   "cache_read_input_tokens": 70, "output_tokens": 0}), 100 * 0.10 / 1e6)
        self.assertEqual(assistant.cost_usd(None), 0)
        self.assertEqual(assistant.cost_usd({"input_tokens": "9", "output_tokens": -4}), 0)

    def test_the_monthly_limit_stops_it(self):
        self.settings["monthly_usd"] = 0.001
        self.answers = [text("One.", tokens_in=6000, tokens_out=900)]  # $0.00105
        self.assertEqual(self.ask("first")[0], 200)
        status, out = self.ask("second")
        self.assertEqual((status, out["error"], out["say"]), (429, "budget_month", "I've reached this month's spending limit."))
        self.assertEqual(len(self.sent), 1)

    def test_the_limit_is_checked_between_tool_steps(self):
        self.settings["monthly_usd"] = 0.0005
        self.answers = [tool("set_timer", {"seconds": 60}, tokens_in=5000, tokens_out=100), text("never asked")]
        status, out = self.ask("timer")
        self.assertEqual((status, len(self.sent)), (429, 1))
        self.assertEqual(out["actions"], [{"type": "set_timer", "seconds": 60, "label": ""}])  # the timer still starts

    def test_a_new_month_starts_again_and_a_new_day_resets_the_count(self):
        self.settings.update(monthly_usd=0.001, daily_requests=1)
        self.answers = [text("One.", tokens_in=100, tokens_out=10), text("Two."), text("Three.", tokens_in=20000)]
        self.ask("first")
        self.assertEqual(self.ask("again")[1]["error"], "budget_day")
        self.clock = datetime(2026, 11, 13, 9, 0)
        self.assertEqual(self.ask("next day")[0], 200)
        self.clock = datetime(2026, 11, 14, 9, 0)
        self.assertEqual(self.ask("third day")[0], 200)
        self.clock = datetime(2026, 11, 15, 9, 0)
        self.assertEqual(self.ask("over the month")[1]["error"], "budget_month")
        self.clock = datetime(2026, 12, 1, 0, 1)
        self.answers = [text("December.")]
        self.assertEqual(self.ask("new month")[1]["say"], "December.")
        self.assertEqual(self.spent()["month"], "2026-12")

    def test_a_spending_record_that_cannot_be_read_stops_it(self):
        for bad in ("{not json", '{"month": "2026-11"}', '{"month": "2026-11", "usd": -1, "day": "2026-11-12", "requests": 0}',
                    '{"month": "2026-11", "usd": "0", "day": "2026-11-12", "requests": 0}', "[]"):
            with open(self.budget_file, "w", encoding="utf-8") as f:
                f.write(bad)
            status, out = self.ask("hello")
            self.assertEqual((status, out["error"]), (429, "budget_unreadable"), bad)
        self.assertEqual(self.sent, [])

    def test_a_record_that_cannot_be_saved_stops_it(self):
        self.answers = [tool("set_timer", {"seconds": 60}), text("never asked")]
        with mock.patch.object(assistant, "_write_atomic", side_effect=OSError("disk full")):
            status, out = self.ask("timer")
        self.assertEqual((status, out["error"], len(self.sent)), (429, "budget_unreadable", 1))


class Route(HouseholdCase):
    """The real request handler, with Claude replaced and every file in a temp folder."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.sent = []
        a = server.ASSISTANT
        for target, name, value in (
                (a, "budget", assistant.Budget(os.path.join(self.dir.name, "b.json"))),
                (a, "shopping", assistant.ShoppingList(os.path.join(self.dir.name, "s.json"))),
                (a, "usuals", assistant.Usuals(os.path.join(self.dir.name, "u.json"))),
                (a, "walmart", walmart.WalmartCart(os.path.join(self.dir.name, "wp"), os.path.join(self.dir.name, "w.json"),
                                                   find=lambda: None)),
                (a, "post", self.post)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(server.CONFIG, {"anthropic_api_key": " sk-test ", "assistant_monthly_usd": 5.0,
                                            "assistant_daily_requests": 300, "menuapp_grocery_url": ""})
        p.start()
        self.addCleanup(p.stop)
        self.calendar = [{"category": "candles", "date": "2026-11-13T16:17:00-05:00", "title": "Candle lighting"},
                         {"category": "havdalah", "date": "2026-11-14T17:19:00-05:00", "title": "Havdalah"}]
        p = mock.patch.object(server.store, "get", lambda key: {
            "calendar": {"items": self.calendar},
            "weather": {"current": {"temp": 48, "feels": 44, "wind_mph": 9}, "today": {"hi": 52, "lo": 39, "precip": 20},
                        "daily": [{"date": "2026-11-13", "hi": 50, "lo": 38, "precip": 10}]}}.get(key))
        p.start()
        self.addCleanup(p.stop)
        self.at("2026-11-12T09:05:00-05:00")

    def at(self, when):
        p = mock.patch.object(server, "now", lambda: server.parse_dt(when))
        p.start()
        self.addCleanup(p.stop)

    def post(self, url, headers, body):
        self.sent.append((headers, body))
        return text("Candle lighting is at four seventeen.")

    def call(self, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_an_answer_with_the_displays_facts(self):
        status, out = self.call("/api/assistant", {"text": "when is candle lighting"})
        self.assertEqual((status, out["say"]), (200, "Candle lighting is at four seventeen."))
        headers, body = self.sent[0]
        self.assertEqual(headers["x-api-key"], "sk-test")
        system = body["system"]
        self.assertIn("It is Thursday, November 12, 2026, 9:05 AM in Teaneck.", system)
        self.assertIn("Weather: 48 F now, feels like 44, wind 9 mph; today's high 52, low 39, 20% chance of precipitation.", system)
        self.assertIn("Candle lighting: Friday November 13, 4:17 PM.", system)
        self.assertIn("Havdalah: Saturday November 14, 5:19 PM.", system)

    def test_nothing_is_asked_on_shabbat(self):
        for when in ("2026-11-13T16:17:00-05:00", "2026-11-14T12:00:00-05:00"):
            self.at(when)
            self.assertEqual(self.call("/api/assistant", {"text": "hello"}), (403, {"ok": False, "error": "holy", "say": ""}))
        self.at("2026-11-14T17:19:00-05:00")
        self.assertEqual(self.call("/api/assistant", {"text": "shavua tov"})[0], 200)
        self.assertEqual(len(self.sent), 1)

    def test_bad_requests_and_the_list(self):
        self.assertEqual(self.call("/api/assistant", raw=b"{not json")[0], 400)
        self.assertEqual(self.call("/api/assistant", raw=b"x" * 70000)[0], 413)
        self.assertEqual(self.call("/api/assistant", {"text": ""})[0], 400)
        server.ASSISTANT.shopping.add(["milk"])
        self.assertEqual(self.call("/api/shopping"), (200, {"ok": True, "items": ["milk"]}))

    def test_shopping_items_go_to_menuapp_once_its_address_is_set(self):
        self.assertIs(server._forward_shopping(["milk"]), False)
        got = []

        class Reply:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"{}"

        def urlopen(req, timeout=None):
            got.append((req.full_url, json.loads(req.data), req.get_method()))
            return Reply()
        server.CONFIG["menuapp_grocery_url"] = "https://recipes.example/grocery-inbox/token"
        with mock.patch.object(server.urllib.request, "urlopen", urlopen):
            self.assertIsNone(server._forward_shopping(["milk", "eggs"]))
        self.assertEqual(got, [("https://recipes.example/grocery-inbox/token", {"items": ["milk", "eggs"], "source": "display"}, "POST")])

    def test_zmanim_hebrew_date_and_the_agenda_only_for_a_screen_that_shows_it(self):
        extra = {"hebdate": {"english": "3 Kislev 5787", "after_sunset": False},
                 "zmanim": {"date": "2026-11-12", "times": {"shema": "2026-11-12T09:11:00-05:00", "sunset": "2026-11-12T16:39:00-05:00", "odd": "x"}},
                 "agenda": {"items": [{"title": "Dentist", "start": "2026-11-13T15:00:00-05:00", "all_day": False},
                                      {"title": "Trip", "start": "2026-11-15T00:00:00-05:00", "all_day": True}]}}
        base = server.store.get
        with mock.patch.object(server.store, "get", lambda key: extra.get(key) or base(key)):
            plain = server.assistant_facts(screen="iPad")
            self.assertIn("Hebrew date: 3 Kislev 5787.", plain)
            self.assertIn("Zmanim for 2026-11-12: Latest Shema (Gra) 9:11 AM; Sunset 4:39 PM.", plain)
            self.assertNotIn("Dentist", plain)
            self.assertNotIn("Dentist", server.assistant_facts())
            h = server.household()
            h["screens"]["Office"] = {"rotation": [{"scene": "agenda", "seconds": 20, "on": True}]}
            server.save_household(h)
            self.assertIn("Agenda: Fri Nov 13 3:00 PM Dentist; Sun Nov 15 all day Trip.", server.assistant_facts(screen="Office"))

    def test_announcements_for_the_screens(self):
        server.ASSISTANT.announcements.add("Dinner is ready.", "iPad")
        last = server.ASSISTANT.announcements.last
        status, got = self.call(f"/api/announcements?since={last - 1}")
        self.assertEqual((status, got["items"]), (200, [{"id": last, "text": "Dinner is ready.", "from": "iPad"}]))
        self.assertEqual(self.call(f"/api/announcements?since={last}")[1]["items"], [])
        self.assertEqual(self.call("/api/announcements?since=nonsense")[0], 200)
        self.at("2026-11-14T12:00:00-05:00")
        self.assertEqual(self.call("/api/announcements?since=0")[1]["items"], [])

    def test_the_shopping_list_is_in_every_screens_state(self):
        server.ASSISTANT.shopping.add(["milk", "eggs"])
        with urllib.request.urlopen(self.base + "/api/state?screen=iPad&preview=1", timeout=5) as r:
            state = json.loads(r.read())
        self.assertEqual(state["data"]["shopping"], {"items": ["milk", "eggs"]})
        self.assertIn({"scene": "shopping", "label": "Shopping list"}, server.scene_catalog())

    def test_the_push_address(self):
        self.assertIs(server._push_announcement("x"), False)
        got = []

        class Reply:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"{}"

        def urlopen(req, timeout=None):
            got.append((req.full_url, req.data, req.get_header("Title")))
            return Reply()
        server.CONFIG["announce_push_url"] = "https://ntfy.sh/a-long-secret-name"
        with mock.patch.object(server.urllib.request, "urlopen", urlopen):
            self.assertIsNone(server._push_announcement("Dinner is ready."))
        self.assertEqual(got, [("https://ntfy.sh/a-long-secret-name", b"Dinner is ready.", "Kitchen display")])
        server.CONFIG["announce_push_url"] = "http://not-https.example/x"
        self.assertIs(server._push_announcement("x"), False)

    def test_the_phones_shopping_page(self):
        with urllib.request.urlopen(self.base + "/shop", timeout=5) as r:
            page = r.read()
            self.assertIn("text/html", r.headers["Content-Type"])
        self.assertIn(b"Usual Walmart items", page)
        self.assertEqual(self.call("/api/shop"), (200, {"ok": True, "items": [], "usuals": [], "cart_url": "",
                                                        "walmart": {"available": True, "signed_in": False}}))
        status, state = self.call("/api/shop", {"op": "add_usual", "name": "Milk", "link": "10450114", "qty": 1})
        self.assertEqual((status, state["cart_url"]), (200, "https://www.walmart.com/sc/cart/addToCart?items=10450114"))
        self.assertEqual(self.call("/api/shop", {"op": "add_item", "text": "eggs"})[1]["items"], ["eggs"])
        self.assertEqual(self.call("/api/shop", raw=b"{nope")[0], 400)

    def test_the_key_never_reaches_a_screen(self):
        with urllib.request.urlopen(self.base + "/api/state", timeout=5) as r:
            self.assertNotIn(b"sk-test", r.read())


if __name__ == "__main__":
    unittest.main()
