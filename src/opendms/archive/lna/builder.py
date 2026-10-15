#!/usr/bin/env python3
"""[Kopija no ProcessGit kisc/dokumentu-arhivesanas-standarts riki/izveidot_pakotni.py — nemainīt šeit, mainīt standartā.]
LNA OPEX pakotnes izveide no apraksta JSON (KISC dokumentu arhivēšanas standarts, 5. nodaļa).

    python3 riki/izveidot_pakotni.py <apraksts.json> <izvades mape>

Izveido <izvades mape>/<pakotne>/ un <pakotne>.zip ar <pakotne>.zip.sha256.
Apraksta struktūra: sk. paraugi/sintetisks/apraksts.json. Šo pašu loģiku izmanto DVS eksports;
rīks paredzēts paraugiem un testiem.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

OPEX = "http://www.openpreservationexchange.org/opex/v1.1"
EAD = "http://ead3.archivists.org/schema/undeprecated/"
AGENT = "KISC arhivēšanas standarts — pakotņu sagatavotājs 0.1.0"


def x(v) -> str:
    return escape("" if v is None else str(v))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def folder_opex(folder: Path, title: str, description: str, security: str) -> None:
    """Mapes .opex ar Manifest un Fixity tiešajām datnēm (izņemot .opex)."""
    dirs = sorted(c.name for c in folder.iterdir() if c.is_dir())
    files = sorted(c for c in folder.iterdir() if c.is_file())
    man_dirs = "".join(f"\n          <Folder>{x(d)}</Folder>" for d in dirs)
    man_files = "".join(
        f'\n          <File type="{"metadata" if f.name.endswith(".opex") else "content"}" size="{f.stat().st_size}">{x(f.name)}</File>'
        for f in files)
    (folder / f"{folder.name}.opex").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<OPEXMetadata xmlns="{OPEX}">
  <Transfer>
    <Manifest>
      <Folders>{man_dirs}
      </Folders>
      <Files>{man_files}
      </Files>
    </Manifest>
  </Transfer>
  <Properties>
    <Title>{x(title)}</Title>
    <Description>{x(description)}</Description>
    <SecurityDescriptor>{x(security)}</SecurityDescriptor>
  </Properties>
</OPEXMetadata>
""", encoding="utf-8")


def odd_list(head, items):
    its = "".join(f"<item>{x(i)}</item>" for i in items) or "<item/>"
    return f"<list><head>{x(head)}</head>{its}</list>"


def odd_table(tid, head, cols, rows):
    th = "".join(f"<entry>{x(c)}</entry>" for c in cols)
    tb = "".join("<row>" + "".join(f"<entry>{x(v)}</entry>" for v in r) + "</row>" for r in rows)
    return (f'<table id="{tid}"><head>{x(head)}</head><tgroup cols="{len(cols)}">'
            f"<thead><row>{th}</row></thead><tbody>{tb}</tbody></tgroup></table>")


