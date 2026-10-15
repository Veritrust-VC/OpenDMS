"""
Database and storage side of the Dokumentu metadatu standarts v2.0.

Three operations, each exposed to UAPF processes as a host capability
(see opendms.uapf.handlers):

    assign_identifiers(doc_id)          identifier.assign@1
    prepare_storage(doc_id)             storage.prepare@1
    build_package(doc_id, rules)        package.build@1

All three are idempotent: running a process twice on the same document does
not create a second identifier, a second registration event or a second
package folder.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

from opendms.config import get_settings
from opendms.database import get_pool
from opendms.standard import package as pkg
from opendms.standard.ids import (
    PREFIX_CASE,
    PREFIX_DOCUMENT,
    PREFIX_EVENT,
    PREFIX_FILE,
    RIGA,
    make_id,
    org_code_kind,
)
from opendms.storage import get_storage, layout

PACKAGE_ROOT = layout.ROOT   # packages live in the document's own folder (storage/layout.py)


class StandardError(Exception):
    """A document cannot be processed under the standard (e.g. organisation code missing)."""


def _json(v: Any) -> Any:
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


async def _load(conn, doc_id: int) -> tuple[dict, dict]:
    doc = await conn.fetchrow("SELECT * FROM documents WHERE id = $1", int(doc_id))
    if not doc:
        raise LookupError(f"Document not found: {doc_id}")
    doc = dict(doc)
    doc["metadata"] = _json(doc.get("metadata"))
    org = await conn.fetchrow("SELECT * FROM organizations WHERE id = $1", doc.get("org_id"))
    if not org:
        raise StandardError("Document has no organisation; set up the organisation first")
    org = dict(org)
    if not org.get("std_code"):
        raise StandardError(
            f"Organisation '{org.get('name')}' has no standard code (std_code): "
            "set its VPK ID, ATVK code or UR registration number"
        )
    org_code_kind(org["std_code"])
    return doc, org


async def _normalise_files(conn, doc: dict) -> None:
    """A file uploaded through the legacy single-file endpoint lives on the
    documents row. Give it a document_files row so every file is handled alike."""
    if not doc.get("storage_key"):
        return
    exists = await conn.fetchval(
        "SELECT 1 FROM document_files WHERE document_id = $1 AND storage_key = $2",
        doc["id"], doc["storage_key"],
    )
    if exists:
        return
    data = await get_storage().get(doc["storage_key"])
    has_primary = await conn.fetchval(
        "SELECT 1 FROM document_files WHERE document_id = $1 AND is_primary", doc["id"])
    await conn.execute(
        """INSERT INTO document_files (document_id, file_name, mime_type, file_size,
               storage_key, storage_backend, checksum_sha256, is_primary, uploaded_by, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
        doc["id"], doc.get("file_name") or "datne", doc.get("mime_type"),
        len(data) if data is not None else doc.get("file_size"),
        doc["storage_key"], doc.get("storage_backend"),
        pkg.sha256_hex(data) if data is not None else None,
        not has_primary, doc.get("created_by"), doc.get("created_at"),
    )


# ── identifier.assign@1 ───────────────────────────────────────────────────

