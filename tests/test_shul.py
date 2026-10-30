import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_server  # noqa: E402  (puts the repo on sys.path)
from pdfmaker import make_pdf  # noqa: E402

server = test_server.server


class PdfTests(unittest.TestCase):
    def test_reads_ascii_runs_with_positions(self):
        pages = server.pdf_pages(make_pdf([[(20, 712, "Candle Lighting"), (185, 712, "5:43 pm")]]))
        self.assertIn((20.0, 712.0, "Candle Lighting"), pages[0])
        self.assertIn((185.0, 712.0, "5:43 pm"), pages[0])

    def test_reads_hebrew_through_tounicode(self):
        pages = server.pdf_pages(make_pdf([[(260, 712, "ת"), (267, 712, "ו")]]))
        self.assertIn((260.0, 712.0, "ת"), pages[0])
        self.assertIn((267.0, 712.0, "ו"), pages[0])

    def test_pages_in_order(self):
        pages = server.pdf_pages(make_pdf([[(20, 700, "first")], [(20, 700, "second (2)")]]))
        self.assertEqual(len(pages), 2)
        self.assertEqual([t for _, _, t in pages[1]], ["second (2)"])

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            server.pdf_pages(b"not a pdf")


def heb(text, right, y, step=6.0):
    """Hebrew placed one character per run, right to left, as Word does."""
    return [(round(right - i * step, 1), y, ch) for i, ch in enumerate(text)]


def box_page(with_ends=True, heading=True):
    """A page laid out like the bulletin's Shabbat Times box (x 20-308), with a
    made-up second column at x 319 and a section below the box."""
    r = []
    if heading:
        r += [(44.4, 730.1, "Shabbat Times")] + heb("זמני שבת", 269, 728.4)
    r += [(19.6, 712, "Candle Lighting"), (185, 712, "5"), (190, 712, ":"), (193, 712, "4"), (198, 712, "3"),
          (205, 712, "pm")] + heb("הדלקת נרות", 299, 712)
    r += [(19.6, 699, "Sephardic"), (61.6, 699, " "), (63.9, 699, "Mincha &"), (104.8, 699, " "),
          (107.1, 699, "Kabbalat "), (184, 693, "5:40 pm"), (19.6, 687, "Shabbat "), (56, 687, "–"),
          (62.2, 687, " "), (64.5, 687, "OLL")] + heb("מנין עדות מזרח", 299, 692, step=3.8)
    r += [(19.6, 674, "Mincha & Kabbalat Shabbat – NM"), (184, 674, "5:50 pm"), (19.6, 645, "Hashkama – New Main"),
          (184, 645, "7:00 am")]
    r += [(19.6, 660, "Latest "), (47.5, 660, "Shema"), (184, 660, "9:5"), (198, 660, "8"), (206, 660, "am")]
    r += [(19.6, 630, "Sefard "), (49, 630, "–"), (55, 630, " "), (57, 630, "Beis Medrash"), (184, 630, "8:30 am")]
    r += heb("נוסח ספרד", 305, 630, step=4.7)
    for y, label, t in ((616, "Sephardic Shacharit – OLL", "9:00 am"), (601, "Ashkenaz – New Main", "9:00 am"),
                        (587, "Ashkenaz – 1/3 Social Hall", "9:10 am"), (572, "Ashkenaz – Old Main", "9:15 am")):
        r += [(19.6, y, label), (184, y, t)]
    r += [(19.6, 558, "Teen Minyan "), (77, 558, "–"), (83, 558, " "), (86, 558, "663 WE Tent"), (185, 558, "9:15 am")]
    r += [(56.8, 544, "Youth Groups Nursery "), (153.6, 544, "–"), (159.7, 544, " "), (162, 544, "4"),
          (167, 547, "th"), (172.9, 544, " "), (175.3, 544, "grade at"),
          (212, 544, "9:15 am in the "), (91, 533, "Youth Classrooms & Nursery Wing"),
          (81, 521, "Junior Congregation – Social Hall Stage")]
    r += [(19.6, 508, "Mommy & Me "), (82, 508, "–"), (88, 508, " "), (90, 508, "2/3 Social Hall"), (182, 508, "10:00 am")]
    r += [(19.6, 495, "Minchas Chinuch "), (95.3, 495, "–"), (101.4, 495, " "), (103.7, 495, "Dr. Alan "),
          (182, 489, "10:30 "), (209, 489, "am"), (21.8, 483, "Kadish"), (51, 483, " "), (53.3, 483, "–"),
          (59.4, 483, " "), (61.7, 483, "after Nusach Sefard")]
    for y, label, t in ((470, "Mincha – New Main", "1:45 pm"), (451, "Parent Learning – BM", "4:15 pm"),
                        (432, "Daf Yomi – OM", "4:40 pm"),
                        (418, "Amud Yomi Chaburah – BM", "4:40 pm"), (403, "Sephardic Mincha – OLL", "5:25 pm"),
                        (389, "Mincha – New Main", "5:40 pm")):
        r += [(19.6, y, label), (184, y, t)]
    r += [(79, 364, "in the New Main after mincha")]
    if with_ends:
        r += [(184, 351, "6:"), (193, 351, "4"), (198, 351, "7 pm"), (19.6, 350, "Maariv & Shabbat Ends")]
        r += heb("מעריב", 299, 350)
        r += [(19.6, 338, "Next Shabbat:"), (185, 336, "5:"), (193, 336, "34"), (205, 336, "pm"),
              (19.6, 327, "Candle lighting"), (186, 311, "5:40 pm"), (19.6, 308, "Mincha & Kabbalat Shabbat")]
        r += heb("הדלקת נרות", 299, 334)
    r += [(34, 297, "Please park responsibly and be considerate of our neighbors")]
    r += [(36, 227, "Made-up building notice at 5:00 pm")]
    # the page's second column: made-up text, some of it with times
    r += [(319.2, 712, "Mazal Tov to the Example family"), (319.2, 630, "Example meeting 8:30 pm"),
          (328.6, 544, "Example shiur 9:15 am"), (319.2, 351, "Example kiddush 6:47 pm")]
    return r


