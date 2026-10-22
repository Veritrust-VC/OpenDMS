"""LNA pieņemšanas simulators — laboratorijas aizstājējs Latvijas Nacionālā arhīva elektroniskajai saskarnei.

Ko simulē (MK 07.05.2024. noteikumi Nr. 282; kisc/dokumentu-arhivesanas-standarts):

    POST /api/v1/iesniegumi            iestāde iesniedz:
        veids=akts        iznīcināšanas akts (ark:IznicinasanasAkts) saskaņošanai        (104. p.)
        veids=saraksts    uzskaites saraksts (ark:UzskaitesSaraksts) apstiprināšanai     (94.–96. p.)
        veids=plans       gada vienošanās par nodošanas laiku un apjomu                   (174. p.)
        veids=nodosana    OPEX pakotne, kas augšupielādēta LNA S3 ievades krātuvē          (69., 176. p.)
    GET  /api/v1/iesniegumi/{id}       statuss un LNA lēmums
    GET  /                             LNA arhīvista skats (saraksts, lēmumi, manuālā izskatīšana)
    POST /ui/lemums/{id}               manuāls lēmums (režīms LNA_REVIEW=manual)

Nodošana: iestāde augšupielādē <pakotne>.zip un <pakotne>.zip.sha256 S3 krātuvē (LNA_S3_BUCKET, prefikss
<iestāde>/), tad iesniedz {s3Key}. Simulators pārbauda kontrolsummu, pārbauda pakotni ar standarta
pārbaudītāju (riki/validet_pakotni.py), pārbaudes atskaiti ieraksta blakus pakotnei (<pakotne>.parbaude.json)
un, ja pakotne pieņemta, izvērš to "glabātavā" (glabatava/<iestāde>/<pakotne>/), kā Preservica OPEX
pakāpeniskā ielāde.

Atšķirības no LNA (apzināti, laboratorijai):
  - JSON pār HTTP ar iestādes žetonu, nevis LNA pieņemtais kanāls un paraksts;
  - lēmumus pēc noteikumiem pieņem automātiski (LNA_REVIEW=auto) vai arhīvists šajā skatā (manual);
  - akta un saraksta saturisko izvērtēšanu aizstāj formālas pārbaudes (XSD, pastāvīgi glabājamie aktā,
    EK izvērtējums, kodu atbilstība).

Konfigurācija: LNA_TOKENS="ombud=<žetons>,varam=<žetons>", LNA_DATA=/data, LNA_REVIEW=auto|manual,
LNA_S3_ENDPOINT, LNA_S3_BUCKET, LNA_S3_ACCESS_KEY, LNA_S3_SECRET_KEY.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from lxml import etree
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
_REPO = HERE.parent / "src" / "opendms" / "archive"          # izstrādē: tieši no OpenDMS
_LNA = HERE / "lna" if (HERE / "lna" / "validator.py").exists() else _REPO / "lna"
_XSD = HERE / "arhivesana-v1.xsd" if (HERE / "arhivesana-v1.xsd").exists() else _REPO / "schemas" / "arhivesana-v1.xsd"
sys.path.insert(0, str(_LNA))
import validator  # noqa: E402  (standarta pārbaudītājs riki/validet_pakotni.py, kopija no opendms/archive/lna)

ARK = "urn:lv:kisc:arhivesana:1.0"
A = {"ark": ARK}
DATA = Path(os.environ.get("LNA_DATA", "/data"))
REVIEW = os.environ.get("LNA_REVIEW", "auto")
BUCKET = os.environ.get("LNA_S3_BUCKET", "lna-ievade")
ARCHIVES = {"LVA": "Latvijas Valsts arhīvs", "LVVA": "Latvijas Valsts vēstures arhīvs",
            "LVKFFDA": "Latvijas Valsts kinofotofonodokumentu arhīvs"}
OFFICER = os.environ.get("LNA_OFFICER", "LNA arhīvists (simulators)")
UNIT = os.environ.get("LNA_UNIT", "Elektronisko dokumentu glabātava (simulators)")

app = FastAPI(title="LNA pieņemšanas simulators (laboratorija)", version="1.0")
_lock = threading.Lock()


def _tokens() -> dict:
    out = {}
    for part in os.environ.get("LNA_TOKENS", "").split(","):
        if "=" in part:
            org, tok = part.split("=", 1)
            out[tok.strip()] = org.strip()
    return out


def _org(authorization: Optional[str]) -> str:
    tok = (authorization or "").removeprefix("Bearer ").strip()
    org = _tokens().get(tok) if tok else None
    if not org:
        raise HTTPException(401, "Nederīgs iestādes žetons")
    return org


def _db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / "lna.db", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS iesniegumi (
        id TEXT PRIMARY KEY, iestade TEXT, veids TEXT, atsauce TEXT, statuss TEXT,
        saturs TEXT, lemums TEXT, izveidots TEXT, izlemts TEXT)""")
    return c


