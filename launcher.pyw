"""
Shabbat Display launcher (Windows, Raspberry Pi / Linux).

Starts the data server and a full-screen browser pointed at it, then keeps
both running: if either one closes or crashes, it is started again.

    Windows:  double-click start-display.bat
    Pi/Linux: ./start-display.sh   (setup-pi.sh makes it start at login)

With --screensaver (Windows only; start-screensaver.bat) it sets Windows' own screen
saver to the Shabbat Display (saver\ShabbatDisplay.scr) instead of opening a browser.
The Display Manager app can switch a PC between always on, screen saver and off.

With "server_url" in settings.json it starts no server and shows that machine's
display instead (a second screen in the house; setup-windows.ps1 finds the server).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import socket
import time
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SAVER = "--screensaver" in sys.argv
PROFILE = os.path.join(HERE, "browser-profile-saver" if SAVER else "browser-profile")
# what the server last said this screen should do (mode, screen-saver options), kept for when it can't be reached
SETTINGS_CACHE = os.path.join(HERE, "screen-settings.json")
LOG_FILE = os.path.join(HERE, "screensaver.log" if SAVER else "launcher.log")
# the Windows screen saver, and what it shows (written here; nothing secret in it)
SAVER_DIR = os.path.join(HERE, "saver")
SCR = os.path.join(SAVER_DIR, "ShabbatDisplay.scr")
SAVER_CONFIG = os.path.join(SAVER_DIR, "saver.json")
MODES = ("always", "saver", "off")
WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if WINDOWS else 0

WINDOWS_BROWSERS = [
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
]
# Raspberry Pi OS calls it chromium-browser (Bookworm) or chromium (Trixie).
LINUX_BROWSERS = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
                  "microsoft-edge"]


def log(msg):
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + msg + "\n")
    except OSError:
        pass


_settings_problem = None


def setting(key, default):
    """One value from settings.json (read fresh each time), or the default. A file that
    can't be read is logged once, since every setting then silently uses its default."""
    global _settings_problem
    try:
        with open(os.path.join(HERE, "settings.json"), encoding="utf-8-sig") as f:
            data = json.load(f)
        _settings_problem = None
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        if str(e) != _settings_problem:
            _settings_problem = str(e)
            log(f"settings.json can't be read ({e}); using the defaults until it's fixed")
        return default
    try:
        return type(default)(data.get(key, default))
    except (TypeError, ValueError, AttributeError):
        return default


def display_url(server_url, port):
    """The page to show: this PC's own server, or (server_url set) another machine's."""
    s = (server_url or "").strip().rstrip("/")
    if not s:
        return f"http://localhost:{port}/"
    if "://" not in s:
        s = "http://" + s
    if not re.search(r":\d+$", s.split("://", 1)[1]):
        s += f":{port}"
    return s + "/"


def profile_for(mode):
    return os.path.join(HERE, "browser-profile-saver" if mode == "saver" else "browser-profile")


def screen_name():
    """This screen's name in the Display Manager: screen_name in settings.json, else the PC's name."""
    name = setting("screen_name", "").strip() or os.environ.get("COMPUTERNAME") or socket.gethostname()
    name = re.sub(r"[^A-Za-z0-9 ._'-]", "-", name)[:40].strip()
    if not name or not name[0].isalnum():
        name = ("PC-" + name)[:40]
    return name


# screen-settings.json keys -> settings.json keys, for when the server has never answered
LOCAL_KEYS = {"minutes": "screensaver_minutes", "lock": "screensaver_lock", "shabbat": "keep_pc_awake"}
_cache_problem = None


