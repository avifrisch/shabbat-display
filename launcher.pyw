"""
Shabbat Display launcher (Windows).

Starts the data server and a full-screen browser pointed at it, then keeps
both running: if either one closes or crashes, it is started again.
Double-click start-display.bat (or this file) to run it.
"""
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:8765/"
PROFILE = os.path.join(HERE, "browser-profile")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

BROWSERS = [
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
]


def keep_awake():
    """Tell Windows the display is in use: no screen-off, no sleep, no screen saver."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
    except Exception as e:  # noqa: BLE001
        log(f"keep-awake failed: {e}")


def log(msg):
    with open(os.path.join(HERE, "launcher.log"), "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + msg + "\n")


def find_browser():
    for p in BROWSERS:
        p = os.path.expandvars(p)
        if os.path.exists(p):
            return p
    return None


def server_up():
    try:
        with urllib.request.urlopen(URL + "health", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def start_server():
    py = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(py):
        py = sys.executable
    log("starting server")
    return subprocess.Popen([py, os.path.join(HERE, "server.py")], cwd=HERE, creationflags=NO_WINDOW)


def start_browser(path):
    log(f"starting browser {path}")
    args = [path, "--kiosk", URL, f"--user-data-dir={PROFILE}", "--no-first-run",
            "--noerrdialogs", "--disable-session-crashed-bubble", "--disable-infobars",
            "--disable-features=Translate,TranslateUI", "--autoplay-policy=no-user-gesture-required",
            "--overscroll-history-navigation=0", "--disable-pinch"]
    if "msedge" in path.lower():
        args.append("--edge-kiosk-type=fullscreen")
    return subprocess.Popen(args)


def main():
    browser_path = find_browser()
    if not browser_path:
        log("no Chrome or Edge found")
        return
    server = None if server_up() else start_server()
    for _ in range(30):
        if server_up():
            break
        time.sleep(1)
    browser = start_browser(browser_path)
    while True:
        keep_awake()
        time.sleep(30)
        if server is not None and server.poll() is not None:
            log(f"server exited with code {server.returncode}; restarting")
            server = start_server()
        elif server is None and not server_up():
            server = start_server()
        if browser.poll() is not None:
            log("browser closed; restarting")
            time.sleep(5)
            browser = start_browser(browser_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"launcher error: {e}")
        raise