DB = None


def db() -> sqlite3.Connection:
    global DB
    if DB is None:
        DB = _db()
    return DB


def _s3():
    import boto3
    from botocore.config import Config
    return boto3.session.Session().client(
        "s3", endpoint_url=os.environ["LNA_S3_ENDPOINT"], region_name="us-east-1",
        aws_access_key_id=os.environ["LNA_S3_ACCESS_KEY"], aws_secret_access_key=os.environ["LNA_S3_SECRET_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── pārbaudes ───────────────────────────────────────────────────────────────

_xsd = None


def xsd():
    global _xsd
    if _xsd is None:
        _xsd = etree.XMLSchema(etree.parse(str(_XSD)))
    return _xsd


def _parse(xml: str, root_tag: str) -> tuple[Optional[etree._Element], list[str]]:
    try:
        el = etree.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except etree.XMLSyntaxError as e:
        return None, [f"XML nav korekts: {e}"]
    if etree.QName(el).localname != root_tag:
        return None, [f"Gaidīts ark:{root_tag}, saņemts {etree.QName(el).localname}"]
    if not xsd().validate(el.getroottree()):
        return el, [f"XSD: {e.message}" for e in list(xsd().error_log)[:10]]
    return el, []


def review_act(xml: str) -> dict:
    el, errs = _parse(xml, "IznicinasanasAkts")
    if el is not None and not errs:
        for r in el.findall("ark:Ieraksts", A):
            gt = r.find("ark:GlabasanasTermins", A)
            if gt is not None and gt.get("veids") == "Pastavigi":
                errs.append(f"Aktā iekļauta pastāvīgi glabājama lieta: {r.findtext('ark:Nosaukums', namespaces=A)} (107. p.)")
        if el.find("ark:Izvertetaji/ark:EkspertuKomisija", A) is None:
            errs.append("Nav ekspertu komisijas izvērtējuma (protokola Nr. un datums, 106. p.)")
    ok = not errs
    return {"lemums": "Saskanots" if ok else "Noraidits", "piezimes": errs,
            "pamatojums": "Iznīcināšana saskaņota (104. p.)" if ok else "Akts jālabo un jāiesniedz atkārtoti"}


def review_list(xml: str) -> dict:
    el, errs = _parse(xml, "UzskaitesSaraksts")
    if el is not None and not errs:
        arh = el.findtext("ark:Arhivs/ark:Kods", namespaces=A)
        fonds = el.findtext("ark:FondaNumurs", namespaces=A)
        nr = el.get("numurs")
        if arh not in ARCHIVES:
            errs.append(f"Nezināms arhīva kods: {arh} (LNA klasifikators: {', '.join(ARCHIVES)})")
        for v in el.findall("ark:Vieniba", A):
            want = f"LV_LNA_{arh}_F{fonds}_{nr}_{v.get('kartasNumurs')}"
            got = v.findtext("ark:UzskaitesKods", namespaces=A)
            if got != want:
                errs.append(f"Vienībai {v.get('kartasNumurs')} uzskaites kods {got}, gaidīts {want}")
        n = int(el.findtext("ark:Kopsavilkums/ark:VienibuSkaits", namespaces=A) or -1)
        if n != len(el.findall("ark:Vieniba", A)):
            errs.append("Kopsavilkuma vienību skaits nesakrīt ar vienībām sarakstā (88. p.)")
    ok = not errs
    return {"lemums": "Apstiprinats" if ok else "Noraidits", "piezimes": errs,
            "pamatojums": "Uzskaites saraksts apstiprināts (96. p.)" if ok else "Saraksts jālabo (95. p.)"}


def review_plan(data: dict) -> dict:
    year = int(data.get("gads") or date.today().year)
    when = max(date(year, 1, 1) + timedelta(days=150), date.today() + timedelta(days=30))   # ne pagātnē
    return {"lemums": "Saskanots", "piezimes": [], "vienosanasDatums": date.today().isoformat(),
            "nodosanasLaiks": when.isoformat(), "apjoms": data.get("apjoms"),
            "pamatojums": f"Vienošanās par {year}. gada nodošanu (174. p.)"}


def review_package(org: str, key: str) -> dict:
    if not key.startswith(f"{org}/"):
        return {"lemums": "Noraidits", "piezimes": [f"Pakotnei jābūt iestādes prefiksā {org}/"]}
    s3 = _s3()
    with tempfile.TemporaryDirectory() as tmp:
        z = Path(tmp) / Path(key).name
        try:
            s3.download_file(BUCKET, key, str(z))
        except Exception as e:
            return {"lemums": "Noraidits", "piezimes": [f"Pakotne nav atrodama S3 krātuvē: {key} ({type(e).__name__})"]}
        try:
            s3.download_file(BUCKET, key + ".sha256", str(z) + ".sha256")
        except Exception:
            pass
        rep = validator.validate_path(z)
        report = {k: rep[k] for k in ("pakotne", "dokumenti", "kludas", "bridinajumi", "ieraksti") if k in rep}
        report["sha256"] = hashlib.sha256(z.read_bytes()).hexdigest()
        s3.put_object(Bucket=BUCKET, Key=key[:-4] + ".parbaude.json",
                      Body=json.dumps(report, ensure_ascii=False, indent=1).encode(), ContentType="application/json")
        ok = rep["derigs"]
        units = 0
        if ok:   # "ielāde": izvērst glabātavā (Preservica OPEX pakāpeniskās ielādes vietā)
            with zipfile.ZipFile(z) as zf:
                for n in zf.namelist():
                    if n.endswith("/"):
                        continue
                    s3.put_object(Bucket=BUCKET, Key=f"glabatava/{org}/{n}", Body=zf.read(n))
                units = len({p.split("/")[4] for p in zf.namelist() if len(p.split("/")) > 5 and p.split("/")[4]})
    errs = [f"{i['vieta']}: {i['zinojums']}" for i in report["ieraksti"] if i["limenis"] == "kluda"]
    return {"lemums": "Pienemts" if ok else "Noraidits", "piezimes": errs[:50],
            "parbaude": {"dokumenti": report.get("dokumenti"), "kludas": report["kludas"], "bridinajumi": report["bridinajumi"],
                         "sha256": report["sha256"], "atskaite": key[:-4] + ".parbaude.json"},
            "pienemsanasAkts": {"datums": date.today().isoformat(), "lnaStrukturvieniba": UNIT, "atbildigais": OFFICER,
                                "vienibas": units, "dokumenti": report.get("dokumenti"),
                                "neatbilstibas": errs[:20], "glabatava": f"glabatava/{org}/"} if ok else None,
            "pamatojums": "Pakotne pieņemta glabāšanā (176. p.)" if ok else "Pakotne neatbilst prasībām — jānovērš kļūdas"}


def decide(row: dict) -> dict:
    data = json.loads(row["saturs"])
    if row["veids"] == "akts":
        return review_act(data["xml"])
    if row["veids"] == "saraksts":
        return review_list(data["xml"])
    if row["veids"] == "plans":
        return review_plan(data)
    if row["veids"] == "nodosana":
        return review_package(row["iestade"], data["s3Key"])
    return {"lemums": "Noraidits", "piezimes": [f"Nezināms veids {row['veids']}"]}


def _save_decision(iid: str, res: dict) -> None:
    with _lock:
        db().execute("UPDATE iesniegumi SET statuss = ?, lemums = ?, izlemts = ? WHERE id = ?",
                     (res["lemums"], json.dumps({**res, "atsauce": f"LNA-SIM-{iid}"}, ensure_ascii=False), _now(), iid))
        db().commit()


# ── API ─────────────────────────────────────────────────────────────────────

class Submission(BaseModel):
    veids: str
    atsauce: Optional[str] = None      # iestādes objekta ID (akts, saraksts, pakotne)
    xml: Optional[str] = None
    s3Key: Optional[str] = None
    gads: Optional[int] = None
    apjoms: Optional[dict] = None


@app.post("/api/v1/iesniegumi", status_code=201)
def submit(s: Submission, authorization: Optional[str] = Header(None)):
    org = _org(authorization)
    if s.veids not in ("akts", "saraksts", "plans", "nodosana"):
        raise HTTPException(400, "veids: akts | saraksts | plans | nodosana")
    if s.veids in ("akts", "saraksts") and not s.xml:
        raise HTTPException(400, "Vajadzīgs xml")
    if s.veids == "nodosana" and not s.s3Key:
        raise HTTPException(400, "Vajadzīgs s3Key")
    iid = f"{date.today():%Y%m%d}-{secrets.token_hex(4)}"
    row = {"id": iid, "iestade": org, "veids": s.veids, "atsauce": s.atsauce, "statuss": "Sanemts",
           "saturs": json.dumps(s.model_dump(exclude_none=True), ensure_ascii=False)}
    with _lock:
        db().execute("INSERT INTO iesniegumi (id, iestade, veids, atsauce, statuss, saturs, izveidots) VALUES (?,?,?,?,?,?,?)",
                     (iid, org, s.veids, s.atsauce, "Sanemts", row["saturs"], _now()))
        db().commit()
    if REVIEW == "auto":
        _save_decision(iid, decide(row))
    return get(iid, authorization)


@app.get("/api/v1/iesniegumi/{iid}")
def get(iid: str, authorization: Optional[str] = Header(None)):
    org = _org(authorization)
    r = db().execute("SELECT * FROM iesniegumi WHERE id = ? AND iestade = ?", (iid, org)).fetchone()
    if not r:
        raise HTTPException(404, "Iesniegums nav atrasts")
    return {"id": r["id"], "veids": r["veids"], "atsauce": r["atsauce"], "statuss": r["statuss"],
            "izlemts": r["izlemts"], "lemums": json.loads(r["lemums"]) if r["lemums"] else None}


@app.get("/health")
def health():
    return {"ok": True, "rezims": REVIEW, "iestades": sorted(set(_tokens().values()))}


# ── arhīvista skats ─────────────────────────────────────────────────────────

VEIDS_LV = {"akts": "Iznīcināšanas akts", "saraksts": "Uzskaites saraksts", "plans": "Nodošanas vienošanās", "nodosana": "Nodošana (OPEX)"}


@app.get("/", response_class=HTMLResponse)
def ui():
    rows = db().execute("SELECT * FROM iesniegumi ORDER BY izveidots DESC LIMIT 200").fetchall()
    tr = []
    for r in rows:
        lem = json.loads(r["lemums"]) if r["lemums"] else {}
        notes = "<br>".join(html.escape(n) for n in (lem.get("piezimes") or [])[:5])
        act = ""
        if r["statuss"] == "Sanemts":
            opts = {"akts": ("Saskanots", "Noraidits"), "saraksts": ("Apstiprinats", "Noraidits"),
                    "plans": ("Saskanots", "Noraidits"), "nodosana": ("Pienemts", "Noraidits")}[r["veids"]]
            act = "".join(f'<form method="post" action="ui/lemums/{r["id"]}" style="display:inline">'
                          f'<button name="lemums" value="{o}">{o}</button></form> ' for o in opts)
            act += f'<form method="post" action="ui/parbaudit/{r["id"]}" style="display:inline"><button>Pārbaudīt pēc noteikumiem</button></form>'
        tr.append(f"<tr><td>{r['izveidots'][:16].replace('T', ' ')}</td><td>{html.escape(r['iestade'])}</td>"
                  f"<td>{VEIDS_LV.get(r['veids'], r['veids'])}</td><td>{html.escape(r['atsauce'] or '')}</td>"
                  f"<td><b>{r['statuss']}</b><br><small>{html.escape(lem.get('pamatojums') or '')}</small></td><td><small>{notes}</small></td><td>{act}</td></tr>")
    return f"""<!doctype html><html lang="lv"><head><meta charset="utf-8"><title>LNA simulators</title>
<style>body{{font:14px system-ui;margin:24px;color:#1f2937}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e5e7eb;padding:6px;text-align:left;vertical-align:top}}
.n{{background:#fef3c7;padding:8px 12px;border-radius:6px;margin-bottom:12px}}</style></head><body>
<h2>Latvijas Nacionālais arhīvs — pieņemšanas simulators</h2>
<div class="n">Laboratorijas simulators, nevis LNA sistēma. Režīms: <b>{REVIEW}</b>. Iestādes: {html.escape(', '.join(sorted(set(_tokens().values()))))}.</div>
<table><tr><th>Saņemts</th><th>Iestāde</th><th>Veids</th><th>Iestādes atsauce</th><th>Statuss</th><th>Piezīmes</th><th></th></tr>{''.join(tr)}</table></body></html>"""


@app.post("/ui/lemums/{iid}")
def ui_decide(iid: str, lemums: str = Form(...)):
    r = db().execute("SELECT * FROM iesniegumi WHERE id = ?", (iid,)).fetchone()
    if not r or r["statuss"] != "Sanemts":
        raise HTTPException(409, "Jau izlemts")
    _save_decision(iid, {"lemums": lemums, "piezimes": [], "pamatojums": f"Arhīvista lēmums: {lemums}"})
    return RedirectResponse("../..", status_code=303)


@app.post("/ui/parbaudit/{iid}")
def ui_check(iid: str):
    r = db().execute("SELECT * FROM iesniegumi WHERE id = ?", (iid,)).fetchone()
    if not r or r["statuss"] != "Sanemts":
        raise HTTPException(409, "Jau izlemts")
    _save_decision(iid, decide(dict(r)))
    return RedirectResponse("../..", status_code=303)
