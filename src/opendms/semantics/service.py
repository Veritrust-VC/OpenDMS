"""
Semantic description of documents (vdvc/dokumentu-semantikas-formats).

Two UAPF capabilities:

  semantics.generate@1  — writes the LOCAL layer from the redacted text, following the
                          profile the process names in schemaRef. After the reviewer's
                          decision the same capability updates it (topics from the final
                          classification, review status) instead of regenerating it.
  semantics.project@1   — makes the CENTRAL layer (projection + identifier patterns + an
                          independent model check), and rebuilds the document package so
                          metadati.xml section 13 carries the local layer. register.submit
                          then sends the central layer.

The format (model, vocabulary, profile, prompts, schemas) is read from ProcessGit, so a
change merged there changes what every DVS writes. Stored in documents.metadata.semantika.
"""

from __future__ import annotations

import io
import json
import logging
import re
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from opendms.database import get_pool
from opendms.semantics import dsf

logger = logging.getLogger(__name__)

_formats: dict[str, tuple[float, dict]] = {}
MONTH_OR_YEAR = re.compile(r"(\d{4}\.?\s*(gad[aā]\s*)?([a-zāčēģīķļņšūž]+[īa]?)?|\d{4}-\d{2}|[a-zāčēģīķļņšūž]+\s+\d{4})", re.I)
CACHE_SECONDS = 600


# ─────────────────────────── the format from ProcessGit ───────────────────────────

def _refs(schema_ref: Optional[str]) -> list[str]:
    return [p[len("processgit:"):] for p in re.split(r"[,\s]+", schema_ref or "") if p.startswith("processgit:")]


async def load_format(schema_ref: Optional[str]) -> dict:
    """{'model', 'schemas', 'profile', 'prompt', 'check_prompt', 'revision', 'repo', 'class_scheme'}"""
    from opendms.uapf.learning import fetch_repo_zip

    refs = _refs(schema_ref)
    prof_ref = next((r for r in refs if "/profili/" in r and r.endswith("profils.yaml")), None)
    if not prof_ref:
        raise ValueError("semantics.* needs schemaRef processgit:<owner>/<repo>/profili/<profils>/profils.yaml")
    owner, repo, path = prof_ref.split("/", 2)
    key = f"{owner}/{repo}"
    hit = _formats.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        fmt = hit[1]
    else:
        data = await fetch_repo_zip(owner, repo)
        z = zipfile.ZipFile(io.BytesIO(data))
        revision = (z.comment or b"").decode("ascii", "ignore").strip()[:12] or "nezinama"
        tmp = Path(tempfile.mkdtemp(prefix="dsf-"))
        z.extractall(tmp)
        root = next(p for p in tmp.iterdir() if p.is_dir())
        fmt = {
            "root": root, "repo": key, "revision": revision,
            "model": dsf.load(root),
            "schemas": {l: json.loads((root / f"shemas/semantika-{l}.schema.json").read_text(encoding="utf-8"))
                        for l in ("lokals", "centrals")},
        }
        _formats[key] = (time.time(), fmt)
    prof_dir = fmt["root"] / Path(path).parent
    profile = next(p for p in fmt["model"]["profili"].values() if (fmt["root"] / p["uzvedne"]).parent == prof_dir)
    out = dict(fmt)
    out["profile"] = profile
    out["prompt"] = (fmt["root"] / profile["uzvedne"]).read_text(encoding="utf-8").split("\n---\n", 1)[-1]
    out["check_prompt"] = (fmt["root"] / profile["parbaudes_uzvedne"]).read_text(encoding="utf-8").split("\n---\n", 1)[-1]
    # The institution's own classifier, if the process names it (an XML file in schemaRef other
    # than the profile): its namespace is Tema.shema; its repository may publish a mapping to
    # EuroVoc in kartejumi/eurovoc.csv (docs/04 of the format).
    out["class_scheme"], out["mapping"], out["eurovoc_candidates"] = None, [], {}
    cref = next((r for r in refs if r.endswith(".xml") and "/profili/" not in r), None)
    if cref:
        out["class_scheme"], out["mapping"] = await _institution_classifier(cref)
    for row in out["mapping"]:
        if row.get("eurovoc"):
            out["eurovoc_candidates"].setdefault(str(row["eurovoc"]), row.get("eurovoc_nosaukums") or "")
    return out


