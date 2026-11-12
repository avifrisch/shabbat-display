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
import threading
import urllib.error
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
the tool has answered. You can keep a shopping list and set kitchen timers. You cannot play \
music, order anything, send messages or control other devices yet; say so briefly if asked. \
You have no internet search: answer from what you know and from the facts below, and say so \
when you don't know.

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

    def __init__(self, settings, budget, shopping, post=post_json, log=print, forward=None):
        self.settings, self.budget, self.shopping = settings, budget, shopping
        self.post, self.log, self.forward = post, log, forward

    # -- what the iPad asks

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
        messages = []
        for h in _clean_history(body.get("history")):
            messages += [{"role": "user", "content": h["q"]}, {"role": "assistant", "content": h["a"]}]
        messages.append({"role": "user", "content": text})
        system = SYSTEM + "\n\nFacts right now:\n" + self._facts(facts, timers)

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
                {"type": "tool_result", "tool_use_id": c.get("id"), **self._run(c, actions, timers)} for c in calls]})
        say = _clean_text(" ".join(t for t in said if t), 600)
        return 200, {"ok": True, "say": say, "actions": actions}

    # -- pieces

    def _limit_sentence(self, why):
        if why == "day":
            return "I've answered as many requests as I'm allowed today."
        if why == "unreadable":
            return "I can't read my spending record, so I've stopped. It needs a look on the display computer."
        return "I've reached this month's spending limit."

    def _facts(self, facts, timers):
        lines = [facts.strip()] if facts and facts.strip() else []
        items = [i["text"] for i in self.shopping.items()]
        lines.append("Shopping list: " + ("; ".join(items) if items else "empty") + ".")
        if timers:
            lines.append("Timers: " + "; ".join(
                f"{t['label'] or 'unnamed'} ({'ringing now' if t['ringing'] else _span(t['seconds_left']) + ' left'})"
                for t in timers) + ".")
        else:
            lines.append("Timers: none running.")
        return "\n".join(lines)

    def _run(self, call, actions, timers):
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
