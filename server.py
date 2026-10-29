#!/usr/bin/env python3
"""
Shabbat Display - local data server.

Runs on the display computer. It fetches weather, zmanim, Yankees/MLB and news
on fixed timers, keeps the last good copy of everything (also on disk), and
serves the dashboard page at http://localhost:8765

Standard library only - no pip installs needed.

    python server.py            run the server
    python server.py --check    fetch every source once and report what worked

Runs on Windows, macOS and Linux (including Raspberry Pi OS).
"""

import calendar as cal_mod
import html
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# Settings - these are the defaults. To change one, put it in settings.json
# (the setup scripts create it from settings.example.json); anything in that
# file overrides the value here, and it survives updates to this file.
# --------------------------------------------------------------------------
CONFIG = {
    "location_name": "Teaneck",
    "lat": 40.8885,
    "lon": -74.0160,
    "zip": "07666",
    "tzid": "America/New_York",

    # Candle lighting minutes before sunset, and havdalah method for Hebcal:
    #   "M=on"  -> tzeit at 8.5 degrees     "m=50" -> 50 minutes after sunset
    "candle_minutes": 18,
    "havdalah": "M=on",

    # Team
    "team_id": 147,          # Yankees
    "team_abbr": "NYY",
    "division_id": 201,      # AL East
    "division_name": "AL East",
    "league_id": 103,        # American League

    # Display
    "zmanim_labels": "hebrew",   # "hebrew" or "english"
    "dim_start": "23:00",        # screen dims between these times
    "dim_end": "06:30",
    "dim_level": 0.55,           # 0 = no dimming, 0.8 = very dark
    "rotation_seconds": {"agenda": 25, "yankees": 30, "mlb": 30, "news": 30, "israel": 25},

    # Weekday agenda: the private ICS link of each calendar to show (the LPM
    # calendar feed, or any other ICS link). Hidden on Shabbat and Yom Tov.
    "agenda_ics": [],

    # NYT subscription sign-in for the reading panel: the NYT-S cookie value
    # (or a whole Cookie header) copied from a signed-in browser. Secret.
    "nyt_cookie": "",

    # Server
    "bind": "127.0.0.1",         # use "0.0.0.0" to view from other devices on your network
    "port": 8765,
}

FEEDS = {
    "yankees_news": [
        "https://www.mlb.com/yankees/feeds/news/rss.xml",
        "https://www.nbcnewyork.com/tag/yankees/feed/",
    ],
    "mlb_news": ["https://www.mlb.com/feeds/news/rss.xml"],
    "nyt": ["https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"],
    "toi": [
        "https://www.timesofisrael.com/feed/",
        # backup if the site's bot protection refuses the request
        "https://news.google.com/rss/search?q=site:timesofisrael.com+when:1d&hl=en-US&gl=US&ceid=US:en",
    ],
}
# CNN stopped updating its RSS feeds, so CNN headlines come from its text-only
# site, with a Google News search for cnn.com as the backup.
CNN_LITE = "https://lite.cnn.com/"
CNN_BACKUP = "https://news.google.com/rss/search?q=site:cnn.com+when:1d&hl=en-US&gl=US&ceid=US:en"

# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "settings.json")
CACHE_FILE = os.path.join(HERE, "cache.json")
LOG_FILE = os.path.join(HERE, "server.log")
PAGE_FILE = os.path.join(HERE, "index.html")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 ShabbatDisplay/1.0")
MLB = "https://statsapi.mlb.com/api/v1"
MLB_CLUBS = {108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121,
             133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 158}

_log_lock = threading.Lock()


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, file=sys.stderr, flush=True)  # stderr, so --setting output stays clean
    with _log_lock:
        try:
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
                os.replace(LOG_FILE, LOG_FILE + ".old")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def load_settings():
    """Overlay settings.json on CONFIG. A bad file is logged and ignored."""
    if not os.path.exists(SETTINGS_FILE):
        return
    try:
        with open(SETTINGS_FILE, encoding="utf-8-sig") as f:
            user = json.load(f)
    except (OSError, ValueError) as e:
        log(f"settings.json not used ({e}); running with defaults")
        return
    for k, v in user.items():
        if k.startswith("_"):
            continue
        if k not in CONFIG:
            log(f"settings.json: unknown setting '{k}' ignored")
        elif isinstance(CONFIG[k], dict) and isinstance(v, dict):
            CONFIG[k] = {**CONFIG[k], **v}
        else:
            CONFIG[k] = v


# ---------------------------------------------------------------- helpers

def http_get(url, accept="*/*", timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        charset = r.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, "replace")


def get_json(url, accept="application/json"):
    return json.loads(http_get(url, accept=accept))


def qs(params):
    return urllib.parse.urlencode(params, safe=",:")


def now():
    return datetime.now().astimezone()


def parse_dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.astimezone()
    except ValueError:
        return None


def baseball_day():
    # A game that runs past midnight still belongs to the previous day.
    return (now() - timedelta(hours=5)).date()


def season_year():
    d = now()
    return d.year if d.month >= 3 else d.year - 1


def clean_text(s, limit=None):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return s


def compass(deg):
    if deg is None:
        return ""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((deg % 360) / 45 + 0.5) % 8]


# ---------------------------------------------------------------- store

class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        self.meta = {}
        self.load()

    def set(self, key, value):
        with self.lock:
            self.data[key] = value
            self.meta[key] = {"updated": time.time(), "ok": True, "error": None}
        self.save()

    def fail(self, key, err):
        with self.lock:
            m = dict(self.meta.get(key) or {"updated": None})
            m.update(ok=False, error=str(err)[:200], failed_at=time.time())
            self.meta[key] = m

    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)

    def snapshot(self):
        with self.lock:
            return {"data": dict(self.data), "meta": dict(self.meta)}

    def save(self):
        snap = self.snapshot()
        tmp = CACHE_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f)
            os.replace(tmp, CACHE_FILE)
        except OSError as e:
            log(f"cache save failed: {e}")

    def load(self):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                snap = json.load(f)
            self.data = snap.get("data", {})
            self.meta = snap.get("meta", {})
            log(f"loaded cached data for {len(self.data)} sources")
        except (OSError, ValueError):
            pass


store = Store()

# ---------------------------------------------------------------- weather