async def _institution_classifier(ref: str) -> tuple[Optional[dict], list[dict]]:
    import csv
    from lxml import etree
    from opendms.uapf.learning import fetch_file, fetch_repo_zip

    root = etree.fromstring(await fetch_file(ref))
    ns = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else None
    scheme = {"uri": ns, "repo": ref} if ns else None
    owner, repo, _ = ref.split("/", 2)
    rows: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(await fetch_repo_zip(owner, repo))) as z:
        name = next((n for n in z.namelist() if n.split("/", 1)[-1] == "kartejumi/eurovoc.csv"), None)
        if name:
            rows = list(csv.DictReader(z.read(name).decode("utf-8").splitlines()))
    return scheme, rows


# ─────────────────────────── helpers ───────────────────────────

def _bullets(d: dict, extra=None) -> str:
    return "\n".join(f"- `{k}` — {v.get('nosaukums', '')}" + (f": {v['definicija']}" if v.get("definicija") else "")
                     + (f" (statusi: {', '.join(v['statusi'])})" if v.get("statusi") else "")
                     for k, v in (d or {}).items())


def _facets(profile: dict, groups: dict) -> str:
    lines = []
    for k, v in (profile.get("pazimes") or {}).items():
        vals = ({g: (x or {}).get("nosaukums", g) for g, x in groups.items()}
                if v.get("vertibas_no") == "vardnica.grupas" else (v.get("vertibas") or {}))
        lines.append(f"- `{k}` ({v.get('nosaukums')}){' — required' if v.get('obligata') else ''}"
                     f"{' — several allowed' if v.get('vairakas') else ''}; value is ONE of: "
                     + "; ".join(f"`{c}` = {lbl}" for c, lbl in vals.items()))
    return "\n".join(lines)


def build_prompt(fmt: dict, text: str) -> str:
    m, p = fmt["model"], fmt["profile"]
    voc = m["vardnica"]
    preds = {**(voc.get("predikati") or {}), **(p.get("predikati") or {})}
    ev = fmt.get("eurovoc_candidates") or {}
    repl = {
        "{{KOPSAVILKUMA_VEIDNE}}": str((p.get("kopsavilkums") or {}).get("veidne", "")).strip(),
        "{{LOMAS}}": _bullets(voc.get("lomas")),
        "{{GRUPAS}}": "\n".join(f"- `{k}` — {v.get('nosaukums')}" for k, v in (voc.get("grupas") or {}).items()),
        "{{PREDIKATI}}": _bullets(preds),
        "{{PAZIMES}}": _facets(p, voc.get("grupas") or {}),
        "{{EUROVOC}}": "\n".join(f"- `{k}` — {v}" for k, v in ev.items()) or "(no candidate list — use EuroVoc concept identifiers)",
        "{{DOKUMENTS}}": text,
    }
    out = fmt["prompt"]
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


def split_pages(text: str) -> list[str]:
    pages = (text or "").split("\f")
    return [p for p in pages if p.strip()] or [text or ""]


def _tokens(s: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-zāčēģīķļņšūž]{4,}", (s or "").lower())}


def locate(quote: str, pages: list[str]) -> dict:
    """Page (1-based) and, when the quote occurs verbatim, its offsets."""
    q = (quote or "").strip()
    for i, p in enumerate(pages, 1):
        k = p.find(q) if q else -1
        if k >= 0:
            return {"lapa": i, "sakums": k, "beigas": k + len(q), "metode": "precizs"}
    qt = _tokens(q)
    best, score = 1, -1.0
    for i, p in enumerate(pages, 1):
        pt = _tokens(p)
        s = len(qt & pt) / (len(qt) or 1)
        if s > score:
            best, score = i, s
    return {"lapa": best, "metode": "aptuvens"}


