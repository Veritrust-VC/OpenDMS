import base64
import datetime as dt
import hashlib
import io
import zipfile

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from opendms.intake import config as cfg
from opendms.intake import edoc, service


def _cert_b64():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.GIVEN_NAME, "Jānis"),
                      x509.NameAttribute(NameOID.SURNAME, "Paraugs"),
                      x509.NameAttribute(NameOID.COMMON_NAME, "JĀNIS PARAUGS")])
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Testa CA")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(issuer).public_key(key.public_key())
            .serial_number(0x1234).not_valid_before(now).not_valid_after(now + dt.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()


def make_edoc(files: dict, tamper: str | None = None) -> bytes:
    refs = "".join(
        f'<ds:Reference URI="{n}"><ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
        f'<ds:DigestValue>{base64.b64encode(hashlib.sha256(d).digest()).decode()}</ds:DigestValue></ds:Reference>'
        for n, d in files.items())
    sig = (f'<asic:XAdESSignatures xmlns:asic="http://uri.etsi.org/02918/v1.2.1#" '
           f'xmlns:ds="http://www.w3.org/2000/09/xmldsig#" xmlns:xades="http://uri.etsi.org/01903/v1.3.2#">'
           f'<ds:Signature><ds:SignedInfo>{refs}<ds:Reference URI="#sp"/></ds:SignedInfo>'
           f'<ds:KeyInfo><ds:X509Data><ds:X509Certificate>{_cert_b64()}</ds:X509Certificate></ds:X509Data></ds:KeyInfo>'
           f'<ds:Object><xades:QualifyingProperties><xades:SignedProperties><xades:SignedSignatureProperties>'
           f'<xades:SigningTime>2026-10-13T10:00:00Z</xades:SigningTime>'
           f'</xades:SignedSignatureProperties></xades:SignedProperties></xades:QualifyingProperties></ds:Object>'
           f'</ds:Signature></asic:XAdESSignatures>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", edoc.ASIC_E_MIME, compress_type=zipfile.ZIP_STORED)
        for n, d in files.items():
            z.writestr(n, d + (b"x" if n == tamper else b""))
        z.writestr("META-INF/manifest.xml", "<manifest/>")
        z.writestr("META-INF/signatures0.xml", sig)
    return buf.getvalue()


def test_edoc_unpack_and_integrity():
    data = make_edoc({"iesniegums.pdf": b"%PDF-1.4 test", "pielikums.docx": b"PK docx"})
    assert edoc.is_edoc("x.edoc", data) and edoc.is_edoc("x.bin", data)
    info = edoc.unpack(data, "x.edoc")
    assert info["asicE"] and info["parakstuSkaits"] == 1
    assert {f["file_name"] for f in info["datnes"]} == {"iesniegums.pdf", "pielikums.docx"}
    p = info["paraksti"][0]
    assert p["parakstitajs"] == "Jānis Paraugs" and p["izdevejs"] == "Testa CA"
    assert p["parakstisanasLaiks"] == "2026-10-13T10:00:00Z"
    assert p["integritate"] is True and info["integritateVisiem"] is True
    assert "NAV pārbaudīti" in info["parbaudesApjoms"]


def test_edoc_tampered_file_detected():
    info = edoc.unpack(make_edoc({"iesniegums.pdf": b"%PDF-1.4 test"}, tamper="iesniegums.pdf"))
    assert info["paraksti"][0]["integritate"] is False
    assert info["integritateVisiem"] is False


def test_edoc_bad_zip():
    with pytest.raises(edoc.EdocError):
        edoc.unpack(b"not a zip")


def test_expand_orders_signed_first_and_keeps_container():
    container = make_edoc({"iesniegums.pdf": b"%PDF-1.4"})
    files, edocs = service.expand(
        [{"file_name": "foto.jpg", "mime_type": "image/jpeg", "data": b"jpg"},
         {"file_name": "iesniegums.edoc", "mime_type": "application/octet-stream", "data": container}],
        body="Labdien, pielikumā iesniegums par ... " * 5)
    names = [f["file_name"] for f in files]
    assert names == ["iesniegums.pdf", "foto.jpg", "iesniegums.edoc", "pavadteksts.txt"]
    assert files[2]["mime_type"] == edoc.ASIC_E_MIME
    assert len(edocs) == 1 and "datnes" in edocs[0] and "data" not in edocs[0]["datnes"][0]


def test_expand_body_only():
    files, _ = service.expand([], body="Īss teksts")
    assert [f["file_name"] for f in files] == ["pavadteksts.txt"]


def test_sender_allowlist():
    ch = {"atlautie_sutitaji": ["rihards@example.com", "*@weget.cc"]}
    assert cfg.sender_allowed(ch, "Rihards@Example.com")
    assert cfg.sender_allowed(ch, "x@weget.cc")
    assert not cfg.sender_allowed(ch, "spam@other.lv")
    assert cfg.sender_allowed({}, "any@one.lv")


def test_tracking_code_matches_register():
    assert service.tracking_code("did:web:x:doc:1") == hashlib.sha256(b"did:web:x:doc:1").hexdigest()[:8]


def test_ack_text():
    subj, body = service.ack_text({"registracijasNr": "3-00042", "dokumentaId": "LV-DOK:90000000000:2026:abc",
                                   "iestade": "Paraugiestāde", "izsekosanasKods": "ab12cd34",
                                   "izsekosanasSaite": "https://reg.example/track/ab12cd34",
                                   "edoc": [{"konteiners": "i.edoc", "paraksti": [{"parakstitajs": "Jānis Paraugs"}],
                                             "integritateVisiem": True}]}, "Sūdzība")
    assert subj == "Reģistrēts Nr. 3-00042: Sūdzība"
    assert "LV-DOK:90000000000:2026:abc" in body and "/track/ab12cd34" in body and "Jānis Paraugs" in body


def test_form_ack_needs_mail_channel():
    assert service._ack_enabled({"veids": "epasts"})
    assert not service._ack_enabled({"veids": "tiessaistes-forma"})
    assert service._ack_enabled({"veids": "tiessaistes-forma", "apstiprinajums": {"kanals": "epasts"}})


def test_config_file(tmp_path, monkeypatch):
    p = tmp_path / "ievade.yaml"
    p.write_text("registrs_publiskais_url: https://r.example/\nkanali:\n"
                 "  - {id: e, veids: epasts, parole_env: TEST_PW, imap: {host: h, lietotajs: u}}\n"
                 "  - {id: f, veids: tiessaistes-forma, ieslegts: false}\n", encoding="utf-8")
    monkeypatch.setenv("OPENDMS_INTAKE_CONFIG", str(p))
    monkeypatch.setenv("TEST_PW", "secret")
    assert cfg.register_public_url() == "https://r.example"
    assert [c["id"] for c in cfg.channels()] == ["e"]
    v = cfg.public_view(cfg.channel("e"))
    assert v["paroleIestatita"] is True and "secret" not in str(v)
