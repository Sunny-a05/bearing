#!/usr/bin/env python3
"""extract.py — universal text extraction for the dock (stdlib-first).

Turns any inbox file into plain text so the thin-digest pass (os/dock/DOCK.md
step 1) can run on it, whatever the format. Pure stdlib covers: txt/md/html/
docx/pptx/xlsx/odt/ods/odp/epub/rtf/csv/json/ipynb — plus a basic built-in PDF
parser. If `pypdf` (or PyPDF2) is installed it is used automatically for PDFs:
better quality, and real decryption support for password-locked files.

Failure is honest, never silent:
  - scanned / image-only PDFs -> needs_ocr=True — route to Gemini or Claude
    vision per os/orchestration.md (multimodal row), don't digest locally.
  - password-locked PDFs      -> retry with --password, or install pypdf.
  - legacy/unknown binaries   -> flagged unsupported, with a routing hint.

Standalone:
  python os/cli/extract.py <file> [--password PW] [--out out.txt]

Importable:
  from extract import extract
  r = extract(path)          # ExtractResult: .text .method .warnings .needs_ocr .ok
"""
import json
import re
import sys
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------- result type

class ExtractResult:
    def __init__(self, text="", method="", warnings=None, needs_ocr=False, ok=True):
        self.text = text
        self.method = method
        self.warnings = warnings or []
        self.needs_ocr = needs_ocr
        self.ok = ok

    def summary(self) -> str:
        lines = [f"method: {self.method}", f"chars:  {len(self.text):,}"]
        if self.needs_ocr:
            lines.append("NEEDS OCR — no machine-readable text. Route to Gemini "
                         "(multimodal) or Claude vision per os/orchestration.md.")
        for w in self.warnings:
            lines.append(f"warning: {w}")
        if not self.ok:
            lines.append("EXTRACTION FAILED — see warnings above.")
        return "\n".join(lines)


TEXT_EXTS = {".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json",
             ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".py", ".js", ".ts",
             ".sh", ".bat", ".ps1", ".sql", ".tex"}

# ------------------------------------------------------------------- helpers

def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# ---------------------------------------------------------------------- html

class _HTMLText(HTMLParser):
    _SKIP = {"script", "style", "head", "noscript", "template"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
              "section", "article", "blockquote", "pre", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _HTMLText()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return _clean("".join(p.parts))

# --------------------------------------------------------------------- ooxml

def _extract_docx(path: Path) -> ExtractResult:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    lines = []
    for el in root.iter():
        name = _localname(el.tag)
        if name == "p":
            runs = [t.text for t in el.iter() if _localname(t.tag) == "t" and t.text]
            lines.append("".join(runs))
    return ExtractResult(_clean("\n".join(lines)), "docx (stdlib zip+xml)")


def _extract_pptx(path: Path) -> ExtractResult:
    def slide_no(name):
        m = re.search(r"slide(\d+)\.xml$", name)
        return int(m.group(1)) if m else 0

    lines = []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist()
                         if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=slide_no)
        for n in slides:
            lines.append(f"\n--- slide {slide_no(n)} ---")
            root = ET.fromstring(z.read(n))
            for el in root.iter():
                if _localname(el.tag) == "p":
                    runs = [t.text for t in el.iter()
                            if _localname(t.tag) == "t" and t.text]
                    if runs:
                        lines.append("".join(runs))
    return ExtractResult(_clean("\n".join(lines)), "pptx (stdlib zip+xml)")


