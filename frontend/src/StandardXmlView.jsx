// Human-readable view of the two package XML files of Dokumentu metadatu standarts v2.0:
//   metadati.xml   (dm:DokumentaPakotne) → organisation + one card per document, labelled sections
//   izsekosana.xml (di:Izsekosana)       → per document, a timeline of events
// Element names in the XML are Latvian ASCII; here they get proper Latvian labels.
// Anything not in the label tables is still shown (name split into words), so schema
// extensions never disappear from the view.

const L = {
  // pakotne, sistēma, organizācija
  SistemasKonteksts: "Sistēma", SistemasNosaukums: "Sistēma", SistemasInstance: "Instance", Vide: "Vide",
  IpasniekaOrganizacija: "Īpašnieka organizācija", OrgKods: "Organizācijas kods", OrgNosaukums: "Organizācija",
  OrgDID: "Organizācijas DID", RegistracijasNumurs: "Reģistrācijas numurs", Kontakti: "Kontakti",
  EAdrese: "e-adrese", Epasts: "E-pasts", Talrunis: "Tālrunis", Adrese: "Adrese",
  // dokuments
  Dokuments: "Dokuments", DokumentaID: "Dokumenta ID", DokumentaDID: "Dokumenta DID",
  ArejieIdentifikatori: "Ārējie identifikatori", Identifikators: "Identifikators",
  Versija: "Versija", VersijasNumurs: "Versijas numurs", IrGalaVersija: "Gala versija",
  IepriekshejasVersijasID: "Iepriekšējās versijas ID",
  Virsraksts: "Virsraksts", Apraksts: "Apraksts", DokumentaDatums: "Dokumenta datums",
  RegistretsUz: "Reģistrēts", Valoda: "Valoda", PedejoReiziMainitsUz: "Pēdējo reizi mainīts",
  PedejaisRedaktors: "Pēdējais redaktors",
  DokumentaVeids: "Dokumenta veids", VeidaKods: "Veida kods", VeidaNosaukums: "Veids",
  KlasifikatoraVersija: "Klasifikatora versija",
  Klasifikacija: "Klasifikācija", ShemasID: "Nomenklatūras shēma", ShemasVersija: "Shēmas versija",
  KlasifikacijasLieta: "Lieta", OperativaLieta: "Operatīvā lieta", LietasID: "Lietas ID",
  LietasIndekss: "Lietas indekss", LietasNosaukums: "Lietas nosaukums", LietasGads: "Lietas gads",
  Glabasana: "Glabāšana", GlabasanasTermins: "Glabāšanas termiņš", GlabasanasTriggeris: "Termiņu skaita",
  IznicinasanasDarbiba: "Pēc termiņa", JuridiskaisAizliegums: "Juridiskais aizliegums iznīcināt",
  NomenklaturasKods: "Nomenklatūras kods",
  Arhivs: "Arhīvs", AprakstaLimenis: "Apraksta līmenis", FondaNumurs: "Fonda numurs",
  NodosanasPlanaID: "Nodošanas plāna ID", NodosanasPakotnesID: "Nodošanas pakotnes ID", NodotsArhivamUz: "Nodots arhīvam",
  Drosiba: "Pieejamība un drošība", InformacijasStatuss: "Informācijas statuss",
  SaturPersonasDatus: "Satur personas datus", PiekluvesIerobezojums: "Piekļuves ierobežojums",
  TiesiskaisPamatojums: "Tiesiskais pamatojums", IerobezojumsLidz: "Ierobežojums līdz",
  Saistibas: "Saistītie dokumenti", Saistiba: "Saistība", MerkaDokumentaID: "Dokumenta ID", MerkaDokumentaDID: "Dokumenta DID",
  Adresati: "Adresāti", Adresats: "Adresāts", PusesTips: "Puses veids", Nosaukums: "Nosaukums",
  Datnes: "Datnes", Datne: "Datne", DatnesID: "Datnes ID", DatnesNosaukums: "Nosaukums", MimeVeids: "MIME veids",
  FormataID: "Formāts (PRONOM)", IzmersBaitos: "Izmērs", Kontrolsumma: "Kontrolsumma",
  GlabasanasAtsauce: "Glabātuves atsauce", OriginalaDatnesID: "Oriģinālās datnes ID",
  Paraksti: "Paraksti", Paraksts: "Paraksts", ParakstaVeids: "Paraksta veids", Parakstitajs: "Parakstītājs",
  ParakstitsUz: "Parakstīts", ParakstitaDatnesID: "Parakstītā datne", SertifikataNospiedums: "Sertifikāta nospiedums",
  ParakstaVertiba: "Paraksta vērtība", VerifikacijasMetode: "Verifikācijas metode",
  Izcelsme: "Izcelsme", IzveidotsUz: "Izveidots", Izveidots: "Izveidots", Izveidotajs: "Izveidotājs",
  Iesniedzejs: "Iesniedzējs", SanemtsUz: "Saņemts", SanemsanasKanals: "Saņemšanas kanāls",
  LietotajaID: "Lietotāja ID", VardsUzvards: "Vārds, uzvārds", Amats: "Amats", Strukturvieniba: "Struktūrvienība",
  SemantiskaisKopsavilkums: "Semantiskais kopsavilkums", Paplasinajumi: "Paplašinājumi", Piezime: "Piezīme",
  // izsekošana
  DokumentaVesture: "Dokumenta vēsture", DokumentaAtsauce: "Dokuments", Notikums: "Notikums",
  NotikumaID: "Notikuma ID", NotikumaTips: "Notikums", NotikumaLaiks: "Laiks", Izdevejs: "Iestāde",
  Darbinieks: "Darbinieks", LokalaisRegistracijasNumurs: "Reģistrācijas numurs", StatusaMaina: "Statuss",
  NoStatusa: "No", UzStatusu: "Uz", Iemesls: "Iemesls",
  Izpilde: "Izpilde", Izpilditajs: "Izpildītājs", IzpildesTermins: "Izpildes termiņš", Uzdevums: "Uzdevums",
  Aprite: "Aprite", Sutitajs: "Sūtītājs", Sanemejs: "Saņēmējs", Kanals: "Kanāls", TransportaID: "Transporta ID",
  Merkis: "Mērķis", AtbildesTermins: "Atbildes termiņš", SaistitaisDokuments: "Saistītais dokuments",
  Pieradijums: "Pierādījums", PieradijumaTips: "Pierādījuma veids",
};

