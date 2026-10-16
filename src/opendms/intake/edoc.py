"""eDoc (.edoc / .asice) — ASiC-E container unpacking.

An eDoc is a ZIP (ETSI EN 319 162, ASiC-E) with:
    mimetype                    "application/vnd.etsi.asic-e+zip"
    <data files>                the signed documents
    META-INF/manifest.xml       list of data files
    META-INF/signatures*.xml    XAdES signatures, one per signing act

What this module does:
  - returns the data files, so the DVS can read and process the document;
  - reads each signature: signer (certificate subject), issuer, serial,
    certificate validity period, signing time;
  - checks INTEGRITY: every data file a signature references must hash to the
    digest in that signature. A changed file shows up here.

What it does NOT do (stated in the result as `parbaudesApjoms`):
  - cryptographic verification of the SignatureValue;
  - certificate chain, revocation (OCSP/CRL) and timestamp validation.
Those need a qualified validation service (e.g. the eParaksts / DSS validator);
the result says so instead of implying the signature is legally valid.
"""

from __future__ import annotations

import base64
import hashlib
import io
import mimetypes
import posixpath
import zipfile
from datetime import timezone
from typing import Any
from urllib.parse import unquote

from lxml import etree

ASIC_E_MIME = "application/vnd.etsi.asic-e+zip"
EDOC_EXTENSIONS = (".edoc", ".asice", ".sce", ".bdoc")

NS = {
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "xades": "http://uri.etsi.org/01903/v1.3.2#",
    "xades141": "http://uri.etsi.org/01903/v1.4.1#",
}

DIGESTS = {
    "http://www.w3.org/2000/09/xmldsig#sha1": "sha1",
    "http://www.w3.org/2001/04/xmlenc#sha256": "sha256",
    "http://www.w3.org/2001/04/xmldsig-more#sha224": "sha224",
    "http://www.w3.org/2001/04/xmldsig-more#sha384": "sha384",
    "http://www.w3.org/2001/04/xmlenc#sha512": "sha512",
}

MAX_FILES = 50
MAX_TOTAL = 200 * 1024 * 1024  # zip-bomb guard


class EdocError(ValueError):
    pass