async def assign_identifiers(doc_id: int, performed_by: str = "OpenDMS process") -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            doc, org = await _load(conn, doc_id)
            code = org["std_code"]
            created = doc.get("created_at") or datetime.now(timezone.utc)

            new = False
            doc_uid = doc.get("doc_uid")
            if not doc_uid:
                doc_uid = make_id(PREFIX_DOCUMENT, code, created)
                await conn.execute("UPDATE documents SET doc_uid = $1 WHERE id = $2", doc_uid, doc["id"])
                new = True

            await _normalise_files(conn, doc)
            rows = await conn.fetch(
                "SELECT id, std_id, created_at FROM document_files WHERE document_id = $1 ORDER BY is_primary DESC, id",
                doc["id"])
            file_ids = []
            for r in rows:
                fid = r["std_id"]
                if not fid:
                    fid = make_id(PREFIX_FILE, code, r["created_at"] or created)
                    await conn.execute("UPDATE document_files SET std_id = $1 WHERE id = $2", fid, r["id"])
                file_ids.append(fid)

            if new:
                await conn.execute(
                    """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
                       VALUES ($1, 'DokumentsRegistrets', NULL, FALSE, $2)""",
                    doc["id"],
                    json.dumps({
                        "registration_number": doc.get("registration_number"),
                        "doc_uid": doc_uid,
                        "performedBy": performed_by,
                    }),
                )

    return {"dokumentaId": doc_uid, "datnuId": file_ids, "jaunsIdentifikators": new,
            "orgKods": code}


# ── storage.prepare@1 ─────────────────────────────────────────────────────

async def prepare_storage(doc_id: int) -> dict:
    pool = await get_pool()
    storage = get_storage()
    async with pool.acquire() as conn:
        doc, _org = await _load(conn, doc_id)
        if not doc.get("doc_uid"):
            raise StandardError("Assign the document identifier (identifier.assign) before preparing storage")
        files = await conn.fetch(
            "SELECT id, file_name, storage_key FROM document_files WHERE document_id = $1 ORDER BY is_primary DESC, id",
            doc["id"])

    folder = pkg.folder_name(doc["doc_uid"])
    prefix = f"{PACKAGE_ROOT}/{folder}"
    copied, moved = [], []
    for f in files:
        target = f"{prefix}/datnes/{f['file_name']}"
        if f["storage_key"] != target:
            if not await storage.exists(target):
                data = await storage.get(f["storage_key"])
                if data is None:
                    raise StandardError(f"File not found in storage: {f['storage_key']}")
                await storage.put(target, data)
            moved.append((f["id"], f["storage_key"], target))
        copied.append(f"datnes/{f['file_name']}")
    # The file now lives in the document's LV-DOK folder: point the records there and
    # drop the temporary DVS-<id> copy (older layouts are left for the relayout step).
    if moved:
        async with pool.acquire() as conn:
            for fid, old, new in moved:
                await conn.execute("UPDATE document_files SET storage_key = $1 WHERE id = $2", new, fid)
                await conn.execute("UPDATE documents SET storage_key = $1 WHERE id = $2 AND storage_key = $3",
                                   new, doc["id"], old)
        for _fid, old, _new in moved:
            if old.startswith(f"{layout.ROOT}/DVS-"):
                await storage.delete(old)
    return {"pakotnesMape": folder, "pakotnesAtslega": prefix, "datnes": copied}


# ── package.build@1 ───────────────────────────────────────────────────────

async def _case_id(conn, org: dict, index: str, name: str, year: int) -> str:
    row = await conn.fetchrow(
        "SELECT case_id FROM standard_cases WHERE org_id = $1 AND case_index = $2 AND case_year = $3",
        org["id"], index, year)
    if row:
        return row["case_id"]
    case_id = make_id(PREFIX_CASE, org["std_code"], datetime.now(timezone.utc))
    await conn.execute(
        """INSERT INTO standard_cases (org_id, case_index, case_year, case_id, case_name)
           VALUES ($1,$2,$3,$4,$5) ON CONFLICT (org_id, case_index, case_year) DO NOTHING""",
        org["id"], index, year, case_id, name)
    return await conn.fetchval(
        "SELECT case_id FROM standard_cases WHERE org_id = $1 AND case_index = $2 AND case_year = $3",
        org["id"], index, year)