def ead_xml(d: dict, code: str, ctx: dict, n_files: int, today: str) -> str:
    persons = lambda rel, names: (f'<persname relator="{rel}">' + "".join(f"<part>{x(n)}</part>" for n in names)
                                  + "</persname>") if names else ""
    dates = "".join(
        f'<unitdate calendar="gregorian" era="ce" normal="{x(v)}" label="{lbl}">{x(v)}</unitdate>'
        for lbl, v in (("Sagatavošanas datums", d.get("sagatavosanas_datums")),
                       ("Dokumenta datums", d["datums"]),
                       ("Nosūtīšanas datums", d.get("nosutisanas_datums"))) if v)
    dao = "".join(f'<dao daotype="borndigital" identifier="{x(i)}"/>' for i in d.get("saistitie", []))
    restrict = d.get("lietosanas_ierobezojums") or {}
    return f"""<ead xmlns="{EAD}" audience="internal">
  <control countryencoding="iso3166-1" dateencoding="iso8601" langencoding="iso639-2b" repositoryencoding="iso15511" scriptencoding="iso15924">
    <recordid instanceurl="">{x(code)}</recordid>
    <filedesc><titlestmt><titleproper>{x(ctx["iestade"]["nosaukums"])}</titleproper></titlestmt></filedesc>
    <maintenancestatus value="new"/>
    <maintenanceagency countrycode="LV"><agencycode>{x(ctx["arhivs"]["kods"])}</agencycode><agencyname>{x(ctx["arhivs"]["nosaukums"])}</agencyname></maintenanceagency>
    <languagedeclaration><language langcode="lav">Latvian</language><script scriptcode="latn">Latin</script></languagedeclaration>
    {f'<localcontrol><datesingle standarddate="{x(restrict["lidz"])}">{x(restrict["lidz"])}</datesingle></localcontrol>' if restrict.get("lidz") else ""}
    <maintenancehistory><maintenanceevent>
      <eventtype value="created"/><eventdatetime standarddatetime="{today}">{today}</eventdatetime>
      <agenttype value="machine"/><agent audience="internal">{x(AGENT)}</agent>
    </maintenanceevent></maintenancehistory>
  </control>
  <archdesc level="item">
    <did>
      <repository><name source="LVKFFDA"><part>Elektronisko dokumentu glabātava</part></name><address><addressline>LNB</addressline></address></repository>
      <unittitle>{x(d["nosaukums"])}</unittitle>
      <unitid>{x(d["arhiva_id"])}</unitid>
      {dates}
      <origination>{persons("creator", d.get("sagatavotaji", []))}{persons("author", d.get("autori", []))}{persons("signer", d.get("parakstitaji", []))}</origination>
      <physdescset><physdescstructured physdescstructuredtype="carrier" coverage="whole"><quantity>{n_files}</quantity><unittype>datnes</unittype></physdescstructured></physdescset>
      <langmaterial><language langcode="lav">Latviešu</language></langmaterial>
      {f'<abstract label="Anotācija">{x(d["anotacija"])}</abstract>' if d.get("anotacija") else ""}
      {f'<didnote>{x(", ".join(d["atslegvardi"]))}</didnote>' if d.get("atslegvardi") else ""}
      {f"<daoset>{dao}</daoset>" if dao else ""}
    </did>
    <odd>
      {odd_list("Iestādes reģistrācijas Nr.", [ctx["iestade"]["registracijas_nr"]])}
      {odd_list("Dokumenta reģistrācijas Nr.", [d["registracijas_nr"]])}
      {odd_list("Nosūtītāja dokumenta Nr.", [d["sutitaja_nr"]] if d.get("sutitaja_nr") else [])}
      {odd_list("Dokumentu grupa", [d["grupa"]])}
      {odd_list("Dokumentu tips", [d["tips"]])}
      {odd_list("Lietas Numurs", [ctx["lieta"]["indekss"]])}
      {odd_list("Adresāts", d.get("adresati", []))}
      {odd_table("t1", "Viza", ["Persona", "Datums", "Piezīmes"], [[v["persona"], v["datums"], v.get("piezimes", "")] for v in d.get("vizas", [])])}
      {odd_table("t2", "Iepazīšanas Atzīme", ["Persona", "Datums", "Piezīmes"], [[v["persona"], v["datums"], v.get("piezimes", "")] for v in d.get("iepazisanas", [])])}
      {odd_table("t3", "Rezolūcija", ["Atbildīgā persona", "Rezolūcijas autors", "Uzdevums", "Izpildes termiņš", "Datums", "Piezīmes"],
                 [[r["atbildigais"], r["autors"], r["uzdevums"], r.get("termins", ""), r["datums"], r.get("piezimes", "")] for r in d.get("rezolucijas", [])])}
    </odd>
    <phystech><head>Tehniskā informācija</head><p>{x(d.get("tehniska_informacija", ""))}</p></phystech>
    {f'<accessrestrict><p>{x(d["piekluves_ierobezojums"])}</p></accessrestrict>' if d.get("piekluves_ierobezojums") else ""}
    {f'<userestrict><p>{x(restrict["teksts"])}</p></userestrict>' if restrict.get("teksts") else ""}
    {f'<scopecontent><p>{x(d["piezimes"])}</p></scopecontent>' if d.get("piezimes") else ""}
  </archdesc>
</ead>"""