def fetch_weather():
    params = {
        "latitude": CONFIG["lat"], "longitude": CONFIG["lon"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
                   "wind_speed_10m,wind_direction_10m,wind_gusts_10m,is_day",
        "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,sunrise,sunset",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "timezone": "auto", "forecast_days": 7,
    }
    j = get_json("https://api.open-meteo.com/v1/forecast?" + qs(params))
    c, h, d = j["current"], j["hourly"], j["daily"]
    hour_key = now().strftime("%Y-%m-%dT%H:00")
    start = next((i for i, t in enumerate(h["time"]) if t >= hour_key), 0)
    hourly = [{
        "time": h["time"][i], "temp": round(h["temperature_2m"][i]),
        "code": h["weather_code"][i], "precip": h["precipitation_probability"][i] or 0,
        "is_day": bool(h["is_day"][i]),
    } for i in range(start + 1, min(start + 9, len(h["time"])))]
    daily = [{
        "date": d["time"][i], "hi": round(d["temperature_2m_max"][i]),
        "lo": round(d["temperature_2m_min"][i]), "code": d["weather_code"][i],
        "precip": d["precipitation_probability_max"][i] or 0,
    } for i in range(len(d["time"]))]
    return {
        "current": {
            "temp": round(c["temperature_2m"]), "feels": round(c["apparent_temperature"]),
            "humidity": c["relative_humidity_2m"], "code": c["weather_code"],
            "is_day": bool(c["is_day"]), "wind_mph": round(c["wind_speed_10m"]),
            "gust_mph": round(c.get("wind_gusts_10m") or 0),
            "wind_dir": compass(c["wind_direction_10m"]),
        },
        "today": daily[0] if daily else None,
        "daily": daily[1:6],
        "hourly": hourly,
        "sunrise": d["sunrise"][0], "sunset": d["sunset"][0],
    }


_nws_forecast_url = None


def fetch_nws_forecast():
    global _nws_forecast_url
    if not _nws_forecast_url:
        p = get_json(f"https://api.weather.gov/points/{CONFIG['lat']},{CONFIG['lon']}",
                     accept="application/geo+json")
        _nws_forecast_url = p["properties"]["forecast"]
    j = get_json(_nws_forecast_url, accept="application/geo+json")
    return [{"name": p["name"], "short": p["shortForecast"], "text": p["detailedForecast"]}
            for p in j["properties"]["periods"][:4]]


def fetch_alerts():
    j = get_json(f"https://api.weather.gov/alerts/active?point={CONFIG['lat']},{CONFIG['lon']}",
                 accept="application/geo+json")
    out = []
    for f in j.get("features", []):
        p = f["properties"]
        out.append({"event": p.get("event"), "headline": p.get("headline"),
                    "severity": p.get("severity"), "ends": p.get("ends") or p.get("expires"),
                    "description": p.get("description") or "", "instruction": p.get("instruction") or ""})
    return out


# ---------------------------------------------------------------- jewish calendar

ZMAN_KEYS = [
    ("alot", "alotHaShachar"), ("sunrise", "sunrise"), ("shema_mga", "sofZmanShmaMGA"),
    ("shema", "sofZmanShma"), ("tefilla", "sofZmanTfilla"), ("chatzot", "chatzot"),
    ("mincha_gedola", "minchaGedola"), ("plag", "plagHaMincha"), ("sunset", "sunset"),
    ("tzeit", "tzeit85deg"),
]


def _zmanim_for(day):
    params = {"cfg": "json", "latitude": CONFIG["lat"], "longitude": CONFIG["lon"],
              "tzid": CONFIG["tzid"], "date": day.isoformat()}
    j = get_json("https://www.hebcal.com/zmanim?" + qs(params))
    t = j["times"]
    return {k: t.get(src) for k, src in ZMAN_KEYS}


def fetch_zmanim():
    today = now().date()
    times = _zmanim_for(today)
    tzeit = parse_dt(times.get("tzeit"))
    if tzeit and now() > tzeit:
        return {"date": (today + timedelta(days=1)).isoformat(), "is_tomorrow": True,
                "times": _zmanim_for(today + timedelta(days=1)), "today": times}
    return {"date": today.isoformat(), "is_tomorrow": False, "times": times, "today": times}


def fetch_hebdate():
    n = now()
    z = store.get("zmanim") or {}
    today_times = z.get("today") if z.get("date") in (n.date().isoformat(), (n.date() + timedelta(days=1)).isoformat()) else None
    if not today_times:
        today_times = _zmanim_for(n.date())
    sunset = parse_dt(today_times.get("sunset"))
    after = bool(sunset and n > sunset)
    params = {"cfg": "json", "gy": n.year, "gm": n.month, "gd": n.day, "g2h": 1}
    if after:
        params["gs"] = "on"
    j = get_json("https://www.hebcal.com/converter?" + qs(params))
    return {"hebrew": j.get("hebrew"), "english": f"{j.get('hd')} {j.get('hm')} {j.get('hy')}",
            "after_sunset": after, "for": n.date().isoformat()}


def fetch_calendar():
    n = now()
    havdalah_key, havdalah_val = CONFIG["havdalah"].split("=")
    params = {
        "v": 1, "cfg": "json", "maj": "on", "min": "on", "mod": "on", "nx": "on",
        "ss": "on", "mf": "on", "c": "on", "s": "on", "geo": "zip", "zip": CONFIG["zip"],
        "b": CONFIG["candle_minutes"], havdalah_key: havdalah_val,
        "start": (n.date() - timedelta(days=2)).isoformat(),
        "end": (n.date() + timedelta(days=10)).isoformat(),
    }
    j = get_json("https://www.hebcal.com/hebcal?" + qs(params))
    items = []
    for it in j.get("items", []):
        items.append({
            "title": it.get("title"), "date": it.get("date"), "category": it.get("category"),
            "hebrew": it.get("hebrew"), "yomtov": bool(it.get("yomtov")),
            "subcat": it.get("subcat"),
        })
    return {"items": items}


# ---------------------------------------------------------------- baseball

def norm_game(g):
    st = g.get("status", {})
    ls = g.get("linescore", {}) or {}
    off = ls.get("offense", {}) or {}
    lt = ls.get("teams", {}) or {}

    def side(which):
        s = g["teams"][which]
        t = s.get("team", {})
        lr = s.get("leagueRecord") or {}
        return {
            "id": t.get("id"),
            "abbr": t.get("abbreviation") or (t.get("teamName") or t.get("name", "?"))[:3].upper(),
            "name": t.get("teamName") or t.get("name"),
            "full": t.get("name"),
            "score": s.get("score"),
            "hits": (lt.get(which) or {}).get("hits"),
            "errors": (lt.get(which) or {}).get("errors"),
            "record": f"{lr['wins']}-{lr['losses']}" if "wins" in lr else None,
            "probable": (s.get("probablePitcher") or {}).get("fullName"),
            "winner": s.get("isWinner"),
        }

    ss = g.get("seriesStatus") or {}
    detail = st.get("detailedState", "")
    state = st.get("abstractGameState")
    if detail in ("Postponed", "Cancelled", "Suspended"):
        state = "Off"
    return {
        "id": g.get("gamePk"), "start": g.get("gameDate"), "day": g.get("officialDate"),
        "state": state, "detail": detail,
        "inning": ls.get("currentInning"), "inning_ordinal": ls.get("currentInningOrdinal"),
        "inning_state": ls.get("inningState"), "half": ls.get("inningHalf"),
        "outs": ls.get("outs"), "balls": ls.get("balls"), "strikes": ls.get("strikes"),
        "bases": [bool(off.get("first")), bool(off.get("second")), bool(off.get("third"))],
        "away": side("away"), "home": side("home"),
        "game_type": g.get("gameType"), "series": g.get("seriesDescription"),
        "series_game": g.get("seriesGameNumber"),
        "series_status": ss.get("result") or ss.get("description"),
        "venue": (g.get("venue") or {}).get("name"),
    }


def schedule(params):
    params = dict(params, sportId=1, hydrate="linescore,team,probablePitcher,seriesStatus")
    j = get_json(f"{MLB}/schedule?" + qs(params))
    games = []
    for d in j.get("dates", []):
        games += [norm_game(g) for g in d.get("games", [])]
    return games


def fetch_team():
    bd = baseball_day()
    games = schedule({"teamId": CONFIG["team_id"],
                      "startDate": (bd - timedelta(days=60)).isoformat(),
                      "endDate": (bd + timedelta(days=21)).isoformat()})
    n = now()
    live = next((g for g in games if g["state"] == "Live"), None)
    upcoming = [g for g in games if g["state"] == "Preview"
                and (parse_dt(g["start"]) or n) > n - timedelta(hours=4)]
    finals = [g for g in games if g["state"] == "Final"]
    nxt = upcoming[0] if upcoming else None
    last = finals[-1] if finals else None
    season_over = bool(not live and not nxt and last
                       and (n - (parse_dt(last["start"]) or n)) > timedelta(days=2))
    return {"live": live, "next": nxt, "last": last, "season_over": season_over,
            "recent": finals[-5:]}


def team_poll_seconds():
    t = store.get("team") or {}
    if t.get("live"):
        return 30
    nxt = t.get("next")
    if nxt:
        start = parse_dt(nxt["start"])
        if start and start - now() < timedelta(minutes=30):
            return 30
    return 180


def fetch_standings():
    j = get_json(f"{MLB}/standings?" + qs({
        "leagueId": CONFIG["league_id"], "season": season_year(),
        "standingsTypes": "regularSeason", "hydrate": "team"}))
    for rec in j.get("records", []):
        if (rec.get("division") or {}).get("id") != CONFIG["division_id"]:
            continue
        teams = []
        for tr in rec.get("teamRecords", []):
            t = tr["team"]
            teams.append({
                "abbr": t.get("abbreviation"), "name": t.get("teamName") or t.get("name"),
                "w": tr.get("wins"), "l": tr.get("losses"), "gb": tr.get("gamesBack"),
                "pct": tr.get("winningPercentage"),
                "streak": (tr.get("streak") or {}).get("streakCode"),
                "rank": tr.get("divisionRank"), "is_team": t.get("id") == CONFIG["team_id"],
            })
        teams.sort(key=lambda x: int(x["rank"] or 99))
        return {"season": season_year(), "teams": teams}
    raise ValueError("division not found in standings")


def fetch_scoreboard():
    bd = baseball_day()
    games = schedule({"date": bd.isoformat()})
    label = "Today"
    if not games and 3 <= now().month <= 11:
        games = schedule({"date": (bd - timedelta(days=1)).isoformat()})
        label = "Yesterday" if games else label
    order = {"Live": 0, "Preview": 1, "Final": 2, "Off": 3}
    games.sort(key=lambda g: (order.get(g["state"], 4), g["start"] or ""))
    return {"date": bd.isoformat(), "label": label, "games": games}


def scoreboard_poll_seconds():
    sb = store.get("scoreboard") or {}
    return 45 if any(g["state"] == "Live" for g in sb.get("games", [])) else 180


TEAM_SKIP_TEXT = ("roster status changed", "changed number")
LEAGUE_KEEP = ("trade", "signed", "released", "designated", "claimed", "retired",
               "suspen", "free agen", "purchased", "selected", "waiver")


def _transactions(params):
    j = get_json(f"{MLB}/transactions?" + qs(params))
    return j.get("transactions", [])


def fetch_transactions():
    today = now().date()
    team_name = None
    team = []
    for t in _transactions({"teamId": CONFIG["team_id"],
                            "startDate": (today - timedelta(days=45)).isoformat(),
                            "endDate": today.isoformat()}):
        desc = t.get("description") or ""
        if not desc or any(s in desc.lower() for s in TEAM_SKIP_TEXT) \
                or (t.get("typeDesc") or "") == "Number Change":
            continue
        if not team_name:
            for side in ("toTeam", "fromTeam"):
                if (t.get(side) or {}).get("id") == CONFIG["team_id"]:
                    team_name = t[side]["name"]
        if team_name and desc.startswith(team_name + " "):
            rest = desc[len(team_name) + 1:]
            desc = rest[:1].upper() + rest[1:]
        team.append({"id": t.get("id"), "date": t.get("date"), "type": t.get("typeDesc"),
                     "text": desc})
    league = []
    for t in _transactions({"sportId": 1,
                            "startDate": (today - timedelta(days=6)).isoformat(),
                            "endDate": today.isoformat()}):
        desc = t.get("description") or ""
        kind = (t.get("typeDesc") or "").lower()
        clubs = {(t.get("toTeam") or {}).get("id"), (t.get("fromTeam") or {}).get("id")}
        if not desc or "minor league contract" in desc or not (clubs & MLB_CLUBS):
            continue
        if not any(k in kind for k in LEAGUE_KEEP):
            continue
        league.append({"id": t.get("id"), "date": t.get("date"), "type": t.get("typeDesc"),
                       "text": desc})
    key = lambda x: (x["date"] or "", x["id"] or 0)
    team.sort(key=key, reverse=True)
    league.sort(key=key, reverse=True)
    return {"team": team[:10], "league": league[:10]}


# ---------------------------------------------------------------- news

def _child(el, *names):
    for n in names:
        for c in el:
            tag = c.tag.split("}")[-1]
            if tag == n:
                return c
    return None


def _date_of(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        return d.astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError):
        d = parse_dt(s)
        return d.isoformat(timespec="seconds") if d else None


def _feed_regex(text, source):
    # Fallback for feeds that aren't well-formed XML.
    def grab(block, tag):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S | re.I)
        if not m:
            return ""
        v = m.group(1)
        c = re.search(r"<!\[CDATA\[(.*?)\]\]>", v, re.S)
        return c.group(1) if c else v
    out = []
    for block in re.findall(r"<item[\s>].*?</item>", text, re.S | re.I):
        t = clean_text(grab(block, "title"))
        if t:
            out.append({"title": t, "summary": clean_text(grab(block, "description"), 260),
                        "time": _date_of(clean_text(grab(block, "pubDate"))),
                        "link": clean_text(grab(block, "link")) or None, "source": source})
    return out


