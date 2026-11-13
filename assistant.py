"""
Shabbat Display - the voice assistant behind the iPad app.

The iPad hears a request, turns it into text and posts it to /api/assistant.
This module asks Claude, runs the tools Claude calls (the shopping list here,
timers on the iPad) and answers with a sentence to speak.

Every Claude request is counted in dollars against a monthly limit
(assistant-budget.json), and the limit is checked before each one. A budget
file that can't be read stops the assistant rather than starting from zero.

Standard library only. The request to Claude is plain HTTPS, so there is
nothing to pip install.
"""

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = "claude-haiku-5-5"
# Dollars per million tokens for MODEL (prompts up to 100K tokens; ours are a few thousand).
PRICE_IN, PRICE_OUT = 0.10, 0.50
MAX_TOKENS = 600          # a spoken answer is a sentence or two
MAX_STEPS = 4             # Claude requests per spoken request (tool calls take extra ones)
MAX_TEXT = 500
MAX_ITEMS = 200
MAX_ITEM_LEN = 80

SYSTEM = """You are the voice of a kitchen display in a family home. Someone spoke to it; \
their words reached you through speech recognition, so expect small mishearings.

Your answer is read aloud. Keep it to one or two short sentences in plain words: no lists, \
no markdown, no emoji, no symbols a voice would stumble on. Say numbers the way people say them.

Use a tool whenever the request is something a tool does, and only say a thing is done after \
the tool has answered. You can keep a shopping list, set kitchen timers, play music from \
Apple Music on the display, and put a code on the display that a phone scans to open the \
shopping list or a Walmart cart of the family's usual items. You cannot place an order, pay, \
or send messages; checkout always happens on the phone. When the facts below list home \
devices, you can also switch them, dim lights, set thermostats, move shades and run scenes with \
the home tools, using the exact device, room and scene names listed. You can lock a door or \
close a garage door, but never unlock or open one: tell them to use the Home app for that. Say so briefly \
if asked. When you start music, just say what you are putting on; the display itself says so \
if it can't find it. You have no internet search: answer from what you know and from the facts below, and say so \
when you don't know.

You can set reminders and alarms for a time of day (set_reminder), announce a message on the \
family's other displays (announce), and play live radio stations (play_radio; music_control \
also pauses or stops the radio). Work out dates and times from the current time in the facts. \
If they say good morning or ask for a briefing, give a short one from the facts: the weather, \
today's agenda if listed, and candle lighting if it is Friday or the eve of a holiday.

If the words look like something the display overheard rather than a request to it, answer \
with an empty reply."""