def doc_opex(target: Path, code: str, d: dict, ctx: dict, files: list[Path], today: str) -> None:
    rel = (lambda f: f.relative_to(target).as_posix()) if target.is_dir() else (lambda f: None)
    fixities = "".join(
        f'\n      <Fixity type="SHA-256" value="{sha256(f)}"' + (f' path="{x(rel(f))}"' if target.is_dir() else "") + "/>"
        for f in files)
    sec = "open" if d.get("informacijas_statuss", "Visparpieejama") == "Visparpieejama" else "closed"
    Path(str(target) + ".opex").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<OPEXMetadata xmlns="{OPEX}">
  <Transfer>
    <SourceID>{x(d.get("dokumenta_id", ""))}</SourceID>
    <Fixities>{fixities}
    </Fixities>
  </Transfer>
  <Properties>
    <Title>{x(code)}</Title>
    <Description>{x(d["nosaukums"])}</Description>
    <SecurityDescriptor>{sec}</SecurityDescriptor>
  </Properties>
  <DescriptiveMetadata>
{ead_xml(d, code, ctx, len(files), today)}
  </DescriptiveMetadata>
</OPEXMetadata>
""", encoding="utf-8")
    return sec


def build(spec: dict, out: Path, src_dir: Path) -> Path:
    today = spec.get("izveides_datums") or dt.date.today().isoformat()
    arh = f"LV_LNA_{spec['arhivs']['kods']}"
    f_code = f"{arh}_F{spec['fonds']['numurs']}"
    us_code = f"{f_code}_{spec['saraksts']['numurs']}"
    gvs = [l["nr"] for l in spec["lietas"]]
    root_name = f"{us_code}_GV{min(gvs)}-{max(gvs)}"
    root = out / root_name
    if root.exists():
        shutil.rmtree(root)
    us_dir = root / arh / f_code / us_code
    us_dir.mkdir(parents=True)
    for lieta in spec["lietas"]:
        gv_code = f"{us_code}_{lieta['nr']}"
        gv = us_dir / gv_code
        gv.mkdir()
        ctx = {**spec, "lieta": lieta}
        secs = []
        for n, d in enumerate(lieta["dokumenti"], 1):
            code = f"{gv_code}_{n}"
            srcs = [src_dir / f for f in d["datnes"]]
            if len(srcs) == 1:
                target = gv / srcs[0].name
                shutil.copyfile(srcs[0], target)
                files = [target]
            else:
                target = gv / f"{code}.pax"
                rep = target / "Representation_Preservation"
                rep.mkdir(parents=True)
                files = []
                for s in srcs:
                    shutil.copyfile(s, rep / s.name)
                    files.append(rep / s.name)
            secs.append(doc_opex(target, code, d, ctx, files, today))
        folder_opex(gv, gv_code, lieta["nosaukums"], "open" if all(s == "open" for s in secs) else "closed")
    folder_opex(us_dir, us_code, spec["saraksts"]["nosaukums"], "public")
    folder_opex(us_dir.parent, f_code, spec["fonds"]["nosaukums"], "public")
    folder_opex(us_dir.parent.parent, arh, spec["arhivs"]["nosaukums"], "public")
    folder_opex(root, root_name, spec["iestade"]["nosaukums"], "public")
    zpath = out / f"{root_name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            z.write(p, p.relative_to(out).as_posix())
    (out / f"{root_name}.zip.sha256").write_text(f"{sha256(zpath)}  {zpath.name}\n")
    return root


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    spec_path = Path(sys.argv[1])
    root = build(json.loads(spec_path.read_text(encoding="utf-8")), Path(sys.argv[2]), spec_path.parent)
    print(root)
