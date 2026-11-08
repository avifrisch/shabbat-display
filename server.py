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
import copy
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
import zlib
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
    "rotation_seconds": {"agenda": 25, "shul": 30, "yankees": 30, "mlb": 30, "news": 30, "israel": 25},

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
SHUL_DIR = os.path.join(HERE, "shul")
SHUL_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "pdf": "application/pdf"}
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


# read by launcher.pyw, not the server
LAUNCHER_SETTINGS = {"screensaver_minutes", "screensaver_lock", "screensaver_screens", "keep_pc_awake", "server_url"}


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
        if k.startswith("_") or k in LAUNCHER_SETTINGS:
            continue
        if k not in CONFIG:
            log(f"settings.json: unknown setting '{k}' ignored")
        elif isinstance(CONFIG[k], dict) and isinstance(v, dict):
            CONFIG[k] = {**CONFIG[k], **v}
        else:
            CONFIG[k] = v


# ---------------------------------------------------------------- helpers

# Our own name, for every new source: never a browser's. The shul's site, ESPN, CNBC, Yahoo
# and the business feeds all answer it.
OWN_UA = "ShabbatDisplay/1.0 (personal home display)"


def http_get(url, accept="*/*", timeout=20, ua=UA):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": accept})
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

# ---------------------------------------------------------------- household
# What the Display Manager app sets: leagues and teams, the stock watchlist, each screen's
# rotation and mode, and the NYT sign-in. Kept in household.json, written only by this
# server and read again whenever the file changes. It overrides settings.json, which
# stays the machine's own setup and is never written here.

HOUSEHOLD_FILE = os.path.join(HERE, "household.json")
KEY_FILE = os.path.join(HERE, "manage-key.txt")
SCENE_SECONDS_RANGE = (5, 300)
# leagues other than MLB, all from ESPN's public site API; MLB stays on statsapi.mlb.com
LEAGUES = {
    "nba":   {"name": "NBA", "sport": "basketball", "path": "basketball/nba", "groups": None},
    "wnba":  {"name": "WNBA", "sport": "basketball", "path": "basketball/wnba", "groups": None},
    "nfl":   {"name": "NFL", "sport": "football", "path": "football/nfl", "groups": None},
    "nhl":   {"name": "NHL", "sport": "hockey", "path": "hockey/nhl", "groups": None},
    "mls":   {"name": "MLS", "sport": "soccer", "path": "soccer/usa.1", "groups": None},
    "ncaam": {"name": "Men's college basketball", "sport": "basketball",
              "path": "basketball/mens-college-basketball", "groups": 50},
    "ncaaw": {"name": "Women's college basketball", "sport": "basketball",
              "path": "basketball/womens-college-basketball", "groups": 50},
    "ncaaf": {"name": "College football", "sport": "football", "path": "football/college-football", "groups": 80},
}
SERVER_PC = "DESKTOP-H72VKDJ"  # the always-on display; the only screen that keeps the agenda at first

_household_lock = threading.RLock()
_household_cache = None
_household_mtime = None
_household_noted = None
seen = {}  # screen name -> {"last": epoch seconds, "launcher": bool}, in memory only


def default_household():
    """Today's display, as the household config it becomes on first start."""
    secs = CONFIG["rotation_seconds"]
    rot = [{"scene": s, "seconds": int(secs.get(s, 30)), "on": True}
           for s in ("shul", "yankees", "mlb", "news", "israel", "business")]
    sports = {"mlb": {"on": True, "favorite": CONFIG["team_id"],
                      "teams": [{"id": CONFIG["team_id"], "abbr": CONFIG["team_abbr"], "name": "New York Yankees"}
                                if CONFIG["team_id"] == 147 else
                                {"id": CONFIG["team_id"], "abbr": CONFIG["team_abbr"], "name": CONFIG["team_abbr"]}]}}
    sports.update({k: {"on": False, "teams": [], "favorite": None} for k in LEAGUES})
    agenda = {"scene": "agenda", "seconds": int(secs.get("agenda", 25)), "on": True}
    return {
        "version": 1,
        "sports": sports,
        "business": {"on": True, "watchlist": [], "news": {"biz_nyt": True, "biz_cnbc": True}},
        "default_rotation": rot,
        "screens": {SERVER_PC: {"rotation": [agenda] + copy.deepcopy(rot), "launcher": True, "saved": False,
                                "mode": "always", "saver": default_saver(), "local": None}},
        "secrets": {"nyt_cookie": ""},
    }


def default_saver():
    return {"minutes": 10, "lock": True, "screens": "all", "keep_awake": False}


def _fill_household(h):
    """Add whatever an older or hand-trimmed file is missing."""
    d = default_household()
    for k, v in d.items():
        if k != "screens" and not isinstance(h.get(k), type(v)):
            h[k] = v
    h.setdefault("screens", {})
    for k, v in d["sports"].items():
        if not isinstance(h["sports"].get(k), dict):
            h["sports"][k] = v
    h["secrets"].setdefault("nyt_cookie", "")
    return h


def household():
    """The household config (a copy, safe to change and pass to save_household())."""
    global _household_cache, _household_mtime, _household_noted
    with _household_lock:
        try:
            mtime = os.path.getmtime(HOUSEHOLD_FILE)
        except OSError:
            mtime = None
        if mtime is None:
            if _household_cache is None:
                _household_cache = default_household()
                save_household(_household_cache)
                log("household.json created from the current settings")
        elif mtime != _household_mtime:
            try:
                with open(HOUSEHOLD_FILE, encoding="utf-8") as f:
                    h = json.load(f)
                if not isinstance(h, dict):
                    raise ValueError("not a JSON object")
                _household_cache, _household_mtime = _fill_household(h), mtime
            except (OSError, ValueError) as e:
                if _household_noted != mtime:
                    _household_noted = mtime
                    log(f"household.json can't be read ({e}); using the last good copy")
                if _household_cache is None:
                    return default_household()
        return copy.deepcopy(_household_cache)


def save_household(h):
    global _household_cache, _household_mtime
    with _household_lock:
        tmp = HOUSEHOLD_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(h, f, indent=1)
        os.replace(tmp, HOUSEHOLD_FILE)
        _household_cache = _fill_household(copy.deepcopy(h))
        try:
            _household_mtime = os.path.getmtime(HOUSEHOLD_FILE)
        except OSError:
            _household_mtime = None


def manage_key():
    """The Display Manager's access code, made on first start. Secret: never logged or returned."""
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            k = f.read().strip()
        if k:
            return k
    except OSError:
        pass
    import secrets
    k = secrets.token_urlsafe(24)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(k + "\n")
    return k


def nyt_cookie():
    """The NYT sign-in cookie: the one set from the app, else settings.json's. Secret."""
    return (household()["secrets"].get("nyt_cookie") or CONFIG.get("nyt_cookie") or "").strip()

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


def mlb_team_info(team_id):
    """An MLB team's abbreviation, division and league, looked up once a week."""
    def get():
        t = get_json(f"{MLB}/teams/{int(team_id)}?hydrate=division")["teams"][0]
        div = (t.get("division") or {}).get("name") or ""
        short = div.replace("American League", "AL").replace("National League", "NL")
        return {"id": t["id"], "abbr": t.get("abbreviation"), "name": t.get("teamName") or t.get("name"),
                "division_id": (t.get("division") or {}).get("id"), "division_name": short,
                "league_id": (t.get("league") or {}).get("id")}
    return cached(f"mlbteam:{int(team_id)}", 7 * 86400, get)


