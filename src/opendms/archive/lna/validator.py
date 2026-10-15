#!/usr/bin/env python3
"""[Kopija no ProcessGit kisc/dokumentu-arhivesanas-standarts riki/validet_pakotni.py — nemainīt šeit, mainīt standartā.]
LNA OPEX pakotnes pārbaude (KISC dokumentu arhivēšanas standarts, 5. nodaļa).

    python3 riki/validet_pakotni.py <pakotnes mape | pakotne.zip> [--json atskaite.json]

Pārbauda:
  1. struktūru un nosaukumus: katrai mapei <mape>.opex, katrai datnei un .pax mapei blakus .opex,
     mapju hierarhija LV_LNA_<Arh> / _F<Fonds> / _<US> / _<GV>, dokumentu kodi _<GV>_<Dok>;
  2. katru .opex pret shemas/lna-opex-profils.xsd, EAD daļu pret shemas/lna-ead3-profils.xsd;
  3. EAD3 laukus pēc profili/lna-ead3-lauki.yaml: obligātums, datumi, unitid (40 hex),
     konstantes un pieļaujamās vērtības; parauga tekstu "(…)" uzskata par neaizpildītu;
  4. recordid = OPEX Title, quantity = datņu skaits;
  5. Transfer/Manifest un Fixity, ja ir;
  6. pakotnes SHA-256, ja blakus .zip ir <pakotne>.zip.sha256.
Izejas kods 0, ja kļūdu nav (brīdinājumi pieļaujami).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import yaml
from lxml import etree

HERE = Path(__file__).resolve().parent   # DVS kopija: archive/lna/shemas, archive/lna/profili
NS = {"opex": "http://www.openpreservationexchange.org/opex/v1.1",
      "ead": "http://ead3.archivists.org/schema/undeprecated/"}
OPEX_NS_OLD = "http://www.openpreservationexchange.org/opex/v1.0"

RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_HEX40 = re.compile(r"^[0-9a-f]{40}$")
RE_ROOT = re.compile(r"^(LV_LNA_[A-Z]{2,10})_F([0-9A-Z]+)_([0-9]+)_GV([0-9]+)-([0-9]+)$")
RE_PLACEHOLDER = re.compile(r"^\(.*\)$|\(piem\.:", re.S)
FIXITY_ALGO = {"MD5": "md5", "SHA-1": "sha1", "SHA-256": "sha256", "SHA-512": "sha512"}
SECURITY = {"open", "closed", "public"}


class Report:
    def __init__(self):
        self.items: list[dict] = []

    def err(self, where, msg):
        self.items.append({"limenis": "kluda", "vieta": where, "zinojums": msg})

    def warn(self, where, msg):
        self.items.append({"limenis": "bridinajums", "vieta": where, "zinojums": msg})

    @property
    def errors(self):
        return [i for i in self.items if i["limenis"] == "kluda"]

    @property
    def warnings(self):
        return [i for i in self.items if i["limenis"] == "bridinajums"]


def filled(v: str | None) -> bool:
    return bool(v and v.strip() and not RE_PLACEHOLDER.search(v.strip()))


def load_schema(name):
    return etree.XMLSchema(etree.parse(str(HERE / "shemas" / name)))


class Validator:
    def __init__(self, root: Path, rep: Report):
        self.root, self.rep = root, rep
        self.opex_xsd = load_schema("lna-opex-profils.xsd")
        self.ead_xsd = load_schema("lna-ead3-profils.xsd")
        self.profile = yaml.safe_load(open(HERE / "profili" / "lna-ead3-lauki.yaml", encoding="utf-8"))
        self.doc_codes: set[str] = set()
        self.unitids: dict[str, str] = {}
        self.docs = 0

    def rel(self, p: Path) -> str:
        """Īss ceļš atskaitei: pēdējās divas daļas (vienība/datne)."""
        parts = p.relative_to(self.root.parent).parts
        return "/".join(parts[-2:]) if len(parts) > 2 else "/".join(parts)

    # ── OPEX ──────────────────────────────────────────────
    def read_opex(self, p: Path):
        where = self.rel(p)
        if not p.exists():
            self.rep.err(where, "trūkst .opex datnes")
            return None
        try:
            doc = etree.parse(str(p))
        except etree.XMLSyntaxError as e:
            self.rep.err(where, f"XML kļūda: {e}")
            return None
        if doc.getroot().tag == f"{{{OPEX_NS_OLD}}}OPEXMetadata":
            self.rep.warn(where, "OPEX 1.0 nosaukumvieta; LNA paraugā 1.1")
            return doc
        if not self.opex_xsd.validate(doc):
            for e in self.opex_xsd.error_log:
                self.rep.err(where, f"OPEX shēma, rinda {e.line}: {e.message}")
        title = doc.findtext("opex:Properties/opex:Title", namespaces=NS)
        sec = doc.findtext("opex:Properties/opex:SecurityDescriptor", namespaces=NS)
        if not filled(title):
            self.rep.err(where, "nav Properties/Title")
        if sec is None:
            self.rep.err(where, "nav Properties/SecurityDescriptor (Preservica bez tā vienību neielādē)")
        elif sec.strip() not in SECURITY:
            self.rep.err(where, f"SecurityDescriptor '{sec.strip()}' — pieļaujams: open, closed, public")
        return doc

    def check_manifest(self, folder: Path, doc):
        man = doc.find("opex:Transfer/opex:Manifest", namespaces=NS)
        where = self.rel(folder / f"{folder.name}.opex")
        if man is None:
            return
        listed_dirs = {f.text for f in man.findall("opex:Folders/opex:Folder", namespaces=NS)}
        listed_files = {f.text: f for f in man.findall("opex:Files/opex:File", namespaces=NS)}
        actual_dirs = {c.name for c in folder.iterdir() if c.is_dir()}
        actual_files = {c.name for c in folder.iterdir() if c.is_file() and c.name != f"{folder.name}.opex"}
        for d in sorted(actual_dirs - listed_dirs):
            self.rep.err(where, f"Manifest: mape '{d}' nav sarakstā")
        for d in sorted(listed_dirs - actual_dirs):
            self.rep.err(where, f"Manifest: mape '{d}' nav pakotnē")
        for f in sorted(actual_files - set(listed_files)):
            self.rep.err(where, f"Manifest: datne '{f}' nav sarakstā")
        for f in sorted(set(listed_files) - actual_files):
            self.rep.err(where, f"Manifest: datne '{f}' nav pakotnē")
        for name, el in listed_files.items():
            size = el.get("size")
            if size and (folder / name).exists() and int(size) != (folder / name).stat().st_size:
                self.rep.err(where, f"Manifest: '{name}' izmērs {size}, faktiski {(folder / name).stat().st_size}")

    def check_fixity(self, content: Path, doc, where):
        for fx in doc.findall("opex:Transfer/opex:Fixities/opex:Fixity", namespaces=NS):
            algo = FIXITY_ALGO.get(fx.get("type"))
            target = content / fx.get("path") if fx.get("path") else content
            if not algo or not target.is_file():
                self.rep.err(where, f"Fixity: nevar pārbaudīt {fx.get('type')} {fx.get('path') or ''}")
                continue
            h = hashlib.new(algo, target.read_bytes()).hexdigest()
            if h.lower() != (fx.get("value") or "").lower():
                self.rep.err(where, f"Fixity {fx.get('type')} nesakrīt: {target.name}")

    # ── EAD3 ──────────────────────────────────────────────
    def check_ead(self, doc, where, title, n_files):
        ead = doc.find("opex:DescriptiveMetadata/ead:ead", namespaces=NS)
        if ead is None:
            self.rep.err(where, "nav DescriptiveMetadata/ead (EAD3)")
            return
        if not self.ead_xsd.validate(etree.ElementTree(ead)):
            for e in self.ead_xsd.error_log:
                self.rep.err(where, f"EAD3 shēma: {e.message}")
        for f in self.profile["lauki"]:
            vals = [v if isinstance(v, str) else (v.text or "") for v in ead.xpath(f["xpath"], namespaces=NS)]
            good = [v.strip() for v in vals if filled(v)]
            label = f["nosaukums"]
            if f.get("obligats") == "ja" and not good:
                placeholder = any(v and RE_PLACEHOLDER.search(v.strip()) for v in vals)
                self.rep.err(where, f"obligāts lauks '{label}' " + ("satur parauga tekstu" if placeholder else "nav aizpildīts"))
                continue
            for v in good:
                t = f.get("tips")
                if t == "datums" and not RE_DATE.match(v):
                    self.rep.err(where, f"'{label}': '{v}' nav formātā gggg-mm-dd")
                elif t == "hex40" and not RE_HEX40.match(v):
                    self.rep.err(where, f"'{label}': '{v}' nav 40 heksadecimālas zīmes")
                elif t == "vesels" and not v.isdigit():
                    self.rep.err(where, f"'{label}': '{v}' nav vesels skaitlis")
                if "vertiba" in f and v != f["vertiba"]:
                    self.rep.err(where, f"'{label}': jābūt '{f['vertiba']}', ir '{v}'")
                if "vertibas" in f and v not in f["vertibas"]:
                    self.rep.err(where, f"'{label}': '{v}' nav pieļaujamo vērtību sarakstā")
            if not good and vals and any(v.strip() for v in vals):
                self.rep.warn(where, f"lauks '{label}' satur parauga tekstu")
        rid = ead.findtext("ead:control/ead:recordid", namespaces=NS)
        if filled(rid) and title and rid.strip() != title.strip():
            self.rep.err(where, f"EAD recordid '{rid.strip()}' ≠ OPEX Title '{title.strip()}'")
        q = ead.findtext("ead:archdesc/ead:did/ead:physdescset/ead:physdescstructured/ead:quantity", namespaces=NS)
        if q and q.strip().isdigit() and int(q) != n_files:
            self.rep.err(where, f"quantity {q.strip()} ≠ datņu skaits {n_files}")
        uid = ead.findtext("ead:archdesc/ead:did/ead:unitid", namespaces=NS)
        if filled(uid):
            if uid.strip() in self.unitids:
                self.rep.err(where, f"unitid atkārtojas (arī {self.unitids[uid.strip()]})")
            self.unitids[uid.strip()] = where
        for dao in ead.xpath("ead:archdesc/ead:did/ead:daoset/ead:dao/@identifier", namespaces=NS):
            if filled(dao) and not RE_HEX40.match(dao.strip()):
                self.rep.err(where, f"saistītā dokumenta ID '{dao}' nav 40 heksadecimālas zīmes")

    # ── hierarhija ────────────────────────────────────────
    def walk(self):
        m = RE_ROOT.match(self.root.name)
        if not m:
            self.rep.err(self.root.name, "pakotnes saknes nosaukums neatbilst LV_LNA_<Arh>_F<Fonds>_<US>_GV<no>-<līdz>")
            arh = fonds = us = None
            gv_from = gv_to = None
        else:
            arh, fonds, us, gv_from, gv_to = m.group(1), m.group(2), m.group(3), int(m.group(4)), int(m.group(5))
        rd = self.read_opex(self.root / f"{self.root.name}.opex")
        if rd is not None:
            self.check_manifest(self.root, rd)
        expect = [arh, f"{arh}_F{fonds}" if arh else None, f"{arh}_F{fonds}_{us}" if arh else None]
        self._level(self.root, 0, expect, (gv_from, gv_to))

    def _level(self, folder: Path, depth: int, expect, gv_range):
        subdirs = sorted(c for c in folder.iterdir() if c.is_dir())
        files = sorted(c for c in folder.iterdir() if c.is_file())
        if depth < 3:   # arhīvs, fonds, uzskaites saraksts — tikai mapes un .opex
            for f in files:
                if f.name != f"{folder.name}.opex":
                    self.rep.err(self.rel(f), f"neparedzēta datne {['saknes', 'arhīva', 'fonda'][depth]} līmenī")
            for d in subdirs:
                want = expect[depth]
                if want and d.name != want:
                    self.rep.err(self.rel(d), f"mapei jābūt '{want}'")
                od = self.read_opex(d / f"{d.name}.opex")
                if od is not None:
                    self.check_manifest(d, od)
                    t = od.findtext("opex:Properties/opex:Title", namespaces=NS)
                    if filled(t) and t.strip() != d.name:
                        self.rep.err(self.rel(d / f"{d.name}.opex"), f"Title '{t.strip()}' ≠ mapes nosaukums")
                if depth < 2:
                    self._level(d, depth + 1, expect, gv_range)
                else:
                    self._units(d, gv_range)
            return

    def _units(self, us_dir: Path, gv_range):
        for f in us_dir.iterdir():
            if f.is_file() and f.name != f"{us_dir.name}.opex":
                self.rep.err(self.rel(f), "neparedzēta datne uzskaites saraksta līmenī")
        seen = []
        for gv in sorted(c for c in us_dir.iterdir() if c.is_dir()):
            if not gv.name.startswith(us_dir.name + "_"):
                self.rep.err(self.rel(gv), f"glabājamās vienības kodam jāsākas ar '{us_dir.name}_'")
                continue
            num = gv.name[len(us_dir.name) + 1:]
            if not num.isdigit():
                self.rep.err(self.rel(gv), "glabājamās vienības numurs nav skaitlis")
            else:
                seen.append(int(num))
            og = self.read_opex(gv / f"{gv.name}.opex")
            if og is not None:
                self.check_manifest(gv, og)
            self._documents(gv)
        lo, hi = gv_range
        if lo and seen and (min(seen) != lo or max(seen) != hi):
            self.rep.err(self.rel(us_dir), f"vienību numuri {min(seen)}–{max(seen)} neatbilst saknes nosaukumam GV{lo}-{hi}")

    def _documents(self, gv: Path):
        for c in sorted(gv.iterdir()):
            if c.name == f"{gv.name}.opex" or c.name.endswith(".opex"):
                if c.is_file() and c.name != f"{gv.name}.opex" and not (gv / c.name[:-5]).exists():
                    self.rep.err(self.rel(c), ".opex bez atbilstošas datnes vai .pax mapes")
                continue
            if c.is_dir():
                if not c.name.endswith(".pax"):
                    self.rep.err(self.rel(c), "dokumenta mapei jābūt <kods>.pax")
                    continue
                rep = c / "Representation_Preservation"
                payload = [p for p in rep.rglob("*") if p.is_file()] if rep.is_dir() else []
                if not payload:
                    self.rep.err(self.rel(c), "nav Representation_Preservation datņu")
                self._document(c, gv, len(payload), expected_title=c.name[:-4])
            else:
                self._document(c, gv, 1, expected_title=None)

    def _document(self, content: Path, gv: Path, n_files: int, expected_title):
        self.docs += 1
        sidecar = content.parent / f"{content.name}.opex"
        where = self.rel(sidecar)
        doc = self.read_opex(sidecar)
        if doc is None:
            return
        title = (doc.findtext("opex:Properties/opex:Title", namespaces=NS) or "").strip()
        if title:
            if not title.startswith(gv.name + "_") or not title[len(gv.name) + 1:].isdigit():
                self.rep.err(where, f"dokumenta kods '{title}' neatbilst '{gv.name}_<Nr>'")
            if expected_title and title != expected_title:
                self.rep.err(where, f"Title '{title}' ≠ .pax mapes nosaukums '{expected_title}'")
            if title in self.doc_codes:
                self.rep.err(where, f"dokumenta kods '{title}' atkārtojas")
            self.doc_codes.add(title)
        if content.is_file():
            self.check_fixity(content, doc, where)
        else:
            self.check_fixity(content, doc, where)
        self.check_ead(doc, where, title, n_files)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pakotne")
    ap.add_argument("--json", help="saglabāt atskaiti JSON formā")
    a = ap.parse_args(argv)
    src = Path(a.pakotne)
    rep = Report()
    tmp = None
    if src.suffix == ".zip":
        sha = src.with_name(src.name + ".sha256")
        if sha.exists():
            want = sha.read_text().split()[0].lower()
            got = hashlib.sha256(src.read_bytes()).hexdigest()
            if want != got:
                rep.err(src.name, "pakotnes SHA-256 nesakrīt")
        else:
            rep.warn(src.name, "nav pakotnes kontrolsummas datnes (<pakotne>.zip.sha256, MK 282 69.1.5.)")
        tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(src) as z:
            z.extractall(tmp.name)
        tops = [p for p in Path(tmp.name).iterdir() if not p.name.startswith("__MACOSX")]
        if len(tops) != 1 or not tops[0].is_dir():
            rep.err(src.name, "ZIP saknē jābūt vienai mapei")
            root = None
        else:
            root = tops[0]
    else:
        root = src
    if root is not None:
        v = Validator(root.resolve(), rep)
        v.walk()
        docs = v.docs
    else:
        docs = 0
    print(f"Pakotne: {src.name} · dokumenti: {docs} · kļūdas: {len(rep.errors)} · brīdinājumi: {len(rep.warnings)}")
    for i in rep.items:
        print(f"  [{'KĻŪDA' if i['limenis'] == 'kluda' else 'brīdin.'}] {i['vieta']}: {i['zinojums']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"pakotne": src.name, "dokumenti": docs, "kludas": len(rep.errors),
                                            "bridinajumi": len(rep.warnings), "ieraksti": rep.items},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    if tmp:
        tmp.cleanup()
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())


def validate_path(src: Path) -> dict:
    """DVS izsaukums: tā pati pārbaude kā komandrindā; atgriež atskaiti."""
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main([str(src), "--json", str(src) + ".parbaude.json"])
    rep = json.loads(Path(str(src) + ".parbaude.json").read_text(encoding="utf-8"))
    return {"derigs": rc == 0, **rep, "teksts": buf.getvalue()}