def is_edoc(file_name: str, data: bytes) -> bool:
    if (file_name or "").lower().endswith(EDOC_EXTENSIONS):
        return True
    if data[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return z.read("mimetype").strip().decode("ascii", "replace") == ASIC_E_MIME
    except Exception:
        return False


def _guess_mime(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _cert_info(b64: str) -> dict[str, Any]:
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    cert = x509.load_der_x509_certificate(base64.b64decode("".join(b64.split())))

    def attr(name, oid):
        v = name.get_attributes_for_oid(oid)
        return v[0].value if v else None

    subj = cert.subject
    given, sur = attr(subj, NameOID.GIVEN_NAME), attr(subj, NameOID.SURNAME)
    try:
        nb, na = cert.not_valid_before_utc, cert.not_valid_after_utc
    except AttributeError:  # cryptography < 42
        nb, na = cert.not_valid_before.replace(tzinfo=timezone.utc), cert.not_valid_after.replace(tzinfo=timezone.utc)
    return {
        "parakstitajs": " ".join(x for x in (given, sur) if x) or attr(subj, NameOID.COMMON_NAME),
        "organizacija": attr(subj, NameOID.ORGANIZATION_NAME),
        "izdevejs": attr(cert.issuer, NameOID.COMMON_NAME) or cert.issuer.rfc4514_string(),
        "sertifikataNr": format(cert.serial_number, "x"),
        "derigsNo": nb.isoformat(),
        "derigsLidz": na.isoformat(),
        # personal code is in serialNumber (PNOLV-…); not copied into the result
    }


def _signature(xml: bytes, name: str, files: dict[str, bytes]) -> dict[str, Any]:
    out: dict[str, Any] = {"datne": name}
    try:
        root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        return {**out, "kluda": f"XML: {exc}"}
    sig = root if root.tag == f"{{{NS['ds']}}}Signature" else root.find(".//ds:Signature", NS)
    if sig is None:
        return {**out, "kluda": "ds:Signature nav atrasts"}

    cert = sig.find(".//ds:KeyInfo/ds:X509Data/ds:X509Certificate", NS)
    if cert is not None and cert.text:
        try:
            out.update(_cert_info(cert.text))
        except Exception as exc:
            out["sertifikataKluda"] = f"{type(exc).__name__}: {exc}"
    st = sig.find(".//xades:SigningTime", NS)
    if st is not None and st.text:
        out["parakstisanasLaiks"] = st.text.strip()
    if sig.find(".//xades:SignatureTimeStamp", NS) is not None:
        out["laikaZimogs"] = True

    refs = []
    for ref in sig.findall("ds:SignedInfo/ds:Reference", NS):
        uri = ref.get("URI") or ""
        if not uri or uri.startswith("#"):
            continue  # SignedProperties
        fname = unquote(uri)
        alg = DIGESTS.get((ref.find("ds:DigestMethod", NS).get("Algorithm") if ref.find("ds:DigestMethod", NS) is not None else ""))
        dv = (ref.findtext("ds:DigestValue", namespaces=NS) or "").strip()
        rec = {"datne": fname}
        data = files.get(fname)
        if data is None:
            rec["atbilst"] = False
            rec["piezime"] = "datne konteinerā nav atrasta"
        elif alg is None:
            rec["atbilst"] = None
            rec["piezime"] = "nezināms jaucējalgoritms"
        else:
            rec["atbilst"] = base64.b64encode(hashlib.new(alg, data).digest()).decode() == "".join(dv.split())
        refs.append(rec)
    out["atsauces"] = refs
    out["integritate"] = bool(refs) and all(r["atbilst"] is True for r in refs)
    return out


def unpack(data: bytes, file_name: str = "") -> dict[str, Any]:
    """Unpack an eDoc. Returns { datnes: [{file_name, mime_type, data}], paraksti: [...], ... }."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise EdocError(f"nav derīgs eDoc (ZIP) konteiners: {exc}") from exc
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES + 10 or sum(i.file_size for i in infos) > MAX_TOTAL:
            raise EdocError("konteiners pārāk liels")
        mime = None
        files: dict[str, bytes] = {}
        signatures: list[tuple[str, bytes]] = []
        for i in infos:
            name = i.filename
            if name.startswith("/") or ".." in name.split("/"):
                continue
            if name == "mimetype":
                mime = z.read(i).strip().decode("ascii", "replace")
            elif name.startswith("META-INF/"):
                if "signature" in posixpath.basename(name).lower() and name.lower().endswith(".xml"):
                    signatures.append((name, z.read(i)))
            else:
                files[name] = z.read(i)

    paraksti = [_signature(x, n, files) for n, x in sorted(signatures)]
    return {
        "konteiners": file_name,
        "mimetype": mime,
        "asicE": mime == ASIC_E_MIME,
        "datnes": [{"file_name": posixpath.basename(n) or n, "path": n, "mime_type": _guess_mime(n), "data": d}
                   for n, d in files.items()],
        "paraksti": paraksti,
        "parakstuSkaits": len(paraksti),
        "integritateVisiem": bool(paraksti) and all(p.get("integritate") for p in paraksti),
        "parbaudesApjoms": ("Pārbaudīta datņu integritāte pret parakstā norādītajām kontrolsummām "
                            "un nolasīti sertifikāta dati. Paraksta kriptogrāfiskā vērtība, sertifikātu "
                            "ķēde, atsaukšanas statuss un laika zīmogs NAV pārbaudīti."),
    }


def summary(info: dict[str, Any]) -> dict[str, Any]:
    """The part kept in document metadata (no file bytes)."""
    return {k: v for k, v in info.items() if k != "datnes"} | {
        "datnes": [{"file_name": f["file_name"], "mime_type": f["mime_type"], "size": len(f["data"])}
                   for f in info.get("datnes", [])]}