def mlb_favorite():
    """The favorite MLB team chosen in the app; the Yankees (CONFIG) if none or the lookup fails."""
    own = {"id": CONFIG["team_id"], "abbr": CONFIG["team_abbr"], "name": None,
           "division_id": CONFIG["division_id"], "division_name": CONFIG["division_name"],
           "league_id": CONFIG["league_id"]}
    fav = household()["sports"]["mlb"].get("favorite")
    if not fav or fav == CONFIG["team_id"]:
        return own
    try:
        return mlb_team_info(fav)
    except Exception as e:  # noqa: BLE001
        log(f"MLB team {fav} lookup failed ({e}); showing team {CONFIG['team_id']}")
        return own


def mlb_on():
    return bool(household()["sports"]["mlb"].get("on", True))


def fetch_team():
    if not mlb_on():
        return {"off": True}
    bd = baseball_day()
    games = schedule({"teamId": mlb_favorite()["id"],
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
    if not mlb_on():
        return {"off": True}
    fav = mlb_favorite()
    j = get_json(f"{MLB}/standings?" + qs({
        "leagueId": fav["league_id"], "season": season_year(),
        "standingsTypes": "regularSeason", "hydrate": "team"}))
    for rec in j.get("records", []):
        if (rec.get("division") or {}).get("id") != fav["division_id"]:
            continue
        teams = []
        for tr in rec.get("teamRecords", []):
            t = tr["team"]
            teams.append({
                "abbr": t.get("abbreviation"), "name": t.get("teamName") or t.get("name"),
                "w": tr.get("wins"), "l": tr.get("losses"), "gb": tr.get("gamesBack"),
                "pct": tr.get("winningPercentage"),
                "streak": (tr.get("streak") or {}).get("streakCode"),
                "rank": tr.get("divisionRank"), "is_team": t.get("id") == fav["id"],
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
    if not mlb_on():
        return {"off": True}
    today = now().date()
    team_id = mlb_favorite()["id"]
    team_name = None
    team = []
    for t in _transactions({"teamId": team_id,
                            "startDate": (today - timedelta(days=45)).isoformat(),
                            "endDate": today.isoformat()}):
        desc = t.get("description") or ""
        if not desc or any(s in desc.lower() for s in TEAM_SKIP_TEXT) \
                or (t.get("typeDesc") or "") == "Number Change":
            continue
        if not team_name:
            for side in ("toTeam", "fromTeam"):
                if (t.get(side) or {}).get("id") == team_id:
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


# ---------------------------------------------------------------- other leagues (ESPN)
# Every league but MLB, from ESPN's public site API (unofficial, like statsapi). Asked with
# our own User-Agent. A date range in ?dates= answers 400, so each request is one day.

ESPN = "https://site.api.espn.com/apis"
STANDING_COLS = {
    "basketball": [("W", "wins"), ("L", "losses"), ("GB", "gamesBehind"), ("Strk", "streak")],
    "football": [("W", "wins"), ("L", "losses"), ("T", "ties"), ("Strk", "streak")],
    "hockey": [("W", "wins"), ("L", "losses"), ("OTL", "otLosses"), ("PTS", "points")],
    "soccer": [("W", "wins"), ("D", "ties"), ("L", "losses"), ("PTS", "points")],
}
ESPN_STATE = {"pre": "Preview", "in": "Live", "post": "Final"}


def espn_json(url):
    return json.loads(http_get(url, accept="application/json", ua=OWN_UA))


def _espn_score(v):
    if isinstance(v, dict):
        v = v.get("value", v.get("displayValue"))
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def norm_espn_game(ev, chosen):
    """An ESPN event (from the scoreboard or a team schedule) in the page's game shape."""
    co = (ev.get("competitions") or [{}])[0]
    st = ev.get("status") or co.get("status") or {}
    ty = st.get("type") or {}
    state = ESPN_STATE.get(ty.get("state"), "Preview")
    if any(w in (ty.get("name") or "") for w in ("POSTPONED", "CANCELED", "SUSPENDED")):
        state = "Off"
    sides = {}
    for c in co.get("competitors") or []:
        t = c.get("team") or {}
        try:
            tid = int(t.get("id"))
        except (TypeError, ValueError):
            tid = None
        rec = (c.get("records") or c.get("record") or [{}])[0]
        lines = [_espn_score(x) for x in c.get("linescores") or []]
        sides[c.get("homeAway")] = {
            "id": tid, "abbr": t.get("abbreviation") or "TBD", "name": t.get("shortDisplayName") or t.get("name") or "TBD",
            "full": t.get("displayName"), "score": _espn_score(c.get("score")),
            "record": rec.get("summary") or rec.get("displayValue"),
            "winner": c.get("winner"), "lines": [x for x in lines if x is not None]}

    def blank():
        return {"id": None, "abbr": "TBD", "name": "TBD", "full": None, "score": None, "record": None,
                "winner": None, "lines": []}
    away, home = sides.get("away") or blank(), sides.get("home") or blank()
    return {"id": str(ev["id"]) if ev.get("id") is not None else None, "start": ev.get("date"),
            "state": state, "detail": ty.get("shortDetail") or ty.get("detail") or "",
            "period": st.get("period"), "clock": st.get("displayClock"),
            "venue": (co.get("venue") or {}).get("fullName"), "away": away, "home": home,
            "chosen": bool({away["id"], home["id"]} & set(chosen))}


def espn_in_season(calendar, today):
    """Any game day, or week that isn't the off-season, from 3 days back to 7 ahead."""
    lo, hi = today - timedelta(days=3), today + timedelta(days=7)

    def day(x):
        p = parse_dt(x) if isinstance(x, str) else None
        return p.date() if p else None

    for c in calendar or []:
        if isinstance(c, str):
            d = day(c)
            if d and lo <= d <= hi:
                return True
        elif isinstance(c, dict) and "off season" not in (c.get("label") or "").lower():
            for e in c.get("entries") or [c]:
                a, b = day(e.get("startDate")), day(e.get("endDate"))
                if a and b and a <= hi and b >= lo:
                    return True
    return False


def norm_espn_standings(j, sport, favorite):
    """The favorite's group (the deepest one listing it, else the first) as a small table."""
    groups = []

    def walk(g, depth):
        if (g.get("standings") or {}).get("entries"):
            groups.append((depth, g))
        for c in g.get("children") or []:
            walk(c, depth + 1)
    walk(j or {}, 0)
    if not groups:
        return None

    def has_fav(g):
        return any(str((e.get("team") or {}).get("id")) == str(favorite) for e in g["standings"]["entries"])
    mine = [x for x in groups if favorite is not None and has_fav(x[1])]
    g = max(mine, key=lambda x: x[0])[1] if mine else groups[0][1]
    cols = STANDING_COLS.get(sport, STANDING_COLS["basketball"])
    rows = []
    for e in g["standings"]["entries"]:
        t = e.get("team") or {}
        stats = {x.get("name"): x.get("displayValue") for x in e.get("stats") or []}
        rows.append({"abbr": t.get("abbreviation"), "name": t.get("shortDisplayName") or t.get("name"),
                     "vals": [stats.get(k, "") for _, k in cols],
                     "is_team": favorite is not None and str(t.get("id")) == str(favorite)})
    return {"group": g.get("name"), "cols": [c for c, _ in cols], "rows": rows}


def _espn_news(path, team=None):
    url = f"{ESPN}/site/v2/sports/{path}/news" + (f"?team={int(team)}" if team else "")
    items = []
    for a in espn_json(url).get("articles") or []:
        link = ((a.get("links") or {}).get("web") or {}).get("href")
        if a.get("headline") and link:
            items.append({"title": clean_text(a["headline"]), "summary": clean_text(a.get("description"), 300),
                          "link": link, "time": a.get("published"), "source": "espn"})
    return {"items": items[:12]}


def league_settings(key):
    return household()["sports"].get(key) or {"on": False, "teams": [], "favorite": None}


def fetch_league(key):
    """One league: today's scores (yesterday's if none), the favorite's live/last/next game,
    its standings group, and news. {"off": True} while the league is switched off."""
    lg, cfg = LEAGUES[key], league_settings(key)
    if not cfg.get("on"):
        return {"off": True}
    path = lg["path"]
    chosen = {t["id"] for t in cfg.get("teams") or []}
    fav = cfg.get("favorite")
    grp = f"&groups={lg['groups']}" if lg["groups"] else ""
    n = now()
    today = n.date()
    board = espn_json(f"{ESPN}/site/v2/sports/{path}/scoreboard?dates={today:%Y%m%d}{grp}")
    calendar = ((board.get("leagues") or [{}])[0]).get("calendar") or []
    games, label = [norm_espn_game(e, chosen) for e in board.get("events") or []], "Today"
    if not games:
        y = espn_json(f"{ESPN}/site/v2/sports/{path}/scoreboard?dates={today - timedelta(days=1):%Y%m%d}{grp}")
        games = [norm_espn_game(e, chosen) for e in y.get("events") or []]
        label = "Yesterday" if games else label
    team = None
    for tid in sorted(chosen, key=lambda t: t != fav):
        sched = [norm_espn_game(e, chosen) for e in
                 espn_json(f"{ESPN}/site/v2/sports/{path}/teams/{int(tid)}/schedule").get("events") or []]
        have = {g["id"] for g in games}
        games += [g for g in sched if g["id"] not in have and (parse_dt(g["start"]) or n).astimezone().date() == today]
        if tid == fav:
            live = next((g for g in sched if g["state"] == "Live"), None)
            upcoming = [g for g in sched if g["state"] == "Preview"
                        and (parse_dt(g["start"]) or n) > n - timedelta(hours=4)]
            finals = [g for g in sched if g["state"] == "Final"]
            team = {"live": live, "next": upcoming[0] if upcoming else None,
                    "last": finals[-1] if finals else None, "recent": finals[-5:]}
    order = {"Live": 0, "Preview": 1, "Final": 2, "Off": 3}
    games.sort(key=lambda g: (not g["chosen"], order.get(g["state"], 4), g["start"] or ""))
    try:
        standings = cached(f"espnstand:{key}:{fav}", 3600, lambda: norm_espn_standings(
            espn_json(f"{ESPN}/v2/sports/{path}/standings"), lg["sport"], fav))
    except Exception as e:  # noqa: BLE001 - the scores still show without the table
        log(f"sport_{key} standings: {e}")
        standings = None
    news = cached(f"espnnews:{key}", 900, lambda: _espn_news(path))
    team_news = cached(f"espnnews:{key}:{fav}", 900, lambda: _espn_news(path, fav)) if fav else {"items": []}
    soon = bool(team and (team["live"] or (team["next"] and
                                           (parse_dt(team["next"]["start"]) or n) - n < timedelta(days=7))))
    return {"on": True, "in_season": espn_in_season(calendar, today) or soon,
            "team": team, "scores": {"label": label, "games": games}, "standings": standings,
            "team_news": team_news, "news": news}


def league_poll_seconds(key):
    """Every 30 s while a chosen team plays or starts within 15 minutes; hourly out of season."""
    if not league_settings(key).get("on"):
        return 600
    v = store.get("sport_" + key) or {}
    if not v.get("on"):
        return 180
    t = v.get("team") or {}
    if t.get("live") or any(g.get("chosen") and g.get("state") == "Live"
                            for g in (v.get("scores") or {}).get("games") or []):
        return 30
    nxt = t.get("next")
    start = parse_dt(nxt["start"]) if nxt else None
    if start and start - now() < timedelta(minutes=15):
        return 30
    return 180 if v.get("in_season") else 3600


def league_fetcher(key):
    return lambda: fetch_league(key)


def league_poller(key):
    return lambda: league_poll_seconds(key)


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
                   "yankees_news": "Yankees news", "mlb_news": "MLB news", "espn": "ESPN"}
ARTICLE_FAILED = "The full article couldn't be loaded."


def feed_item_for(url):
    """The feed item linking to url. Only these are fetched, so the server can't be
    used to fetch arbitrary pages by anyone on the network."""
    for key in ARTICLE_FEEDS:
        for it in (store.get(key) or {}).get("items", []):
            if it.get("link") and it["link"] == url:
                return it
    for key in LEAGUES:
        v = store.get("sport_" + key) or {}
        for part in ("news", "team_news"):
            for it in (v.get(part) or {}).get("items", []):
                if it.get("link") and it["link"] == url:
                    return it
    return None


def is_nyt(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host == "nytimes.com" or host.endswith(".nytimes.com")


def article_headers(url):
    headers = {"Accept": "text/html"}
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host == "espn.com" or host.endswith(".espn.com"):
        headers["User-Agent"] = OWN_UA
    cookie = nyt_cookie() if is_nyt(url) else ""
    if cookie:
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
            "is_team": gt.get("id") == mlb_favorite()["id"],
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


# ---------------------------------------------------------------- shul
# Bnai Yeshurun's weekly davening chart, Shabbat bulletin and monthly calendar.
# The bulletin is a PDF; this reads just enough of the format to get its text.

_PDF_TOKEN = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/\[\]()<>{}%]+"
                        rb"|[-+]?\d*\.?\d+|[A-Za-z'\"*]+")
_PDF_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}


def _pdf_literal(tok):
    s, out, i = tok[1:-1], bytearray(), 0
    while i < len(s):
        c = s[i]
        if c != 0x5C or i + 1 >= len(s):
            out.append(c)
            i += 1
            continue
        n = s[i + 1]
        if n in _PDF_ESC:
            out.append(_PDF_ESC[n])
            i += 2
        elif 48 <= n <= 55:  # octal
            j, v = i + 1, 0
            while j < len(s) and j < i + 4 and 48 <= s[j] <= 55:
                v, j = v * 8 + s[j] - 48, j + 1
            out.append(v & 255)
            i = j
        elif n in (10, 13):  # line continuation
            i += 2
        else:
            out.append(n)
            i += 2
    return bytes(out)


def _pdf_stream(body):
    m = re.search(rb"stream\r?\n(.*)\r?\nendstream", body, re.S)
    if not m:
        return b""
    raw = m.group(1)
    if b"/FlateDecode" in body:
        return zlib.decompressobj().decompress(raw)
    return raw


def _pdf_tounicode(objs, font_num):
    """{code: text}, code width in bytes; ({}, 0) for a plain single-byte font."""
    m = re.search(rb"/ToUnicode\s+(\d+) 0 R", objs.get(font_num, b""))
    if not m:
        return {}, 0
    cm = _pdf_stream(objs.get(int(m.group(1)), b""))
    mp, width = {}, 1
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", cm, re.S):
        for a, u in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            width = len(a) // 2
            mp[int(a, 16)] = bytes.fromhex(u.decode()).decode("utf-16-be", "replace")
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", cm, re.S):
        for a, b, u, arr in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(?:<([0-9A-Fa-f]+)>|\[([^\]]*)\])", blk):
            width, lo, hi = len(a) // 2, int(a, 16), int(b, 16)
            if hi - lo > 0xFFFF:  # a real range stays within 256 codes; never list millions
                continue
            if not u:  # [<target> <target> ...]: one per code, e.g. pointed Hebrew letters
                for c, t in zip(range(lo, hi + 1), re.findall(rb"<([0-9A-Fa-f]+)>", arr)):
                    mp[c] = bytes.fromhex(t.decode()).decode("utf-16-be", "replace")
                continue
            # the target is UTF-16 (maybe a surrogate pair); the range counts up its last unit
            dst = bytes.fromhex(u.decode())
            head, last = dst[:-2], int.from_bytes(dst[-2:], "big")
            for i, c in enumerate(range(lo, hi + 1)):
                mp[c] = (head + ((last + i) & 0xFFFF).to_bytes(2, "big")).decode("utf-16-be", "replace")
    return mp, width