const V = {
  // notikumi
  DokumentsIzveidots: "Dokuments izveidots", PavadvestuleIzveidota: "Pavadvēstule izveidota",
  DokumentsRegistrets: "Dokuments reģistrēts", DokumentsSanemts: "Dokuments saņemts",
  DokumentsNosutits: "Dokuments nosūtīts", DokumentsParsutits: "Dokuments pārsūtīts",
  DokumentsPieskirtsIzpildei: "Nodots izpildei", DokumentsIzskatisana: "Nodots izskatīšanai",
  DokumentsVizets: "Dokuments vizēts", DokumentsParakstits: "Dokuments parakstīts",
  DokumentsLemums: "Pieņemts lēmums", DokumentsAtgriezts: "Dokuments atgriezts",
  DokumentsIzpildits: "Dokuments izpildīts", DokumentsSlegts: "Dokuments slēgts",
  DokumentsNodotsArhivam: "Nodots arhīvam", DokumentsArhivets: "Arhivēts", DokumentsIznicinats: "Iznīcināts",
  // statusi
  Projekts: "Projekts", Registrets: "Reģistrēts", Izpilde: "Izpildē", Izskatisana: "Izskatīšanā",
  Izpildits: "Izpildīts", Slegts: "Slēgts", NodotsArhivam: "Nodots arhīvam", Arhivets: "Arhivēts", Iznicinats: "Iznīcināts",
  // klasifikatori
  IerobezotasPieejamibas: "Ierobežotas pieejamības", Visparpieejama: "Vispārpieejama", DienestaVajadzibam: "Dienesta vajadzībām",
  NoLietasSlegsanas: "no lietas slēgšanas", NoDokumentaDatuma: "no dokumenta datuma", NoIzpildes: "no izpildes",
  NoNotikuma: "no notikuma", Iznicinat: "Iznīcināt", NodotArhivam: "Nodot arhīvam", Parskatit: "Pārskatīt",
  Pastavigi: "Pastāvīgi", FiziskaPersona: "Fiziska persona", JuridiskaPersona: "Juridiska persona",
  ValstsIestade: "Valsts iestāde", Pasvaldiba: "Pašvaldība", Persona: "Persona", Sistema: "Sistēma",
  EAdrese: "e-adrese", EPasts: "E-pasts", Pasts: "Pasts", Klatiene: "Klātienē", Portals: "Portāls", API: "API",
  DVSIntegracija: "DVS integrācija", DVSLietotajs: "DVS lietotājs", MIAgents: "MI aģents",
  ViedoklaSniegsanai: "Viedokļa sniegšanai", Zinasanai: "Zināšanai", Izpildei: "Izpildei",
  Saskanosanai: "Saskaņošanai", Atbilde: "Atbilde", Arhivesanai: "Arhivēšanai", Cits: "Cits",
  Pamatdatne: "Pamatdatne", Pielikums: "Pielikums", Atvasinajums: "Atvasinājums", ParakstaKonteiners: "Paraksta konteiners",
  DrossElektroniskaisParaksts: "Drošs elektroniskais paraksts", ElektroniskaisZimogs: "Elektroniskais zīmogs",
  Pasrocigs: "Pašrocīgs", Vizesana: "Vīzēšana", PecPiekritibas: "Pēc piekrišanas",
  RegistracijasNumurs: "Reģistrācijas numurs", IepriekshejaisUID: "Iepriekšējais UID",
  SanemejaRegistracijasNumurs: "Saņēmēja reģ. numurs", DVSIeksejaisID: "DVS iekšējais ID",
  EAdresesSutijumaID: "e-adreses sūtījuma ID", ArhivaPakotnesID: "Arhīva pakotnes ID",
  pavada: "pavada", atbildeUz: "atbilde uz", atsauceUz: "atsauce uz", aizstaj: "aizstāj",
  papildina: "papildina", irPielikumsPie: "ir pielikums pie", irDalaNo: "ir daļa no",
  dokuments: "dokuments", lieta: "lieta", serija: "sērija", fonds: "fonds",
  true: "Jā", false: "Nē", lv: "latviešu", en: "angļu",
};