def _extract_xlsx(path: Path) -> ExtractResult:
    shared = []
    lines = []
    with zipfile.ZipFile(path) as z:
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root:
                shared.append("".join(t.text or "" for t in si.iter()
                                       if _localname(t.tag) == "t"))
        sheets = sorted(n for n in z.namelist()
                        if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for n in sheets:
            lines.append(f"\n--- {n.rsplit('/', 1)[-1]} ---")
            root = ET.fromstring(z.read(n))
            for row in (el for el in root.iter() if _localname(el.tag) == "row"):
                cells = []
                for c in (el for el in row.iter() if _localname(el.tag) == "c"):
                    ctype = c.get("t", "")
                    v = next((x.text for x in c.iter()
                              if _localname(x.tag) == "v" and x.text), None)
                    if ctype == "s" and v is not None and v.isdigit() and int(v) < len(shared):
                        cells.append(shared[int(v)])
                    elif ctype == "inlineStr":
                        cells.append("".join(t.text or "" for t in c.iter()
                                             if _localname(t.tag) == "t"))
                    elif v is not None:
                        cells.append(v)
                if any(cells):
                    lines.append("\t".join(cells))
    return ExtractResult(_clean("\n".join(lines)), "xlsx (stdlib zip+xml)")


def _extract_odf(path: Path) -> ExtractResult:
    """ODT / ODS / ODP — OpenDocument content.xml."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    lines = []
    for el in root.iter():
        if _localname(el.tag) in ("p", "h"):
            txt = "".join(el.itertext())
            if txt.strip():
                lines.append(txt)
    return ExtractResult(_clean("\n".join(lines)), f"{path.suffix[1:]} (stdlib zip+xml)")


def _extract_epub(path: Path) -> ExtractResult:
    parts = []
    with zipfile.ZipFile(path) as z:
        docs = sorted(n for n in z.namelist()
                      if n.lower().endswith((".xhtml", ".html", ".htm")))
        for n in docs:
            parts.append(html_to_text(z.read(n).decode("utf-8", errors="replace")))
    return ExtractResult(_clean("\n\n".join(p for p in parts if p)),
                         "epub (stdlib zip+html)")

# ----------------------------------------------------------------------- rtf

_RTF_DESTINATIONS = ("fonttbl", "colortbl", "stylesheet", "info", "pict",
                     "themedata", "header", "footer", "generator", "xmlnstbl")

def _extract_rtf(path: Path) -> ExtractResult:
    text = path.read_text(encoding="latin-1", errors="ignore")
    # drop destination groups (brace-matched)
    for dest in _RTF_DESTINATIONS:
        while True:
            start = text.find("{\\" + dest)
            if start == -1:
                start = text.find("{\\*\\" + dest)
            if start == -1:
                break
            depth, i = 0, start
            while i < len(text):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            text = text[:start] + text[i + 1:]
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    text = text.replace("\\par", "\n").replace("\\line", "\n").replace("\\tab", "\t")
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)   # control words
    text = text.replace("{", "").replace("}", "").replace("\\", "")
    return ExtractResult(_clean(text), "rtf (stdlib, approximate)",
                         warnings=["RTF stripping is approximate — spot-check the output."])

# --------------------------------------------------------------------- ipynb

def _extract_ipynb(path: Path) -> ExtractResult:
    nb = json.loads(_read_text(path))
    parts = []
    for cell in nb.get("cells", []):
        src = "".join(cell.get("source", []))
        if cell.get("cell_type") == "code":
            src = "```\n" + src + "\n```"
        parts.append(src)
    return ExtractResult(_clean("\n\n".join(parts)), "ipynb (stdlib json)")

# ----------------------------------------------------------------------- pdf

def _pypdf_reader():
    try:
        from pypdf import PdfReader
        return PdfReader, "pypdf"
    except ImportError:
        pass
    try:
        from PyPDF2 import PdfReader
        return PdfReader, "PyPDF2"
    except ImportError:
        return None, None


def _extract_pdf_pypdf(path: Path, password: str) -> ExtractResult:
    PdfReader, libname = _pypdf_reader()
    reader = PdfReader(str(path))
    warnings = []
    if reader.is_encrypted:
        # empty owner-password first (very common), then the supplied one
        unlocked = False
        for pw in ("", password or ""):
            try:
                if reader.decrypt(pw):
                    unlocked = True
                    break
            except Exception:
                continue
        if not unlocked:
            return ExtractResult(
                "", f"pdf ({libname})", ok=False,
                warnings=["PDF is password-locked and neither the empty password nor "
                          "the supplied one opened it. Get the password from the owner and "
                          "rerun with --password."])
        warnings.append("PDF was encrypted — decrypted successfully.")
    pages = []
    for pg in reader.pages:
        try:
            pages.append(pg.extract_text() or "")
        except Exception as e:
            warnings.append(f"page extraction error: {e}")
            pages.append("")
    text = _clean("\n\n".join(pages))
    if len(text) < 20 * max(len(reader.pages), 1):
        return ExtractResult(text, f"pdf ({libname})", warnings=warnings, needs_ocr=True)
    return ExtractResult(text, f"pdf ({libname})", warnings=warnings)


_PDF_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
                b"(": b"(", b")": b")", b"\\": b"\\"}


def _pdf_unescape(s: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(s):
        if s[i:i + 1] == b"\\" and i + 1 < len(s):
            nxt = s[i + 1:i + 2]
            if nxt in _PDF_ESCAPES:
                out += _PDF_ESCAPES[nxt]
                i += 2
                continue
            m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
            i += 1
            continue
        out += s[i:i + 1]
        i += 1
    return bytes(out)


_PDF_TOKEN = re.compile(
    rb"(\((?:\\.|[^\\()])*\))"        # literal string
    rb"|(<[0-9A-Fa-f\s]*>)"           # hex string
    rb"|(T\*|Td|TD)"                  # line-advance operators
)


def _pdf_decode_str(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16-be", errors="replace").lstrip("﻿")
        except Exception:
            pass
    return raw.decode("latin-1", errors="replace")


def _extract_pdf_stdlib(path: Path) -> ExtractResult:
    data = path.read_bytes()
    warnings = ["built-in PDF parser (approximate) — install pypdf for better results: "
                "pip install pypdf"]
    if b"/Encrypt" in data:
        return ExtractResult(
            "", "pdf (stdlib)", ok=False,
            warnings=["PDF is encrypted — the built-in parser cannot decrypt. "
                      "Install pypdf (pip install pypdf) and rerun "
                      "(add --password if it has a real password)."])
    # decompress every Flate stream; keep raw streams that already look like content
    contents = []
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        raw = data[start:end].rstrip(b"\r\n")
        try:
            contents.append(zlib.decompress(raw))
        except zlib.error:
            if b"BT" in raw and b"ET" in raw:
                contents.append(raw)
    parts = []
    for content in contents:
        for bt in re.finditer(rb"BT(.*?)ET", content, re.DOTALL):
            buf = []
            for tok in _PDF_TOKEN.finditer(bt.group(1)):
                lit, hexs, op = tok.groups()
                if lit is not None:
                    buf.append(_pdf_decode_str(_pdf_unescape(lit[1:-1])))
                elif hexs is not None:
                    hx = re.sub(rb"\s", b"", hexs[1:-1])
                    if len(hx) % 2:
                        hx += b"0"
                    try:
                        buf.append(_pdf_decode_str(bytes.fromhex(hx.decode("ascii"))))
                    except ValueError:
                        pass
                elif op is not None:
                    buf.append("\n")
            parts.append("".join(buf))
    text = _clean("\n".join(parts))
    if not text:
        if any(k in data for k in (b"/DCTDecode", b"/JPXDecode", b"/CCITTFaxDecode", b"/Image")):
            return ExtractResult("", "pdf (stdlib)", warnings=warnings, needs_ocr=True)
        return ExtractResult("", "pdf (stdlib)", ok=False,
                             warnings=warnings + ["no text found and no obvious page "
                                                  "images — file may be malformed."])
    # garbage heuristic: subsetted fonts without ToUnicode decode to junk
    sample = text[:2000]
    good = sum(1 for ch in sample if ch.isalnum() or ch in " .,;:!?'\"()-\n\t")
    if sample and good / len(sample) < 0.6:
        warnings.append("extracted text looks garbled (subsetted fonts?) — "
                        "treat as unreliable; use pypdf or route to Gemini.")
    return ExtractResult(text, "pdf (stdlib, approximate)", warnings=warnings)


def _extract_pdf(path: Path, password: str = "") -> ExtractResult:
    if _pypdf_reader()[0] is not None:
        try:
            return _extract_pdf_pypdf(path, password)
        except Exception as e:
            fallback = _extract_pdf_stdlib(path)
            fallback.warnings.insert(0, f"pypdf failed ({e}) — fell back to built-in parser.")
            return fallback
    return _extract_pdf_stdlib(path)

# ----------------------------------------------------------------- dispatcher

def extract(path, password: str = "") -> ExtractResult:
    """Extract plain text from any supported file. Never raises on bad input."""
    path = Path(path)
    if not path.is_file():
        return ExtractResult("", "none", ok=False, warnings=[f"not a file: {path}"])
    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXTS or ext == "":
            return _sniff_text(path)
        if ext in (".html", ".htm", ".xhtml"):
            return ExtractResult(html_to_text(_read_text(path)), "html (stdlib)")
        if ext == ".docx":
            return _extract_docx(path)
        if ext == ".pptx":
            return _extract_pptx(path)
        if ext == ".xlsx":
            return _extract_xlsx(path)
        if ext in (".odt", ".ods", ".odp"):
            return _extract_odf(path)
        if ext == ".epub":
            return _extract_epub(path)
        if ext == ".rtf":
            return _extract_rtf(path)
        if ext == ".ipynb":
            return _extract_ipynb(path)
        if ext == ".pdf":
            return _extract_pdf(path, password)
        if ext in (".doc", ".xls", ".ppt"):
            return ExtractResult("", "none", ok=False,
                                 warnings=[f"legacy binary Office format ({ext}) — convert "
                                           "to the x-variant, or route to Gemini per "
                                           "os/orchestration.md."])
        return _sniff_text(path)
    except Exception as e:
        return ExtractResult("", f"{ext} (failed)", ok=False,
                             warnings=[f"extraction error: {e.__class__.__name__}: {e}"])


def _sniff_text(path: Path) -> ExtractResult:
    head = path.read_bytes()[:8192]
    if b"\x00" in head:
        return ExtractResult("", "none", ok=False,
                             warnings=[f"unrecognized binary format ({path.suffix or 'no ext'}) "
                                       "— route to Gemini (multimodal) or ask the user."])
    text = _read_text(path)
    bad = text.count("�")
    if text and bad / max(len(text), 1) > 0.15:
        return ExtractResult("", "none", ok=False,
                             warnings=["file decodes badly as UTF-8 — probably binary; "
                                       "route to Gemini or ask the user."])
    return ExtractResult(text, "plain text")

# ----------------------------------------------------------------------- cli

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Extract plain text from any dock file.")
    ap.add_argument("file")
    ap.add_argument("--password", default="", help="password for encrypted PDFs")
    ap.add_argument("--out", help="write text here instead of stdout")
    args = ap.parse_args()
    r = extract(args.file, password=args.password)
    print(r.summary(), file=sys.stderr)
    if args.out:
        Path(args.out).write_text(r.text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(r.text)
    sys.exit(0 if r.ok else 1)


if __name__ == "__main__":
    main()
