"""Builds small made-up PDFs shaped like the shul's Word-made bulletin, for tests.

ASCII runs use a WinAnsi font and literal strings. Runs with other characters
(Hebrew) use a Type0 font with 2-byte glyph codes and a ToUnicode map, one run
per character, the way Word writes them.
"""
import zlib


def _lit(s):
    return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def make_pdf(pages):
    """pages: list of pages, each a list of (x, y, text). Returns PDF bytes."""
    codes = {}
    for runs in pages:
        for _, _, text in runs:
            if not text.isascii():
                for ch in text:
                    codes.setdefault(ch, len(codes) + 3)
    objs = {}

    def stream(n, body, extra=""):
        z = zlib.compress(body)
        objs[n] = (f"<</Length {len(z)}/Filter/FlateDecode{extra}>>\nstream\n").encode() + z + b"\nendstream"

    objs[3] = b"<</Type/Font/Subtype/TrueType/BaseFont/TimesNewRoman/Encoding/WinAnsiEncoding>>"
    cmap = "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n" \
           "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n" \
           f"{len(codes)} beginbfchar\n" + \
           "".join(f"<{c:04X}> <{ord(ch):04X}>\n" for ch, c in codes.items()) + \
           "endbfchar\nendcmap\nend\nend\n"
    stream(5, cmap.encode())
    objs[4] = b"<</Type/Font/Subtype/Type0/BaseFont/FrankRuhl/Encoding/Identity-H/ToUnicode 5 0 R>>"
    kids = []
    n = 10
    for runs in pages:
        ops = []
        for x, y, text in runs:
            if text.isascii():
                ops.append(f"BT\n/F1 10.02 Tf\n1 0 0 1 {x} {y} Tm\n[{_lit(text)}] TJ\nET")
            else:
                hexs = "".join(f"{codes[ch]:04X}" for ch in text)
                ops.append(f"BT\n/F2 10.02 Tf\n1 0 0 1 {x} {y} Tm\n[<{hexs}>] TJ\nET")
        stream(n + 1, ("q\n" + "\n".join(ops) + "\nQ").encode())
        objs[n] = (f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 3 0 R/F2 4 0 R>>>>"
                   f"/Contents {n + 1} 0 R>>").encode()
        kids.append(f"{n} 0 R")
        n += 2
    objs[1] = b"<</Type/Catalog/Pages 2 0 R>>"
    objs[2] = f"<</Type/Pages/Count {len(kids)}/Kids[{' '.join(kids)}]>>".encode()
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    for k in sorted(objs):
        out += f"{k} 0 obj\n".encode() + objs[k] + b"\nendobj\n"
    out += b"trailer\n<</Root 1 0 R>>\n%%EOF\n"
    return bytes(out)
