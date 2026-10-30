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


if __name__ == "__main__":
    unittest.main()