def _cached_settings():
    global _cache_problem
    try:
        with open(SETTINGS_CACHE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        _cache_problem = None
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        if str(e) != _cache_problem:
            _cache_problem = str(e)
            log(f"screen-settings.json can't be read ({e}); using settings.json")
        return {}


def screen_setting(key, default):
    """mode, minutes, lock or shabbat: what the server said last, else settings.json,
    else (mode) the flag the launcher was started with."""
    c = _cached_settings()
    saver = c.get("saver") if isinstance(c.get("saver"), dict) else {}
    v = c.get("mode") if key == "mode" else saver.get(key)
    if key == "mode":
        return v if v in MODES else ("saver" if SAVER else "always")
    if key == "shabbat" and v is None:
        v = saver.get("keep_awake")  # an answer from before the Shabbat switch
    if v is None:
        return setting(LOCAL_KEYS[key], default)
    try:
        return type(default)(v) if default is not None else v
    except (TypeError, ValueError):
        return default


def local_report():
    """This PC's own settings, sent on each check-in; the server keeps them until the screen is saved in the app."""
    minutes = max(1, round(setting("screensaver_minutes", 10.0)))
    return {"mode": "saver" if SAVER else "always", "minutes": str(minutes),
            "lock": int(setting("screensaver_lock", True)), "shabbat": int(setting("keep_pc_awake", False))}


_fetch_problem = None


def fetch_screen_settings():
    """Ask the server what this screen should do, and remember the answer. None when it can't be reached."""
    global _fetch_problem
    url = URL + "api/screen-settings?" + urllib.parse.urlencode({"screen": screen_name(), **local_report()})
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        if data.get("mode") not in MODES:
            raise ValueError("no mode in the answer")
        tmp = SETTINGS_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, SETTINGS_CACHE)
        _fetch_problem = None
        return data
    except Exception as e:  # noqa: BLE001 - keep the last answer
        if str(e) != _fetch_problem:
            _fetch_problem = str(e)
            log(f"couldn't get this screen's settings from the server ({e}); keeping the last ones")
        return None


def page_url(saver):
    """The display page, with this screen's name; ?saver=1 lets the power plan still turn the screen off."""
    return URL + "?" + urllib.parse.urlencode({"screen": screen_name(), **({"saver": 1} if saver else {})})


# With "server_url" in settings.json this PC only shows the display; the data
# server runs on another machine in the house (setup finds it).
REMOTE = bool(setting("server_url", "").strip())
URL = display_url(setting("server_url", ""), setting("port", 8765))