TOOLS = [
    {"name": "set_timer",
     "description": "Start a countdown timer on the kitchen display. It rings and says its name when it ends.",
     "input_schema": {"type": "object", "properties": {
         "seconds": {"type": "integer", "description": "Length in seconds, 1 to 86400."},
         "label": {"type": "string", "description": "A short name to say when it rings, such as 'pasta'. Empty if none was given."}},
         "required": ["seconds"]}},
    {"name": "cancel_timer",
     "description": "Stop a running or ringing timer. Give its label, or 'all' for every timer.",
     "input_schema": {"type": "object", "properties": {
         "label": {"type": "string", "description": "The timer's label, or 'all'."}},
         "required": ["label"]}},
    {"name": "add_to_shopping_list",
     "description": "Add items to the family's shopping list. One entry per item, with any amount in the entry ('2 dozen eggs').",
     "input_schema": {"type": "object", "properties": {
         "items": {"type": "array", "items": {"type": "string"}}},
         "required": ["items"]}},
    {"name": "play_music",
     "description": "Play music on the display from Apple Music. Replaces whatever is playing.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "What to search Apple Music for: a song, album, artist, playlist or kind of music, in the user's words ('Shlomo Carlebach', 'quiet jazz', 'Abbey Road')."},
         "kind": {"type": "string", "enum": ["any", "song", "album", "artist", "playlist", "station"],
                  "description": "What the query names, when the user made that clear; otherwise 'any'."}},
         "required": ["query"]}},
    {"name": "music_control",
     "description": "Control the music playing on the display.",
     "input_schema": {"type": "object", "properties": {
         "command": {"type": "string", "enum": ["pause", "resume", "next", "previous", "stop"]}},
         "required": ["command"]}},
    {"name": "set_reminder",
     "description": "Remind the family at a time of day: the display chimes and says the text then. Also for alarms ('wake me at 7').",
     "input_schema": {"type": "object", "properties": {
         "when": {"type": "string", "description": "Local date and time, YYYY-MM-DDTHH:MM (24-hour). For a repeating reminder, its first time."},
         "text": {"type": "string", "description": "What to say, as a short phrase: 'take the challah out'."},
         "repeat": {"type": "string", "enum": ["none", "daily", "weekdays"], "description": "weekdays = Sunday to Thursday mornings plus Friday; never on Shabbat. Default none."}},
         "required": ["when", "text"]}},
    {"name": "cancel_reminder",
     "description": "Cancel a reminder by its text, or 'all'.",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "announce",
     "description": "Say a message on the family's other displays around the house, and show it on their screens.",
     "input_schema": {"type": "object", "properties": {
         "message": {"type": "string", "description": "The announcement, worded to be heard: 'Dinner is ready.'"}},
         "required": ["message"]}},
    {"name": "play_radio",
     "description": "Play a live radio station on the display, by its name or call letters ('WNYC', 'BBC World Service', 'Kol Israel').",
     "input_schema": {"type": "object", "properties": {"station": {"type": "string"}}, "required": ["station"]}},
    {"name": "home_set",
     "description": "Change one device in the home (Apple Home). Call it once per device; for 'all the kitchen lights', call it for each light listed in that room.",
     "input_schema": {"type": "object", "properties": {
         "device": {"type": "string", "description": "The device's name exactly as listed in the facts."},
         "room": {"type": "string", "description": "Its room exactly as listed, to tell apart devices with the same name."},
         "action": {"type": "string", "enum": ["on", "off", "brightness", "temperature", "position", "lock", "close"],
                    "description": "on/off for lights, switches, plugs and fans; brightness 0-100 for lights; temperature in Fahrenheit for a thermostat; position 0 (closed) to 100 (open) for shades; lock for a door lock; close for a garage door."},
         "value": {"type": "number", "description": "The number for brightness, temperature or position."}},
         "required": ["device", "action"]}},
    {"name": "home_scene",
     "description": "Run one of the home's scenes (Apple Home), by its exact listed name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "send_to_phone",
     "description": "Show a code on the display for a phone's camera. 'cart' opens Walmart with the family's usual items in the cart, ready for them to check out; 'list' opens the shopping list page, where items can be ticked off and the usual Walmart items are set up.",
     "input_schema": {"type": "object", "properties": {
         "what": {"type": "string", "enum": ["cart", "list"]}},
         "required": ["what"]}},
    {"name": "add_usuals_to_shopping_list",
     "description": "Copy the family's usual Walmart items onto the shopping list.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "remove_from_shopping_list",
     "description": "Take items off the shopping list. Use the items' names as they appear on the list.",
     "input_schema": {"type": "object", "properties": {
         "items": {"type": "array", "items": {"type": "string"}}},
         "required": ["items"]}},
]


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def post_json(url, headers, body, timeout=30):
    """POST to Claude. Returns the parsed answer, or raises ApiError (status 0: no answer)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("error", {}).get("message", "")
        except (ValueError, AttributeError, OSError):
            detail = ""
        raise ApiError(e.code, detail or str(e.reason))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ApiError(0, str(e))


def cost_usd(usage):
    """What one Claude answer cost. Cached tokens are counted at the full input price."""
    u = usage if isinstance(usage, dict) else {}

    def n(key):
        v = u.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0
    tokens_in = n("input_tokens") + n("cache_creation_input_tokens") + n("cache_read_input_tokens")
    return (tokens_in * PRICE_IN + n("output_tokens") * PRICE_OUT) / 1_000_000


def _write_atomic(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Budget:
    """This month's spending and today's request count, kept on disk."""

    def __init__(self, path, now=datetime.now):
        self.path, self.now = path, now
        self.lock = threading.Lock()

    def _read(self):
        """The stored figures brought to today, or None when the file can't be trusted."""
        today = self.now()
        month, day = today.strftime("%Y-%m"), today.strftime("%Y-%m-%d")
        fresh = {"month": month, "usd": 0.0, "day": day, "requests": 0}
        if not os.path.exists(self.path):
            return fresh
        try:
            with open(self.path, encoding="utf-8") as f:
                b = json.load(f)
            usd, requests = b["usd"], b["requests"]
            ok = (isinstance(b["month"], str) and isinstance(b["day"], str)
                  and isinstance(usd, (int, float)) and not isinstance(usd, bool) and usd >= 0
                  and isinstance(requests, int) and not isinstance(requests, bool) and requests >= 0)
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not ok:
            return None
        if b["month"] != month:
            return fresh
        return {"month": month, "usd": float(usd), "day": day, "requests": requests if b["day"] == day else 0}

    def status(self):
        with self.lock:
            return self._read()

    def allows(self, monthly_usd, daily_requests):
        """None when another request may go out, else why not: 'unreadable', 'month' or 'day'."""
        b = self.status()
        if b is None:
            return "unreadable"
        if b["usd"] >= monthly_usd:
            return "month"
        if b["requests"] >= daily_requests:
            return "day"
        return None

    def add(self, usd):
        """Record one request. False if it couldn't be saved (the caller then stops)."""
        with self.lock:
            b = self._read()
            if b is None:
                return False
            b["usd"] = round(b["usd"] + usd, 8)
            b["requests"] += 1
            try:
                _write_atomic(self.path, b)
            except OSError:
                return False
            return True


