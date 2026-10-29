"""
Shabbat Display launcher (Windows, Raspberry Pi / Linux).

Starts the data server and a full-screen browser pointed at it, then keeps
both running: if either one closes or crashes, it is started again.

    Windows:  double-click start-display.bat
    Pi/Linux: ./start-display.sh   (setup-pi.sh makes it start at login)
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, "browser-profile")
LOG_FILE = os.path.join(HERE, "launcher.log")
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


def port():
    try:
        with open(os.path.join(HERE, "settings.json"), encoding="utf-8-sig") as f:
            return int(json.load(f).get("port", 8765))
    except (OSError, ValueError, TypeError, AttributeError):
        return 8765


URL = f"http://localhost:{port()}/"


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
    args = [path, "--kiosk", URL, f"--user-data-dir={PROFILE}", "--no-first-run",
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
        handle = k32.CreateMutexW(None, False, "ShabbatDisplayLauncher")
        return None if ctypes.get_last_error() == 183 else handle  # ERROR_ALREADY_EXISTS
    import fcntl
    f = open(os.path.join(HERE, "launcher.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main():
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
