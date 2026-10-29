"""
Shabbat Display launcher (Windows, Raspberry Pi / Linux).

Starts the data server and a full-screen browser pointed at it, then keeps
both running: if either one closes or crashes, it is started again.

    Windows:  double-click start-display.bat
    Pi/Linux: ./start-display.sh   (setup-pi.sh makes it start at login)

With --screensaver (Windows only; start-screensaver.bat) it acts as a screen saver
instead: the server stays running in the background, the browser opens after
screensaver_minutes without mouse or keyboard input, and any input closes it.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SAVER = "--screensaver" in sys.argv
PROFILE = os.path.join(HERE, "browser-profile-saver" if SAVER else "browser-profile")
LOG_FILE = os.path.join(HERE, "screensaver.log" if SAVER else "launcher.log")
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


def setting(key, default):
    try:
        with open(os.path.join(HERE, "settings.json"), encoding="utf-8-sig") as f:
            return type(default)(json.load(f).get(key, default))
    except (OSError, ValueError, TypeError, AttributeError):
        return default


URL = f"http://localhost:{setting('port', 8765)}/"


def log(msg):
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + msg + "\n")
    except OSError:
        pass


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


def browser_running():
    """Whether a browser is using our profile. Chrome relaunches itself under a new process,
    so the process we started is no guide; the profile's lock is."""
    if WINDOWS:
        # Held open while the browser runs, so it can't be deleted; gone or deletable means stopped.
        try:
            os.remove(os.path.join(PROFILE, "lockfile"))
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return False
    try:  # a symlink to "hostname-pid"
        pid = int(os.readlink(os.path.join(PROFILE, "SingletonLock")).rsplit("-", 1)[1])
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, IndexError):
        return False


def mark_clean_exit():
    """After a power cut the browser would offer to restore pages; tell it the last exit was clean."""
    prefs = os.path.join(PROFILE, "Default", "Preferences")
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
                os.unlink(os.path.join(PROFILE, name))
            except OSError:
                pass


def start_browser(path):
    log(f"starting browser {path}")
    mark_clean_exit()
    # ?saver=1: the page skips its wake lock, so the power plan can still turn the screen off.
    args = [path, "--kiosk", URL + ("?saver=1" if SAVER else ""), f"--user-data-dir={PROFILE}", "--no-first-run",
            "--noerrdialogs", "--disable-session-crashed-bubble", "--disable-infobars",
            "--disable-features=Translate,TranslateUI", "--autoplay-policy=no-user-gesture-required",
            "--overscroll-history-navigation=0", "--disable-pinch",
            "--check-for-update-interval=31536000"]  # no "browser is out of date" bubble
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


def last_input():
    """Tick count (ms) of the last mouse or keyboard input anywhere in this session."""
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return info.dwTime


def idle_seconds():
    import ctypes
    return ((ctypes.windll.kernel32.GetTickCount() - last_input()) & 0xFFFFFFFF) / 1000


# SHQueryUserNotificationState: Windows' own test for "don't interrupt now", the one it
# uses to hold back notifications. A maximized window doesn't count; a slideshow does.
BUSY_STATES = {1: "locked or away", 2: "a full-screen app is in front", 3: "a full-screen game or video is in front",
               4: "presentation mode is on"}


def screen_busy():
    """Why the screen saver shouldn't appear now (locked, slideshow, video call...), or ''."""
    import ctypes
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return ""
    except (OSError, AttributeError):
        return ""
    return BUSY_STATES.get(state.value, "")


def browser_pids():
    """Main browser processes using our profile. Chrome relaunches itself at startup,
    so the process start_browser() returns is usually gone by now."""
    prof = PROFILE.replace("'", "''")
    cmd = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='msedge.exe'\" | "
           f"Where-Object {{ $_.CommandLine -like '*{prof}*' -and $_.CommandLine -notlike '*--type=*' }} | "
           "ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                             timeout=30, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in out.split() if x.isdigit()]


def stop_browser(pids):
    """Close the screen-saver browser at once. A polite close takes seconds, and
    mark_clean_exit() keeps the forced one from causing a restore-pages bubble next time."""
    for _ in range(2):
        for pid in pids or browser_pids():
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], creationflags=NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            if not browser_running():
                return
            time.sleep(0.1)
        pids = None  # look again, in case it had relaunched under a new process


def screen_off_seconds():
    """The power plan's 'turn off my screen after' while plugged in, in seconds (0 = never)."""
    try:
        out = subprocess.run(["powercfg", "/q", "SCHEME_CURRENT", "SUB_VIDEO", "VIDEOIDLE"], capture_output=True,
                             text=True, timeout=15, creationflags=NO_WINDOW).stdout
        return int(re.findall(r"0x[0-9a-fA-F]+", out)[-2], 16)  # the last two are plugged in, then battery
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return 0


def saver_loop(browser_path, server):
    wait = max(0.25, setting("screensaver_minutes", 10.0)) * 60
    log(f"screen saver on: opens after {wait / 60:g} minutes idle")
    off = screen_off_seconds()
    if off and off <= wait:
        log(f"warning: the power plan turns the screen off after {off / 60:g} minutes, before the screen saver"
            " opens. Raise 'Turn off my screen after' in Settings > System > Power, or run setup again.")
    showing, pids, noted = False, [], ""
    while True:
        if not showing:
            time.sleep(2)
            idle = idle_seconds()
            busy = screen_busy() if idle >= wait else ""
            if busy != noted:  # log each reason once, so screensaver.log shows why it didn't appear
                if busy:
                    log(f"not opening: {busy}")
                noted = busy
            if idle >= wait and not busy:
                log("opening")
                start_browser(browser_path)
                showing, pids, shown_at = True, [], last_input()
                for _ in range(50):  # wait for the relaunched browser, then remember its process
                    if last_input() != shown_at or browser_running():
                        break
                    time.sleep(0.1)
        else:
            time.sleep(0.2)
            if not pids and last_input() == shown_at:
                pids = browser_pids()
            if last_input() != shown_at or not browser_running():
                stop_browser(pids)
                showing = False
                log("closed: input" if last_input() != shown_at else "closed: browser exited")
        if server is not None and server.poll() is not None:
            log(f"server exited with code {server.returncode}; restarting")
            server = start_server()
        elif server is None and not server_up():
            server = start_server()


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
    server = None if server_up() else start_server()
    for _ in range(30):
        if server_up():
            break
        time.sleep(1)
    if SAVER:
        saver_loop(browser_path, server)
        return
    keep_awake()
    if not browser_running():
        start_browser(browser_path)
    while True:
        time.sleep(30)
        keep_awake()
        if server is not None and server.poll() is not None:
            log(f"server exited with code {server.returncode}; restarting")
            server = start_server()
        elif server is None and not server_up():
            server = start_server()
        if not browser_running():
            log("browser closed; restarting")
            start_browser(browser_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"launcher error: {e}")
        raise
