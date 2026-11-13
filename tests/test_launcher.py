import importlib.machinery
import importlib.util
import os
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader("launcher", os.path.join(ROOT, "launcher.pyw"))
_spec = importlib.util.spec_from_loader("launcher", _loader)
launcher = importlib.util.module_from_spec(_spec)
_loader.exec_module(launcher)


class DisplayUrlTests(unittest.TestCase):
    def test_own_server_by_default(self):
        self.assertEqual(launcher.display_url("", 8765), "http://localhost:8765/")

    def test_another_machines_server(self):
        self.assertEqual(launcher.display_url("http://100.98.145.119:8765", 8765), "http://100.98.145.119:8765/")
        self.assertEqual(launcher.display_url("http://desktop-h72vkdj:8765/", 8765), "http://desktop-h72vkdj:8765/")

    def test_bare_address_gets_scheme_and_port(self):
        self.assertEqual(launcher.display_url("192.168.4.109", 8765), "http://192.168.4.109:8765/")
        self.assertEqual(launcher.display_url(" 192.168.4.109:9000 ", 8765), "http://192.168.4.109:9000/")


SPANS = [{"start": "2026-11-13T16:17:00-05:00", "end": "2026-11-14T17:20:00-05:00"}]
SCR = r"C:\ShabbatDisplay\saver\ShabbatDisplay.scr"


def at(s):
    return datetime.fromisoformat(s)


class WindowsSaverTests(unittest.TestCase):
    def test_saver_registry_points_windows_at_the_scr(self):
        self.assertEqual(launcher.saver_registry("saver", 10, True, False, SCR),
                         {"SCRNSAVE.EXE": SCR, "ScreenSaveActive": "1", "ScreenSaveTimeOut": "600", "ScreenSaverIsSecure": "1"})

    def test_holy_turns_lock_off(self):
        self.assertEqual(launcher.saver_registry("saver", 10, True, True, SCR)["ScreenSaverIsSecure"], "0")

    def test_only_changed_values_are_written(self):
        want = launcher.saver_registry("saver", 10, True, False, SCR)
        self.assertEqual(launcher.registry_changes(want, dict(want, ScreenSaveTimeOut="300"), "saver", SCR), {"ScreenSaveTimeOut": "600"})
        self.assertEqual(launcher.registry_changes(want, want, "saver", SCR), {})

    def test_off_only_undoes_our_own_saver(self):
        off = launcher.saver_registry("off", 10, True, False, SCR)
        mystify = {"SCRNSAVE.EXE": r"C:\Windows\system32\Mystify.scr", "ScreenSaveActive": "1"}
        self.assertEqual(launcher.registry_changes(off, mystify, "off", SCR), {})
        ours = {"SCRNSAVE.EXE": SCR.lower(), "ScreenSaveActive": "1"}
        self.assertEqual(launcher.registry_changes(off, ours, "off", SCR), {"ScreenSaveActive": "0"})

    def test_scr_path_with_spaces_uses_short_path(self):
        self.assertEqual(launcher.scr_registry_path(SCR, shorten=lambda p: "X"), SCR)
        self.assertEqual(launcher.scr_registry_path(r"C:\dev\shabbat display\saver\ShabbatDisplay.scr",
                                                    shorten=lambda p: r"C:\dev\SHABBA~1\saver\SHABBA~1.SCR"),
                         r"C:\dev\SHABBA~1\saver\SHABBA~1.SCR")

    def test_scr_path_uses_windows_separators(self):
        self.assertEqual(launcher.scr_registry_path("C:/ShabbatDisplay/saver/ShabbatDisplay.scr"), SCR)

    def test_holy_now_and_shabbat_day(self):
        cases = {"2026-11-12T23:00:00-05:00": (False, False), "2026-11-13T09:00:00-05:00": (False, True),
                 "2026-11-13T16:30:00-05:00": (True, True), "2026-11-14T17:30:00-05:00": (False, False)}
        for t, (holy, day) in cases.items():
            self.assertEqual((launcher.holy_now(SPANS, at(t)), launcher.shabbat_day(SPANS, at(t))), (holy, day), t)

    def test_bad_spans_are_skipped(self):
        bad = [{"start": "soon", "end": "later"}, "x", {"start": "2026-11-13T16:17:00-05:00"}]
        self.assertFalse(launcher.holy_now(bad + [], at("2026-11-13T16:30:00-05:00")))
        self.assertTrue(launcher.holy_now(bad + SPANS, at("2026-11-13T16:30:00-05:00")))

    def test_screen_off_checked_again_each_day(self):
        # a power plan reset mid-week (Windows Update) must still be caught before Shabbat
        import tempfile
        from unittest import mock

        class Stop(Exception):
            pass

        days = iter([datetime.fromisoformat("2026-11-10T23:59:30-05:00"), datetime.fromisoformat("2026-11-11T00:00:10-05:00")])

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return next(days)

        checks = []
        with tempfile.TemporaryDirectory() as d:
            cache = os.path.join(d, "screen-settings.json")
            with open(cache, "w") as f:
                f.write('{"mode": "saver", "saver": {"minutes": 10, "lock": true, "shabbat": true}, "holy": []}')
            with mock.patch.object(launcher, "SETTINGS_CACHE", cache), \
                    mock.patch.object(launcher, "SAVER_CONFIG", os.path.join(d, "saver.json")), \
                    mock.patch.object(launcher, "datetime", Clock), \
                    mock.patch.object(launcher, "fetch_screen_settings", lambda: None), \
                    mock.patch.object(launcher, "read_saver_registry", lambda: {}), \
                    mock.patch.object(launcher, "apply_registry_changes", lambda c: None), \
                    mock.patch.object(launcher, "restore_brightness", lambda: None), \
                    mock.patch.object(launcher, "set_awake", lambda pc: None), \
                    mock.patch.object(launcher, "screen_off_seconds", lambda: checks.append(1) or 0), \
                    mock.patch.object(launcher, "REMOTE", True), \
                    mock.patch.object(launcher, "log", lambda m: None), \
                    mock.patch.object(launcher.time, "sleep", mock.Mock(side_effect=[None, Stop])):
                with self.assertRaises(Stop):
                    launcher.windows_saver_loop(None, "saver")
        self.assertEqual(len(checks), 2)

    def test_a_change_that_wont_stick_is_logged_once(self):
        # at the lock screen Windows refuses the change, so the launcher tries again every 30 s
        import ctypes
        from unittest import mock
        logged = []
        fake = mock.Mock()
        with mock.patch.object(ctypes, "windll", fake, create=True), mock.patch.object(launcher, "log", logged.append):
            launcher.apply_registry_changes({"ScreenSaverIsSecure": "0"})
            launcher.apply_registry_changes({"ScreenSaverIsSecure": "0"})
            launcher.apply_registry_changes({"ScreenSaverIsSecure": "1"})
        self.assertEqual(len(logged), 2)
        self.assertEqual(fake.user32.SystemParametersInfoW.call_count, 3)

    def test_screen_off_raised_only_when_too_soon(self):
        self.assertEqual(launcher.screen_off_target(10, 10), 30)
        self.assertIsNone(launcher.screen_off_target(0, 10))    # never turns off
        self.assertIsNone(launcher.screen_off_target(45, 10))