const STATUS_COLOR = {
  Projekts: "bg-gray-100 text-gray-700", Registrets: "bg-sky-100 text-sky-700", Izpilde: "bg-amber-100 text-amber-800",
  Izskatisana: "bg-amber-100 text-amber-800", Izpildits: "bg-emerald-100 text-emerald-700", Slegts: "bg-gray-200 text-gray-700",
  NodotsArhivam: "bg-violet-100 text-violet-700", Arhivets: "bg-violet-100 text-violet-700", Iznicinats: "bg-red-100 text-red-700",
};

const label = (name) => L[name] || name.replace(/([a-z])([A-Z])/g, "$1 $2");
const val = (v) => V[v] ?? v;
const kids = (el) => Array.from(el.children);
const child = (el, name) => el && kids(el).find((c) => c.localName === name);
const text = (el, name) => child(el, name)?.textContent.trim() || "";

const isDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s);
const isDateTime = (s) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s);
function fmtDate(s) {
  if (isDateTime(s)) return new Date(s).toLocaleString("lv-LV", { dateStyle: "medium", timeStyle: "short" });
  if (isDate(s)) return new Date(s + "T00:00:00").toLocaleDateString("lv-LV", { dateStyle: "medium" });
  return s;
}
const fmtSize = (n) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;

// Value of a leaf element, formatted by what it is.
function leafValue(el) {
  const name = el.localName;
  const raw = el.textContent.trim();
  if (name === "IzmersBaitos" && /^\d+$/.test(raw)) return fmtSize(+raw);
  if (name === "GlabasanasTermins") return el.getAttribute("veids") === "Pastavigi" ? "Pastāvīgi"
    : el.getAttribute("veids") === "LidzDatumam" ? `līdz ${fmtDate(el.getAttribute("lidz") || "")}` : `${raw} gadi`;
  if (name === "Kontrolsumma") return <Mono>{(el.getAttribute("algoritms") || "") + " " + raw}</Mono>;
  if (isDate(raw) || isDateTime(raw)) return fmtDate(raw);
  if (/^(LV-[A-Z]+:|did:|urn:|fmt\/)/.test(raw) || /ID$|DID$/.test(name)) return <Mono>{raw}</Mono>;
  let v = val(raw);
  const tips = el.getAttribute("tips");
  if (name === "Identifikators" && tips) return <>{raw} <span className="text-ink-400">({val(tips)}{el.getAttribute("avots") ? ", " + el.getAttribute("avots") : ""})</span></>;
  return v;
}

