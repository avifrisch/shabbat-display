import importlib.machinery
import importlib.util
import os
import unittest

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


LAPTOP = {"pos": (50, 50), "internal": True}
MONITOR = {"pos": (1970, 50), "internal": False}


class ScreenChoiceTests(unittest.TestCase):
    def test_all_screens_by_default(self):
        self.assertEqual(launcher.pick_screens([LAPTOP, MONITOR], "all"), [(50, 50), (1970, 50)])

    def test_external_only(self):
        self.assertEqual(launcher.pick_screens([LAPTOP, MONITOR], "external"), [(1970, 50)])

    def test_external_falls_back_to_the_laptop_alone(self):
        self.assertEqual(launcher.pick_screens([LAPTOP], "external"), [(50, 50)])

    def test_unknown_value_means_all(self):
        self.assertEqual(launcher.pick_screens([LAPTOP, MONITOR], "both"), [(50, 50), (1970, 50)])


class IdleTests(unittest.TestCase):
    def test_idle_time(self):
        self.assertEqual(launcher.idle_from(tick=100_000, last=40_000), 60.0)

    def test_tick_counter_wrapping(self):
        self.assertEqual(launcher.idle_from(tick=5_000, last=2**32 - 5_000), 10.0)

    def test_input_newer_than_now_is_not_idle(self):
        # input that lands between reading the clock and reading the last input
        self.assertEqual(launcher.idle_from(tick=100_000, last=100_016), 0.0)


class AwakeFlagsTests(unittest.TestCase):
    # ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED
    def test_off_lets_windows_decide(self):
        self.assertEqual(launcher.awake_flags(keep_pc=False, showing=True), 0x80000000)

    def test_idle_pc_stays_awake_but_screens_may_turn_off(self):
        self.assertEqual(launcher.awake_flags(keep_pc=True, showing=False), 0x80000001)

    def test_showing_keeps_the_screens_on(self):
        # on a modern-standby laptop, screens off means standby and a locked PC
        self.assertEqual(launcher.awake_flags(keep_pc=True, showing=True), 0x80000003)


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
        self.write_cache({"mode": "saver", "saver": {"minutes": 20, "lock": True, "screens": "external", "keep_awake": True}})
        self.assertEqual(launcher.screen_setting("minutes", 10.0), 20.0)
        self.assertTrue(launcher.screen_setting("keep_awake", False))
        self.assertEqual(launcher.screen_setting("screens", "all"), "external")
        self.assertEqual(launcher.screen_setting("mode", None), "saver")

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
        self.write_settings({"screen_name": "Den", "screensaver_minutes": 15, "screensaver_screens": "external", "keep_pc_awake": True})
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
        self.assertIn("screens=external", seen[0])
        self.assertIn("awake=1", seen[0])

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


if __name__ == "__main__":
    unittest.main()