def parse_feed(text, source):
    text = text.lstrip("﻿ \r\n\t")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return _feed_regex(text, source)
    entries = [e for e in root.iter() if e.tag.split("}")[-1] in ("item", "entry")]
    out = []
    for e in entries:
        title = _child(e, "title")
        t = clean_text(title.text if title is not None else "")
        if not t:
            continue
        desc = _child(e, "description", "summary")
        when = _child(e, "pubDate", "published", "updated", "date")
        link = _child(e, "link")
        href = (link.text or link.get("href")) if link is not None else None
        out.append({"title": t, "summary": clean_text(desc.text if desc is not None else "", 260),
                    "time": _date_of(when.text if when is not None else None),
                    "link": href, "source": source})
    return out


def feed_fetcher(key):
    def fetch():
        errors = []
        for url in FEEDS[key]:
            try:
                items = parse_feed(http_get(url, accept="application/rss+xml, application/xml, text/xml"), key)
                if "news.google.com" in url:
                    for it in items:
                        it["title"] = re.sub(r"\s+-\s+[^-]+$", "", it["title"])
                        it["summary"] = ""
                if items:
                    return {"items": items[:14], "from": url}
                errors.append(f"{url}: empty")
            except Exception as e:  # noqa: BLE001 - try the next url
                errors.append(f"{url}: {e}")
        raise RuntimeError("; ".join(errors))
    return fetch