class ShabbatTimesTests(unittest.TestCase):
    def times(self, **kw):
        return server.shabbat_times(server.pdf_pages(make_pdf([[(20, 700, "Page one")], box_page(**kw)])))

    def test_rows_labels_times_hebrew(self):
        rows = self.times()["rows"]
        self.assertEqual(rows[0], {"label": "Candle Lighting", "time": "5:43 pm", "he": "הדלקת נרות"})
        self.assertIn({"label": "Maariv & Shabbat Ends", "time": "6:47 pm", "he": "מעריב"}, rows)
        self.assertIn({"label": "Sephardic Mincha & Kabbalat Shabbat – OLL", "time": "5:40 pm",
                       "he": "מנין עדות מזרח"}, rows)

    def test_split_time_runs_join(self):
        rows = self.times()["rows"]
        self.assertIn({"label": "Latest Shema", "time": "9:58 am", "he": ""}, rows)

    def test_two_line_label(self):
        labels = {r["label"]: r["time"] for r in self.times()["rows"]}
        self.assertEqual(labels["Minchas Chinuch – Dr. Alan Kadish – after Nusach Sefard"], "10:30 am")

    def test_centered_lines_are_notes(self):
        t = self.times()
        self.assertNotIn("9:15 am in the", " ".join(r["label"] for r in t["rows"]))
        notes = [n["text"] for n in t["notes"]]
        self.assertIn("Youth Groups Nursery – 4th grade at 9:15 am in the", notes)
        self.assertIn("Junior Congregation – Social Hall Stage", notes)
        note = next(n for n in t["notes"] if n["text"].startswith("Youth Classrooms"))
        labels = [r["label"] for r in t["rows"]]
        self.assertEqual(labels[note["after"] - 1], "Teen Minyan – 663 WE Tent")

    def test_label_lines_attach_to_their_time(self):
        rows = {r["label"]: r["time"] for r in self.times()["rows"]}
        self.assertEqual(rows["Next Shabbat: Candle lighting"], "5:34 pm")

    def test_no_space_added_inside_words(self):
        t = server.shabbat_times(server.pdf_pages(make_pdf([box_page() + [
            (22, 376, "Example "), (188, 376, "Avraham"), (226, 376, "’"), (228, 376, "s"), (232, 376, " "),
            (234, 376, "Journey"), (268, 376, ", Part II")]])))
        self.assertIn("Example Avraham’s Journey, Part II", [n["text"] for n in t["notes"]])

    def test_right_column_ignored(self):
        t = self.times()
        everything = " ".join([r["label"] for r in t["rows"]] + [n["text"] for n in t["notes"]])
        self.assertNotIn("Example", everything)
        self.assertNotIn("Please park", everything)
        self.assertNotIn("building notice", everything)
        self.assertEqual(len(t["rows"]), 22)

    def test_first_hebrew_letter_kept(self):
        rows = {r["label"]: r["he"] for r in self.times()["rows"]}
        self.assertEqual(rows["Sefard – Beis Medrash"], "נוסח ספרד")

    def test_unreadable_layout_returns_none(self):
        self.assertIsNone(self.times(heading=False))
        self.assertIsNone(self.times(with_ends=False))