async def _doc_context(doc_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow(
            """SELECT d.id, d.doc_uid, d.title, d.created_at, d.metadata, o.name AS org_name
                 FROM documents d LEFT JOIN organizations o ON o.id = d.org_id WHERE d.id = $1""", doc_id)
        files = await conn.fetch(
            "SELECT std_id, checksum_sha256, file_name, is_primary FROM document_files WHERE document_id = $1 "
            "ORDER BY is_primary DESC, id", doc_id)
        sess = await conn.fetchval(
            "SELECT package_id FROM uapf_sessions WHERE document_id = $1 AND package_id <> '<pending>' "
            "ORDER BY started_at DESC LIMIT 1", doc_id)
    if not doc:
        raise LookupError(f"Document {doc_id} not found")
    meta = doc["metadata"]
    meta = json.loads(meta) if isinstance(meta, str) else (meta or {})
    return {"doc": dict(doc), "meta": meta, "files": [dict(f) for f in files], "package": sess}


async def _save(doc_id: int, semantika: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
                           json.dumps({"semantika": semantika}, ensure_ascii=False), doc_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _institution_topic(fmt: dict, inp: dict, avots: str) -> Optional[dict]:
    s = fmt.get("class_scheme")
    code = inp.get("kods") or inp.get("kategorija")
    if not s or not s.get("uri") or not code:
        return None
    return {"shema": s["uri"], "kods": str(code),
            "nosaukums": inp.get("kodaNosaukums") or inp.get("kategorijasNosaukums") or "",
            "loma": "galvena", "avots": avots}


def _mapped_eurovoc(fmt: dict, kategorija: Optional[str]) -> Optional[dict]:
    """Institution category -> EuroVoc via the institution's published mapping."""
    if not kategorija:
        return None
    for row in fmt.get("mapping") or []:
        if str(row.get("kods")) == str(kategorija) and row.get("eurovoc"):
            return {"shema": "http://eurovoc.europa.eu/", "kods": str(row["eurovoc"]),
                    "nosaukums": row.get("eurovoc_nosaukums") or "", "loma": "papildu", "avots": "kartejums"}
    return None


# ─────────────────────────── semantics.generate@1 ───────────────────────────

async def handle_semantics_generate(ctx: dict) -> dict:
    from opendms.ai import _cfg, _complete_json

    inp = ctx.get("input") or {}
    doc_id = int(inp["documentId"])
    fmt = await load_format(ctx.get("schema_ref"))
    m, profile = fmt["model"], fmt["profile"]
    c = await _doc_context(doc_id)
    prev = (c["meta"].get("semantika") or {}).get("lokals")
    decision = inp.get("decision")

    # After the reviewer's decision: update, do not regenerate.
    if prev and decision in ("apstiprinats", "labots"):
        local = json.loads(json.dumps(prev))
        corrected = decision == "labots" or bool(inp.get("labots"))
        inst = _institution_topic(fmt, inp, "cilveks")
        temas = [t for t in local.get("temas") or []
                 if not (fmt.get("class_scheme") and t.get("shema") == fmt["class_scheme"]["uri"])
                 and t.get("avots") != "kartejums"]
        if inst:
            temas.append(inst)
        mapped = _mapped_eurovoc(fmt, inp.get("kategorija"))
        if mapped and not any(t.get("kods") == mapped["kods"] and t.get("shema") == mapped["shema"] for t in temas):
            temas.append(mapped)
        local["temas"] = temas
        for a in local.get("apgalvojumi") or []:
            a.setdefault("novertejums", {})["parbaudits"] = True
        local["dokuments"]["metadatuVersija"] = int(local["dokuments"].get("metadatuVersija") or 1) + 1
        # identifiers may have been assigned after the first description (registration runs in parallel)
        if c["doc"].get("doc_uid"):
            local["dokuments"]["id"] = c["doc"]["doc_uid"]
        files = [{"id": f["std_id"], "sha256": f["checksum_sha256"],
                  **({"lapas": local["dokuments"]["datnes"][0]["lapas"]} if local["dokuments"].get("datnes") else {})}
                 for f in c["files"][:1] if f.get("std_id") and f.get("checksum_sha256")]
        if files:
            old_ids = {x.get("id") for x in local["dokuments"].get("datnes") or []}
            local["dokuments"]["datnes"] = files
            for a in local.get("apgalvojumi") or []:
                for e in a.get("pieradijumi") or []:
                    if e.get("datne") in old_ids or str(e.get("datne", "")).startswith(("DVS:", "LV-DOK")) or e.get("datne", "").isdigit():
                        e["datne"] = files[0]["id"]
        local["izcelsme"]["parskatisana"] = {"statuss": "labots" if corrected else "apstiprinats",
                                             "loma": inp.get("role") or inp.get("reviewerRole") or "darbinieks",
                                             "laiks": _now()}
        errs = dsf.check(local, m, fmt["schemas"]["lokals"])
        await _save(doc_id, {**(c["meta"].get("semantika") or {}), "lokals": local, "kludas": errs})
        return {"output": {"semantikaDeriga": not errs, "semantikaVersija": local["dokuments"]["metadatuVersija"],
                           "semantikaParskatita": True}}

    # Generate the local layer from the redacted text.
    original = inp.get("content") or ""
    redacted = inp.get("redactedContent") or ""
    if not redacted.strip():
        raise ValueError("semantics.generate needs redactedContent (run ai.redact first)")
    if len(redacted.strip()) < 200:
        msg = (f"Dokumenta teksts nav nolasīts (tikai {len(redacted.strip())} rakstzīmes) — "
               "apraksts netiek ģenerēts no virsraksta.")
        await _save(doc_id, {"lokals": None, "kludas": [msg], "generets": _now()})
        return {"output": {"semantikaDeriga": False, "semantikaKluda": msg}}
    ans = await _complete_json("You write structured semantic descriptions of documents as JSON.",
                               build_prompt(fmt, redacted[:14000]), max_tokens=4000, timeout=240.0)
    if not ans:
        await _save(doc_id, {"lokals": None, "kludas": ["modelis neatgrieza derīgu JSON"], "generets": _now()})
        return {"output": {"semantikaDeriga": False, "semantikaKluda": "modelis neatgrieza derīgu JSON"}}

    pages = split_pages(original)
    primary = c["files"][0] if c["files"] else None
    doc = c["doc"]
    voc = m["vardnica"]
    preds = {**(voc.get("predikati") or {}), **(profile.get("predikati") or {})}
    people = []
    for i, d in enumerate(ans.get("dalibnieki") or [], 1):
        d = {k: v for k, v in d.items() if k in ("id", "loma", "tips", "nosaukums", "grupa", "identifikators") and v not in (None, "")}
        d.setdefault("id", f"D{i}")
        if d.get("tips") not in ("fiziska-persona", "juridiska-persona", "iestade", "nav-zinams"):
            d["tips"] = "nav-zinams"
        if d["tips"] in ("fiziska-persona", "nav-zinams"):
            d.pop("nosaukums", None)
            d.pop("identifikators", None)
        if d.get("grupa") and d["grupa"] not in (voc.get("grupas") or {}):
            d.pop("grupa")
        people.append(d)
    ids = {d["id"] for d in people}
    dropped = []
    claims = []
    for i, a in enumerate(ans.get("apgalvojumi") or [], 1):
        p = preds.get(a.get("predikats"))
        if not p or a.get("statuss") not in (p.get("statusi") or []):
            dropped.append(a.get("predikats"))
            continue
        ev = []
        for e in a.get("pieradijumi") or []:
            loc = locate(e.get("fragments", ""), pages)
            ev.append({"datne": primary["std_id"] if primary else (doc.get("doc_uid") or str(doc_id)),
                       **({"lapa": loc["lapa"]} if loc.get("lapa") else {}),
                       "fragments": str(e.get("fragments", ""))[:300],
                       **({k: loc[k] for k in ("sakums", "beigas") if k in loc}),
                       "metode": loc["metode"]})
        claim = {"id": a.get("id") or f"A{i}", "subjekts": a.get("subjekts") if a.get("subjekts") in ids else "dokuments",
                 "predikats": a["predikats"], "vertiba": str(a.get("vertiba") or ""),
                 "apgalvo": a.get("apgalvo") if a.get("apgalvo") in ids else "dokuments",
                 "statuss": a["statuss"], "pieradijumi": ev,
                 "novertejums": {"metode": "modelis", "parbaudits": False,
                                 **({"parlieciba": float(a["parlieciba"])} if isinstance(a.get("parlieciba"), (int, float)) else {})}}
        if a.get("vertibasKods"):
            claim["vertibasKods"] = str(a["vertibasKods"])
        if isinstance(a.get("laiks"), dict) and a["laiks"].get("precizitate") in ("diena", "menesis", "gads", "nav-zinama"):
            claim["laiks"] = {k: str(v) for k, v in a["laiks"].items() if k in ("datums", "no", "lidz", "precizitate", "apraksts") and v}
        if a.get("nosacijumi"):
            claim["nosacijumi"] = str(a["nosacijumi"])
        claims.append(claim)
    facets_spec = profile.get("pazimes") or {}
    facets = [f for f in (ans.get("pazimes") or []) if isinstance(f, dict) and f.get("kods") in facets_spec]
    facets = [{"kods": f["kods"], "vertiba": str(f.get("vertiba")).lower() if isinstance(f.get("vertiba"), bool) else str(f.get("vertiba"))} for f in facets]
    groups_voc = set((voc.get("grupas") or {}))
    kept = []
    for f in facets:   # a value outside the profile's list is dropped and noted, not guessed
        spec = facets_spec[f["kods"]]
        allowed = groups_voc if spec.get("vertibas_no") == "vardnica.grupas" else {str(x) for x in (spec.get("vertibas") or {})}
        if f["vertiba"] in allowed:
            kept.append(f)
        else:
            kept_note = {"lauks": f"pazimes/{f['kods']}", "iemesls": "pretrunigs",
                         "piezime": f"Modeļa vērtība '{f['vertiba']}' nav profila sarakstā."}
            ans.setdefault("nenoteiktibas", []).append(kept_note)
    facets = kept
    ev_known = fmt.get("eurovoc_candidates") or {}
    ev_rx = re.compile(m["tematika"]["shemas"]["eurovoc"].get("koda_paraugs") or r"^(\d+|c_[0-9a-f]{8})$")
    temas = []
    for t in (ans.get("temas") or [])[:3]:
        k = str(t.get("kods"))
        if (k in ev_known) if ev_known else bool(ev_rx.match(k)):
            temas.append({"shema": "http://eurovoc.europa.eu/", "kods": k, "nosaukums": ev_known.get(k, ""),
                          "loma": "galvena" if not temas else "papildu", "avots": "modelis"})
    inst = _institution_topic(fmt, inp, "noteikumi" if inp.get("klasifikacijasAvots") == "noteikumi" else "modelis")
    if inst:
        temas.append(inst)
    mapped = _mapped_eurovoc(fmt, inp.get("kategorija"))
    if mapped and not any(t["kods"] == mapped["kods"] and t["shema"] == mapped["shema"] for t in temas):
        temas.append(mapped)
    unc = [{"lauks": str(u.get("lauks")), "iemesls": u.get("iemesls"), **({"piezime": str(u["piezime"])} if u.get("piezime") else {})}
           for u in ans.get("nenoteiktibas") or []
           if isinstance(u, dict) and u.get("iemesls") in ("nav-noradits", "nav-salasams", "nav-attiecinams", "slepts", "pretrunigs")]
    if dropped:
        unc.append({"lauks": "apgalvojumi", "iemesls": "pretrunigs",
                    "piezime": f"Izlaisti {len(dropped)} apgalvojumi ar nederīgu predikātu vai statusu."})
    created = doc.get("created_at") or datetime.now(timezone.utc)
    local = {
        "formataVersija": m["versija"],
        "profils": f"{profile['profils']}/{profile['versija']}",
        "slanis": "lokals",
        "dokuments": {
            "id": doc.get("doc_uid") or f"DVS:{doc_id}",
            "dvsId": str(doc_id),
            "metadatuVersija": 1,
            "dokumentaVeids": ans.get("dokumentaVeids") if ans.get("dokumentaVeids") in (profile.get("dokumenta_veidi") or []) else profile["profils"],
            "valoda": str(ans.get("valoda") or "lv")[:2],
            "datums": created.date().isoformat(),
            "virsraksts": doc.get("title") or "",
            "datnes": [{"id": f["std_id"], "sha256": f["checksum_sha256"], "lapas": len(pages)} for f in c["files"][:1]
                       if f.get("std_id") and f.get("checksum_sha256")],
        },
        "kopsavilkums": {"teksts": str(ans.get("kopsavilkums") or ""), "valoda": "lv",
                         "balstitsUz": [a["id"] for a in claims], "generets": True},
        "temas": temas, "dalibnieki": people, "apgalvojumi": claims, "pazimes": facets,
        "nenoteiktibas": unc,
        "izcelsme": {
            "generators": f"OpenDMS ({doc.get('org_name') or 'iestāde'})",
            "procesaVersija": c["package"] or "nezinams",
            "noteikumuVersija": f"{fmt['repo']}@{fmt['revision']}",
            "modelis": _cfg().get("model"),
            "generetsUz": _now(),
            "ievade": "aizklats-teksts",
            "parskatisana": {"statuss": "neparskatits"},
        },
        "piekluve": {"klase": "lokals-ierobezots"},
    }
    if not local["dokuments"]["datnes"]:
        local["dokuments"].pop("datnes")
    errs = dsf.check(local, m, fmt["schemas"]["lokals"])
    await _save(doc_id, {"lokals": local, "kludas": errs, "generets": _now(), "schemaRef": ctx.get("schema_ref")})
    return {"output": {"semantikaDeriga": not errs, "semantikaVersija": 1,
                       "semantikaKopsavilkums": local["kopsavilkums"]["teksts"][:1000],
                       "semantikaKludas": len(errs)}}


# ─────────────────────────── semantics.project@1 ───────────────────────────

async def handle_semantics_project(ctx: dict) -> dict:
    from opendms.ai import _complete_json

    inp = ctx.get("input") or {}
    doc_id = int(inp["documentId"])
    fmt = await load_format(ctx.get("schema_ref"))
    m = fmt["model"]
    c = await _doc_context(doc_id)
    sem = c["meta"].get("semantika") or {}
    local = sem.get("lokals")
    if not local:
        return {"output": {"centralaisSlanis": False, "centralaisIemesls": "nav lokālā slāņa"}}

    central, report = dsf.project_central(local, m)
    # independent model check for indirect identifiers (texts only, not the document)
    texts = [t for _, t in dsf.iter_texts({"k": central.get("kopsavilkums", {}).get("teksts"),
                                            "a": [a.get("vertiba") for a in central.get("apgalvojumi") or []],
                                            "n": [a.get("nosacijumi") for a in central.get("apgalvojumi") or []],
                                            "u": [u.get("piezime") for u in central.get("nenoteiktibas") or []]}) if t]
    chk = await _complete_json("You check texts for personal identifiers. Answer JSON only.",
                               fmt["check_prompt"].replace("{{TEKSTI}}", "\n".join(f"- {t}" for t in texts)),
                               max_tokens=1500, timeout=120.0)
    replaced = 0
    model_checked = chk is not None
    for f in (chk or {}).get("atradumi") or []:
        frag, rep = str(f.get("teksts") or ""), str(f.get("aizstat") or "")
        if len(frag) < 3 or MONTH_OR_YEAR.fullmatch(frag.strip()):
            continue   # month and year are kept on purpose (docs/03)
        if not rep or "[" in rep:
            rep = "noteiktā laikā" if re.search(r"\d{4}", frag) else "attiecīgā persona"
        for path_obj in [central.get("kopsavilkums") or {}] + list(central.get("apgalvojumi") or []) + list(central.get("nenoteiktibas") or []):
            for key in ("teksts", "vertiba", "nosacijumi", "piezime"):
                if isinstance(path_obj.get(key), str) and frag in path_obj[key]:
                    path_obj[key] = path_obj[key].replace(frag, rep)
                    replaced += 1
    findings = []
    for path, text in dsf.iter_texts(central):
        for name in dsf.text_findings(text):
            findings.append({"vieta": path, "iemesls": name})
    unresolved = [f for f in (chk or {}).get("atradumi") or []
                  if len(str(f.get("teksts") or "")) >= 3 and not MONTH_OR_YEAR.fullmatch(str(f["teksts"]).strip())
                  and any(str(f["teksts"]) in t for _, t in dsf.iter_texts(central))]
    ok = model_checked and not findings and not unresolved
    deid = central["piekluve"]["deidentifikacija"]
    deid["parbaudes"] = deid["parbaudes"] + (["modeļa-pārbaude"] if model_checked else [])
    deid["izmainas"] = int(deid["izmainas"]) + replaced
    deid["rezultats"] = "atbilst" if ok else "neatbilst"
    errs = dsf.check(central, m, fmt["schemas"]["centrals"])
    ok = ok and not errs

    # metadati.xml section 13 carries the local layer: rebuild the package with it
    package_ok, package_err = True, None
    try:
        from lxml import etree
        from opendms.standard.service import rebuild_package
        el = dsf.to_xml(local, m)
        xsd = etree.XMLSchema(etree.parse(str(fmt["root"] / "shemas/semantika.xsd")))
        if not xsd.validate(etree.ElementTree(el)):
            raise ValueError("semantika.xsd: " + "; ".join(e.message for e in list(xsd.error_log)[:3]))
        await rebuild_package(doc_id, semantika_xml=etree.tostring(el),
                              semantika_versija=m["versija"])
    except Exception as e:  # the semantic layer is still kept; the submit step reports it
        package_ok, package_err = False, str(e)[:300]
        logger.warning("semantics.project: package rebuild failed for %s: %s", doc_id, e)

    await _save(doc_id, {**sem, "centrals": central if ok else None,
                         "centralaPrieksskatijums": central,
                         "projekcija": {"derigs": ok, "nonemti": report["nonemti"], "visparinati": report["visparinati"],
                                        "aizstati": replaced, "atradumi": findings, "modelaAtradumi": (chk or {}).get("atradumi") or [],
                                        "modelaParbaude": model_checked, "kludas": errs, "laiks": _now(),
                                        "pakotne": package_ok, "pakotnesKluda": package_err}})
    return {"output": {"centralaisSlanis": ok,
                       "centralaisIemesls": None if ok else ("modeļa pārbaude nav pieejama" if not model_checked
                                                             else "; ".join(errs[:3] + [f["iemesls"] for f in findings[:3]]
                                                                            + [str(u.get('iemesls')) for u in unresolved[:3]]))}}