def fetch_cnn():
    try:
        page = http_get(CNN_LITE, accept="text/html")
        seen, items = set(), []
        for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
            m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
            title = clean_text(inner)
            if not m or len(title) < 20 or title in seen:
                continue
            seen.add(title)
            day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            items.append({"title": title, "summary": "", "time": None, "day": day,
                          "link": urllib.parse.urljoin("https://www.cnn.com", href.replace("lite.cnn.com", "www.cnn.com")),
                          "source": "cnn"})
        if len(items) >= 5:
            return {"items": items[:14], "from": CNN_LITE}
        raise ValueError("too few headlines on lite.cnn.com")
    except Exception as e:  # noqa: BLE001 - fall back to the backup feed
        log(f"cnn lite failed ({e}); using backup feed")
    items = parse_feed(http_get(CNN_BACKUP), "cnn")
    for it in items:
        it["title"] = re.sub(r"\s+-\s+CNN.*$", "", it["title"])
        it["summary"] = ""
    return {"items": items[:14], "from": CNN_BACKUP}


# ---------------------------------------------------------------- agenda
# Reads published calendars (ICS). Handles recurring events, moved and
# cancelled occurrences, and the time zones Outlook embeds in the file, since
# Python on Windows has no time zone database of its own.

ICS_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
# Outlook uses Windows time zone names; zoneinfo (on the Pi) wants IANA names.
WIN_TZ = {"Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
          "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
          "Israel Standard Time": "Asia/Jerusalem", "GMT Standard Time": "Europe/London", "UTC": "UTC"}


def _ics_prop(line):
    # 'DTSTART;TZID="Eastern Standard Time":20261029T090000' -> (name, params, value)
    quoted = False
    for i, c in enumerate(line):
        if c == '"':
            quoted = not quoted
        elif c == ":" and not quoted:
            break
    else:
        return None
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', line[:i])
    if not parts:
        return None
    params = {}
    for part in parts[1:]:
        k, _, v = part.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, line[i + 1:]


def _ics_components(text):
    """ICS text -> nested {"type", "props": [(name, params, value)], "children"}."""
    lines = []
    for line in re.split(r"\r\n|\n|\r", text):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif line.strip():
            lines.append(line)
    root = {"type": "ROOT", "props": [], "children": []}
    stack = [root]
    for line in lines:
        p = _ics_prop(line)
        if not p:
            continue
        if p[0] == "BEGIN":
            comp = {"type": p[2].strip().upper(), "props": [], "children": []}
            stack[-1]["children"].append(comp)
            stack.append(comp)
        elif p[0] == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1]["props"].append(p)
    return root


def _ics_get(comp, name, all_=False):
    found = [p for p in comp["props"] if p[0] == name]
    return found if all_ else (found[0] if found else None)


def _ics_text(comp, name):
    p = _ics_get(comp, name)
    if not p:
        return ""
    return re.sub(r"\\([\\;,nN])", lambda m: " " if m.group(1) in "nN" else m.group(1), p[2]).strip()


def _rrule(value):
    return dict(part.split("=", 1) for part in value.upper().split(";") if "=" in part)


def _naive(v):
    """'20261029T090000' -> (naive datetime, False); '...Z' -> (naive, True); '20261029' -> (date, False)."""
    m = re.fullmatch(r"(\d{8})(?:T(\d{6})(Z?))?", v.strip())
    if not m:
        return None, False
    if not m.group(2):
        return datetime.strptime(m.group(1), "%Y%m%d").date(), False
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"), bool(m.group(3))


def _month_days(y, m, rule, default_day):
    """Days of month y-m picked by a rule's BYDAY (e.g. 2TU, -1FR), BYSETPOS or BYMONTHDAY."""
    last = cal_mod.monthrange(y, m)[1]
    if "BYDAY" in rule:
        days = set()
        for tok in rule["BYDAY"].split(","):
            mt = re.fullmatch(r"([+-]?\d+)?([A-Z]{2})", tok.strip())
            if not mt or mt.group(2) not in ICS_DAYS:
                continue
            wd = ICS_DAYS.index(mt.group(2))
            hits = [d for d in range(1, last + 1) if date(y, m, d).weekday() == wd]
            n = int(mt.group(1) or 0)
            if n == 0:
                days.update(hits)
            elif abs(n) <= len(hits):
                days.add(hits[n - 1] if n > 0 else hits[n])
        days = sorted(days)
        if "BYSETPOS" in rule:
            picked = {days[p - 1] if p > 0 else days[p]
                      for p in map(int, rule["BYSETPOS"].split(",")) if p and abs(p) <= len(days)}
            days = sorted(picked)
        return days
    if "BYMONTHDAY" in rule:
        days = []
        for t in rule["BYMONTHDAY"].split(","):
            d = int(t)
            d = d if d > 0 else last + 1 + d
            if 1 <= d <= last:
                days.append(d)
        return sorted(days)
    return [default_day] if default_day <= last else []


class IcsZone:
    """A VTIMEZONE block: when each STANDARD/DAYLIGHT rule starts, and its UTC offset."""

    def __init__(self, comp):
        self.rules = []
        for ch in comp["children"]:
            st, to = _ics_get(ch, "DTSTART"), _ics_get(ch, "TZOFFSETTO")
            if ch["type"] not in ("STANDARD", "DAYLIGHT") or not st or not to:
                continue
            start, _ = _naive(st[2])
            m = re.fullmatch(r"([+-])(\d{2})(\d{2})", to[2].strip())
            if not isinstance(start, datetime) or not m:
                continue
            off = timedelta(hours=int(m.group(2)), minutes=int(m.group(3))) * (-1 if m.group(1) == "-" else 1)
            rr = _ics_get(ch, "RRULE")
            self.rules.append((start, _rrule(rr[2]) if rr else None, off))

    def offset_at(self, n):
        best = None
        for start, rule, off in self.rules:
            onsets = [start]
            if rule:
                until = _naive(rule["UNTIL"])[0] if "UNTIL" in rule else None
                months = [int(x) for x in rule.get("BYMONTH", str(start.month)).split(",")]
                onsets = [datetime(y, mo, d, start.hour, start.minute)
                          for y in (n.year - 1, n.year) for mo in months
                          for d in _month_days(y, mo, rule, start.day)]
                if isinstance(until, datetime):
                    onsets = [o for o in onsets if o <= until]
            for o in onsets:
                if start <= o <= n and (best is None or o > best[0]):
                    best = (o, off)
        return best[1] if best else self.rules[0][2]