class ShoppingList:
    def __init__(self, path, now=datetime.now):
        self.path, self.now = path, now
        self.lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                items = json.load(f)["items"]
            return [i for i in items if isinstance(i, dict) and isinstance(i.get("text"), str)]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def items(self):
        with self.lock:
            return self._load()

    def add(self, texts):
        """Add what isn't already there. Returns (added, already_there)."""
        added, dup = [], []
        with self.lock:
            items = self._load()
            have = {i["text"].casefold() for i in items}
            for text in texts:
                if text.casefold() in have:
                    dup.append(text)
                elif len(items) < MAX_ITEMS:
                    items.append({"text": text, "added": self.now().isoformat(timespec="seconds"), "sent": False})
                    have.add(text.casefold())
                    added.append(text)
            if added:
                _write_atomic(self.path, {"items": items})
        return added, dup

    def remove(self, texts):
        """Remove by name (case ignored; a name that is part of an item's text also matches)."""
        removed = []
        with self.lock:
            items = self._load()
            for text in texts:
                want = text.casefold()
                hit = next((i for i in items if i["text"].casefold() == want), None) \
                    or next((i for i in items if want in i["text"].casefold()), None)
                if hit:
                    items.remove(hit)
                    removed.append(hit["text"])
            if removed:
                _write_atomic(self.path, {"items": items})
        return removed

    def remove_exact(self, text):
        with self.lock:
            items = self._load()
            kept = [i for i in items if i["text"].casefold() != text.casefold()]
            if len(kept) != len(items):
                _write_atomic(self.path, {"items": kept})

    def mark_sent(self, texts):
        with self.lock:
            items = self._load()
            names = {t.casefold() for t in texts}
            changed = False
            for i in items:
                if i["text"].casefold() in names and not i.get("sent"):
                    i["sent"] = changed = True
            if changed:
                _write_atomic(self.path, {"items": items})

    def unsent(self):
        return [i["text"] for i in self.items() if not i.get("sent")]


WALMART_CART = "https://www.walmart.com/sc/cart/addToCart?items="


def walmart_item_id(link):
    """The item number in a Walmart product link (.../ip/Name/123456789) or typed by itself; "" if none."""
    text = link.strip() if isinstance(link, str) else ""
    if text.isdigit():
        return text if 4 <= len(text) <= 15 else ""
    m = re.search(r"walmart\.com/ip/(?:[^/?#]+/)?(\d{4,15})(?:[/?#]|$)", text)
    return m.group(1) if m else ""


def walmart_item_name(link):
    """A readable name from a Walmart product link's own words (.../ip/Great-Value-Whole-Milk/123); "" if it has none."""
    m = re.search(r"walmart\.com/ip/([^/?#]+)/\d{4,15}(?:[/?#]|$)", link.strip() if isinstance(link, str) else "")
    if not m or m.group(1).isdigit():
        return ""
    return _clean_text(urllib.parse.unquote(m.group(1)).replace("-", " "), MAX_ITEM_LEN)