const Mono = ({ children }) => <code className="font-mono text-[11px] break-all text-ink-700">{children}</code>;

// Generic block: leaves become label/value rows, containers become sub-blocks.
function Block({ el, depth = 0, skip = [] }) {
  const items = kids(el).filter((c) => !skip.includes(c.localName));
  const leaves = items.filter((c) => !c.children.length);
  const groups = items.filter((c) => c.children.length);
  return (
    <div className="space-y-2">
      {leaves.length > 0 && (
        <dl className="grid grid-cols-[minmax(8rem,12rem)_1fr] gap-x-3 gap-y-1 text-xs">
          {leaves.map((c, i) => (
            <Row key={i} k={label(c.localName)} v={leafValue(c)} />
          ))}
        </dl>
      )}
      {groups.map((g, i) => (
        <div key={i} className={depth === 0 ? "" : "pl-3 border-l border-ink-100"}>
          <div className="text-2xs uppercase tracking-wide text-ink-400 mb-1">
            {label(g.localName)}
            {g.getAttribute("loma") && <span className="normal-case tracking-normal"> · {val(g.getAttribute("loma"))}</span>}
            {g.getAttribute("tips") && <span className="normal-case tracking-normal"> · {val(g.getAttribute("tips"))}</span>}
          </div>
          <Block el={g} depth={depth + 1} />
        </div>
      ))}
    </div>
  );
}

const Row = ({ k, v }) => (
  <>
    <dt className="text-ink-400">{k}</dt>
    <dd className="text-ink-800 min-w-0 break-words">{v}</dd>
  </>
);

const Section = ({ title, children }) => (
  <div className="border-t border-ink-100 pt-2">
    <div className="text-xs font-semibold text-ink-700 mb-1.5">{title}</div>
    {children}
  </div>
);

// ── metadati.xml ──────────────────────────────────────────────────────────

function Metadata({ root }) {
  const sys = child(root, "SistemasKonteksts");
  const org = child(root, "IpasniekaOrganizacija");
  const docs = kids(root).filter((c) => c.localName === "Dokuments");
  return (
    <div className="space-y-4">
      <div className="text-xs text-ink-500 flex flex-wrap gap-x-4 gap-y-1">
        <span>Shēmas versija <b className="text-ink-700">{root.getAttribute("shemasVersija")}</b></span>
        {root.getAttribute("izveidotsUz") && <span>Izveidots <b className="text-ink-700">{fmtDate(root.getAttribute("izveidotsUz"))}</b></span>}
        {sys && <span>Sistēma <b className="text-ink-700">{[text(sys, "SistemasNosaukums"), text(sys, "SistemasInstance"), text(sys, "Vide")].filter(Boolean).join(" · ")}</b></span>}
      </div>
      {org && (
        <div className="rounded-md bg-gray-50 px-3 py-2">
          <div className="text-sm font-medium text-ink-900">{text(org, "OrgNosaukums")}</div>
          <Block el={org} skip={["OrgNosaukums"]} />
        </div>
      )}
      {docs.map((d, i) => <MetaDocument key={i} d={d} />)}
    </div>
  );
}