def rules_from_variables(v: dict) -> dict:
    """Map process (DMN) output variables to package rules."""
    def b(x, default):
        if isinstance(x, bool):
            return x
        if isinstance(x, str):
            return x.strip().lower() in ("true", "1", "jā", "ja", "yes")
        return default
    return {
        "documentType": {"code": v.get("dokumentaVeidaKods"), "name": v.get("dokumentaVeidaNosaukums"),
                         "version": v.get("klasifikatoraVersija")},
        "caseIndex": v.get("lietasIndekss"),
        "caseName": v.get("lietasNosaukums"),
        "schemeId": v.get("nomenklaturasShemasId"),
        "schemeVersion": v.get("nomenklaturasVersija"),
        "retention": {
            "years": v.get("glabasanasTerminsGadi"),
            "permanent": b(v.get("glabasanasPastavigi"), False),
            "trigger": v.get("glabasanasTriggeris"),
            "disposition": v.get("iznicinasanasDarbiba"),
        },
        "infoStatus": v.get("informacijasStatuss"),
        "personalData": b(v.get("saturPersonasDatus"), True),
        "legalBasis": v.get("piekluvesPamatojums"),
    }


async def build_package(doc_id: int, rules: dict, semantika_xml: bytes | None = None,
                        semantika_versija: str | None = None) -> dict:
    s = get_settings()
    pool = await get_pool()
    storage = get_storage()
    async with pool.acquire() as conn:
        doc, org = await _load(conn, doc_id)
        if not doc.get("doc_uid"):
            raise StandardError("Assign the document identifier (identifier.assign) before building the package")

        created = doc.get("created_at") or datetime.now(timezone.utc)
        year = created.astimezone(RIGA).year
        index = rules.get("caseIndex") or "0"
        name = rules.get("caseName") or "Nenoteikta lieta"
        rules = {**rules, "case": {"id": await _case_id(conn, org, index, name, year),
                                   "index": index, "name": name, "year": year}}
        # dokuments → lieta (arhivēšana 03): tikai ja vēl nav piesaistīts un lieta ir atvērta
        await conn.execute(
            """UPDATE documents d SET case_id = c.id FROM standard_cases c
                WHERE d.id = $1 AND d.case_id IS NULL AND c.org_id = $2 AND c.case_index = $3
                  AND c.case_year = $4 AND c.status = 'Atverta'""", doc["id"], org["id"], index, year)

        files = [dict(r) for r in await conn.fetch(
            "SELECT * FROM document_files WHERE document_id = $1 ORDER BY is_primary DESC, id", doc["id"])]
        if any(not f.get("std_id") for f in files):
            raise StandardError("Some files have no identifier; run identifier.assign again")

        events = [dict(r) for r in await conn.fetch(
            "SELECT * FROM document_events WHERE document_id = $1 ORDER BY created_at, id", doc["id"])]
        for e in events:
            e["details"] = _json(e.get("details"))
        std_events = pkg.standard_events(events)
        for e in std_events:
            if not e.get("std_id"):
                e["std_id"] = make_id(PREFIX_EVENT, org["std_code"], e["created_at"])
                await conn.execute("UPDATE document_events SET std_id = $1 WHERE id = $2", e["std_id"], e["id"])

        user_ids = {i for i in [doc.get("created_by")] + [e.get("actor_id") for e in std_events] if i}
        users = {r["id"]: dict(r) for r in await conn.fetch(
            "SELECT id, email, full_name, department FROM users WHERE id = ANY($1::bigint[])", list(user_ids))}

    folder = pkg.folder_name(doc["doc_uid"])
    prefix = f"{PACKAGE_ROOT}/{folder}"
    contents: dict[str, bytes] = {}
    for f in files:
        data = await storage.get(f"{prefix}/datnes/{f['file_name']}") or await storage.get(f["storage_key"])
        if data is None:
            raise StandardError(f"File not found in storage: {f['file_name']}")
        f["file_size"] = len(data)
        f["checksum_sha256"] = pkg.sha256_hex(data)
        contents[f["file_name"]] = data

    now = datetime.now(timezone.utc)
    # Public name of this DVS: the did:web host when configured (the base URL is
    # the engine's internal callback address, e.g. http://api:8002).
    host_did = s.opendms_host_did or ""
    instance = host_did[len("did:web:"):] if host_did.startswith("did:web:") and "localhost" not in host_did \
        and host_did != "did:web:opendms.local" else None
    system = {"name": "OpenDMS", "instance": instance, "environment": "TEST"}
    document = {**doc, "sdk_did": doc.get("doc_did")}
    meta_xml = pkg.build_metadata_xml(org=org, document=document, files=files, rules=rules,
                                      creator=users.get(doc.get("created_by")), system=system,
                                      generated_at=now, semantic_xml=semantika_xml,
                                      semantic_version=semantika_versija)
    track_xml = pkg.build_tracking_xml(org=org, document=doc, events=std_events, users=users,
                                       generated_at=now)
    package = pkg.assemble(meta_xml, track_xml, contents)
    problems = pkg.validate(package)

    for path, data in package.items():
        await storage.put(f"{prefix}/{path}", data)

    result = {
        "pakotnesMape": folder,
        "pakotnesAtslega": prefix,
        "dokumentaId": doc["doc_uid"],
        "datnes": sorted(package),
        "derigs": not problems,
        "problemas": problems,
        "izveidots": now.isoformat(),
        "noteikumi": {k: v for k, v in rules.items() if k != "case"},   # for rebuild_package
        "semantika": bool(semantika_xml),
    }
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
            json.dumps({"standartaPakotne": result}), doc["id"])
    if problems:
        raise StandardError("Package does not conform to the standard: " + "; ".join(problems[:5]))
    return result