def _pdf_page_runs(objs, page):
    fd = re.search(rb"/Font\s*<<(.*?)>>", page, re.S)
    fonts = {k.decode(): _pdf_tounicode(objs, int(v))
             for k, v in re.findall(rb"/([^\s/]+)\s+(\d+) 0 R", fd.group(1) if fd else b"")}
    cm = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+ 0 R)", page)
    refs = [int(r) for r in re.findall(rb"(\d+) 0 R", cm.group(1))] if cm else []
    content = b"\n".join(_pdf_stream(objs.get(r, b"")) for r in refs)
    runs, stack, font = [], [], None
    tm, lm, lead = [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0], 0.0

    def show(b):
        mp, w = fonts.get(font, ({}, 0))
        if not w:
            return b.decode("cp1252", "replace")
        return "".join(mp.get(int.from_bytes(b[i:i + w], "big"), "") for i in range(0, len(b), w))

    def emit(text):
        if text:
            runs.append((round(tm[4], 1), round(tm[5], 1), text))

    for tok in _PDF_TOKEN.findall(content):
        c = tok[:1]
        if c == b"(":
            stack.append(_pdf_literal(tok))
        elif c == b"<":
            hexs = re.sub(rb"\s", b"", tok[1:-1])
            stack.append(bytes.fromhex(hexs.decode() + ("0" if len(hexs) % 2 else "")))
        elif tok == b"[":
            stack.append("[")
        elif tok == b"]":
            arr = []
            while stack and stack[-1] != "[":
                arr.insert(0, stack.pop())
            if stack:
                stack.pop()
            stack.append(arr)
        elif c == b"/":
            stack.append(tok[1:].decode("latin-1"))
        elif re.fullmatch(rb"[-+]?\d*\.?\d+", tok):
            stack.append(float(tok))
        else:
            op = tok.decode("latin-1")
            nums = [v for v in stack if isinstance(v, float)]
            if op == "Tf" and len(stack) >= 2 and isinstance(stack[-2], str):
                font = stack[-2]
            elif op == "Tm" and len(nums) >= 6:
                tm = nums[-6:]
                lm = list(tm)
            elif op in ("Td", "TD") and len(nums) >= 2:
                lm[4] += nums[-2] * lm[0]
                lm[5] += nums[-1] * lm[3]
                tm = list(lm)
                if op == "TD":
                    lead = -nums[-1]
            elif op == "TL" and nums:
                lead = nums[-1]
            elif op == "T*":
                lm[5] -= lead
                tm = list(lm)
            elif op == "BT":
                tm, lm = [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0]
            elif op in ("Tj", "'", '"') and stack and isinstance(stack[-1], bytes):
                emit(show(stack[-1]))
            elif op == "TJ" and stack and isinstance(stack[-1], list):
                emit("".join(show(v) if isinstance(v, bytes) else (" " if v < -200 else "")
                             for v in stack[-1] if isinstance(v, (bytes, float))))
            stack = []
    return runs


