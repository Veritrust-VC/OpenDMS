"""Text from uploaded files — the one place every reader (AI analysis, UAPF
processes, the agent channel) gets a document's text from.

The format is decided from the file's own bytes first, then its name, and only
last from the content type the browser sent: on Windows a .rtf commonly arrives
as application/msword and a .odt as application/octet-stream.

Readers:
  PDF            pdftotext
  DOCX, ODT      pandoc (LibreOffice if pandoc fails)
  DOC, RTF, …    LibreOffice (soffice --convert-to txt), own profile per call
  text, HTML     decoded (UTF-8, else Windows-1257)

The full text is returned. Callers that must fit a model's window use fit(),
which keeps the beginning AND the end: in an application the sender's name,
date, contacts and signature are usually at the end.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

# A ceiling against pathological files, far above any real application.
MAX_EXTRACT = 1_000_000

OFFICE_EXT = {".doc", ".rtf", ".odt", ".docx", ".wpd", ".wps", ".sxw", ".dot", ".dotx", ".ott", ".pages"}


def detect_format(data: bytes, mime_type: str = "", filename: str = "") -> str:
    """'pdf' | 'docx' | 'odt' | 'doc' | 'rtf' | 'html' | 'text' | 'office' | 'unknown'."""
    head = data[:8]
    ext = Path(filename or "").suffix.lower()
    mime = (mime_type or "").lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if data[:5].lstrip(b"\xef\xbb\xbf").startswith(b"{\\rt"):
        return "rtf"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):   # OLE2: Word 97–2003 (or .xls/.msg)
        return "doc" if ext not in (".xls", ".msg", ".ppt") else "office"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(BytesIO(data)) as z:
                names = set(z.namelist())
                if "word/document.xml" in names:
                    return "docx"
                if "mimetype" in names and z.read("mimetype").startswith(b"application/vnd.oasis.opendocument.text"):
                    return "odt"
        except zipfile.BadZipFile:
            pass
        return "office" if ext in OFFICE_EXT else "unknown"
    if "html" in mime or ext in (".html", ".htm"):
        return "html"
    if mime.startswith("text/") or ext in (".txt", ".csv", ".md", ".xml", ".json"):
        return "text"
    if ext == ".pdf" or "pdf" in mime:
        return "pdf"
    if ext in OFFICE_EXT or "msword" in mime or "opendocument" in mime or "rtf" in mime or "wordprocessingml" in mime:
        return "office"
    # No signature and no telling name: treat as text if it decodes cleanly.
    try:
        data[:4096].decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return "unknown"


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1257"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _run(cmd: list[str], timeout: int) -> str:
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exit {r.returncode}: {r.stderr[:200]!r}")
    return _decode(r.stdout)


def _with_file(data: bytes, suffix: str, fn):
    with tempfile.TemporaryDirectory(prefix="odms-x-") as d:
        src = Path(d) / f"in{suffix}"
        src.write_bytes(data)
        return fn(src, Path(d))


def _pandoc(data: bytes, fmt: str) -> str:
    if not shutil.which("pandoc"):
        raise RuntimeError("pandoc missing")
    return _with_file(data, f".{fmt}", lambda src, _d: _run(
        ["pandoc", f"--from={fmt}", "--to=plain", "--wrap=none", str(src)], 60))


def _soffice(data: bytes, suffix: str) -> str:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice missing")

    def conv(src: Path, d: Path) -> str:
        prof = d / "profile"
        out = d / "out"
        subprocess.run([soffice, f"-env:UserInstallation=file://{prof}", "--headless", "--norestore",
                        "--convert-to", "txt:Text (encoded):UTF8", "--outdir", str(out), str(src)],
                       capture_output=True, timeout=120, check=True)
        res = out / (src.stem + ".txt")
        if not res.exists():
            raise RuntimeError("LibreOffice produced no text")
        return _decode(res.read_bytes())

    return _with_file(data, suffix, conv)


def _pdftotext(data: bytes) -> str:
    return _with_file(data, ".pdf", lambda src, _d: _run(["pdftotext", "-enc", "UTF-8", "-layout", str(src), "-"], 60))


def _html(data: bytes) -> str:
    t = _decode(data)
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    import html as _h
    return _h.unescape(t)


def _tidy(t: str) -> str:
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    t = re.sub(r"[ \t ]+\n", "\n", t)
    t = re.sub(r"\n{4,}", "\n\n\n", t)
    return t.strip()[:MAX_EXTRACT]


def extract_text(data: bytes, mime_type: str = "", filename: str = "") -> str:
    """Full text of a file, or "" when it holds no readable text (a scan, an image)."""
    if not data:
        return ""
    fmt = detect_format(data, mime_type, filename)
    ext = Path(filename or "").suffix.lower()
    tries: list = []
    if fmt == "pdf":
        tries = [_pdftotext]
    elif fmt == "docx":
        tries = [lambda d: _pandoc(d, "docx"), lambda d: _soffice(d, ".docx")]
    elif fmt == "odt":
        tries = [lambda d: _pandoc(d, "odt"), lambda d: _soffice(d, ".odt")]
    elif fmt == "rtf":
        tries = [lambda d: _soffice(d, ".rtf")]
    elif fmt == "doc":
        tries = [lambda d: _soffice(d, ".doc")]
    elif fmt == "office":
        tries = [lambda d: _soffice(d, ext or ".bin")]
    elif fmt == "html":
        tries = [_html]
    elif fmt == "text":
        tries = [_decode]
    for fn in tries:
        try:
            t = _tidy(fn(data))
            if t:
                return t
        except Exception as e:  # one reader failing must not stop the next
            logger.warning("text_extract: %s %s failed: %s", fmt, filename, e)
    return ""


def fit(text: str, limit: int, tail_share: float = 0.3) -> str:
    """Text cut to `limit` characters keeping the beginning and the end."""
    if not text or len(text) <= limit:
        return text or ""
    marker = "\n\n[… teksta vidusdaļa izlaista …]\n\n"
    tail = int(limit * tail_share)
    head = max(0, limit - tail - len(marker))
    return text[:head].rstrip() + marker + text[-tail:].lstrip()