class Usuals:
    """The things the family buys again and again: [{id, name, item_id, qty}] in usuals.json.
    `item_id` is Walmart's number for the product ("" until a product link is given)."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                items = json.load(f)["items"]
        except (OSError, ValueError, KeyError, TypeError):
            return []
        out = []
        for i in items if isinstance(items, list) else []:
            if isinstance(i, dict) and isinstance(i.get("id"), str) and isinstance(i.get("name"), str):
                qty = i.get("qty")
                out.append({"id": i["id"], "name": i["name"],
                            "item_id": i["item_id"] if isinstance(i.get("item_id"), str) and i["item_id"].isdigit() else "",
                            "qty": qty if isinstance(qty, int) and not isinstance(qty, bool) and 1 <= qty <= 24 else 1})
        return out

    def items(self):
        with self.lock:
            return self._load()

    def add(self, name, link="", qty=1):
        """Add an item, or update the one with this name. Returns it, or None if there is no name."""
        name = _clean_text(name, MAX_ITEM_LEN) or walmart_item_name(link)
        if not name:
            return None
        qty = qty if isinstance(qty, int) and not isinstance(qty, bool) and 1 <= qty <= 24 else 1
        item_id = walmart_item_id(link)
        with self.lock:
            items = self._load()
            item = next((i for i in items if i["name"].casefold() == name.casefold()), None)
            if item:
                item.update(qty=qty, item_id=item_id or item["item_id"])
            elif len(items) < MAX_ITEMS:
                item = {"id": os.urandom(4).hex(), "name": name, "item_id": item_id, "qty": qty}
                items.append(item)
            else:
                return None
            _write_atomic(self.path, {"items": items})
            return item

    def remove(self, item_id):
        with self.lock:
            items = self._load()
            kept = [i for i in items if i["id"] != item_id]
            if len(kept) != len(items):
                _write_atomic(self.path, {"items": kept})
            return len(kept) != len(items)

    def cart_url(self):
        """Walmart's add-to-cart link for every usual item that has a product number; "" if none has."""
        parts = [i["item_id"] if i["qty"] == 1 else f"{i['item_id']}_{i['qty']}" for i in self.items() if i["item_id"]]
        return WALMART_CART + ",".join(parts) if parts else ""


def shop_state(shopping, usuals):
    """What the phone's shopping page shows."""
    return {"ok": True, "items": [i["text"] for i in shopping.items()], "usuals": usuals.items(), "cart_url": usuals.cart_url()}


def shop_change(shopping, usuals, body, forward=None):
    """One change from the shopping page. Returns (http status, dict)."""
    if not isinstance(body, dict):
        return 400, {"ok": False, "error": "That request couldn't be read."}
    op = body.get("op")
    try:
        if op == "add_item":
            items = _clean_items([body.get("text")])
            if not items:
                return 400, {"ok": False, "error": "Type an item first."}
            shopping.add(items)
            if forward:
                try:
                    pending = shopping.unsent()
                    if pending and forward(pending) is not False:
                        shopping.mark_sent(pending)
                except Exception:  # noqa: BLE001 - the item is saved here either way
                    pass
        elif op == "remove_item":
            shopping.remove_exact(_clean_text(body.get("text"), MAX_ITEM_LEN))
        elif op == "add_usual":
            link = body.get("link") if isinstance(body.get("link"), str) else ""
            if link.strip() and not walmart_item_id(link):
                return 400, {"ok": False, "error": "That doesn't look like a Walmart product link. Open the product on walmart.com and copy its link."}
            if not usuals.add(body.get("name"), link, body.get("qty")):
                return 400, {"ok": False, "error": "Give the item a name, or paste its Walmart product link."}
        elif op == "remove_usual":
            usuals.remove(body.get("id") if isinstance(body.get("id"), str) else "")
        else:
            return 400, {"ok": False, "error": "That request couldn't be read."}
    except OSError:
        return 500, {"ok": False, "error": "That couldn't be saved on the display computer."}
    return 200, shop_state(shopping, usuals)


def _clean_items(value):
    out = []
    for v in value if isinstance(value, list) else []:
        if isinstance(v, str):
            text = " ".join(v.split())[:MAX_ITEM_LEN]
            if text and text.casefold() not in {o.casefold() for o in out}:
                out.append(text)
    return out[:30]


def _clean_text(value, limit=MAX_TEXT):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _clean_timers(value):
    """The iPad's running timers: [{label, seconds_left, ringing}]."""
    out = []
    for t in value if isinstance(value, list) else []:
        if isinstance(t, dict) and isinstance(t.get("seconds_left"), (int, float)) and not isinstance(t.get("seconds_left"), bool):
            out.append({"label": _clean_text(t.get("label"), 40), "seconds_left": max(0, int(t["seconds_left"])),
                        "ringing": bool(t.get("ringing"))})
    return out[:10]