class SettingsReadTests(unittest.TestCase):
    def test_bad_settings_file_is_logged(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "settings.json"), "w", encoding="utf-8") as f:
                f.write('{"screensaver_lock": false,}')
            logged = []
            with mock.patch.object(launcher, "HERE", d), mock.patch.object(launcher, "log", logged.append):
                self.assertTrue(launcher.setting("screensaver_lock", True))
        self.assertEqual(len(logged), 1)
        self.assertIn("settings.json", logged[0])


class ScreenSettingsTests(unittest.TestCase):
    """The launcher's own name, and the mode and screen-saver options it takes from the server."""

    def setUp(self):
        import tempfile
        from unittest import mock
        self.mock = mock
        self._dir = tempfile.TemporaryDirectory()
        self._patches = [mock.patch.object(launcher, "HERE", self._dir.name),
                         mock.patch.object(launcher, "SETTINGS_CACHE", os.path.join(self._dir.name, "screen-settings.json")),
                         mock.patch.object(launcher, "log", lambda m: None)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._dir.cleanup()

    def write_settings(self, d):
        import json
        with open(os.path.join(self._dir.name, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)

    def write_cache(self, d):
        import json
        with open(launcher.SETTINGS_CACHE, "w", encoding="utf-8") as f:
            json.dump(d, f)

    def test_screen_name_from_settings_or_pc(self):
        self.write_settings({"screen_name": "Ariela's Acer"})
        self.assertEqual(launcher.screen_name(), "Ariela's Acer")
        self.write_settings({})
        with self.mock.patch.dict(os.environ, {"COMPUTERNAME": "ARIELA-ACER"}):
            self.assertEqual(launcher.screen_name(), "ARIELA-ACER")

    def test_screen_name_is_made_safe(self):
        self.write_settings({"screen_name": "Den / TV 😀" + "x" * 50})
        name = launcher.screen_name()
        self.assertLessEqual(len(name), 40)
        self.assertRegex(name, r"^[A-Za-z0-9][A-Za-z0-9 ._'-]*$")

    def test_server_answer_overrides_settings(self):
        self.write_settings({"screensaver_minutes": 10, "keep_pc_awake": False})
        self.write_cache({"mode": "saver", "saver": {"minutes": 20, "lock": False, "shabbat": True}})
        self.assertEqual(launcher.screen_setting("minutes", 10.0), 20.0)
        self.assertTrue(launcher.screen_setting("shabbat", False))
        self.assertFalse(launcher.screen_setting("lock", True))
        self.assertEqual(launcher.screen_setting("mode", None), "saver")

    def test_off_mode_from_the_server(self):
        self.write_cache({"mode": "off", "saver": {}})
        self.assertEqual(launcher.screen_setting("mode", None), "off")

    def test_old_cache_keep_awake_means_shabbat(self):
        self.write_cache({"mode": "saver", "saver": {"minutes": 10, "lock": True, "screens": "all", "keep_awake": True}})
        self.assertTrue(launcher.screen_setting("shabbat", False))

    def test_shabbat_falls_back_to_keep_pc_awake(self):
        self.write_settings({"keep_pc_awake": True})
        self.assertTrue(launcher.screen_setting("shabbat", False))

    def test_holy_spans_survive_unreachable_server(self):
        self.write_cache({"mode": "saver", "saver": {}, "holy": SPANS})
        with self.mock.patch.object(launcher.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertIsNone(launcher.fetch_screen_settings())
        self.assertEqual(launcher.cached_holy(), SPANS)

    def test_write_saver_config_only_when_changed(self):
        import json
        path = os.path.join(self._dir.name, "saver", "saver.json")
        with self.mock.patch.object(launcher, "SAVER_CONFIG", path):
            self.assertTrue(launcher.write_saver_config("http://100.98.145.119:8765/", "Ariela's Acer", True, SPANS))
            self.assertFalse(launcher.write_saver_config("http://100.98.145.119:8765/", "Ariela's Acer", True, SPANS))
            self.assertTrue(launcher.write_saver_config("http://100.98.145.119:8765/", "Ariela's Acer", False, SPANS))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"url": "http://100.98.145.119:8765/", "screen": "Ariela's Acer",
                                            "shabbat": False, "holy": SPANS})

    def test_local_report_sends_shabbat(self):
        self.write_settings({"screensaver_minutes": 12.0, "keep_pc_awake": True})
        r = launcher.local_report()
        self.assertEqual(set(r), {"mode", "minutes", "lock", "shabbat"})
        self.assertEqual((r["minutes"], r["shabbat"]), ("12", 1))

    def test_corrupt_cache_falls_back_to_settings(self):
        self.write_settings({"screensaver_minutes": 12})
        with open(launcher.SETTINGS_CACHE, "w") as f:
            f.write("{not json")
        self.assertEqual(launcher.screen_setting("minutes", 10.0), 12.0)

    def test_no_answer_ever_uses_startup_flag(self):
        with self.mock.patch.object(launcher, "SAVER", True):
            self.assertEqual(launcher.screen_setting("mode", None), "saver")
        with self.mock.patch.object(launcher, "SAVER", False):
            self.assertEqual(launcher.screen_setting("mode", None), "always")

    def test_unreachable_server_keeps_cache(self):
        self.write_cache({"mode": "always", "saver": {}})
        with self.mock.patch.object(launcher.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertIsNone(launcher.fetch_screen_settings())
        self.assertEqual(launcher.screen_setting("mode", None), "always")

    def test_fetch_writes_cache_and_reports_local_settings(self):
        import io
        import json
        self.write_settings({"screen_name": "Den", "screensaver_minutes": 15, "keep_pc_awake": True})
        seen = []

        class Answer(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(url, timeout=None):
            seen.append(url)
            return Answer(json.dumps({"ok": True, "screen": "Den", "mode": "always", "saver": {"minutes": 15}, "saved": True}).encode())
        with self.mock.patch.object(launcher.urllib.request, "urlopen", fake), \
                self.mock.patch.object(launcher, "SAVER", True):
            got = launcher.fetch_screen_settings()
        self.assertEqual(got["mode"], "always")
        self.assertEqual(launcher.screen_setting("mode", None), "always")
        self.assertIn("api/screen-settings?screen=Den&mode=saver&minutes=15", seen[0])
        self.assertIn("shabbat=1", seen[0])

    def test_page_url_carries_screen(self):
        self.write_settings({"screen_name": "Den"})
        self.assertTrue(launcher.page_url(True).endswith("?screen=Den&saver=1"))
        self.assertTrue(launcher.page_url(False).endswith("?screen=Den"))

    def test_always_profile_found_when_quoted(self):
        # a folder path with a space is quoted on the command line, so the profile is followed by a quote
        cmds = []

        class Done:
            stdout = ""
        with self.mock.patch.object(launcher.subprocess, "run", lambda args, **kw: cmds.append(args[-1]) or Done()):
            launcher.browser_pids(r"C:\Users\Some Name\ShabbatDisplay\browser-profile")
        self.assertIn(r"""-like '*C:\Users\Some Name\ShabbatDisplay\browser-profile"*'""", cmds[0])

    def test_stop_looks_again_for_the_same_profile(self):
        looked = []
        with self.mock.patch.object(launcher, "browser_pids", lambda profile=None: looked.append(profile) or []), \
                self.mock.patch.object(launcher, "browser_running", lambda p: True), \
                self.mock.patch.object(launcher.subprocess, "run", lambda *a, **k: None), \
                self.mock.patch.object(launcher.time, "sleep", lambda s: None):
            launcher.stop_browser([], [launcher.profile_for("always")])
        self.assertTrue(looked)
        self.assertTrue(all(p == launcher.profile_for("always") for p in looked))

    def test_profile_per_mode(self):
        self.assertTrue(launcher.profile_for("saver").endswith("browser-profile-saver"))
        self.assertTrue(launcher.profile_for("always").endswith("browser-profile"))


class AnnounceTests(unittest.TestCase):
    WEEKDAY = datetime.fromisoformat("2026-11-12T12:00:00-05:00")
    SHABBAT = datetime.fromisoformat("2026-11-14T10:00:00-05:00")

    def step(self, mark, answer, now=None, cache=None):
        from unittest import mock
        said = []
        cache = {"holy": SPANS} if cache is None else cache

        def fetch(since):
            if isinstance(answer, Exception):
                raise answer
            return answer
        with mock.patch.object(launcher, "_cached_settings", lambda: cache),                 mock.patch.object(launcher, "screen_name", lambda: "Den"):
            return launcher.announce_step(mark, fetch, said.append, now or self.WEEKDAY), said

    def test_first_answer_only_sets_the_mark(self):
        self.assertEqual(self.step(None, {"last": 4, "items": [{"id": 4, "text": "Dinner", "from": "Kitchen"}]}), (4, []))

    def test_new_ones_are_said_but_not_this_screens_own(self):
        items = [{"id": 5, "text": " Dinner is ready ", "from": "Kitchen"}, {"id": 6, "text": "Mine", "from": "Den"},
                 {"id": 7, "text": "", "from": "x"}, "junk"]
        self.assertEqual(self.step(4, {"last": 7, "items": items}), (7, ["Dinner is ready"]))

    def test_never_on_shabbat_or_with_no_candle_lighting_ahead(self):
        a = {"last": 5, "items": [{"id": 5, "text": "Dinner", "from": "Kitchen"}]}
        self.assertEqual(self.step(4, a, self.SHABBAT), (5, []))
        self.assertEqual(self.step(4, a, datetime.fromisoformat("2026-11-15T10:00:00-05:00")), (5, []))  # a stale calendar
        self.assertEqual(self.step(4, a, cache={}), (5, []))

    def test_switched_off_in_the_app(self):
        a = {"last": 5, "items": [{"id": 5, "text": "Dinner", "from": "Kitchen"}]}
        self.assertEqual(self.step(4, a, cache={"holy": SPANS, "announce": False}), (5, []))

    def test_server_down_or_restarted(self):
        self.assertEqual(self.step(4, OSError("down")), (4, []))
        self.assertEqual(self.step(9, {"last": 0, "items": []}), (0, []))


if __name__ == "__main__":
    unittest.main()
