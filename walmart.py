"""
Shabbat Display - putting things in the family's Walmart cart.

Walmart has no ordering API for a home project, but it documents an
add-to-cart link (assistant.Usuals.cart_url). This module opens that link on
the display computer in a browser profile of its own, in which someone signed
in to Walmart once. The items land in the account's cart; a person reviews
the cart and pays in the Walmart app or site. Nothing here checks out.

The browser is an ordinary Chrome or Edge window, kept off screen. It is not
driven: the link is opened, and the tab's address is read back from the
browser's own status page to see that it reached the cart.

Standard library only.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

WINDOWS = sys.platform == "win32"
WINDOWS_BROWSERS = [
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
]
OTHER_BROWSERS = ["chromium-browser", "chromium", "google-chrome", "google-chrome-stable", "microsoft-edge",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
SIGN_IN_URL = "https://www.walmart.com/account/login"
STATUS_PORT = 9347


def find_browser():
    if WINDOWS:
        for p in WINDOWS_BROWSERS:
            p = os.path.expandvars(p)
            if os.path.exists(p):
                return p
        return None
    for name in OTHER_BROWSERS:
        p = name if os.path.isabs(name) and os.path.exists(name) else shutil.which(name)
        if p:
            return p
    return None


def read_tabs(port, timeout=2):
    """The browser's open tabs as [{url, title, id}], from its own status page; [] if it isn't answering."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=timeout) as r:
            tabs = json.loads(r.read().decode("utf-8"))
        return [t for t in tabs if isinstance(t, dict) and t.get("type") == "page"]
    except (OSError, ValueError):
        return []


def where(tabs):
    """What the Walmart tab shows: 'cart', 'blocked' (Walmart's robot check), 'signin' or 'other'."""
    for t in tabs:
        url = str(t.get("url", ""))
        if "walmart.com/blocked" in url:
            return "blocked"
        if "walmart.com/cart" in url or "walmart.com/shoppingcart" in url:
            return "cart"
        if "walmart.com/account/login" in url:
            return "signin"
    return "other"


class WalmartCart:
    """`state_file` remembers that someone said they signed in; the browser profile holds the sign-in itself."""

    def __init__(self, profile_dir, state_file, log=print, find=find_browser, popen=subprocess.Popen,
                 tabs=read_tabs, sleep=time.sleep, clock=time.monotonic):
        self.profile_dir, self.state_file, self.log = profile_dir, state_file, log
        self.find, self.popen, self.tabs, self.sleep, self.clock = find, popen, tabs, sleep, clock
        self.lock = threading.Lock()

    # -- signing in (a person does it, once)

    def signed_in(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return bool(json.load(f).get("signed_in"))
        except (OSError, ValueError, AttributeError):
            return False

    def set_signed_in(self, yes):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump({"signed_in": bool(yes)}, f)

    def open_sign_in(self):
        """Open Walmart's sign-in page in a normal window on the display computer. Returns '' or why not."""
        exe = self.find()
        if not exe:
            return "Chrome or Edge wasn't found on the display computer."
        try:
            self.popen([exe, f"--user-data-dir={self.profile_dir}", "--no-first-run", "--no-default-browser-check",
                        "--new-window", SIGN_IN_URL])
        except OSError as e:
            self.log(f"walmart: the sign-in window couldn't be opened ({e})")
            return "The browser couldn't be opened on the display computer."
        return ""

    # -- adding to the cart

    def add(self, cart_url, wait=30):
        """Open the add-to-cart link in the signed-in profile. Returns (ok, reason): reason is '' on
        success, else 'not_signed_in', 'no_browser', 'blocked', 'signin' or 'timeout'."""
        if not self.signed_in():
            return False, "not_signed_in"
        exe = self.find()
        if not exe:
            return False, "no_browser"
        if not self.lock.acquire(blocking=False):
            return False, "busy"
        proc = None
        try:
            args = [exe, f"--user-data-dir={self.profile_dir}", f"--remote-debugging-port={STATUS_PORT}",
                    "--no-first-run", "--no-default-browser-check", "--new-window",
                    "--window-position=-2400,-2400", "--window-size=1000,800", cart_url]
            extra = {}
            if WINDOWS:
                info = subprocess.STARTUPINFO()
                info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                info.wShowWindow = 7  # minimized, without taking the keyboard from the display
                extra["startupinfo"] = info
            proc = self.popen(args, **extra)
            deadline, seen = self.clock() + wait, "other"
            while self.clock() < deadline:
                self.sleep(1)
                seen = where(self.tabs(STATUS_PORT))
                if seen in ("cart", "blocked", "signin"):
                    break
            if seen == "cart":
                self.sleep(3)  # let the cart save before the window closes
                return True, ""
            if seen == "signin":
                self.set_signed_in(False)
            self.log(f"walmart: the cart link ended at '{seen}'")
            return False, seen if seen in ("blocked", "signin") else "timeout"
        except OSError as e:
            self.log(f"walmart: the browser couldn't be started ({e})")
            return False, "no_browser"
        finally:
            self._close(proc)
            self.lock.release()

    def _close(self, proc):
        if proc is None:
            return
        for t in self.tabs(STATUS_PORT):  # closing its tabs lets the browser save and exit by itself
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{STATUS_PORT}/json/close/{t.get('id')}", timeout=2).read()
            except (OSError, ValueError):
                pass
        try:
            proc.wait(timeout=4)
        except Exception:  # noqa: BLE001 - still running (macOS keeps it open): stop it
            try:
                proc.terminate()
            except OSError:
                pass


SENTENCES = {
    "not_signed_in": "Walmart isn't signed in on the display computer yet.",
    "no_browser": "The display computer has no Chrome or Edge to open Walmart with.",
    "blocked": "Walmart asked the display computer to prove it isn't a robot.",
    "signin": "Walmart signed the display computer out.",
    "timeout": "Walmart didn't answer in time.",
    "busy": "The display computer is already filling the cart.",
}