IMG = "https://images.shulcloud.com/1268/uploads/"


class LinkTests(unittest.TestCase):
    def test_picks_chart_bulletin_calendars(self):
        links = server.shul_links(test_server.fixture("shul_minyan.html"), test_server.fixture("shul_bulletin.html"),
                                  test_server.fixture("shul_calendar.html"))
        self.assertEqual(links, {
            "chart": IMG + "Weekly-Davening-Schedule/2026/Oct25-weeklydavening.png",
            "bulletin": IMG + "Bulletin/2026/24Oct-LechLecha.pdf",
            "calendars": [IMG + "Monthly-Calendars/2026/November2026.jpg",
                          IMG + "Monthly-Calendars/2026/October2026.jpg"]})

    def test_missing_items_are_none(self):
        self.assertEqual(server.shul_links("", "", ""), {"chart": None, "bulletin": None, "calendars": []})

    def test_file_date_forms(self):
        today = date(2026, 10, 30)
        self.assertEqual(server.file_date("24Oct-LechLecha.pdf", today), date(2026, 10, 24))
        self.assertEqual(server.file_date("Oct25-weeklydavening.png", today), date(2026, 10, 25))
        self.assertEqual(server.file_date("5Sept-Nitzavim-Vayeilech_3.pdf", today), date(2026, 9, 5))

    def test_file_date_none(self):
        self.assertIsNone(server.file_date("PurimScheduleBulletin2026.pdf", date(2026, 10, 30)))

    def test_file_date_year_boundary(self):
        self.assertEqual(server.file_date("3Jan-Vayechi.pdf", date(2026, 12, 30)), date(2027, 1, 3))

    def test_upcoming_shabbat(self):
        self.assertEqual(server.upcoming_shabbat(date(2026, 10, 30)), date(2026, 10, 31))
        self.assertEqual(server.upcoming_shabbat(date(2026, 10, 31)), date(2026, 10, 31))
        self.assertEqual(server.upcoming_shabbat(date(2026, 11, 1)), date(2026, 11, 7))


TZ = timezone(timedelta(hours=-4))
CHART = IMG + "Weekly-Davening-Schedule/2026/Oct25-weeklydavening.png"
BULLETIN = IMG + "Bulletin/2026/24Oct-LechLecha.pdf"
CALS = [IMG + "Monthly-Calendars/2026/November2026.jpg", IMG + "Monthly-Calendars/2026/October2026.jpg"]