class Announcements:
    """Messages for every display, kept in memory for two minutes: long enough for each screen
    to fetch them once, short enough that a screen switched on later doesn't replay old ones."""
    KEEP = 120

    def __init__(self, now=datetime.now):
        self.now, self.lock, self.items, self.last = now, threading.Lock(), [], 0

    def add(self, text, origin=""):
        with self.lock:
            self.last += 1
            self.items.append({"id": self.last, "text": text, "from": origin, "at": self.now()})
            return self.last

    def since(self, last_seen):
        """Announcements newer than `last_seen` and still fresh, plus the newest id."""
        with self.lock:
            cutoff = self.now()
            self.items = [i for i in self.items if (cutoff - i["at"]).total_seconds() <= self.KEEP]
            return {"ok": True, "last": self.last,
                    "items": [{"id": i["id"], "text": i["text"], "from": i["from"]} for i in self.items if i["id"] > last_seen]}


def _clean_reminders(value):
    """The iPad's reminders: [{text, when, repeat}]."""
    out = []
    for r in value if isinstance(value, list) else []:
        if isinstance(r, dict) and _clean_text(r.get("text"), 120) and isinstance(r.get("when"), str):
            out.append({"text": _clean_text(r.get("text"), 120), "when": r["when"][:16],
                        "repeat": r.get("repeat") if r.get("repeat") in ("daily", "weekdays") else "none"})
    return out[:30]


HOME_KINDS = ("light", "switch", "plug", "fan", "thermostat", "shade", "lock", "garage door", "sensor")
HOME_ACTIONS = {"on": ("light", "switch", "plug", "fan"), "off": ("light", "switch", "plug", "fan"),
                "brightness": ("light",), "temperature": ("thermostat",), "position": ("shade",),
                "lock": ("lock",), "close": ("garage door",)}
HOME_RANGE = {"brightness": (0, 100), "temperature": (50, 90), "position": (0, 100)}


def _clean_home(value):
    """What the iPad sees in Apple Home: {devices: [{name, room, kind, state}], scenes: [name]}, or None."""
    if not isinstance(value, dict):
        return None
    devices = []
    for d in value.get("devices") if isinstance(value.get("devices"), list) else []:
        if isinstance(d, dict) and d.get("kind") in HOME_KINDS and _clean_text(d.get("name"), 60):
            devices.append({"name": _clean_text(d.get("name"), 60), "room": _clean_text(d.get("room"), 40),
                            "kind": d["kind"], "state": _clean_text(d.get("state"), 40)})
    scenes = [_clean_text(n, 60) for n in (value.get("scenes") if isinstance(value.get("scenes"), list) else [])]
    return {"devices": devices[:120], "scenes": [n for n in scenes if n][:60]}


def _clean_music(value):
    """What the iPad is playing: {playing, title}."""
    if not isinstance(value, dict):
        return None
    return {"playing": bool(value.get("playing")), "title": _clean_text(value.get("title"), 120)}


def _clean_history(value):
    """Earlier exchanges of this conversation: [{q, a}], oldest first."""
    out = []
    for h in value if isinstance(value, list) else []:
        if isinstance(h, dict):
            q, a = _clean_text(h.get("q")), _clean_text(h.get("a"))
            if q and a:
                out.append({"q": q, "a": a})
    return out[-4:]


def _span(seconds):
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    parts = ([f"{h} h"] if h else []) + ([f"{m} min"] if m else []) + ([f"{s} s"] if s or not (h or m) else [])
    return " ".join(parts)


