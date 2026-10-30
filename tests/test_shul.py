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


if __name__ == "__main__":
    unittest.main()