def keep_awake():
    """Keep the screen on: no screen-off, no sleep, no screen saver."""
    if WINDOWS:
        try:
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        except Exception as e:  # noqa: BLE001
            log(f"keep-awake failed: {e}")
    elif os.environ.get("DISPLAY") and shutil.which("xset"):
        # X11 only. Under Wayland, setup-pi.sh turns screen blanking off instead.
        subprocess.run(["xset", "s", "off", "s", "noblank", "-dpms"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def find_browser():
    if WINDOWS:
        for p in WINDOWS_BROWSERS:
            p = os.path.expandvars(p)
            if os.path.exists(p):
                return p
        return None
    for name in LINUX_BROWSERS:
        p = shutil.which(name)
        if p:
            return p
    return None


def server_up():
    try:
        with urllib.request.urlopen(URL + "health", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def start_server():
    py = sys.executable
    if WINDOWS:
        w = py.replace("python.exe", "pythonw.exe")
        py = w if os.path.exists(w) else py
    log("starting server")
    return subprocess.Popen([py, os.path.join(HERE, "server.py")], cwd=HERE, creationflags=NO_WINDOW,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def browser_running(profile=PROFILE):
    """Whether a browser is using the profile. Chrome relaunches itself under a new process,
    so the process we started is no guide; the profile's lock is."""
    if WINDOWS:
        # Held open while the browser runs, so it can't be deleted; gone or deletable means stopped.
        try:
            os.remove(os.path.join(profile, "lockfile"))
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return False
    try:  # a symlink to "hostname-pid"
        pid = int(os.readlink(os.path.join(profile, "SingletonLock")).rsplit("-", 1)[1])
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, IndexError):
        return False


def mark_clean_exit(profile=PROFILE):
    """After a power cut the browser would offer to restore pages; tell it the last exit was clean."""
    prefs = os.path.join(profile, "Default", "Preferences")
    try:
        with open(prefs, encoding="utf-8") as f:
            data = json.load(f)
        profile = data.setdefault("profile", {})
        if profile.get("exit_type") != "Normal" or not profile.get("exited_cleanly", True):
            profile["exit_type"] = "Normal"
            profile["exited_cleanly"] = True
            with open(prefs, "w", encoding="utf-8") as f:
                json.dump(data, f)
    except (OSError, ValueError, AttributeError):
        pass
    # Linux leaves a lock behind on a hard power-off, and the browser then refuses the profile.
    if not WINDOWS:
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            try:
                os.unlink(os.path.join(profile, name))
            except OSError:
                pass


def start_browser(path, profile=PROFILE, position=None):
    log(f"starting browser {path}" + (f" at {position[0]},{position[1]}" if position else ""))
    mark_clean_exit(profile)
    saver = os.path.basename(profile).startswith("browser-profile-saver")
    args = [path, "--kiosk", page_url(saver), f"--user-data-dir={profile}", "--no-first-run",
            "--noerrdialogs", "--disable-session-crashed-bubble", "--disable-infobars",
            "--disable-features=Translate,TranslateUI", "--autoplay-policy=no-user-gesture-required",
            "--overscroll-history-navigation=0", "--disable-pinch",
            "--check-for-update-interval=31536000"]  # no "browser is out of date" bubble
    if position:  # kiosk goes full screen on whichever monitor the window starts on
        args.append(f"--window-position={position[0]},{position[1]}")
    if "msedge" in path.lower():
        args.append("--edge-kiosk-type=fullscreen")
    if not WINDOWS:
        args.append("--password-store=basic")  # no keyring password prompt on the Pi
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def single_instance():
    """Hold a lock for as long as this launcher runs. Returns None if another copy already has it."""
    if WINDOWS:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.CreateMutexW(None, False, "ShabbatDisplaySaver" if SAVER else "ShabbatDisplayLauncher")
        return None if ctypes.get_last_error() == 183 else handle  # ERROR_ALREADY_EXISTS
    import fcntl
    f = open(os.path.join(HERE, "launcher.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


DIM_FILE = os.path.join(HERE, "brightness-before-saver.txt")


def restore_brightness():
    """Put the laptop screen back to the brightness it had before the screen saver darkened it."""
    try:
        with open(DIM_FILE) as f:
            level = int(f.read().strip())
    except (OSError, ValueError):
        return
    set_internal_brightness(level)
    try:
        os.remove(DIM_FILE)
    except OSError:
        pass


def set_internal_brightness(level):
    """Set the built-in panel's brightness (0-100) and return what it was, or None if
    this PC has no adjustable built-in panel. Windows can't switch off one screen,
    so 0 is as close to off as it gets."""
    ps = ("$b = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop | "
          "Select-Object -First 1; $b.CurrentBrightness; "
          "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
          f"Select-Object -First 1 | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=0; Brightness={int(level)}}} | Out-Null")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout.split()
        return int(out[0]) if out and out[0].isdigit() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def browser_pids(profile=None):
    """Main browser processes using our profiles (browser-profile-saver, -2, ... all match).
    Chrome relaunches itself at startup, so the process start_browser() returns is usually gone by now."""
    # the saver profiles (-saver, -saver-2, ...) by prefix; any other profile exactly, so browser-profile
    # doesn't also match browser-profile-saver
    prof = (profile or profile_for("saver")).replace("'", "''")
    match = (f"$_.CommandLine -like '*{prof}*'" if not profile else
             f"($_.CommandLine -like '*{prof}' -or $_.CommandLine -like '*{prof} *' -or $_.CommandLine -like '*{prof}\"*')")
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='msedge.exe'\" | "
           f"Where-Object {{ {match} "
           "-and $_.CommandLine -notlike '*--type=*' } | "
           "ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                             timeout=30, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in out.split() if x.isdigit()]


def stop_browser(pids, profiles):
    """Close the screen-saver browsers at once. A polite close takes seconds, and
    mark_clean_exit() keeps the forced one from causing a restore-pages bubble next time."""
    # the screen-saver profiles are found together by their shared prefix; any other one by its own path
    lookups = {None if os.path.basename(p).startswith("browser-profile-saver") else p for p in profiles}
    for _ in range(2):
        for pid in pids or [x for prof in lookups for x in browser_pids(prof)]:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], creationflags=NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            if not any(browser_running(p) for p in profiles):
                return
            time.sleep(0.1)
        pids = None  # look again, in case it had relaunched under a new process
    log("couldn't close the display's browser window")


def screen_off_seconds():
    """The power plan's 'turn off my screen after' while plugged in, in seconds (0 = never)."""
    try:
        out = subprocess.run(["powercfg", "/q", "SCHEME_CURRENT", "SUB_VIDEO", "VIDEOIDLE"], capture_output=True,
                             text=True, timeout=15, creationflags=NO_WINDOW).stdout
        return int(re.findall(r"0x[0-9a-fA-F]+", out)[-2], 16)  # the last two are plugged in, then battery
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return 0


def cached_holy():
    """Shabbat and Yom Tov spans from the server's last answer; kept while it can't be reached."""
    holy = _cached_settings().get("holy")
    return [h for h in holy if isinstance(h, dict)] if isinstance(holy, list) else []


def _spans(spans):
    for h in spans:
        try:
            start, end = datetime.fromisoformat(h["start"]), datetime.fromisoformat(h["end"])
            yield (start if start.tzinfo else start.astimezone()), (end if end.tzinfo else end.astimezone())
        except (TypeError, KeyError, ValueError):
            continue


def holy_now(spans, now):
    """Between a candle lighting and its havdalah."""
    return any(start <= now < end for start, end in _spans(spans))


def shabbat_day(spans, now):
    """From midnight of the candle-lighting day until havdalah: the PC must not sleep."""
    return any(start.replace(hour=0, minute=0, second=0, microsecond=0) <= now < end for start, end in _spans(spans))


def _short_path(path):
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    return buf.value if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024) else ""


def scr_registry_path(path, shorten=None):
    """The .scr's path for SCRNSAVE.EXE, with Windows separators: Windows may not start a screen saver
    whose path has a space, so that gets the short (8.3) form."""
    path = os.path.normpath(path)
    if " " not in path:
        return path
    return (shorten or _short_path)(path) or path


def saver_registry(mode, minutes, lock, holy, scr):
    """Windows' screen-saver values (HKCU\\Control Panel\\Desktop) for this mode. Over Shabbat nothing locks."""
    if mode != "saver":
        return {"ScreenSaveActive": "0"}
    return {"SCRNSAVE.EXE": scr, "ScreenSaveActive": "1", "ScreenSaveTimeOut": str(int(minutes) * 60),
            "ScreenSaverIsSecure": "0" if holy else ("1" if lock else "0")}


def _same_path(a, b):
    return bool(a) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def registry_changes(desired, current, mode, scr):
    """Only the values that differ. Out of screen-saver mode, someone else's screen saver is left alone."""
    if mode != "saver" and not _same_path(current.get("SCRNSAVE.EXE"), scr):
        return {}
    return {k: v for k, v in desired.items() if current.get(k) != v}


DESKTOP_KEY = r"Control Panel\Desktop"
SAVER_VALUES = ("SCRNSAVE.EXE", "ScreenSaveActive", "ScreenSaveTimeOut", "ScreenSaverIsSecure")


def read_saver_registry():
    import winreg
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY) as k:
            for name in SAVER_VALUES:
                try:
                    out[name] = str(winreg.QueryValueEx(k, name)[0])
                except OSError:
                    pass
    except OSError:
        pass
    return out


def apply_registry_changes(changes):
    """Write them the way Control Panel does, so Windows picks them up at once."""
    import ctypes
    import winreg
    spi = {"ScreenSaveTimeOut": 0x000F, "ScreenSaveActive": 0x0011, "ScreenSaverIsSecure": 0x0077}
    SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 0x01, 0x02
    try:
        if "SCRNSAVE.EXE" in changes:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "SCRNSAVE.EXE", 0, winreg.REG_SZ, changes["SCRNSAVE.EXE"])
        for name, action in spi.items():
            if name in changes:
                ctypes.windll.user32.SystemParametersInfoW(action, int(changes[name]), None,
                                                           SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
        log("Windows screen saver: " + ", ".join(f"{k}={v}" for k, v in changes.items()))
    except (OSError, ValueError) as e:
        log(f"couldn't change the Windows screen saver settings: {e}")


def saver_policy():
    """Screen-saver values set by a policy (a work or school PC); Windows then ignores ours."""
    import winreg
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Policies\Microsoft\Windows\Control Panel\Desktop") as k:
            i = 0
            while True:
                try:
                    name = winreg.EnumValue(k, i)[0]
                except OSError:
                    break
                if name.lower().startswith("screensave") or name.upper() == "SCRNSAVE.EXE":
                    found.append(name)
                i += 1
    except OSError:
        pass
    return found


def write_saver_config(url, screen, shabbat, holy):
    """saver.json for the .scr, rewritten only when it changes. Returns whether it was written."""
    text = json.dumps({"url": url, "screen": screen, "shabbat": bool(shabbat), "holy": holy}, indent=1)
    try:
        with open(SAVER_CONFIG, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(SAVER_CONFIG), exist_ok=True)
        tmp = SAVER_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, SAVER_CONFIG)
        return True
    except OSError as e:
        log(f"couldn't write saver.json: {e}")
        return False


def screen_off_target(off_minutes, wait_minutes):
    """A new plugged-in screen-off time when the screen would turn off before the screen saver starts."""
    return wait_minutes + 20 if 0 < off_minutes <= wait_minutes else None


def set_awake(pc):
    """Keep the PC from sleeping, or let Windows decide. Never the screens: holding them on would
    stop Windows from ever starting the screen saver (it holds them on itself over Shabbat)."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if pc else 0))
    except (OSError, AttributeError) as e:
        log(f"keep-awake failed: {e}")


def undo_our_saver():
    """Leaving screen-saver mode: Windows' screen saver off, if it is ours."""
    scr = scr_registry_path(SCR)
    changes = registry_changes(saver_registry("off", 10, True, False, scr), read_saver_registry(), "off", scr)
    if changes:
        apply_registry_changes(changes)


def windows_saver_loop(server, mode):
    """Mode saver: Windows' own screen saver is the Shabbat Display, set and kept that way here.
    Mode off: no screen saver of ours. No browser either way. Returns when the mode changes."""
    restore_brightness()  # the old screen saver may have left the laptop screen dark
    log("mode: " + ("screen saver" if mode == "saver" else "off"))
    noted, checked, raised_for = set(), 0.0, None

    def once(key, msg):
        if key not in noted:
            noted.add(key)
            log(msg)

    while True:
        if time.time() - checked >= 55:
            checked = time.time()
            fetch_screen_settings()
            if screen_setting("mode", None) != mode:
                set_awake(False)
                return server
        minutes = max(1, min(240, round(screen_setting("minutes", 10.0))))
        shabbat = mode == "saver" and screen_setting("shabbat", False)
        spans, now = cached_holy(), datetime.now().astimezone()
        scr = scr_registry_path(SCR)
        want = saver_registry(mode, minutes, screen_setting("lock", True), shabbat and holy_now(spans, now), scr)
        changes = registry_changes(want, read_saver_registry(), mode, scr)
        if changes:
            apply_registry_changes(changes)
        if mode == "saver":
            if not os.path.exists(SCR):
                once("missing", "saver\\ShabbatDisplay.scr is missing; rebuild it (build-saver.bat) or reinstall")
            if saver_policy():
                once("policy", "a Windows policy controls the screen saver on this PC, so these settings may not apply")
            write_saver_config(URL, screen_name(), shabbat, spans)
            if shabbat and raised_for != minutes:
                raised_for = minutes
                target = screen_off_target(screen_off_seconds() / 60, minutes)
                if target:
                    subprocess.run(["powercfg", "/change", "monitor-timeout-ac", str(target)],
                                   creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    log(f"the screen turned off before the screen saver would start; it now turns off after {target} minutes")
        set_awake(shabbat and shabbat_day(spans, now))
        if not REMOTE:
            if server is not None and server.poll() is not None:
                log(f"server exited with code {server.returncode}; restarting")
                server = start_server()
            elif server is None and not server_up():
                server = start_server()
        time.sleep(30)


def main():
    if SAVER and not WINDOWS:
        print("Screen saver mode is for Windows. On the Pi, run the display full time.", file=sys.stderr)
        return
    lock = single_instance()  # noqa: F841 - must stay referenced while running
    if lock is None:
        log("launcher already running; this copy exits")
        return
    browser_path = find_browser()
    if not browser_path:
        log("no Chrome, Chromium or Edge found")
        print("No Chrome, Chromium or Edge found. Run the setup script first.", file=sys.stderr)
        return
    server = None if REMOTE or server_up() else start_server()
    for _ in range(30):
        if server_up():
            break
        time.sleep(1)
    if REMOTE:
        log(f"showing the display from {URL}" + ("" if server_up() else " (not answering yet)"))
    fetch_screen_settings()
    log(f"this screen is \"{screen_name()}\" in the Display Manager")
    while True:
        mode = screen_setting("mode", None)
        if mode in ("saver", "off") and WINDOWS:
            server = windows_saver_loop(server, mode)
        else:
            if mode != "always":
                log(f"mode {mode} is for Windows; showing the display full time")
            log("mode: always on")
            server = always_loop(browser_path, server)


def always_loop(browser_path, server):
    """The display full time. Returns (with the browser closed) when the server switches this screen to the screen saver."""
    profile = profile_for("always")
    if WINDOWS:
        undo_our_saver()
    keep_awake()
    if not browser_running(profile) and (not REMOTE or server_up()):
        start_browser(browser_path, profile)
    checked = time.time()
    while True:
        time.sleep(30)
        if time.time() - checked >= 55:
            checked = time.time()
            fetch_screen_settings()
            if screen_setting("mode", None) in ("saver", "off") and WINDOWS:
                stop_browser(browser_pids(profile), [profile])
                return server
        keep_awake()
        if REMOTE:
            # another machine's server: open the browser once it answers, never start one here
            if not browser_running(profile) and server_up():
                log("browser not running; starting")
                start_browser(browser_path, profile)
            continue
        if server is not None and server.poll() is not None:
            log(f"server exited with code {server.returncode}; restarting")
            server = start_server()
        elif server is None and not server_up():
            server = start_server()
        if not browser_running(profile):
            log("browser closed; restarting")
            start_browser(browser_path, profile)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"launcher error: {e}")
        raise