class ShulSourceTests(test_server.Isolated):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.web = {
            server.SHUL_SITE + "/minyan": test_server.fixture("shul_minyan.html").encode(),
            server.SHUL_SITE + "/bulletin": test_server.fixture("shul_bulletin.html").encode(),
            server.SHUL_SITE + "/monthlycalendar": test_server.fixture("shul_calendar.html").encode(),
            CHART: b"PNG chart", BULLETIN: make_pdf([[(20, 700, "Page one")], box_page()]),
            CALS[0]: b"JPG nov", CALS[1]: b"JPG oct"}
        self.asked = []
        for p in (mock.patch.object(server, "SHUL_DIR", self.dir),
                  mock.patch.object(server, "shul_get", self.get),
                  mock.patch.object(server.store, "save", lambda: None),
                  mock.patch.object(server, "now", lambda: datetime(2026, 10, 30, 13, 0, tzinfo=TZ))):
            p.start()
            self.addCleanup(p.stop)
        server.store.data.pop("shul", None)

    def get(self, url, limit=20_000_000):
        self.asked.append(url)
        v = self.web[url]
        if isinstance(v, Exception):
            raise v
        return v

    def test_first_run_downloads_everything(self):
        v = server.fetch_shul(force=True)
        self.assertEqual(v["chart"], {"file": "Oct25-weeklydavening.png", "url": CHART, "week_of": "2026-10-25"})
        self.assertEqual(v["bulletin"]["shabbat"], "2026-10-24")
        self.assertEqual(v["bulletin"]["file"], "24Oct-LechLecha.pdf")
        self.assertTrue(v["bulletin"]["times"]["rows"])
        self.assertEqual([c["file"] for c in v["calendars"]], ["November2026.jpg", "October2026.jpg"])
        with open(os.path.join(self.dir, "Oct25-weeklydavening.png"), "rb") as f:
            self.assertEqual(f.read(), b"PNG chart")

    def test_unchanged_urls_not_downloaded(self):
        server.store.data["shul"] = server.fetch_shul(force=True)
        self.asked.clear()
        server.fetch_shul(force=True)
        self.assertEqual(sorted(self.asked), sorted(u for u in self.web if u.startswith(server.SHUL_SITE)))

    def test_not_due_makes_no_requests(self):
        stored = server.fetch_shul(force=True)
        server.store.data["shul"] = stored
        self.asked.clear()
        with mock.patch.object(server, "now", lambda: datetime(2026, 10, 28, 10, 0, tzinfo=TZ)):
            self.assertIs(server.fetch_shul(), stored)
        self.assertEqual(self.asked, [])

    def test_due_friday_window(self):
        cur = server.fetch_shul(force=True)  # bulletin is for Oct 24, last Shabbat
        candles = datetime(2026, 10, 30, 17, 34, tzinfo=TZ)
        fri = lambda h, m: datetime(2026, 10, 30, h, m, tzinfo=TZ)  # noqa: E731
        self.assertTrue(server.shul_due(fri(12, 0), cur, candles))
        self.assertFalse(server.shul_due(fri(11, 59), cur, candles))
        self.assertFalse(server.shul_due(fri(17, 34), cur, candles))
        self.assertFalse(server.shul_due(fri(18, 1), cur, None))
        current = dict(cur, bulletin=dict(cur["bulletin"], shabbat="2026-10-31"))
        self.assertFalse(server.shul_due(fri(13, 0), current, candles))
        self.assertTrue(server.shul_due(fri(13, 0), None, candles))
        os.remove(os.path.join(self.dir, "October2026.jpg"))
        self.assertTrue(server.shul_due(datetime(2026, 10, 28, 10, 0, tzinfo=TZ), current, candles))

    def test_refusal_keeps_old(self):
        stored = server.fetch_shul(force=True)
        server.store.data["shul"] = stored
        self.web[server.SHUL_SITE + "/bulletin"] = urllib.error.HTTPError(
            server.SHUL_SITE + "/bulletin", 406, "Not Acceptable", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            server.fetch_shul(force=True)
        self.assertIs(server.store.get("shul"), stored)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "24Oct-LechLecha.pdf")))

    def test_unreadable_bulletin_times_none(self):
        self.web[BULLETIN] = make_pdf([[(20, 700, "Just a page")]])
        v = server.fetch_shul(force=True)
        self.assertIsNone(v["bulletin"]["times"])
        self.assertEqual(v["bulletin"]["shabbat"], "2026-10-24")
        self.assertEqual(v["chart"]["week_of"], "2026-10-25")

class ShulGetTests(unittest.TestCase):
    def test_requests_say_what_they_are(self):
        seen = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b"ok"

        def opener(req, timeout=None):
            seen.append(req.get_header("User-agent"))
            return Resp()
        with mock.patch.object(server.urllib.request, "urlopen", opener):
            server.shul_get(CHART)
        self.assertEqual(seen, ["ShabbatDisplay/1.0 (personal home display)"])


class ShulRouteTests(test_server.RouteTests):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        with open(os.path.join(self.dir, "Oct25-weeklydavening.png"), "wb") as f:
            f.write(b"PNG chart")
        with open(os.path.join(self.dir, ".hidden"), "wb") as f:
            f.write(b"x")
        p = mock.patch.object(server, "SHUL_DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)

    def test_serves_shul_files(self):
        with server.urllib.request.urlopen(self.base + "/shul/Oct25-weeklydavening.png", timeout=10) as r:
            self.assertEqual((r.status, r.headers["Content-Type"], r.read()), (200, "image/png", b"PNG chart"))

    def test_bad_shul_names_are_404(self):
        for path in ("/shul/..%2fsettings.json", "/shul/.hidden", "/shul/missing.png", "/shul/../server.py",
                     "/shul/"):
            self.assertEqual(self.status(path), 404, path)

    def test_update_from_this_machine(self):
        v = {"chart": {"file": "a.png", "url": "u", "week_of": None},
             "bulletin": None, "calendars": [], "checked": "2026-10-30T13:00:00-04:00"}
        with mock.patch.object(server, "fetch_shul", lambda force=False: v),                 mock.patch.object(server.store, "save", lambda: None):
            with server.urllib.request.urlopen(self.base + "/api/shul-update", timeout=10) as r:
                body = json.loads(r.read())
        self.assertTrue(body["ok"])
        self.assertIn("a.png", body["summary"])
        self.assertIs(server.store.get("shul"), v)


if __name__ == "__main__":
    unittest.main()
