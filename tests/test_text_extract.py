"""Text extraction for every format an application arrives in: the format comes
from the file's bytes, not the content type the browser sent."""

import io
import shutil
import subprocess
import zipfile

import pytest

from opendms.text_extract import detect_format, extract_text, fit

HAS_SOFFICE = bool(shutil.which("soffice") or shutil.which("libreoffice"))
LV = "Iesniegums tiesībsargam. Ģimene, bērns, šķērslis — Jānis Bērziņš, 2026. gada 20. oktobris."


def _zip(files: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return b.getvalue()


def test_detect_from_bytes_not_from_browser_type():
    rtf = b"{\\rtf1\\ansi Sveiki}"
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100
    docx = _zip({"[Content_Types].xml": "x", "word/document.xml": "<w/>"})
    odt = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": "<x/>"})
    # Windows commonly sends .rtf as application/msword and others as octet-stream
    assert detect_format(rtf, "application/msword", "a.rtf") == "rtf"
    assert detect_format(ole, "application/octet-stream", "a.doc") == "doc"
    assert detect_format(docx, "application/octet-stream", "a.docx") == "docx"
    assert detect_format(odt, "application/octet-stream", "KB-transp08.2026..odt") == "odt"
    assert detect_format(b"%PDF-1.7 ...", "", "x") == "pdf"
    assert detect_format("Labdien, tiesībsarg!".encode(), "", "x") == "text"
    assert detect_format("Labdien".encode("cp1257"), "text/plain", "x.txt") == "text"


def test_plain_text_utf8_and_windows_1257():
    assert extract_text(LV.encode("utf-8"), "text/plain", "a.txt") == LV
    assert extract_text(LV.encode("cp1257"), "text/plain", "a.txt") == LV


def test_fit_keeps_beginning_and_end():
    body = "Ievads. " + "vidus " * 5000 + "2026. gada 13. martā Aija Smilga"
    out = fit(body, 2000)
    assert len(out) <= 2000
    assert out.startswith("Ievads.")
    assert out.endswith("2026. gada 13. martā Aija Smilga")
    assert "izlaista" in out
    assert fit("īss", 2000) == "īss"


@pytest.mark.skipif(not HAS_SOFFICE, reason="LibreOffice not installed")
def test_rtf_with_latvian_letters():
    rtf = (b"{\\rtf1\\ansi\\uc1 Iesniegums: \\u290?imene, b\\u275?rns, \\u353?\\u311?\\u275?rslis.\\par "
           b"J\\u257?nis B\\u275?rzi\\u326?\\u353?}")
    t = extract_text(rtf, "application/msword", "Egons Soms iesniegums.rtf")
    assert "Ģimene, bērns, šķērslis" in t and "Jānis Bērziņš" in t


@pytest.mark.skipif(not HAS_SOFFICE, reason="LibreOffice not installed")
@pytest.mark.parametrize("fmt,flt", [("odt", "odt"), ("doc", "doc:MS Word 97"), ("docx", "docx"), ("rtf", "rtf")])
def test_office_formats_round_trip(tmp_path, fmt, flt):
    src = tmp_path / "in.txt"
    src.write_text(LV + "\n\n" + "Rindkopa. " * 3000 + "\n\nAr cieņu, Jānis Bērziņš", encoding="utf-8")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    subprocess.run([soffice, f"-env:UserInstallation=file://{tmp_path}/p", "--headless", "--infilter=Text (encoded):UTF8",
                    "--convert-to", flt, "--outdir", str(tmp_path), str(src)], check=True, capture_output=True, timeout=120)
    data = (tmp_path / f"in.{fmt}").read_bytes()
    t = extract_text(data, "application/octet-stream", f"Iesniegums..{fmt}")
    assert LV in t
    assert t.rstrip().endswith("Jānis Bērziņš")   # nothing cut: the full text, end included
    assert len(t) > 20000