def _zone_fn(tzid, zones):
    """Function turning a naive wall-clock time in TZID into an aware local time."""
    if tzid and tzid in zones and zones[tzid].rules:
        z = zones[tzid]
        return lambda n: n.replace(tzinfo=timezone(z.offset_at(n))).astimezone()
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            zi = ZoneInfo(WIN_TZ.get(tzid, tzid))
            return lambda n: n.replace(tzinfo=zi).astimezone()
        except Exception:  # noqa: BLE001 - no tz database (Windows): treat as local time
            pass
    return lambda n: n.astimezone()


def _when(prop, zones, value=None):
    """(naive datetime or date, function to make it aware) for a DTSTART-like property."""
    v, utc = _naive(value if value is not None else prop[2])
    if utc:
        return v, lambda n: n.replace(tzinfo=timezone.utc).astimezone()
    return v, _zone_fn(prop[1].get("TZID"), zones)


def _key(v, fn):
    return fn(v).astimezone(timezone.utc).strftime("%Y%m%dT%H%M") if isinstance(v, datetime) else v.isoformat()


def _duration(ev, start, fn, zones):
    en = _ics_get(ev, "DTEND")
    if en:
        end, efn = _when(en, zones)
        if isinstance(start, datetime) and isinstance(end, datetime):
            return efn(end) - fn(start)
        if end is not None and not isinstance(start, datetime) and not isinstance(end, datetime):
            return end - start
    du = _ics_get(ev, "DURATION")
    m = du and re.fullmatch(r"\+?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", du[2].strip())
    if m:
        w, d, h, mi, s = (int(x or 0) for x in m.groups())
        return timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
    return timedelta(0) if isinstance(start, datetime) else timedelta(days=1)


def _occurrences(start, rule, limit, fn):
    """Starts of a recurring event (same type as `start`), in order, through date `limit`."""
    freq, step = rule.get("FREQ"), int(rule.get("INTERVAL") or 1)
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until, until_utc = _naive(rule["UNTIL"]) if "UNTIL" in rule else (None, False)
    timed = isinstance(start, datetime)
    sd = start.date() if timed else start
    at = (lambda d: datetime.combine(d, start.time())) if timed else (lambda d: d)

    def past_until(c):
        if until is None:
            return False
        if timed and isinstance(until, datetime):
            u = until.replace(tzinfo=timezone.utc) if until_utc else fn(until)
            return fn(c) > u
        cd = c.date() if timed else c
        return cd > (until.date() if isinstance(until, datetime) else until)

    wkst = ICS_DAYS.index(rule["WKST"]) if rule.get("WKST") in ICS_DAYS else 0
    bydays = {ICS_DAYS.index(t[-2:]) for t in rule.get("BYDAY", "").split(",") if t[-2:] in ICS_DAYS}
    months = [int(x) for x in rule["BYMONTH"].split(",")] if "BYMONTH" in rule else None
    n = 0
    for k in range(50000):
        if freq == "DAILY":
            ref = sd + timedelta(days=k * step)
            cands = [ref] if (not bydays or ref.weekday() in bydays) and (not months or ref.month in months) else []
        elif freq == "WEEKLY":
            ref = sd - timedelta(days=(sd.weekday() - wkst) % 7) + timedelta(weeks=k * step)
            cands = sorted(ref + timedelta(days=(wd - wkst) % 7) for wd in (bydays or {sd.weekday()}))
        elif freq == "MONTHLY":
            y, m = divmod(sd.month - 1 + k * step, 12)
            ref = date(sd.year + y, m + 1, 1)
            cands = [] if months and ref.month not in months else \
                [date(ref.year, ref.month, d) for d in _month_days(ref.year, ref.month, rule, sd.day)]
        elif freq == "YEARLY":
            ref = date(sd.year + k * step, 1, 1)
            cands = [date(ref.year, mo, d) for mo in (months or [sd.month])
                     for d in _month_days(ref.year, mo, rule, sd.day)]
        else:
            yield start
            return
        if ref > limit:
            return
        for d in cands:
            if d < sd:
                continue
            c = at(d)
            if past_until(c) or (count is not None and n >= count):
                return
            n += 1
            yield c


def _ics_events(text, w0, w1, cal):
    root = _ics_components(text)
    vcal = next((c for c in root["children"] if c["type"] == "VCALENDAR"), root)
    zones = {}
    for c in vcal["children"]:
        tz = c["type"] == "VTIMEZONE" and _ics_get(c, "TZID")
        if tz:
            zones[tz[2].strip()] = IcsZone(c)
    events = [c for c in vcal["children"] if c["type"] == "VEVENT"]
    # occurrences of a series that were moved or edited have their own VEVENT
    moved = {}
    for ev in events:
        rid = _ics_get(ev, "RECURRENCE-ID")
        if rid:
            v, fn = _when(rid, zones)
            if v is not None:
                moved.setdefault(_ics_text(ev, "UID"), set()).add(_key(v, fn))
    out = []
    for ev in events:
        st = _ics_get(ev, "DTSTART")
        if not st or _ics_text(ev, "STATUS").upper() == "CANCELLED":
            continue
        start, fn = _when(st, zones)
        if start is None:
            continue
        dur = _duration(ev, start, fn, zones)
        rr = _ics_get(ev, "RRULE")
        if rr and not _ics_get(ev, "RECURRENCE-ID"):
            skip = set(moved.get(_ics_text(ev, "UID"), set()))
            for ex in _ics_get(ev, "EXDATE", all_=True):
                for val in ex[2].split(","):
                    v, efn = _when(ex, zones, val)
                    if v is not None:
                        skip.add(_key(v, efn))
            starts = (c for c in _occurrences(start, _rrule(rr[2]), w1.date() + timedelta(days=1), fn)
                      if _key(c, fn) not in skip
                      and not (isinstance(c, datetime) and c.date().isoformat() in skip))
        else:
            starts = [start]
        title = _ics_text(ev, "SUMMARY") or "Busy"
        loc = _ics_text(ev, "LOCATION")
        # LPM puts its entry type (deadline, court_date, meeting...) in CATEGORIES
        kind = _ics_text(ev, "CATEGORIES").split(",")[0].strip().lower().replace(" ", "_")
        for c in starts:
            if isinstance(c, datetime):
                s = fn(c)
                e = s + dur
                if s < w1 and (e > w0 or s >= w0):
                    out.append({"title": title, "location": loc, "all_day": False, "cal": cal, "kind": kind,
                                "start": s.isoformat(timespec="seconds"), "end": e.isoformat(timespec="seconds")})
            else:
                e = c + max(dur, timedelta(days=1))
                if c < w1.date() and e > w0.date():
                    out.append({"title": title, "location": loc, "all_day": True, "cal": cal, "kind": kind,
                                "start": c.isoformat(), "end": e.isoformat()})
    return out