function MetaDocument({ d }) {
  const type = child(d, "DokumentaVeids");
  const sec = child(d, "Drosiba");
  const glab = child(d, "Glabasana");
  const cas = child(child(d, "Klasifikacija"), "KlasifikacijasLieta");
  const shown = ["DokumentaID", "DokumentaDID", "Virsraksts", "Apraksts", "DokumentaVeids", "DokumentaDatums", "RegistretsUz", "Valoda",
                 "ArejieIdentifikatori", "Versija", "Klasifikacija", "Glabasana", "Drosiba", "Datnes", "Izcelsme",
                 "SemantiskaisKopsavilkums"];
  const rest = kids(d).filter((c) => !shown.includes(c.localName));
  const regNr = kids(child(d, "ArejieIdentifikatori") || d).find((c) => c.getAttribute?.("tips") === "RegistracijasNumurs");
  const files = kids(child(d, "Datnes") || d).filter((c) => c.localName === "Datne");
  return (
    <div className="border rounded-lg p-3 space-y-3">
      <div>
        <div className="flex flex-wrap items-center gap-2 mb-1">
          {type && <span className="text-[10px] px-2 py-0.5 rounded-full bg-sky-100 text-sky-700 font-medium">{text(type, "VeidaNosaukums") || text(type, "VeidaKods")}</span>}
          {sec && <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${text(sec, "InformacijasStatuss") === "Visparpieejama" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>{val(text(sec, "InformacijasStatuss"))}</span>}
          {text(sec, "SaturPersonasDatus") === "true" && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 font-medium">satur personas datus</span>}
        </div>
        <div className="text-sm font-semibold text-ink-900">{text(d, "Virsraksts")}</div>
        {text(d, "Apraksts") && <p className="text-xs text-ink-600 mt-1">{text(d, "Apraksts")}</p>}
      </div>

      <dl className="grid grid-cols-[minmax(8rem,12rem)_1fr] gap-x-3 gap-y-1 text-xs">
        <Row k="Dokumenta ID" v={<Mono>{text(d, "DokumentaID")}</Mono>} />
        {text(d, "DokumentaDID") && <Row k="Dokumenta DID" v={<Mono>{text(d, "DokumentaDID")}</Mono>} />}
        {regNr && <Row k="Reģistrācijas numurs" v={regNr.textContent.trim()} />}
        {text(d, "DokumentaDatums") && <Row k="Dokumenta datums" v={fmtDate(text(d, "DokumentaDatums"))} />}
        {text(d, "RegistretsUz") && <Row k="Reģistrēts" v={fmtDate(text(d, "RegistretsUz"))} />}
        {cas && <Row k="Lieta" v={<>{text(cas, "LietasIndekss")} {text(cas, "LietasNosaukums")} <span className="text-ink-400">({text(cas, "LietasGads")})</span></>} />}
        {child(glab, "GlabasanasTermins") && <Row k="Glabāšana" v={<>{leafValue(child(glab, "GlabasanasTermins"))} {val(text(glab, "GlabasanasTriggeris"))}, pēc tam — {val(text(glab, "IznicinasanasDarbiba")).toLowerCase()}</>} />}
        {text(child(sec, "PiekluvesIerobezojums"), "TiesiskaisPamatojums") && <Row k="Piekļuves pamatojums" v={text(child(sec, "PiekluvesIerobezojums"), "TiesiskaisPamatojums")} />}
      </dl>

      {child(d, "SemantiskaisKopsavilkums") && <Semantics sk={child(d, "SemantiskaisKopsavilkums")} />}

      {child(d, "Izcelsme") && <Section title="Izcelsme"><Block el={child(d, "Izcelsme")} /></Section>}

      {files.length > 0 && (
        <Section title={`Datnes (${files.length})`}>
          <div className="space-y-2">
            {files.map((f, i) => (
              <div key={i} className="rounded bg-gray-50 px-2 py-1.5">
                <div className="text-xs font-medium text-ink-800 break-all">
                  {text(f, "DatnesNosaukums")}
                  <span className="font-normal text-ink-400"> · {val(f.getAttribute("loma") || "")}{text(f, "IzmersBaitos") && " · " + fmtSize(+text(f, "IzmersBaitos"))}</span>
                </div>
                <Block el={f} skip={["DatnesNosaukums", "IzmersBaitos"]} />
              </div>
            ))}
          </div>
        </Section>
      )}

      {rest.map((c, i) => (
        <Section key={i} title={label(c.localName)}>
          {c.children.length ? <Block el={c} /> : <div className="text-xs">{leafValue(c)}</div>}
        </Section>
      ))}

      <details className="text-xs">
        <summary className="cursor-pointer text-ink-400 hover:text-ink-700">Visi lauki</summary>
        <div className="mt-2"><Block el={d} /></div>
      </details>
    </div>
  );
}

// 13. Semantiskais kopsavilkums (vdvc/dokumentu-semantikas-formats)
const STATUSS = { apgalvots: "apgalvo", pieprasits: "lūdz", apliecinats: "apliecina", noliegts: "noliedz", secinats: "secināts" };
const PARSK = { neparskatits: "nav pārskatīts", apstiprinats: "pārskatīts, apstiprināts", labots: "pārskatīts, labots" };
function Semantics({ sk }) {
  const a = kids(sk).find((c) => c.localName === "SemantiskaisApraksts");
  if (!a) return <Section title="Semantiskais kopsavilkums"><Block el={sk} /></Section>;
  const list = (name) => kids(child(a, name) || a).filter((c) => c.parentNode === child(a, name));
  const people = Object.fromEntries(list("Dalibnieki").map((p) => [p.getAttribute("id"), text(p, "Nosaukums") || text(p, "Loma")]));
  const rev = child(child(a, "Izcelsme"), "Parskatisana")?.getAttribute("statuss");
  return (
    <Section title={<>Semantiskais kopsavilkums <span className="font-normal text-ink-400">· {a.getAttribute("profils")} · {a.getAttribute("slanis")} slānis · MI ģenerēts, {PARSK[rev] || rev}</span></>}>
      <p className="text-xs text-ink-800 leading-relaxed">{text(child(a, "Kopsavilkums"), "Teksts")}</p>
      <div className="flex flex-wrap gap-1 mt-2">
        {list("Temas").map((t, i) => (
          <span key={i} className={`text-[10px] px-1.5 py-0.5 rounded ${(t.getAttribute("shema") || "").includes("eurovoc") ? "bg-indigo-50 text-indigo-800" : "bg-emerald-50 text-emerald-800"}`}>
            {(t.getAttribute("shema") || "").includes("eurovoc") ? "EuroVoc" : "Klasifikators"} {t.getAttribute("kods")} {text(t, "Nosaukums")}
          </span>
        ))}
        {list("Pazimes").map((p, i) => <span key={"p" + i} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-ink-700">{p.getAttribute("kods")}: {text(p, "Vertiba")}</span>)}
      </div>
      <dl className="grid grid-cols-[minmax(8rem,12rem)_1fr] gap-x-3 gap-y-1 text-xs mt-2">
        {list("Apgalvojumi").map((c, i) => (
          <Row key={i} k={text(c, "Predikats")}
            v={<><span className="text-ink-400">{people[text(c, "Apgalvo")] || text(c, "Apgalvo")} {STATUSS[text(c, "Statuss")] || text(c, "Statuss")}:</span> {text(c, "Vertiba")}</>} />
        ))}
      </dl>
      <details className="text-xs mt-1">
        <summary className="cursor-pointer text-ink-400 hover:text-ink-700">Visi semantiskā apraksta lauki</summary>
        <div className="mt-2"><Block el={a} /></div>
      </details>
    </Section>
  );
}

// ── izsekosana.xml ────────────────────────────────────────────────────────

function Tracking({ root }) {
  const histories = kids(root).filter((c) => c.localName === "DokumentaVesture");
  return (
    <div className="space-y-4">
      <div className="text-xs text-ink-500">
        Shēmas versija <b className="text-ink-700">{root.getAttribute("shemasVersija")}</b>
        {root.getAttribute("izveidotsUz") && <> · Izveidots <b className="text-ink-700">{fmtDate(root.getAttribute("izveidotsUz"))}</b></>}
      </div>
      {histories.map((h, i) => {
        const ref = child(h, "DokumentaAtsauce");
        const events = kids(h).filter((c) => c.localName === "Notikums");
        return (
          <div key={i} className="border rounded-lg p-3">
            <div className="text-sm font-semibold text-ink-900">{text(ref, "Virsraksts") || "Dokuments"}</div>
            <div className="mb-3"><Mono>{text(ref, "DokumentaID")}</Mono></div>
            <ol className="relative border-l-2 border-ink-100 ml-2 space-y-4">
              {events.map((e, j) => <Event key={j} e={e} />)}
            </ol>
          </div>
        );
      })}
    </div>
  );
}

function Event({ e }) {
  const who = child(e, "Darbinieks");
  const org = child(e, "Izdevejs");
  const st = child(e, "StatusaMaina");
  const shown = ["NotikumaID", "NotikumaTips", "NotikumaLaiks", "Darbinieks", "Izdevejs", "StatusaMaina", "LokalaisRegistracijasNumurs"];
  const rest = kids(e).filter((c) => !shown.includes(c.localName));
  return (
    <li className="ml-4">
      <span className="absolute -left-[7px] mt-1 w-3 h-3 rounded-full bg-white border-2 border-sky-500" />
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-medium text-ink-900">{val(text(e, "NotikumaTips"))}</span>
        <span className="text-xs text-ink-400">{fmtDate(text(e, "NotikumaLaiks"))}</span>
      </div>
      {st && (
        <div className="flex items-center gap-1.5 mt-1 text-[11px]">
          {text(st, "NoStatusa") && <><Status s={text(st, "NoStatusa")} /><span className="text-ink-400">→</span></>}
          <Status s={text(st, "UzStatusu")} />
          {text(st, "Iemesls") && <span className="text-ink-500 ml-1">{text(st, "Iemesls")}</span>}
        </div>
      )}
      <div className="text-xs text-ink-600 mt-1">
        {[text(who, "VardsUzvards"), text(who, "Amats"), text(who, "Strukturvieniba")].filter(Boolean).join(", ")}
        {who && org && " · "}
        {org && <span className="text-ink-400">{text(org, "OrgNosaukums") || text(org, "OrgKods")}</span>}
        {text(e, "LokalaisRegistracijasNumurs") && <> · reģ. nr. <b className="text-ink-700">{text(e, "LokalaisRegistracijasNumurs")}</b></>}
      </div>
      {rest.length > 0 && (
        <div className="mt-2 space-y-2">
          {rest.map((c, i) => c.localName === "Aprite" ? (
            <div key={i} className="text-xs text-ink-600">
              <span className="font-medium text-ink-800">{text(child(c, "Sutitajs"), "OrgNosaukums") || text(child(c, "Sutitajs"), "OrgKods")}</span>
              <span className="text-ink-400"> → </span>
              <span className="font-medium text-ink-800">{text(child(c, "Sanemejs"), "OrgNosaukums") || text(child(c, "Sanemejs"), "OrgKods")}</span>
              {[text(c, "Kanals") && "kanāls: " + val(text(c, "Kanals")),
                text(c, "Merkis") && val(text(c, "Merkis")).toLowerCase(),
                text(c, "AtbildesTermins") && "atbilde līdz " + fmtDate(text(c, "AtbildesTermins"))]
                .filter(Boolean).map((x, k) => <span key={k}> · {x}</span>)}
              {text(c, "TransportaID") && <div className="text-[10px] text-ink-400">transporta ID <Mono>{text(c, "TransportaID")}</Mono></div>}
            </div>
          ) : c.localName === "Datnes" ? (
            <div key={i} className="text-xs text-ink-600">
              <span className="text-ink-400">Datnes: </span>
              {kids(c).map((f) => text(f, "DatnesNosaukums") || text(f, "DatnesID")).join(", ")}
            </div>
          ) : c.localName === "SaistitaisDokuments" ? (
            <div key={i} className="text-xs text-ink-600">
              <span className="text-ink-400">Saistītais dokuments ({val(c.getAttribute("loma") || "")}): </span><Mono>{text(c, "DokumentaID")}</Mono>
            </div>
          ) : (
            <div key={i} className="rounded bg-gray-50 px-2 py-1.5">
              <div className="text-2xs uppercase tracking-wide text-ink-400 mb-1">
                {label(c.localName)}{c.getAttribute("loma") && <span className="normal-case tracking-normal"> · {val(c.getAttribute("loma"))}</span>}
              </div>
              {c.children.length ? <Block el={c} depth={1} /> : <div className="text-xs">{leafValue(c)}</div>}
            </div>
          ))}
        </div>
      )}
      <div className="mt-1 text-[10px] text-ink-300"><Mono>{text(e, "NotikumaID")}</Mono></div>
    </li>
  );
}

const Status = ({ s }) => <span className={`px-1.5 py-0.5 rounded font-medium ${STATUS_COLOR[s] || "bg-gray-100 text-gray-700"}`}>{val(s)}</span>;

// ── entry ─────────────────────────────────────────────────────────────────

export function hasReadableView(name) {
  return name === "metadati.xml" || name === "izsekosana.xml";
}

export default function StandardXmlView({ xml }) {
  let root;
  try {
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error();
    root = doc.documentElement;
  } catch {
    return <div className="p-3 text-xs text-red-600">XML neizdevās nolasīt — skatiet cilni „XML”.</div>;
  }
  return (
    <div className="p-3 overflow-auto max-h-[70vh]">
      {root.localName === "DokumentaPakotne" ? <Metadata root={root} />
        : root.localName === "Izsekosana" ? <Tracking root={root} />
        : <Block el={root} />}
    </div>
  );
}
