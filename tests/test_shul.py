import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