def fetch_agenda():
    urls = CONFIG["agenda_ics"]
    urls = [u.strip() for u in ([urls] if isinstance(urls, str) else urls) if u and u.strip()]
    if not urls:
        return {"configured": False, "items": []}
    w0 = now().replace(hour=0, minute=0, second=0, microsecond=0)
    w1 = w0 + timedelta(days=4)
    items, errors = [], []
    for i, url in enumerate(urls):
        try:
            text = http_get(re.sub(r"^webcal://", "https://", url, flags=re.I), accept="text/calendar")
            items += _ics_events(text, w0, w1, i)
        except Exception as e:  # noqa: BLE001 - the link is private, so it isn't logged
            errors.append(f"calendar {i + 1}: {e}")
    if len(errors) == len(urls):
        raise RuntimeError("; ".join(errors))
    seen, unique = set(), []
    for it in sorted(items, key=lambda x: (x["start"][:10], not x["all_day"], x["start"])):
        if (it["title"], it["start"]) not in seen:
            seen.add((it["title"], it["start"]))
            unique.append(it)
    return {"configured": True, "items": unique[:80], "errors": errors}


# ---------------------------------------------------------------- on demand
# Fetched only when someone opens a panel on the display, and kept briefly.

_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fn):
    """ttl is seconds, or a function of the value giving seconds. Expired entries are
    dropped on each store, so the cache doesn't grow without end."""
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() < hit[0]:
            return hit[1]
    value = fn()  # an exception is not cached
    with _cache_lock:
        t = time.time()
        for k in [k for k, (expires, _) in _cache.items() if expires <= t]:
            del _cache[k]
        _cache[key] = (t + (ttl(value) if callable(ttl) else ttl), value)
    return value


class CookieSafeRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies every header to a redirect target; the NYT cookie must only go to
    nytimes.com over https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and not (is_nyt(newurl) and newurl.lower().startswith("https://")):
            new.remove_header("Cookie")
        return new


_opener = urllib.request.build_opener(CookieSafeRedirect)


def http_get_with(url, headers, timeout=15, limit=3_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with _opener.open(req, timeout=timeout) as r:
        raw = r.read(limit)
        charset = r.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, "replace")


ARTICLE_FEEDS = ("nyt", "cnn", "toi", "yankees_news", "mlb_news")
ARTICLE_SOURCES = {"nyt": "New York Times", "cnn": "CNN", "toi": "Times of Israel",
                   "yankees_news": "Yankees news", "mlb_news": "MLB news"}
ARTICLE_FAILED = "The full article couldn't be loaded."


def feed_item_for(url):
    """The feed item linking to url. Only these are fetched, so the server can't be
    used to fetch arbitrary pages by anyone on the network."""
    for key in ARTICLE_FEEDS:
        for it in (store.get(key) or {}).get("items", []):
            if it.get("link") and it["link"] == url:
                return it
    return None


