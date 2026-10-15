"""Arhīvs: iestatījumi un lietu klasifikācijas shēma (kisc/dokumentu-arhivesanas-standarts 02, 04).

    GET  /api/archive/settings                   arhīva iestatījumi (arhīva kods, fonds, reģ. Nr., P2 slēdzis)
    PUT  /api/archive/settings
    GET  /api/archive/schemes                    shēmas pa periodiem
    POST /api/archive/schemes                    jauna shēma (tukša vai kopija no iepriekšējās)
    GET  /api/archive/schemes/active?on=YYYY-MM-DD
    GET  /api/archive/schemes/{id}               shēma ar ierakstiem
    DELETE /api/archive/schemes/{id}             tikai projektu
    POST /api/archive/schemes/{id}/import        .xlsx | .csv | .xml; ?izmeginajums=1 — tikai priekšskatījums
    POST /api/archive/schemes/{id}/status        {statuss, datums, atsauce, piezimes}
    GET  /api/archive/schemes/{id}/problems      kas neļauj apstiprināt
    GET  /api/archive/schemes/{id}/export.xml    ark:KlasifikacijasShema (pārbaudīts pret XSD)
    PATCH /api/archive/schemes/{id}/entries/{eid}
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from opendms.archive import scheme as sch
from opendms.audit import log_integration_event
from opendms.middleware.auth import get_current_user, require_role
from opendms.org_context import get_default_org_required

router = APIRouter(prefix="/api/archive", tags=["Archive"])
ADMIN = require_role("superadmin", "admin")


def _err(e: Exception):
    raise HTTPException(400, str(e))


async def _org() -> dict:
    return dict(await get_default_org_required())


async def _audit(user: dict, org: dict, action: str, entity_id: str, summary: dict):
    try:
        await log_integration_event(actor_user_id=user.get("id"), actor_email=user.get("email"), actor_role=user.get("role"),
                                    organization_id=org["id"], entity_type="classification_scheme", entity_id=entity_id,
                                    action=action, target_system="opendms", success=True,
                                    response_summary=json.dumps(summary, ensure_ascii=False, default=str)[:2000])
    except Exception:
        pass


class SettingsIn(BaseModel):
    archive_code: Optional[str] = None
    archive_name: Optional[str] = None
    fonds_number: Optional[str] = None
    fonds_name: Optional[str] = None
    registration_number: Optional[str] = None
    enforce_registration_minimum: Optional[bool] = None


@router.get("/settings")
async def get_settings(user=Depends(get_current_user)):
    return await sch.get_settings(await _org())


@router.put("/settings")
async def put_settings(body: SettingsIn, user=Depends(ADMIN)):
    org = await _org()
    try:
        out = await sch.put_settings(org, body.model_dump(exclude_unset=True), user.get("email"))
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.settings.update", str(org["id"]), body.model_dump(exclude_unset=True))
    return out


class SchemeIn(BaseModel):
    period_from: date
    period_to: date
    title: Optional[str] = None
    sector: bool = False
    copy_from: Optional[int] = None


@router.get("/schemes")
async def list_schemes(user=Depends(get_current_user)):
    return await sch.list_schemes((await _org())["id"])


@router.post("/schemes", status_code=201)
async def create_scheme(body: SchemeIn, user=Depends(ADMIN)):
    org = await _org()
    try:
        s = await sch.create_scheme(org["id"], body.period_from, body.period_to, body.title, body.sector, body.copy_from, user.get("email"))
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.scheme.create", str(s["id"]), body.model_dump(mode="json"))
    return s


@router.get("/schemes/active")
async def active(on: Optional[date] = None, user=Depends(get_current_user)):
    s = await sch.active_scheme((await _org())["id"], on or date.today())
    if not s:
        raise HTTPException(404, "Šim datumam nav apstiprinātas klasifikācijas shēmas")
    return s


@router.get("/schemes/{scheme_id}")
async def get_scheme(scheme_id: int, user=Depends(get_current_user)):
    try:
        s, entries = await sch.get_scheme((await _org())["id"], scheme_id)
    except sch.SchemeError as e:
        raise HTTPException(404, str(e))
    return {**s, "entries": entries}


@router.delete("/schemes/{scheme_id}", status_code=204)
async def delete_scheme(scheme_id: int, user=Depends(ADMIN)):
    org = await _org()
    try:
        await sch.delete_scheme(org["id"], scheme_id)
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.scheme.delete", str(scheme_id), {})


@router.post("/schemes/{scheme_id}/import")
async def import_scheme(scheme_id: int, file: UploadFile = File(...), izmeginajums: bool = Query(False), user=Depends(ADMIN)):
    org = await _org()
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Datne lielāka par 10 MB")
    name = file.filename or "datne"
    try:
        parsed = sch.parse_ark_xml(data) if name.lower().endswith(".xml") else sch.rows_to_entries(sch.read_table(name, data))
    except sch.SchemeError as e:
        _err(e)
    except Exception as e:
        raise HTTPException(400, f"Datni nevar nolasīt: {type(e).__name__}: {e}")
    preview = {"datne": name, "kopsavilkums": parsed["summary"], "bridinajumi": parsed["warnings"],
               "ailes": parsed.get("columns"), "ieraksti": parsed["entries"][:400]}
    if izmeginajums:
        return {"izmeginajums": True, **preview}
    try:
        prob = await sch.replace_entries(org["id"], scheme_id, parsed, {"veids": "imports", "datne": name,
                                                                        "kas": user.get("email"), "kad": date.today().isoformat(),
                                                                        "bridinajumi": len(parsed["warnings"])})
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.scheme.import", str(scheme_id), {"datne": name, **parsed["summary"]})
    return {"izmeginajums": False, **preview, "problemas": prob}


class StatusIn(BaseModel):
    statuss: str
    datums: Optional[date] = None
    atsauce: Optional[str] = None
    piezimes: Optional[str] = None


@router.post("/schemes/{scheme_id}/status")
async def set_status(scheme_id: int, body: StatusIn, user=Depends(ADMIN)):
    org = await _org()
    try:
        s = await sch.set_status(org["id"], scheme_id, body.statuss, body.datums.isoformat() if body.datums else None,
                                 body.atsauce, body.piezimes, user.get("email"))
    except sch.SchemeError as e:
        _err(e)
    await _audit(user, org, "opendms.archive.scheme.status", str(scheme_id), body.model_dump(mode="json"))
    return s


@router.get("/schemes/{scheme_id}/problems")
async def problems(scheme_id: int, user=Depends(get_current_user)):
    try:
        return await sch.problems((await _org())["id"], scheme_id)
    except sch.SchemeError as e:
        raise HTTPException(404, str(e))


@router.get("/schemes/{scheme_id}/export.xml")
async def export_xml(scheme_id: int, user=Depends(get_current_user)):
    org = await _org()
    try:
        s, entries = await sch.get_scheme(org["id"], scheme_id)
        data = sch.to_ark_xml(s, entries, org, await sch.get_settings(org))
    except sch.SchemeError as e:
        _err(e)
    fname = f"klasifikacijas-shema-{s['period_from']}-{s['period_to']}.xml"
    return Response(data, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class EntryIn(BaseModel):
    name: Optional[str] = None
    retention_kind: Optional[str] = None
    retention_years: Optional[int] = None
    retention_marks: Optional[list[str]] = None
    retention_legal_basis: Optional[str] = None
    retention_trigger: Optional[str] = None
    disposition: Optional[str] = None
    responsible_unit: Optional[str] = None
    responsible_person: Optional[str] = None
    medium: Optional[str] = None
    information_system: Optional[str] = None
    default_info_status: Optional[str] = None
    access_basis: Optional[str] = None
    access_until: Optional[date] = None
    long_running: Optional[bool] = None
    notes: Optional[str] = None


@router.patch("/schemes/{scheme_id}/entries/{entry_id}")
async def patch_entry(scheme_id: int, entry_id: int, body: EntryIn, user=Depends(ADMIN)):
    from opendms.database import get_pool
    org = await _org()
    try:
        s, _ = await sch.get_scheme(org["id"], scheme_id)
    except sch.SchemeError as e:
        raise HTTPException(404, str(e))
    if not s["editable"]:
        raise HTTPException(400, f"Shēmu statusā '{s['status_lv']}' mainīt nevar")
    vals = body.model_dump(exclude_unset=True)
    if not vals:
        return {"ok": True}
    pool = await get_pool()
    async with pool.acquire() as conn:
        sets = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(vals))
        try:
            row = await conn.fetchrow(f"UPDATE scheme_entries SET {sets} WHERE id = $1 AND scheme_id = $2 RETURNING *",
                                      entry_id, scheme_id, *vals.values())
        except Exception as e:
            raise HTTPException(400, f"Nederīga vērtība: {e}")
    if not row:
        raise HTTPException(404, "Ieraksts nav atrasts")
    await _audit(user, org, "opendms.archive.scheme.entry.update", str(entry_id), {k: str(v) for k, v in vals.items()})
    return dict(row)