def pdf_pages(data):
    """Text runs (x, y, text) for each page, in page order. Needs plain (not object-stream) pages."""
    objs = {int(m.group(1)): m.group(2)
            for m in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", data, re.S)}
    pages = [n for n in sorted(objs) if re.search(rb"/Type\s*/Page(?![s\w])", objs[n])]
    if not pages:
        raise ValueError("no readable pages in the PDF")
    return [_pdf_page_runs(objs, objs[n]) for n in pages]


SHUL_SITE = "https://www.bnaiyeshurun.org"
SHUL_FILES = "https://images.shulcloud.com/"
# The shul's site turns away generic tools but answers a request that says what it is.
# Never swap this for a browser's User-Agent to get past a refusal.
SHUL_UA = OWN_UA
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _shul_urls(page, folder, ext):
    found = []
    for u in re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", page or "", re.I):
        u = html.unescape(u)
        if u.startswith(SHUL_FILES) and f"/uploads/{folder}/" in u and re.search(ext + r"$", u, re.I) \
                and u not in found:
            found.append(u)
    return found


def shul_links(minyan_html, bulletin_html, calendar_html):
    """The newest weekly chart and bulletin, and every monthly calendar image, from the shul's pages."""
    chart = _shul_urls(minyan_html, "Weekly-Davening-Schedule", r"\.(png|jpe?g)")
    bulletin = _shul_urls(bulletin_html, "Bulletin", r"\.pdf")
    return {"chart": chart[0] if chart else None, "bulletin": bulletin[0] if bulletin else None,
            "calendars": _shul_urls(calendar_html, "Monthly-Calendars", r"\.jpe?g")}


def file_date(name, today):
    """The date in a shul file name ("24Oct-LechLecha.pdf", "Oct25-weeklydavening.png"),
    in the year that puts it nearest today; None if there is none."""
    m = re.match(r"(\d{1,2})([A-Za-z]{3,9})\b|([A-Za-z]{3,9})(\d{1,2})-", name)
    if not m:
        return None
    day, mon = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    if mon[:3].lower() not in _MONTHS:
        return None
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            d = date(y, _MONTHS.index(mon[:3].lower()) + 1, int(day))
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def upcoming_shabbat(today):
    return today + timedelta(days=(5 - today.weekday()) % 7)


# Where the bulletin's "Shabbat Times" box puts things, in PDF points, measured
# on the real bulletin: labels left of 180, times 180-228, Hebrew from 228 to
# the box's right edge (found from the gap before the page's next column).
SHABBAT_TIME = re.compile(r"(\d{1,2}:\d{2}) ?([ap]m)", re.I)
_TIME_X, _HEB_X, _BOX_RIGHT = 180, 228, 316
_HEBREW = re.compile(r"[֐-׿]")


def _note_text(parts):
    """A line that isn't a row: its English left to right, then its Hebrew right to
    left. A space run goes with the nearest run that isn't a space."""
    solid = [(x, t) for x, t in parts if t.strip()]
    heb, rest = [], []
    for x, t in parts:
        ref = t if t.strip() else min(solid, key=lambda p: abs(p[0] - x), default=(0, ""))[1]
        (heb if _HEBREW.search(ref) else rest).append((x, t))
    latin = " ".join(s for s in (_join_runs([p for p in rest if p[0] < _TIME_X]),
                                 _join_runs([p for p in rest if p[0] >= _TIME_X])) if s)
    hebrew = " ".join("".join(t for x, t in sorted(heb, reverse=True)).split())
    return " ".join(s for s in (latin, hebrew) if s)


def _join_runs(runs):
    """Join a line's runs left to right. Word stores spaces as runs of their own,
    except sometimes between a word and a time ("at" "9:15")."""
    out = ""
    for x, t in sorted(runs):
        if out[-1:].isalpha() and t[:1].isdigit():
            out += " "
        out += t
    return " ".join(out.split())


def shabbat_times(pages):
    """The bulletin's Shabbat Times box as {"rows": [{label, time, he}],
    "notes": [{text, after}]} (after = rows above the note), or None when there is
    no box that reads cleanly. Never a partial guess."""
    for runs in pages:
        head = next(((x, y) for x, y, t in runs if t.strip() == "Shabbat Times"), None)
        if head:
            break
    else:
        return None
    top = head[1] - 3
    # right edge: the first gap of more than 8 pt between run starts right of 280,
    # and never past where the box ends on the real bulletin (x 308)
    xs = sorted({x for x, y, t in runs if x > 280 and y < top})
    right = min(next((a + 8 for a, b in zip(xs, xs[1:]) if b - a > 8), _BOX_RIGHT), _BOX_RIGHT)
    box = sorted(((x, y, t) for x, y, t in runs if y < top and x < right), key=lambda r: (-r[1], r[0]))
    lines = []  # [y, [(x, text)], [y of each run]] top to bottom, runs within 3.5 pt of a line's first y
    for x, y, t in box:
        if lines and lines[-1][0] - y <= 3.5:
            lines[-1][1].append((x, t))
            lines[-1][2].append(y)
        else:
            lines.append([y, [(x, t)], [y]])
    kept = []
    for y, parts, ys in lines:
        text = _join_runs(parts)
        if text.startswith("Please park") or (kept and kept[-1][0] - y > 25):
            break
        if text:
            kept.append((y, parts, ys))
    anchors = []  # (y of the time itself, time)
    for y, parts, ys in kept:
        tcol = [(x, t, ry) for (x, t), ry in zip(parts, ys) if _TIME_X <= x < _HEB_X]
        m = SHABBAT_TIME.fullmatch("".join(t for x, t, _ in sorted(tcol)).replace(" ", ""))
        if m:
            anchors.append((sum(ry for _, _, ry in tcol) / len(tcol), f"{m.group(1)} {m.group(2).lower()}"))
    rows = [{"y": y, "time": t, "label": [], "he": []} for y, t in anchors]
    notes = []
    for y, parts, _ in kept:
        near = min(rows, key=lambda r: abs(r["y"] - y), default=None)
        if near is None or abs(near["y"] - y) > 10:
            notes.append({"text": _note_text(parts), "y": y})
            continue
        label = _join_runs([(x, t) for x, t in parts if x < _TIME_X])
        heb_col = [(x, t) for x, t in parts if x >= _HEB_X]
        if any(re.search(r"[A-Za-z0-9]", t) for _, t in heb_col):
            return None  # something other than Hebrew where a row's Hebrew goes: the layout changed
        he = "".join(t for x, t in sorted(heb_col, reverse=True))
        if label:
            near["label"].append(label)
        if he.strip():
            near["he"].append(" ".join(he.split()))
    out = [{"label": " ".join(r["label"]), "time": r["time"], "he": " ".join(r["he"])} for r in rows]
    if not any("Candle" in r["label"] for r in out) or not any("Ends" in r["label"] for r in out):
        return None
    return {"rows": out,
            "notes": [{"text": n["text"], "after": sum(1 for r in rows if r["y"] > n["y"])} for n in notes]}


def shul_get(url, limit=20_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": SHUL_UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(limit)


def _shul_files(cur):
    cur = cur or {}
    return [e["file"] for e in [cur.get("chart"), cur.get("bulletin"), *(cur.get("calendars") or [])] if e]


def todays_candles():
    today = now().date().isoformat()
    for it in (store.get("calendar") or {}).get("items", []):
        if it.get("category") == "candles" and (it.get("date") or "").startswith(today):
            return parse_dt(it["date"])
    return None


def shul_due(n, cur, candles):
    """Fetch when nothing is stored or a stored file is gone; on Friday or any day
    with candle lighting (Erev Yom Tov), from noon until candle lighting, while the
    bulletin is dated before today; and 8:00-20:00 on weekdays while the chart is
    more than 6 days old. Never on Saturday. The source runs at most hourly."""
    if not cur or any(not os.path.exists(os.path.join(SHUL_DIR, f)) for f in _shul_files(cur)):
        return True
    if n.weekday() == 5:
        return False
    today = n.date().isoformat()
    if (candles is not None or n.weekday() == 4) and n.hour >= 12 \
            and n < (candles or n.replace(hour=18, minute=0, second=0, microsecond=0)):
        shabbat = (cur.get("bulletin") or {}).get("shabbat")
        if not shabbat or shabbat < today:
            return True
    week = (cur.get("chart") or {}).get("week_of")
    return bool(week) and 8 <= n.hour < 20 and (n.date() - date.fromisoformat(week)).days > 6


class ShulBusy(Exception):
    pass


_shul_lock = threading.Lock()


def fetch_shul(force=False, wait=True):
    """One fetch at a time: the source thread waits its turn, an update request
    (wait=False) gets ShulBusy instead."""
    if not _shul_lock.acquire(blocking=wait):
        raise ShulBusy("already updating")
    try:
        return _fetch_shul(force)
    finally:
        _shul_lock.release()


def _fetch_shul(force):
    cur = store.get("shul")
    n = now()
    if not force and not shul_due(n, cur, todays_candles()):
        return cur
    cur = cur or {}
    links = shul_links(*(shul_get(f"{SHUL_SITE}/{p}").decode("utf-8", "replace")
                         for p in ("minyan", "bulletin", "monthlycalendar")))
    os.makedirs(SHUL_DIR, exist_ok=True)

    def keep_or_get(old, url):
        """(entry, bytes or None): the stored entry when the URL hasn't changed, else a fresh download."""
        if old and old.get("url") == url and os.path.exists(os.path.join(SHUL_DIR, old["file"])):
            return old, None
        name = re.sub(r"[^A-Za-z0-9._-]", "_", urllib.parse.unquote(url.rsplit("/", 1)[-1])).lstrip(".")
        data = shul_get(url)
        tmp = os.path.join(SHUL_DIR, name + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, os.path.join(SHUL_DIR, name))
        return {"file": name, "url": url}, data

    def dated(entry, key):
        d = file_date(entry["file"], n.date())
        return dict(entry, **{key: d.isoformat() if d else None})

    chart, bulletin = cur.get("chart"), cur.get("bulletin")
    if links["chart"]:
        chart = dated(keep_or_get(chart, links["chart"])[0], "week_of")
    if links["bulletin"]:
        entry, data = keep_or_get(bulletin, links["bulletin"])
        if data is not None:
            try:
                entry["times"] = shabbat_times(pdf_pages(data))
            except Exception as e:  # noqa: BLE001 - an unreadable bulletin still gets shown as a PDF
                log(f"shul: bulletin times not readable ({e})")
                entry["times"] = None
        bulletin = dated(entry, "shabbat")
    old_cals = {c["url"]: c for c in cur.get("calendars") or []}
    calendars = [keep_or_get(old_cals.get(u), u)[0] for u in links["calendars"][:4]] or cur.get("calendars") or []
    value = {"chart": chart, "bulletin": bulletin, "calendars": calendars,
             "checked": n.isoformat(timespec="seconds")}
    used = set(_shul_files(value))
    for f in os.listdir(SHUL_DIR):  # drop last week's files
        if f not in used and not f.endswith(".tmp"):
            try:
                os.remove(os.path.join(SHUL_DIR, f))
            except OSError:
                pass
    return value


def shul_summary(v):
    v = v or {}
    ch, b = v.get("chart") or {}, v.get("bulletin") or {}
    t = b.get("times")
    return (f"Davening: {ch.get('file', 'none')} · Bulletin: {b.get('file', 'none')} "
            f"({b.get('shabbat') or 'no date'}) · Calendar: "
            f"{', '.join(c['file'] for c in v.get('calendars') or []) or 'none'}\n"
            f"Shabbat times: {len(t['rows']) if t else 'not readable'}{' rows' if t else ''}")


def update_shul():
    """--update-shul: ask the running server to fetch now, or fetch here if it isn't running."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CONFIG['port']}/api/shul-update", timeout=180) as r:
            print(json.loads(r.read())["summary"])
            return 0
    except urllib.error.HTTPError as e:
        print(f"The display server couldn't update: {json.loads(e.read() or b'{}').get('error', e)}")
        return 1
    except (urllib.error.URLError, OSError):
        pass  # not running: do it here
    try:
        v = fetch_shul(force=True)
    except Exception as e:  # noqa: BLE001
        print(f"Couldn't update: {e}")
        return 1
    store.set("shul", v)
    print(shul_summary(v))
    return 0


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
    ("shul",          fetch_shul,                   3600),  # fetches only when shul_due()
] + [("sport_" + k, league_fetcher(k), league_poller(k)) for k in LEAGUES]  # each sleeps while switched off


# after a failure most sources retry sooner than their interval; the shul's site gets
# at most one try an hour, even when it is refusing
RETRY_FLOOR = {"shul": 3600}


def retry_wait(key, retry, interval):
    return max(RETRY_FLOOR.get(key, 0), min(retry, interval))


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
            wait = retry_wait(key, retry, every() if callable(every) else every)
            retry = min(retry * 2, 900)
        time.sleep(wait)


def start_sources():
    for i, (key, fn, every) in enumerate(SOURCES):
        threading.Thread(target=run_source, args=(key, fn, every), daemon=True,
                         name=f"src-{key}").start()
        time.sleep(0.3)  # stagger startup requests


def check_in(name, launcher, local):
    """Note that a screen asked for its page or settings. A new name joins the household with
    the house rotation; until it's saved from the app, a launcher's own settings are kept."""
    with _household_lock:
        w = seen.setdefault(name, {"last": None, "launcher": False})
        w["last"] = time.time()
        w["launcher"] = w["launcher"] or launcher
        h = household()
        s = h["screens"].get(name)
        changed = s is None
        if s is None:
            s = h["screens"][name] = _new_screen()
        if launcher and not s.get("launcher"):
            s["launcher"] = changed = True
        if launcher and local is not None and not s.get("saved") and s.get("local") != local:
            s["local"] = local
            changed = True
        if changed:
            save_household(h)
        return s


def effective_rotation(name, h=None):
    h = h or household()
    s = h["screens"].get(name) if name else None
    rot = (s or {}).get("rotation") or h["default_rotation"]
    return [{"scene": r["scene"], "seconds": r["seconds"]} for r in rot if r.get("on", True)]


def sports_config(h):
    out = {}
    names = {"mlb": "MLB", **{k: v["name"] for k, v in LEAGUES.items()}}
    for k, v in h["sports"].items():
        if k not in names or not v.get("on"):
            continue
        fav = next((t for t in v.get("teams") or [] if t["id"] == v.get("favorite")), None) or {}
        out[k] = {"name": names[k], "favorite_abbr": fav.get("abbr"), "favorite_name": fav.get("name"),
                  "teams": [t["id"] for t in v.get("teams") or []]}
    return out


def state_json(screen=None):
    """The page's data. With a valid screen name, that screen's rotation; the agenda only
    goes to screens whose rotation has it."""
    if screen is not None and not valid_screen(screen):
        screen = None
    if screen:
        check_in(screen, False, None)
    h = household()
    rot = effective_rotation(screen, h)
    snap = store.snapshot()
    data = snap["data"]
    if "agenda" not in [r["scene"] for r in rot]:
        data = {k: v for k, v in data.items() if k != "agenda"}
    cfg = {k: CONFIG[k] for k in ("location_name", "team_abbr", "division_name", "zmanim_labels",
                                  "dim_start", "dim_end", "dim_level", "rotation_seconds")}
    fav = mlb_favorite()
    cfg.update(team_abbr=fav["abbr"], division_name=fav["division_name"])
    cfg.update(rotation=rot, screen=screen, sports=sports_config(h),
               business_news=dict(h["business"].get("news") or {}))
    return json.dumps({"now": now().isoformat(timespec="seconds"), "config": cfg,
                       "data": data, "meta": snap["meta"]})


def _flag(v, default):
    return default if v is None else v in ("1", "true", "yes", "on")


def screen_settings_route(query):
    """/api/screen-settings: a launcher checks in with its own settings and gets back the
    ones to follow. No access code; nothing secret in it."""
    q = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
    name = q.get("screen", "")
    if not valid_screen(name):
        return 400, json.dumps({"ok": False, "error": "bad screen name"})
    try:
        minutes = max(0.25, min(240.0, float(q.get("minutes", 10))))
    except ValueError:
        minutes = 10
    local = {"mode": "saver" if q.get("mode") == "saver" else "always",
             "saver": {"minutes": minutes, "lock": _flag(q.get("lock"), True),
                       "screens": "external" if q.get("screens") == "external" else "all",
                       "keep_awake": _flag(q.get("awake"), False)}}
    s = check_in(name, True, local)
    src = s if s.get("saved") else (s.get("local") or local)
    return 200, json.dumps({"ok": True, "screen": name, "mode": src.get("mode", "always"),
                            "saver": src.get("saver") or default_saver(), "saved": bool(s.get("saved"))})


# ---------------------------------------------------------------- management API
# For the Display Manager app. Every request carries the access code from manage-key.txt
# in X-Manage-Key. Nothing here returns a secret, only whether one is set.

STARTED = time.time()
BUILTIN_SCENES = [("agenda", "Agenda (private)"), ("shul", "Shul"), ("yankees", "MLB team"), ("mlb", "Around the majors"),
                  ("news", "Headlines"), ("israel", "Israel"), ("business", "Business")]
TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")


class BadRequest(Exception):
    """A request the app should fix; the message is shown to Avi as is."""


def scene_catalog():
    out = [{"scene": s, "label": label} for s, label in BUILTIN_SCENES]
    for k, lg in LEAGUES.items():
        out += [{"scene": k + "_team", "label": lg["name"] + " team"},
                {"scene": k, "label": "Around the " + lg["name"]}]
    return out


def league_pair(league):
    return ["yankees", "mlb"] if league == "mlb" else [league + "_team", league]


def shul_status():
    """What the display has from the shul this week, in the app's terms."""
    v = store.get("shul") or {}
    m = store.meta.get("shul") or {}
    n = now()
    today = n.date()
    sat = upcoming_shabbat(today).isoformat()
    ch, b = v.get("chart"), v.get("bulletin")
    chart = bulletin = None
    if ch:
        week = ch.get("week_of")
        chart = {"file": ch.get("file"), "date": week,
                 "this_week": bool(week) and 0 <= (today - date.fromisoformat(week)).days <= 6}
    if b:
        times = b.get("times")
        bulletin = {"file": b.get("file"), "date": b.get("shabbat"), "this_shabbat": b.get("shabbat") == sat,
                    "rows": len(times["rows"]) if times else None}
    month = MONTH_NAMES[today.month - 1]
    calendars = [{"file": c.get("file"), "this_month": month in (c.get("file") or "").lower()}
                 for c in v.get("calendars") or []]
    problem = None
    candles = todays_candles()
    friday_afternoon = (candles is not None or n.weekday() == 4) and n.hour >= 12
    if not v:
        problem = "The shul's files haven't been downloaded yet."
    elif bulletin and bulletin["rows"] is None:
        problem = ("This week's bulletin downloaded, but its Shabbat times couldn't be read." if bulletin["this_shabbat"]
                   else "The bulletin's Shabbat times couldn't be read.")
    elif friday_afternoon and not (bulletin and bulletin["this_shabbat"]):
        problem = "This week's bulletin hasn't come in yet."
    elif chart and not chart["this_week"] and chart["date"] and (today - date.fromisoformat(chart["date"])).days > 6:
        problem = "The weekly davening chart is more than a week old."
    elif m.get("ok") is False:
        problem = f"The last check of the shul's site failed: {m.get('error')}"
    return {"chart": chart, "bulletin": bulletin, "calendars": calendars,
            "meta": {"ok": m.get("ok"), "updated": m.get("updated"), "error": m.get("error")}, "problem": problem}


MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december"]


def log_tail(n):
    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n") for line in f.readlines()[-n:]]
    except OSError:
        return []


def _need(cond, msg):
    if not cond:
        raise BadRequest(msg)


def _check_rotation(rot):
    _need(isinstance(rot, list) and rot, "A rotation needs at least one scene.")
    known = {s["scene"] for s in scene_catalog()}
    lo, hi = SCENE_SECONDS_RANGE
    out = []
    for r in rot:
        _need(isinstance(r, dict), "Each rotation item needs a scene, seconds and on.")
        _need(r.get("scene") in known, f"Unknown scene: {r.get('scene')}")
        sec = r.get("seconds")
        _need(isinstance(sec, int) and not isinstance(sec, bool) and lo <= sec <= hi,
              f"Seconds for {r['scene']} must be between {lo} and {hi}.")
        out.append({"scene": r["scene"], "seconds": sec, "on": bool(r.get("on", True))})
    _need(len({r["scene"] for r in out}) == len(out), "A scene appears twice in the rotation.")
    _need(any(r["on"] for r in out), "Choose at least one scene.")
    return out


def _check_team(t):
    _need(isinstance(t, dict) and isinstance(t.get("id"), int) and not isinstance(t.get("id"), bool),
          "Each team needs an id, abbr and name.")
    return {"id": t["id"], "abbr": str(t.get("abbr") or "")[:6], "name": str(t.get("name") or "")[:60]}


def _save_sports(h, body):
    _need(isinstance(body, dict) and body, "Nothing to save.")
    for league, v in body.items():
        _need(league == "mlb" or league in LEAGUES, f"Unknown league: {league}")
        _need(isinstance(v, dict), f"Settings for {league} are missing.")
        teams = v.get("teams") or []
        _need(isinstance(teams, list) and len(teams) <= 10, "At most 10 teams per league.")
        teams = [_check_team(t) for t in teams]
        fav = v.get("favorite")
        _need(fav is None or fav in [t["id"] for t in teams], "The favorite team must be one of the chosen teams.")
        if fav is None and teams:
            fav = teams[0]["id"]
        was_on = h["sports"][league]["on"]
        on = bool(v.get("on"))
        h["sports"][league] = {"on": on, "teams": teams, "favorite": fav}
        if on and not was_on:
            pair = league_pair(league)
            rot = h["default_rotation"]
            have = {r["scene"] for r in rot}
            at = next((i for i, r in enumerate(rot) if r["scene"] == "business"), len(rot))
            rot[at:at] = [{"scene": s, "seconds": 30, "on": True} for s in pair if s not in have]
            for s in h["screens"].values():
                if s.get("rotation"):
                    have = {r["scene"] for r in s["rotation"]}
                    s["rotation"] += [{"scene": p, "seconds": 30, "on": False} for p in pair if p not in have]


def _save_business(h, body):
    _need(isinstance(body, dict), "Nothing to save.")
    wl = body.get("watchlist") or []
    _need(isinstance(wl, list) and len(wl) <= 30, "At most 30 stocks.")
    out = []
    for s in wl:
        sym = (s.get("symbol") if isinstance(s, dict) else None) or ""
        _need(TICKER.fullmatch(sym), f"Not a ticker: {sym}")
        if sym not in [x["symbol"] for x in out]:
            out.append({"symbol": sym, "name": str(s.get("name") or sym)[:80]})
    news = dict(h["business"].get("news") or {})
    for k, v in (body.get("news") or {}).items():
        _need(k in ("biz_nyt", "biz_cnbc"), f"Unknown news source: {k}")
        news[k] = bool(v)
    h["business"] = {"on": bool(body.get("on", True)), "watchlist": out, "news": news}


def _new_screen():
    return {"rotation": None, "launcher": False, "saved": False, "mode": "always", "saver": default_saver(), "local": None}


def _save_rotation(h, body):
    _need(isinstance(body, dict), "Nothing to save.")
    name, rot = body.get("screen"), body.get("rotation")
    if name is None:
        _need(rot is not None, "The house rotation can't be empty.")
        h["default_rotation"] = _check_rotation(rot)
        return
    _need(isinstance(name, str) and valid_screen(name), "That screen name isn't allowed.")
    s = h["screens"].setdefault(name, _new_screen())
    s["rotation"] = None if rot is None else _check_rotation(rot)


def _save_screen(h, body):
    _need(isinstance(body, dict), "Nothing to save.")
    name = body.get("name")
    _need(isinstance(name, str) and valid_screen(name), "That screen name isn't allowed.")
    mode = body.get("mode")
    _need(mode in ("always", "saver"), "The mode must be always on or screen saver.")
    sv = body.get("saver") or {}
    _need(isinstance(sv, dict), "Screen saver options are missing.")
    if mode == "saver" or sv:
        mins = sv.get("minutes")
        _need(isinstance(mins, (int, float)) and not isinstance(mins, bool) and 1 <= mins <= 240,
              "Idle minutes must be between 1 and 240.")
        _need(sv.get("screens", "all") in ("all", "external"), "The monitor must be all screens or the plugged-in monitor.")
        sv = {"minutes": mins, "lock": bool(sv.get("lock", True)), "screens": sv.get("screens", "all"),
              "keep_awake": bool(sv.get("keep_awake", False))}
    s = h["screens"].setdefault(name, _new_screen())
    s.update(mode=mode, saved=True)
    if sv:
        s["saver"] = sv


def valid_screen(name):
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._'-]{0,39}", name or ""))


def _public_household(h):
    out = {k: v for k, v in h.items() if k != "secrets"}
    out["nyt_signed_in"] = bool(nyt_cookie())
    out["agenda_set"] = bool(CONFIG.get("agenda_ics"))
    out["leagues"] = {k: v["name"] for k, v in LEAGUES.items()}
    out["scenes"] = scene_catalog()
    return out


def _manage_status():
    snap = store.snapshot()
    h = household()
    feeds = {k: {"ok": m.get("ok"), "updated": m.get("updated"), "error": m.get("error"), "failed_at": m.get("failed_at")}
             for k, m in snap["meta"].items()}
    screens = []
    for name in sorted(set(h["screens"]) | set(seen)):
        s, w = h["screens"].get(name) or {}, seen.get(name) or {}
        screens.append({"name": name, "last": w.get("last"), "launcher": bool(s.get("launcher") or w.get("launcher")),
                        "mode": s.get("mode"), "saved": bool(s.get("saved"))})
    return {"ok": True, "started": STARTED, "feeds": feeds, "shul": shul_status(), "screens": screens}


def _restart_soon():
    log("restart asked for by the Display Manager")
    threading.Timer(0.5, lambda: os._exit(0)).start()


SAVERS = {"sports": _save_sports, "business": _save_business, "rotation": _save_rotation, "screen": _save_screen}


def manage_route(method, path, query, key, body):
    """(status, JSON text) for /api/manage/..."""
    import hmac
    if not key or not hmac.compare_digest(key.encode(), manage_key().encode()):
        return 401, json.dumps({"ok": False, "error": "access code needed"})
    name = path[len("/api/manage/"):]
    q = urllib.parse.parse_qs(query)
    try:
        if method == "GET" and name == "status":
            return 200, json.dumps(_manage_status())
        if method == "GET" and name == "household":
            return 200, json.dumps(_public_household(household()))
        if method == "GET" and name == "log":
            try:
                n = max(1, min(500, int((q.get("lines") or ["200"])[0])))
            except ValueError:
                raise BadRequest("lines must be a number") from None
            return 200, json.dumps({"lines": log_tail(n)})
        if method != "POST":
            return 404, json.dumps({"ok": False, "error": "not found"})
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            raise BadRequest("The request wasn't valid JSON.") from None
        if name in SAVERS:
            with _household_lock:
                h = household()
                SAVERS[name](h, data)
                save_household(h)
            return 200, json.dumps({"ok": True})
        if name == "nyt":
            cookie = data.get("cookie") if isinstance(data, dict) else None
            _need(isinstance(cookie, str) and len(cookie) < 8000, "The cookie is missing.")
            with _household_lock:
                h = household()
                h["secrets"]["nyt_cookie"] = cookie.strip()
                save_household(h)
            _cache.clear()  # articles fetched signed out (or in) are fetched again
            return 200, json.dumps({"ok": True, "nyt_signed_in": bool(nyt_cookie())})
        if name == "shul-update":
            code, out = shul_update_now()
            out["shul"] = shul_status()
            return code, json.dumps(out)
        if name == "restart":
            _restart_soon()
            return 200, json.dumps({"ok": True})
        return 404, json.dumps({"ok": False, "error": "not found"})
    except BadRequest as e:
        return 400, json.dumps({"ok": False, "error": str(e)})


def shul_update_now():
    """A forced shul fetch, for /api/shul-update and the app: (status, body dict)."""
    try:
        v = fetch_shul(force=True, wait=False)
        store.set("shul", v)
        return 200, {"ok": True, "summary": shul_summary(v)}
    except ShulBusy:
        return 409, {"ok": False, "error": "already updating; try again in a minute"}
    except Exception as e:  # noqa: BLE001
        store.fail("shul", e)
        log(f"shul: {e}")
        return 503, {"ok": False, "error": str(e)[:200]}


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
                screen = (urllib.parse.parse_qs(parsed.query).get("screen") or [None])[0]
                self._send(200, state_json(screen), "application/json")
            elif path == "/api/screen-settings":
                self._send(*screen_settings_route(parsed.query), "application/json")
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
            elif path.startswith("/shul/"):
                name = path[len("/shul/"):]
                fp = os.path.join(SHUL_DIR, name)
                if re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", name) and os.path.isfile(fp):
                    ext = name.rsplit(".", 1)[-1].lower()
                    with open(fp, "rb") as f:
                        self._send(200, f.read(), SHUL_TYPES.get(ext, "application/octet-stream"))
                else:
                    self._send(404, "not found", "text/plain")
            elif path == "/api/shul-update":
                if self.client_address[0] != "127.0.0.1":
                    self._send(403, json.dumps({"ok": False, "error": "only from this machine"}),
                               "application/json")
                    return
                code, out = shul_update_now()
                self._send(code, json.dumps(out), "application/json")
            elif path.startswith("/api/manage/"):
                self._send(*manage_route("GET", path, parsed.query, self.headers.get("X-Manage-Key"), b""),
                           "application/json")
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

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if not parsed.path.startswith("/api/manage/"):
                self._send(404, "not found", "text/plain")
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= 65536:
                self._send(413, json.dumps({"ok": False, "error": "request too large"}), "application/json")
                return
            body = self.rfile.read(n) if n else b""
            self._send(*manage_route("POST", parsed.path, parsed.query, self.headers.get("X-Manage-Key"), body),
                       "application/json")
        except (OSError, ConnectionError):
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
            if val == {"off": True}:
                print(f"  off   {key:<14} switched off in the Display Manager")
                ok += 1
                continue
            size = len(val.get("items", [])) if isinstance(val, dict) and "items" in val else ""
            print(f"  OK    {key:<14} {time.time() - t:4.1f}s  {size}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {key:<14} {e}")
    print(f"\n{ok}/{len(SOURCES)} sources working.")


def main():
    load_settings()
    manage_key()
    if "--setting" in sys.argv:  # used by the setup scripts
        print(CONFIG.get(sys.argv[sys.argv.index("--setting") + 1], ""))
        return
    if "--check" in sys.argv:
        check()
        return
    if "--update-shul" in sys.argv:
        sys.exit(update_shul())
    household()  # creates household.json from today's settings on first start
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