class Assistant:
    """One per server. `settings()` gives {"api_key", "monthly_usd", "daily_requests"} each time,
    so a changed settings file takes effect without rebuilding this."""

    def __init__(self, settings, budget, shopping, usuals, post=post_json, log=print, forward=None, announcements=None):
        self.settings, self.budget, self.shopping, self.usuals = settings, budget, shopping, usuals
        self.post, self.log, self.forward = post, log, forward
        self.announcements = announcements or Announcements(budget.now)

    # -- what the iPad asks

    _screen = ""

    def handle(self, body, facts="", holy=False):
        """Answer one spoken request. Returns (http status, dict); the dict's `say` is read aloud."""
        if holy:
            return 403, {"ok": False, "error": "holy", "say": ""}
        if not isinstance(body, dict):
            return 400, {"ok": False, "error": "bad request", "say": ""}
        text = _clean_text(body.get("text"))
        if not text:
            return 400, {"ok": False, "error": "nothing was said", "say": ""}
        s = self.settings()
        if not s.get("api_key"):
            return 503, {"ok": False, "error": "not_set_up",
                         "say": "The assistant isn't set up yet. The display computer needs its Claude key."}
        timers = _clean_timers(body.get("timers"))
        home = _clean_home(body.get("home"))
        reminders = _clean_reminders(body.get("reminders"))
        self._screen = _clean_text(body.get("screen"), 40)
        messages = []
        for h in _clean_history(body.get("history")):
            messages += [{"role": "user", "content": h["q"]}, {"role": "assistant", "content": h["a"]}]
        messages.append({"role": "user", "content": text})
        system = SYSTEM + "\n\nFacts right now:\n" + self._facts(facts, timers, _clean_music(body.get("music")), home, reminders)

        actions, said = [], []
        for _ in range(MAX_STEPS):
            why = self.budget.allows(s["monthly_usd"], s["daily_requests"])
            if why:
                return 429, {"ok": False, "error": "budget_" + why, "say": self._limit_sentence(why), "actions": actions}
            try:
                answer = self.post(API_URL, {"x-api-key": s["api_key"], "anthropic-version": API_VERSION,
                                             "content-type": "application/json"},
                                   {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system, "tools": TOOLS,
                                    "output_config": {"effort": "low"}, "messages": messages})
            except ApiError as e:
                self.log(f"assistant: Claude answered {e.status}: {e}")
                say = ("The Claude key was refused. Check it on the display computer." if e.status in (401, 403)
                       else "I couldn't reach Claude just now.")
                return 502, {"ok": False, "error": "claude_%d" % e.status, "say": say, "actions": actions}
            if not self.budget.add(cost_usd(answer.get("usage"))):
                self.log("assistant: the spending record couldn't be saved; stopping")
                return 429, {"ok": False, "error": "budget_unreadable", "say": self._limit_sentence("unreadable"),
                             "actions": actions}
            content = answer.get("content") if isinstance(answer.get("content"), list) else []
            said += [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            calls = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            stop = answer.get("stop_reason")
            if stop == "refusal":
                return 200, {"ok": True, "say": "Sorry, I can't help with that.", "actions": actions}
            if stop != "tool_use" or not calls:
                break
            said = []  # words before a tool call are superseded by the answer after it
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": c.get("id"), **self._run(c, actions, timers, home)} for c in calls]})
        say = _clean_text(" ".join(t for t in said if t), 600)
        return 200, {"ok": True, "say": say, "actions": actions}

    # -- pieces

    def _limit_sentence(self, why):
        if why == "day":
            return "I've answered as many requests as I'm allowed today."
        if why == "unreadable":
            return "I can't read my spending record, so I've stopped. It needs a look on the display computer."
        return "I've reached this month's spending limit."

    def _facts(self, facts, timers, music=None, home=None, reminders=()):
        lines = [facts.strip()] if facts and facts.strip() else []
        items = [i["text"] for i in self.shopping.items()]
        lines.append("Shopping list: " + ("; ".join(items) if items else "empty") + ".")
        if timers:
            lines.append("Timers: " + "; ".join(
                f"{t['label'] or 'unnamed'} ({'ringing now' if t['ringing'] else _span(t['seconds_left']) + ' left'})"
                for t in timers) + ".")
        else:
            lines.append("Timers: none running.")
        if music and music["title"]:
            lines.append(f"Music: {music['title']} ({'playing' if music['playing'] else 'paused'}).")
        else:
            lines.append("Music: nothing playing.")
        lines.append("Reminders: " + ("; ".join(
            f"{r['text']} at {r['when'].replace('T', ' ')}" + ("" if r["repeat"] == "none" else f", {r['repeat']}")
            for r in reminders) if reminders else "none") + ".")
        lines += self._home_facts(home)
        usual = self.usuals.items()
        if usual:
            lines.append("Usual Walmart items: " + "; ".join(
                (f"{u['qty']} x " if u["qty"] > 1 else "") + u["name"] + ("" if u["item_id"] else " (no product link yet)")
                for u in usual) + ".")
        else:
            lines.append("Usual Walmart items: none set up.")
        return "\n".join(lines)

    def _home_facts(self, home):
        if home is None:
            return ["Home devices: home control isn't switched on on this display."]
        rooms = {}
        for d in home["devices"]:
            rooms.setdefault(d["room"] or "No room", []).append(
                f"{d['name']} ({d['kind']}" + (f", {d['state']}" if d["state"] else "") + ")")
        lines = ["Home devices, by room:"] + [f"  {room}: " + "; ".join(names) + "." for room, names in rooms.items()]
        if not home["devices"]:
            lines = ["Home devices: none found."]
        lines.append("Home scenes: " + ("; ".join(home["scenes"]) if home["scenes"] else "none") + ".")
        return lines

    def _home_tool(self, name, args, actions, home):
        if home is None:
            return {"content": "Home control isn't switched on in the display's settings.", "is_error": True}
        if name == "home_scene":
            want = _clean_text(args.get("name"), 60).casefold()
            scene = next((n for n in home["scenes"] if n.casefold() == want), None)
            if not scene:
                return {"content": "There is no scene with that name. The scenes are: " + ("; ".join(home["scenes"]) or "none") + ".",
                        "is_error": True}
            actions.append({"type": "home_scene", "name": scene})
            return {"content": f"The display is running {scene}, and will say so if it couldn't."}
        action = args.get("action")
        if action not in HOME_ACTIONS:
            return {"content": "That isn't something the display can do to a device. Unlocking and opening are done in the Home app.",
                    "is_error": True}
        want, room = _clean_text(args.get("device"), 60).casefold(), _clean_text(args.get("room"), 40).casefold()
        found = [d for d in home["devices"] if d["name"].casefold() == want and (not room or d["room"].casefold() == room)]
        if not found:
            return {"content": "No device has that name" + (" in that room" if room else "") + ". Use a name from the list.", "is_error": True}
        if len(found) > 1:
            return {"content": "More than one device has that name; give its room: " + ", ".join(d["room"] for d in found) + ".", "is_error": True}
        device = found[0]
        if device["kind"] not in HOME_ACTIONS[action]:
            return {"content": f"{device['name']} is a {device['kind']}; '{action}' doesn't apply to it.", "is_error": True}
        out = {"type": "home_set", "device": device["name"], "room": device["room"], "action": action}
        if action in HOME_RANGE:
            value, (low, high) = args.get("value"), HOME_RANGE[action]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= value <= high:
                return {"content": f"{action} needs a number from {low} to {high}.", "is_error": True}
            out["value"] = round(value)
        actions.append(out)
        return {"content": "The display is doing that now, and will say so if it couldn't."}

    def _run(self, call, actions, timers, home=None):
        """Run one tool call. Returns the tool_result's `content` (and `is_error`)."""
        name = call.get("name")
        args = call.get("input") if isinstance(call.get("input"), dict) else {}
        try:
            if name == "set_timer":
                seconds = args.get("seconds")
                if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= 86400:
                    return {"content": "A timer is 1 second to 24 hours.", "is_error": True}
                label = _clean_text(args.get("label"), 40)
                actions.append({"type": "set_timer", "seconds": seconds, "label": label})
                return {"content": f"Started: {label or 'timer'}, {_span(seconds)}."}
            if name == "cancel_timer":
                label = _clean_text(args.get("label"), 40) or "all"
                if not timers:
                    return {"content": "No timers are running."}
                actions.append({"type": "cancel_timer", "label": label})
                return {"content": "Stopped." if label.casefold() == "all" else f"Stopped {label} if it was running."}
            if name == "add_to_shopping_list":
                items = _clean_items(args.get("items"))
                if not items:
                    return {"content": "No items were given.", "is_error": True}
                added, dup = self.shopping.add(items)
                self._send_on()
                note = (f" Already on the list: {', '.join(dup)}." if dup else "") + \
                       ("" if len(added) + len(dup) == len(items) else " The list is full.")
                return {"content": (f"Added: {', '.join(added)}." if added else "Nothing new was added.") + note}
            if name == "play_music":
                query = _clean_text(args.get("query"), 120)
                if not query:
                    return {"content": "Say what to play.", "is_error": True}
                kind = args.get("kind") if args.get("kind") in ("song", "album", "artist", "playlist", "station") else "any"
                actions.append({"type": "play_music", "query": query, "kind": kind})
                return {"content": f"The display is looking for '{query}' on Apple Music and will play it, or say that it couldn't."}
            if name == "music_control":
                command = args.get("command")
                if command not in ("pause", "resume", "next", "previous", "stop"):
                    return {"content": "The commands are pause, resume, next, previous and stop.", "is_error": True}
                actions.append({"type": "music_control", "command": command})
                return {"content": "Done."}
            if name == "set_reminder":
                text = _clean_text(args.get("text"), 120)
                try:
                    when = datetime.strptime(args.get("when") if isinstance(args.get("when"), str) else "", "%Y-%m-%dT%H:%M")
                except ValueError:
                    when = None
                if not text or when is None:
                    return {"content": "A reminder needs a text and a time as YYYY-MM-DDTHH:MM.", "is_error": True}
                repeat = args.get("repeat") if args.get("repeat") in ("daily", "weekdays") else "none"
                now = self.budget.now().replace(tzinfo=None)
                if repeat == "none" and (when - now).total_seconds() < -60:
                    return {"content": f"That time has passed. It is now {now:%Y-%m-%dT%H:%M}.", "is_error": True}
                if (when - now).days > 366:
                    return {"content": "A reminder can be up to a year ahead.", "is_error": True}
                actions.append({"type": "set_reminder", "when": when.strftime("%Y-%m-%dT%H:%M"), "text": text, "repeat": repeat})
                return {"content": f"Set for {when:%A %B} {when.day} at {when:%I:%M %p}".replace(" 0", " ")
                                   + ("" if repeat == "none" else f", {repeat}") + ". The display skips reminders that fall on Shabbat or Yom Tov."}
            if name == "cancel_reminder":
                actions.append({"type": "cancel_reminder", "text": _clean_text(args.get("text"), 120) or "all"})
                return {"content": "Cancelled if there was one."}
            if name == "announce":
                message = _clean_text(args.get("message"), 240)
                if not message:
                    return {"content": "Say what to announce.", "is_error": True}
                self.announcements.add(message, self._screen)
                return {"content": "It is being said on the other displays now. Screens that are off or closed won't hear it."}
            if name == "play_radio":
                station = _clean_text(args.get("station"), 80)
                if not station:
                    return {"content": "Say which station.", "is_error": True}
                actions.append({"type": "play_radio", "station": station})
                return {"content": f"The display is looking for the station '{station}' and will play it, or say that it couldn't."}
            if name in ("home_set", "home_scene"):
                return self._home_tool(name, args, actions, home)
            if name == "send_to_phone":
                if args.get("what") == "list":
                    actions.append({"type": "show_code", "path": "/shop", "title": "Shopping list"})
                    return {"content": "A code is on the display. A phone on the home Wi-Fi that scans it opens the shopping list."}
                cart = self.usuals.cart_url()
                if not cart:
                    actions.append({"type": "show_code", "path": "/shop", "title": "Set up your usual items"})
                    return {"content": "No usual Walmart items have a product link yet, so there is no cart to open. A code is on the "
                                       "display instead: it opens the page where the usual items are set up."}
                missing = [u["name"] for u in self.usuals.items() if not u["item_id"]]
                actions.append({"type": "show_code", "url": cart, "title": "Walmart cart"})
                return {"content": "A code is on the display. Scanning it with a phone opens Walmart with the usual items in the cart; "
                                   "they review it and check out there." + (f" Left out, no product link yet: {', '.join(missing)}." if missing else "")}
            if name == "add_usuals_to_shopping_list":
                names = [(f"{u['qty']} x " if u["qty"] > 1 else "") + u["name"] for u in self.usuals.items()]
                if not names:
                    return {"content": "No usual items are set up yet."}
                added, dup = self.shopping.add(names)
                self._send_on()
                return {"content": (f"Added: {', '.join(added)}." if added else "They were all on the list already.")}
            if name == "remove_from_shopping_list":
                items = _clean_items(args.get("items"))
                removed = self.shopping.remove(items)
                return {"content": f"Removed: {', '.join(removed)}." if removed else "None of those were on the list."}
        except OSError as e:
            self.log(f"assistant: {name} failed ({e})")
            return {"content": "That couldn't be saved on the display computer.", "is_error": True}
        return {"content": f"There is no tool called {name}.", "is_error": True}

    def _send_on(self):
        """Pass new items on (to MenuApp, when the server is set up for it). Failures wait for next time."""
        if not self.forward:
            return
        pending = self.shopping.unsent()
        if not pending:
            return
        try:
            if self.forward(pending) is not False:  # False: nowhere to send them yet
                self.shopping.mark_sent(pending)
        except Exception as e:  # noqa: BLE001 - whatever the forwarder raises, the list itself is saved
            self.log(f"assistant: shopping items not passed on yet ({e})")
