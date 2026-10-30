"""Tiny dependency-free PDF writer (A4, built-in Helvetica fonts, word wrap, tables, links, page numbers).

Enough for clean text reports; no images. Text is encoded as Windows-1252 (WinAnsi); unsupported characters are
replaced with close ASCII equivalents.
"""
from __future__ import annotations

import zlib
from datetime import datetime

W, H = 595.28, 841.89  # A4 points
MARGIN = 50
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
        [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
         611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
         556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
        [333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667,
         611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889,
         611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]
_REPL = {"≥": ">=", "≤": "<=", "→": "->", "←": "<-", "✓": "v", "×": "x", "≈": "~", " ": " ", " ": " ", " ": " ", "ₓ": "x"}
GREEN, INK, GREY, AMBER = (0.02, 0.47, 0.34), (0.06, 0.16, 0.14), (0.38, 0.45, 0.43), (0.62, 0.37, 0.02)


def clean(s) -> str:
    s = "" if s is None else str(s)
    return "".join(_REPL.get(ch, ch) for ch in s)


def width(text: str, size: float, bold: bool = False) -> float:
    table = _BOLD if bold else _HELV
    return sum(table[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text) * size / 1000


def wrap(text: str, size: float, max_w: float, bold: bool = False) -> list[str]:
    lines: list[str] = []
    for para in clean(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = (cur + " " + word) if cur else word
            if width(trial, size, bold) <= max_w:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            while width(word, size, bold) > max_w:  # hard-break very long tokens (URLs)
                n = max(1, int(len(word) * max_w / max(1.0, width(word, size, bold))))
                lines.append(word[:n])
                word = word[n:]
            cur = word
        lines.append(cur)
    return lines


def _esc(s: str) -> bytes:
    b = clean(s).encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class PDF:
    def __init__(self, title: str, subtitle: str | None = None) -> None:
        self.doc_title = clean(title)
        self.pages: list[list[bytes]] = []
        self.links: list[list[tuple[float, float, float, float, str]]] = []
        self.y = 0.0
        self._new_page()
        self.text(title, 20, bold=True, color=INK)
        if subtitle:
            self.text(subtitle, 10, color=GREY)
        self.rule()

    # ---------------------------------------------------------------- primitives
    def _new_page(self) -> None:
        self.pages.append([])
        self.links.append([])
        self.y = H - MARGIN

    def _ensure(self, h: float) -> None:
        if self.y - h < MARGIN + 30:
            self._new_page()

    def _op(self, s: bytes) -> None:
        self.pages[-1].append(s)

    def _line(self, txt: str, x: float, size: float, bold: bool, color) -> None:
        r, g, b = color
        self._op(b"BT /%s %.1f Tf %.3f %.3f %.3f rg %.2f %.2f Td (" % (b"F2" if bold else b"F1", size, r, g, b, x, self.y) + _esc(txt) + b") Tj ET\n")

    # ---------------------------------------------------------------- blocks
    def text(self, txt, size: float = 10, bold: bool = False, color=INK, indent: float = 0, gap: float = 4) -> None:
        lead = size * 1.35
        for ln in wrap(txt, size, W - 2 * MARGIN - indent, bold):
            self._ensure(lead)
            self.y -= lead
            self._line(ln, MARGIN + indent, size, bold, color)
        self.y -= gap

    def heading(self, txt: str) -> None:
        self._ensure(40)
        self.y -= 8
        self.text(txt, 13, bold=True, color=GREEN, gap=2)

    def note(self, txt: str) -> None:
        self.text(txt, 8.5, color=GREY, gap=3)

    def warning(self, txt: str) -> None:
        self.text(txt, 9.5, bold=True, color=AMBER, gap=4)

    def bullets(self, items, size: float = 9.5) -> None:
        for it in items:
            lead = size * 1.35
            lines = wrap(str(it), size, W - 2 * MARGIN - 14)
            for i, ln in enumerate(lines):
                self._ensure(lead)
                self.y -= lead
                if i == 0:
                    self._line("-", MARGIN + 2, size, False, GREY)
                self._line(ln, MARGIN + 14, size, False, INK)
        self.y -= 4

    def link(self, label: str, url: str, size: float = 9) -> None:
        txt = f"{label}: {url}"
        lead = size * 1.35
        for ln in wrap(txt, size, W - 2 * MARGIN):
            self._ensure(lead)
            self.y -= lead
            self._line(ln, MARGIN, size, False, GREEN)
            self.links[-1].append((MARGIN, self.y - 2, MARGIN + width(ln, size), self.y + size, url))
        self.y -= 3

    def kv(self, rows: list[tuple[str, str]], key_w: float = 150) -> None:
        for k, v in rows:
            lines = wrap(v if v not in (None, "") else "Not available", 9.5, W - 2 * MARGIN - key_w)
            lead = 9.5 * 1.35
            self._ensure(lead * len(lines))
            for i, ln in enumerate(lines):
                self.y -= lead
                if i == 0:
                    self._line(k, MARGIN, 9.5, True, INK)
                self._line(ln, MARGIN + key_w, 9.5, False, INK)
        self.y -= 4

    def table(self, headers: list[str], rows: list[list], widths: list[float] | None = None, size: float = 9) -> None:
        total = W - 2 * MARGIN
        widths = widths or [1 / len(headers)] * len(headers)
        cols = [w * total for w in widths]
        lead = size * 1.35

        def draw(cells, bold):
            wrapped = [wrap("" if c is None else str(c), size, cw - 6, bold) for c, cw in zip(cells, cols)]
            n = max(len(w) for w in wrapped)
            self._ensure(n * lead + 4)
            top = self.y
            for i in range(n):
                self.y -= lead
                x = MARGIN
                for wl, cw in zip(wrapped, cols):
                    if i < len(wl):
                        self._line(wl[i], x + 3, size, bold, INK)
                    x += cw
            self.y -= 3
            self._op(b"0.85 0.88 0.87 RG 0.5 w %.2f %.2f m %.2f %.2f l S\n" % (MARGIN, self.y, W - MARGIN, self.y))
            return top

        draw(headers, True)
        for r in rows:
            draw(r, False)
        self.y -= 6

    def rule(self) -> None:
        self.y -= 6
        self._op(b"0.02 0.47 0.34 RG 1 w %.2f %.2f m %.2f %.2f l S\n" % (MARGIN, self.y, W - MARGIN, self.y))
        self.y -= 8

    # ---------------------------------------------------------------- output
    def build(self) -> bytes:
        objs: list[bytes] = []
        n_pages = len(self.pages)
        stamp = datetime.now().strftime("%d %b %Y %H:%M")
        font1 = 3
        page_ids, content_ids, annot_ids = [], [], []
        next_id = 5
        for i in range(n_pages):
            page_ids.append(next_id); content_ids.append(next_id + 1); next_id += 2
            annot_ids.append(list(range(next_id, next_id + len(self.links[i])))); next_id += len(self.links[i])
        objs_map: dict[int, bytes] = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % p for p in page_ids) + b"] /Count %d >>" % n_pages,
            font1: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        }
        for i in range(n_pages):
            footer = f"{self.doc_title}  |  Page {i + 1} of {n_pages}  |  Generated {stamp} by SmartPlateAI"
            ops = b"".join(self.pages[i]) + b"BT /F1 7.5 Tf 0.45 0.5 0.5 rg %.2f %.2f Td (" % (MARGIN, 28) + _esc(footer) + b") Tj ET\n"
            data = zlib.compress(ops)
            annots = b" /Annots [" + b" ".join(b"%d 0 R" % a for a in annot_ids[i]) + b"]" if annot_ids[i] else b""
            objs_map[page_ids[i]] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >>"
                                     b" /Contents %d 0 R%s >>" % (W, H, content_ids[i], annots))
            objs_map[content_ids[i]] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream"
            for aid, (x1, y1, x2, y2, url) in zip(annot_ids[i], self.links[i]):
                objs_map[aid] = (b"<< /Type /Annot /Subtype /Link /Rect [%.2f %.2f %.2f %.2f] /Border [0 0 0] /A << /S /URI /URI (" % (x1, y1, x2, y2)
                                 + _esc(url) + b") >> >>")
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for oid in range(1, next_id):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % oid + objs_map[oid] + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % next_id + b"".join(b"%010d 00000 n \n" % o for o in offsets)
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info << /Title (" % next_id + _esc(self.doc_title) + b") /Producer (SmartPlateAI) >> >>\n"
        out += b"startxref\n%d\n%%%%EOF\n" % xref
        objs.clear()
        return bytes(out)