async def rebuild_package(doc_id: int, semantika_xml: bytes | None = None,
                          semantika_versija: str | None = None) -> dict:
    """Build the package again with the rules it was first built with (e.g. to add the
    semantic description in metadati.xml section 13)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        meta = _json(await conn.fetchval("SELECT metadata FROM documents WHERE id = $1", doc_id)) or {}
    prev = meta.get("standartaPakotne") or {}
    if not prev:
        raise StandardError("The document has no package yet (package.build has not run)")
    if "noteikumi" not in prev:
        raise StandardError("The package was built before its rules were kept; it is not rebuilt with default rules")
    rules = prev.get("noteikumi") or {}
    return await build_package(doc_id, rules, semantika_xml=semantika_xml, semantika_versija=semantika_versija)


async def _package_info(doc_id: int) -> tuple[str, list[str]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT doc_uid, metadata FROM documents WHERE id = $1", int(doc_id))
    if not doc or not doc["doc_uid"]:
        raise LookupError("Document has no standard package yet")
    info = _json(doc["metadata"]).get("standartaPakotne") or {}
    if not info.get("datnes"):
        raise LookupError("Document has no standard package yet")
    return pkg.folder_name(doc["doc_uid"]), list(info["datnes"])


def _media_type(path: str) -> str:
    import mimetypes
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".xml"):
        return "application/xml"
    if name == "SHA256SUMS":
        return "text/plain"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


async def package_files(doc_id: int) -> dict:
    """List the files of the stored package with size and SHA-256."""
    folder, paths = await _package_info(doc_id)
    storage = get_storage()
    files = []
    for path in sorted(paths, key=lambda p: (p != "metadati.xml", p != "izsekosana.xml", p == "SHA256SUMS", p)):
        data = await storage.get(f"{PACKAGE_ROOT}/{folder}/{path}")
        files.append({"path": path, "size": len(data) if data is not None else None,
                      "sha256": pkg.sha256_hex(data) if data is not None else None,
                      "mediaType": _media_type(path), "missing": data is None})
    return {"folder": folder, "files": files}


async def package_file(doc_id: int, path: str) -> tuple[bytes, str]:
    """One file of the stored package. Only paths recorded in the package are served."""
    folder, paths = await _package_info(doc_id)
    if path not in paths:
        raise LookupError(f"Not in the package: {path}")
    data = await get_storage().get(f"{PACKAGE_ROOT}/{folder}/{path}")
    if data is None:
        raise LookupError(f"Missing from storage: {path}")
    return data, _media_type(path)


async def package_zip(doc_id: int) -> tuple[str, bytes]:
    """Zip the stored package for download. Returns (zip name, bytes)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT doc_uid, metadata FROM documents WHERE id = $1", int(doc_id))
    if not doc or not doc["doc_uid"]:
        raise LookupError("Document has no standard package yet")
    info = _json(doc["metadata"]).get("standartaPakotne") or {}
    folder = pkg.folder_name(doc["doc_uid"])
    storage = get_storage()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in info.get("datnes") or []:
            data = await storage.get(f"{PACKAGE_ROOT}/{folder}/{path}")
            if data is not None:
                z.writestr(f"{folder}/{path}", data)
    return f"{folder}.zip", buf.getvalue()