def is_nyt(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host == "nytimes.com" or host.endswith(".nytimes.com")


def article_headers(url):
    headers = {"Accept": "text/html"}
    cookie = (CONFIG.get("nyt_cookie") or "").strip()
    if cookie and is_nyt(url):
        headers["Cookie"] = cookie if "=" in cookie else "NYT-S=" + cookie
    return headers


class _Paragraphs(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "aside", "figure", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.article = 0     # depth inside <article> or the NYT's <section name="articleBody">
        self.section = []    # whether each open <section> is the NYT article body
        self.buf = None
        self.inside, self.outside = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "article":
            self.article += 1
        elif tag == "section":
            body = dict(attrs).get("name") == "articleBody"
            self.section.append(body)
            self.article += body
        elif tag == "p" and not self.skip:
            self.buf = []

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "article":
            self.article = max(0, self.article - 1)
        elif tag == "section" and self.section:
            self.article = max(0, self.article - self.section.pop())
        elif tag == "p" and self.buf is not None:
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            (self.inside if self.article else self.outside).append(text)
            self.buf = None

    def handle_data(self, data):
        if self.buf is not None and not self.skip:
            self.buf.append(data)


def extract_article(page):
    p = _Paragraphs()
    try:
        p.feed(page)
        p.close()
    except Exception:  # noqa: BLE001 - keep whatever was parsed
        pass
    seen, out = set(), []
    for text in p.inside or p.outside:
        if len(text) >= 40 and text not in seen:
            seen.add(text)
            out.append(text)
    return out


# Google News backup links are redirect pages with no article in them.
NO_ARTICLE_HOSTS = ("news.google.com",)
# Paywalled NYT pages say so in their JSON-LD; free pieces (briefs, newsletters) don't.
PAYWALLED = re.compile(r'"isAccessibleForFree"\s*:\s*"?false', re.I)


def article_json(url):
    item = feed_item_for(url)
    if item is None or urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise LookupError(url)

    def load():
        base = {"title": item.get("title"), "source": ARTICLE_SOURCES.get(item.get("source"), ""),
                "time": item.get("time")}
        paras, paywalled = [], False
        if (urllib.parse.urlparse(url).hostname or "").lower() not in NO_ARTICLE_HOSTS:
            try:
                page = http_get_with(url, article_headers(url))
                paras, paywalled = extract_article(page), bool(PAYWALLED.search(page))
            except Exception:  # noqa: BLE001 - the panel shows the summary instead
                log(f"article: {urllib.parse.urlparse(url).hostname} failed")
        if not paras:
            out = {**base, "ok": False, "summary": item.get("summary") or "", "message": ARTICLE_FAILED}
            if is_nyt(url):
                out["hint"] = ("The Times sometimes turns away requests that don't come from a browser. "
                               "If you added \"nyt_cookie\" to settings.json, it may have expired (see README).")
            return out
        return {**base, "ok": True, "paragraphs": paras, "truncated": is_nyt(url) and paywalled and len(paras) < 5}

    # a failure is retried after a minute, in case it was a passing network problem
    return cached("article:" + url, lambda j: 600 if j["ok"] else 60, load)


def article_route(query):
    url = (urllib.parse.parse_qs(query).get("url") or [""])[0]
    try:
        return 200, json.dumps(article_json(url))
    except LookupError:
        return 404, json.dumps({"ok": False, "message": "not found"})


def _decision(note):
    """'(W, 14-8)' -> ('W', '14-8'); '' -> ('', '')."""
    m = re.match(r"\((\w+),\s*([^)]*)\)", note or "")
    return (m.group(1), m.group(2)) if m else ("", "")


class GameNotFound(Exception):
    pass


def norm_boxscore(feed):
    gd, ld = feed.get("gameData", {}), feed.get("liveData", {})
    if not gd.get("status"):
        raise GameNotFound()
    st, ls = gd.get("status", {}), ld.get("linescore", {})
    detail = st.get("detailedState", "")
    state = "Off" if detail in ("Postponed", "Cancelled", "Suspended") else st.get("abstractGameState")
    names = {k: v.get("boxscoreName") for k, v in gd.get("players", {}).items()}
    box = ld.get("boxscore", {}).get("teams", {})
    decisions = {}

    def name(p):
        return names.get(f"ID{p['person']['id']}") or p["person"].get("fullName", "")

    def side(which):
        gt, bt = gd.get("teams", {}).get(which, {}), box.get(which, {})
        players = bt.get("players", {})
        batters = sorted((p for p in players.values() if p.get("battingOrder")
                          and p["person"]["id"] in bt.get("batters", [])),
                         key=lambda p: int(p["battingOrder"]))
        pitchers = []
        for pid in bt.get("pitchers", []):
            p = players.get(f"ID{pid}")
            if not p:
                continue
            s = p["stats"].get("pitching", {})
            letter, rec = _decision(s.get("note"))
            if letter in ("W", "L", "S"):
                decisions[letter.lower()] = f"{name(p)} ({rec})"
            pitchers.append({"name": name(p), "note": letter, "ip": s.get("inningsPitched"), "h": s.get("hits"),
                             "er": s.get("earnedRuns"), "bb": s.get("baseOnBalls"), "k": s.get("strikeOuts"),
                             "era": p["seasonStats"].get("pitching", {}).get("era")})
        line = ls.get("teams", {}).get(which, {})
        return {
            "abbr": gt.get("abbreviation"), "name": gt.get("teamName") or gt.get("name"),
            "r": line.get("runs"), "h": line.get("hits"), "e": line.get("errors"),
            "is_team": gt.get("id") == CONFIG["team_id"],
            "probable": (gd.get("probablePitchers", {}).get(which) or {}).get("fullName"),
            "batters": [{"name": name(p), "pos": p["position"]["abbreviation"].upper(),
                         "sub": not str(p["battingOrder"]).endswith("00"),
                         **{k: p["stats"].get("batting", {}).get(src) for k, src in
                            (("ab", "atBats"), ("r", "runs"), ("h", "hits"), ("rbi", "rbi"),
                             ("bb", "baseOnBalls"), ("k", "strikeOuts"))},
                         "avg": p["seasonStats"].get("batting", {}).get("avg")} for p in batters],
            "pitchers": pitchers,
        }

    away, home = side("away"), side("home")
    homers = []
    for play in ld.get("plays", {}).get("allPlays", []):
        if play["result"].get("eventType") == "home_run":
            b = play["matchup"]["batter"]
            n = re.search(r"\((\d+)\)", play["result"].get("description", ""))
            homers.append(f"{names.get(f'ID{b['id']}') or b.get('fullName')} ({n.group(1) if n else '?'})")
    off = ls.get("offense", {})
    return {
        "id": feed.get("gamePk"), "state": state, "detail": detail,
        "start": gd.get("datetime", {}).get("dateTime"), "venue": gd.get("venue", {}).get("name"),
        "inning": ls.get("currentInning"), "inning_state": ls.get("inningState"),
        "outs": ls.get("outs"), "balls": ls.get("balls"), "strikes": ls.get("strikes"),
        "bases": [bool(off.get("first")), bool(off.get("second")), bool(off.get("third"))],
        "innings": [{"num": i.get("num"), "away": i.get("away", {}).get("runs"), "home": i.get("home", {}).get("runs")}
                    for i in ls.get("innings", [])],
        "decisions": {k: decisions.get(k) for k in ("w", "l", "s")},
        "homers": homers, "away": away, "home": home,
    }


def game_json(pk):
    return cached(f"game:{pk}", lambda b: 25 if b.get("state") in ("Live", "Preview") else 600,
                  lambda: norm_boxscore(get_json(f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live")))


def game_id_from_query(query):
    v = (urllib.parse.parse_qs(query).get("id") or [""])[0]
    return int(v) if re.fullmatch(r"[0-9]{1,11}", v) else None  # ASCII digits only


def game_route(query):
    pk = game_id_from_query(query)
    if pk is None:
        return 404, json.dumps({"ok": False, "message": "not found"})
    try:
        return 200, json.dumps(game_json(pk))
    except GameNotFound:
        return 404, json.dumps({"ok": False, "message": "not found"})
    except urllib.error.HTTPError as e:
        return (404 if e.code == 404 else 503), json.dumps({"ok": False})
    except Exception as e:  # noqa: BLE001
        log(f"game {pk}: {e}")
        return 503, json.dumps({"ok": False})


RADAR_URL = "https://radar.weather.gov/ridge/standard/KOKX_loop.gif"  # Upton, NY
AQI_WORDS = ((50, "Good"), (100, "Moderate"), (150, "Unhealthy for sensitive groups"),
             (200, "Unhealthy"), (300, "Very unhealthy"))


def aqi_word(aqi):
    if aqi is None:
        return ""
    return next((w for top, w in AQI_WORDS if aqi <= top), "Hazardous")


def pressure_trend(values):
    """Over the last three hours of hourly pressure (hPa)."""
    if len(values) < 4 or None in values[-4:]:
        return "steady"
    d = values[-1] - values[-4]
    return "rising" if d >= 0.6 else "falling" if d <= -0.6 else "steady"


def build_forecast(om, aq, nws, start=None):
    c, h, d = om["current"], om["hourly"], om["daily"]
    tz = timezone(timedelta(seconds=om.get("utc_offset_seconds", 0)))
    start = start or now().astimezone(tz).strftime("%Y-%m-%dT%H:00")
    i0 = next((i for i, t in enumerate(h["time"]) if t >= start), 0)
    hours = [{"time": h["time"][i], "temp": round(h["temperature_2m"][i]),
              "precip": h["precipitation_probability"][i] or 0, "amount_in": h["precipitation"][i] or 0,
              "code": h["weather_code"][i], "is_day": bool(h["is_day"][i])}
             for i in range(i0, min(i0 + 48, len(h["time"])))]
    d0 = next((i for i, t in enumerate(d["time"]) if t >= start[:10]), 0)  # today
    days = [{"date": d["time"][i], "hi": round(d["temperature_2m_max"][i]), "lo": round(d["temperature_2m_min"][i]),
             "code": d["weather_code"][i], "precip": d["precipitation_probability_max"][i] or 0,
             "amount_in": d["precipitation_sum"][i] or 0}
            for i in range(d0 + 1, min(d0 + 8, len(d["time"])))]
    aqi = ((aq or {}).get("current") or {}).get("us_aqi")
    periods = [{"name": p["name"], "start": p["startTime"], "is_day": p["isDaytime"],
                "short": p["shortForecast"], "text": p["detailedForecast"]}
               for p in ((nws or {}).get("properties") or {}).get("periods", [])]
    t0 = datetime.fromisoformat(start).replace(tzinfo=tz)
    marks = []
    for it in (store.get("calendar") or {}).get("items", []):
        when = parse_dt(it.get("date")) if it.get("category") in ("candles", "havdalah") else None
        if when and t0 <= when < t0 + timedelta(hours=48):
            marks.append({"label": "Candles" if it["category"] == "candles" else "Havdalah",
                          "time": when.isoformat(timespec="minutes")})
    return {
        "now": {"temp": round(c["temperature_2m"]), "feels": round(c["apparent_temperature"]),
                "humidity": c["relative_humidity_2m"], "dew": round(c["dew_point_2m"]),
                "aqi": aqi, "aqi_word": aqi_word(aqi), "code": c["weather_code"], "is_day": bool(c["is_day"]),
                "wind_mph": round(c["wind_speed_10m"]), "wind_dir": compass(c["wind_direction_10m"]),
                "gust_mph": round(c.get("wind_gusts_10m") or 0), "uv": round(c.get("uv_index") or 0),
                "pressure_inhg": round(c["pressure_msl"] * 0.02953, 2),
                "pressure_trend": pressure_trend(h["pressure_msl"][max(0, i0 - 3):i0 + 1])},
        "hours": hours, "days": days, "periods": periods,
        "alerts": store.get("alerts") or [], "marks": marks,
    }


def forecast_json():
    def load():
        om = get_json("https://api.open-meteo.com/v1/forecast?" + qs({
            "latitude": CONFIG["lat"], "longitude": CONFIG["lon"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,weather_code,"
                       "wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,pressure_msl,is_day",
            "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,is_day,pressure_msl",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
            "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
            # yesterday too, so the 3-hour pressure trend works just after midnight
            "timezone": "auto", "forecast_days": 8, "past_days": 1}))
        try:
            aq = get_json("https://air-quality-api.open-meteo.com/v1/air-quality?" + qs({
                "latitude": CONFIG["lat"], "longitude": CONFIG["lon"], "current": "us_aqi"}))
        except Exception as e:  # noqa: BLE001 - the panel leaves air quality out
            log(f"air quality: {e}")
            aq = None
        global _nws_forecast_url
        try:
            if not _nws_forecast_url:
                p = get_json(f"https://api.weather.gov/points/{CONFIG['lat']},{CONFIG['lon']}",
                             accept="application/geo+json")
                _nws_forecast_url = p["properties"]["forecast"]
            nws = get_json(_nws_forecast_url, accept="application/geo+json")
        except Exception as e:  # noqa: BLE001 - the panel leaves the written forecast out
            log(f"nws forecast: {e}")
            nws = None
        return build_forecast(om, aq, nws)
    return cached("forecast", 600, load)


def radar_gif():
    def load():
        req = urllib.request.Request(RADAR_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read(15_000_000)
    return cached("radar", 300, load)


# ---------------------------------------------------------------- scheduler

SOURCES = [
    # key,            fetch function,               seconds between refreshes
    ("weather",       fetch_weather,                600),
    ("nws",           fetch_nws_forecast,           1800),
    ("alerts",        fetch_alerts,                 300),
    ("zmanim",        fetch_zmanim,                 600),
    ("hebdate",       fetch_hebdate,                300),
    ("calendar",      fetch_calendar,               3600),
    ("team",          fetch_team,                   team_poll_seconds),
    ("standings",     fetch_standings,              3600),
    ("scoreboard",    fetch_scoreboard,             scoreboard_poll_seconds),
    ("transactions",  fetch_transactions,           1800),
    ("yankees_news",  feed_fetcher("yankees_news"), 900),
    ("mlb_news",      feed_fetcher("mlb_news"),     900),
    ("nyt",           feed_fetcher("nyt"),          600),
    ("cnn",           fetch_cnn,                    600),
    ("toi",           feed_fetcher("toi"),          600),
    ("agenda",        fetch_agenda,                 600),
]


def run_source(key, fn, every):
    retry = 60
    while True:
        try:
            store.set(key, fn())
            retry = 60
            wait = every() if callable(every) else every
        except Exception as e:  # noqa: BLE001 - keep last good data and retry
            store.fail(key, e)
            log(f"{key}: {e}")
            interval = every() if callable(every) else every
            wait = min(retry, interval)
            retry = min(retry * 2, 900)
        time.sleep(wait)


def start_sources():
    for i, (key, fn, every) in enumerate(SOURCES):
        threading.Thread(target=run_source, args=(key, fn, every), daemon=True,
                         name=f"src-{key}").start()
        time.sleep(0.3)  # stagger startup requests


def state_json():
    snap = store.snapshot()
    cfg = {k: CONFIG[k] for k in ("location_name", "team_abbr", "division_name", "zmanim_labels",
                                  "dim_start", "dim_end", "dim_level", "rotation_seconds")}
    return json.dumps({"now": now().isoformat(timespec="seconds"), "config": cfg,
                       "data": snap["data"], "meta": snap["meta"]})


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                with open(PAGE_FILE, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._send(200, state_json(), "application/json")
            elif path == "/api/article":
                self._send(*article_route(parsed.query), "application/json")
            elif path == "/api/game":
                self._send(*game_route(parsed.query), "application/json")
            elif path == "/api/forecast":
                try:
                    self._send(200, json.dumps(forecast_json()), "application/json")
                except Exception as e:  # noqa: BLE001
                    log(f"forecast: {e}")
                    self._send(503, json.dumps({"ok": False}), "application/json")
            elif path == "/api/radar":
                try:
                    self._send(200, radar_gif(), "image/gif")
                except Exception as e:  # noqa: BLE001
                    log(f"radar: {e}")
                    self._send(503, "radar unavailable", "text/plain")
            elif path == "/health":
                self._send(200, "ok", "text/plain")
            elif path.startswith("/fonts/") and ".." not in path:
                fp = os.path.join(HERE, path.lstrip("/").replace("/", os.sep))
                with open(fp, "rb") as f:
                    self._send(200, f.read(), "font/woff2")
            else:
                self._send(404, "not found", "text/plain")
        except (OSError, ConnectionError):
            try:
                self._send(404, "not found", "text/plain")
            except OSError:
                pass

    def log_message(self, *args):
        pass


def check():
    ok = 0
    for key, fn, _ in SOURCES:
        t = time.time()
        try:
            val = fn()
            store.set(key, val)
            size = len(val.get("items", [])) if isinstance(val, dict) and "items" in val else ""
            print(f"  OK    {key:<14} {time.time() - t:4.1f}s  {size}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {key:<14} {e}")
    print(f"\n{ok}/{len(SOURCES)} sources working.")


def main():
    load_settings()
    if "--setting" in sys.argv:  # used by the setup scripts
        print(CONFIG.get(sys.argv[sys.argv.index("--setting") + 1], ""))
        return
    if "--check" in sys.argv:
        check()
        return
    try:
        server = ThreadingHTTPServer((CONFIG["bind"], CONFIG["port"]), Handler)
    except OSError as e:
        log(f"can't open port {CONFIG['port']} ({e}). Is the display server already running?")
        sys.exit(1)
    log(f"starting on http://{CONFIG['bind']}:{CONFIG['port']}")
    start_sources()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log(traceback.format_exc())
        raise