# ── storage explorer ──────────────────────────────────────────────────────
# Read-only view of the package root in storage: pakotnes/<DokumentaID>/...
# Only folders that belong to documents of the given organisation are shown,
# and every path is checked segment by segment before it reaches storage.

def _clean_path(path: str) -> list[str]:
    parts = [p for p in (path or "").replace("\\", "/").split("/") if p != ""]
    for p in parts:
        if p in (".", "..") or "\x00" in p:
            raise LookupError("Invalid path")
    return parts


async def _owned_folders(org_id: int) -> dict[str, dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, doc_uid, title, registration_number, status, created_at, metadata
               FROM documents WHERE org_id = $1 AND doc_uid IS NOT NULL""", int(org_id))
    out = {}
    for r in rows:
        info = _json(r["metadata"]).get("standartaPakotne") or {}
        out[pkg.folder_name(r["doc_uid"])] = {
            "documentId": r["id"], "docUid": r["doc_uid"], "title": r["title"],
            "registrationNumber": r["registration_number"], "status": r["status"],
            "created": r["created_at"].isoformat() if r["created_at"] else None,
            "valid": info.get("derigs"), "packageBuilt": info.get("izveidots")}
    return out


async def browse_storage(org_id: int, path: str = "") -> dict:
    """List one level of the package storage. ``path`` is relative to the
    package root: "" lists the document folders, "<folder>[/sub]" lists inside one."""
    parts = _clean_path(path)
    owned = await _owned_folders(org_id)
    storage = get_storage()
    if not parts:
        listing = await storage.list(PACKAGE_ROOT)
        # Newest first: the folder name ends with the document's UUIDv7, which sorts by creation time.
        folders = [{"name": f, "path": f, "document": owned[f]}
                   for f in sorted(listing["folders"], reverse=True) if f in owned]
        return {"root": PACKAGE_ROOT, "path": "", "document": None, "folders": folders, "files": []}
    if parts[0] not in owned:
        raise LookupError("Folder not found")
    rel = "/".join(parts)
    listing = await storage.list(f"{PACKAGE_ROOT}/{rel}")
    return {"root": PACKAGE_ROOT, "path": rel, "document": owned[parts[0]],
            "folders": [{"name": f, "path": f"{rel}/{f}"} for f in listing["folders"]],
            "files": [{**f, "path": f"{rel}/{f['name']}", "mediaType": _media_type(f["name"])}
                      for f in listing["files"]]}


async def read_storage_file(org_id: int, path: str) -> tuple[bytes, str]:
    """One file under the package root, within a folder owned by the organisation."""
    parts = _clean_path(path)
    if len(parts) < 2:
        raise LookupError("Not a file")
    owned = await _owned_folders(org_id)
    if parts[0] not in owned:
        raise LookupError("Folder not found")
    data = await get_storage().get(f"{PACKAGE_ROOT}/{'/'.join(parts)}")
    if data is None:
        raise LookupError("File not found")
    return data, _media_type(parts[-1])
