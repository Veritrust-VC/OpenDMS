// Arhīvs — dokumentu arhivēšana pēc MK 282 un kisc/dokumentu-arhivesanas-standarts.
// Sadaļas: klasifikācijas shēma (periodi, statusi, imports, eksports), arhīva iestatījumi, vecā eksporta partija.
import { useState, useEffect } from "react";

const STATUS_STYLE = {
  Projekts: "bg-gray-100 text-gray-700", IzskatitsEK: "bg-sky-100 text-sky-700", IesniegtsLNA: "bg-amber-100 text-amber-800",
  SaskanotsLNA: "bg-teal-100 text-teal-700", NoraiditsLNA: "bg-red-100 text-red-700", NavJasaskano: "bg-teal-100 text-teal-700",
  Apstiprinats: "bg-green-100 text-green-700", Aizstata: "bg-gray-200 text-gray-500",
};
const STATUS_LV = {
  Projekts: "Projekts", IzskatitsEK: "Izskatīts EK", IesniegtsLNA: "Iesniegts LNA", SaskanotsLNA: "Saskaņots ar LNA",
  NoraiditsLNA: "LNA noraidīts", NavJasaskano: "Nav jāsaskaņo", Apstiprinats: "Apstiprināts", Aizstata: "Aizstāta",
};
const NEXT_LABEL = {
  IzskatitsEK: "Atzīmēt: izskatīts EK", IesniegtsLNA: "Atzīmēt: iesniegts LNA", NavJasaskano: "Nav jāsaskaņo ar LNA",
  SaskanotsLNA: "LNA saskaņoja", NoraiditsLNA: "LNA noraidīja", Apstiprinats: "Apstiprināt shēmu", Projekts: "Atgriezt projektā",
};
const NESEJS = { E: "elektronisks", P: "papīrs", C: "cits", H: "hibrīds" };
const RICIBA = { Iznicinat: "iznīcināt", NodotArhivam: "nodot arhīvam", Parskatit: "pārskatīt (EK)" };

function Pill({ s }) {
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLE[s] || "bg-gray-100"}`}>{STATUS_LV[s] || s}</span>;
}
const termins = (e) => e.retention_kind === "Pastavigi" ? "Pastāvīgi"
  : (e.retention_years ? `${e.retention_years} g.` : "—") + (e.retention_marks?.length ? " " + e.retention_marks.join(" ") : "");
const field = "w-full text-sm px-3 py-2 border rounded";

// ───────────────────────── iestatījumi ─────────────────────────
function Settings({ api, notify }) {
  const [s, setS] = useState(null);
  const load = async () => { try { setS(await api("/archive/settings")); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); }, []);
  if (!s) return <div className="text-sm text-gray-400">Ielādē…</div>;
  const set = (k) => (e) => setS({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const save = async (extra = {}) => {
    try {
      const body = { archive_code: s.archive_code || null, archive_name: s.archive_name || null, fonds_number: s.fonds_number || null,
                     fonds_name: s.fonds_name || null, registration_number: s.registration_number || null, ...extra };
      setS(await api("/archive/settings", { method: "PUT", body: JSON.stringify(body) })); notify("Saglabāts");
    } catch (e) { notify(e.message, "error"); load(); }
  };
  const row = (k, label, ph, hint) => (
    <label className="block"><span className="text-xs font-medium text-gray-600">{label}</span>
      <input value={s[k] || ""} onChange={set(k)} placeholder={ph} className={field} />
      {hint && <span className="text-xs text-gray-400">{hint}</span>}</label>);
  return (
    <div className="max-w-2xl space-y-4">
      {s.missing?.length > 0 && <div className="text-sm bg-amber-50 border border-amber-200 text-amber-800 rounded p-3">
        Bez šiem datiem nevar veidot LNA uzskaites kodus un pakotnes: {s.missing.join(", ")}.</div>}
      <div className="bg-white border rounded-lg p-4 space-y-3">
        <div className="text-sm font-semibold">Arhīvs un fonds</div>
        <div className="grid grid-cols-2 gap-3">
          {row("archive_code", "Arhīva kods (LNA klasifikators)", "LVA")}
          {row("archive_name", "Arhīva nosaukums", "Latvijas Valsts arhīvs")}
          {row("fonds_number", "Fonda numurs", "1234")}
          {row("fonds_name", "Fonda nosaukums", "Iestādes nosaukums")}
        </div>
        {row("registration_number", "Iestādes reģistrācijas Nr.", s.registration_number_from_org || "90000000000",
             s.registration_number_from_org ? `Ja tukšs, izmanto organizācijas datus: ${s.registration_number_from_org}` : "Nepieciešams LNA EAD3 laukam")}
        <button onClick={() => save()} className="text-sm px-4 py-2 bg-emerald-600 text-white rounded">Saglabāt</button>
      </div>
      <div className="bg-white border rounded-lg p-4 space-y-2">
        <div className="text-sm font-semibold">Reģistrācijas minimums (process P2)</div>
        <p className="text-xs text-gray-500">Ieslēgts: dokumentu nevar reģistrēt bez lietas no apstiprinātās klasifikācijas shēmas, glabāšanas termiņa,
          informācijas statusa, datuma, veida un glabājamiem datņu formātiem. Ieslēgt var, kad šim periodam ir apstiprināta shēma.</p>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={!!s.enforce_registration_minimum}
                 onChange={(e) => save({ enforce_registration_minimum: e.target.checked })} />
          {s.enforce_registration_minimum ? "Ieslēgts" : "Izslēgts"}
        </label>
      </div>
    </div>);
}

// ───────────────────────── shēma ─────────────────────────
function NewScheme({ api, notify, schemes, onCreated }) {
  const y = new Date().getFullYear() + 1;
  const [f, setF] = useState({ period_from: `${y}-01-01`, period_to: `${y}-12-31`, title: "", copy_from: "" });
  const create = async () => {
    try {
      const s = await api("/archive/schemes", { method: "POST", body: JSON.stringify({ ...f, title: f.title || null,
        copy_from: f.copy_from ? Number(f.copy_from) : null }) });
      notify("Shēma izveidota"); onCreated(s.id);
    } catch (e) { notify(e.message, "error"); }
  };
  return (
    <div className="bg-white border rounded-lg p-3 space-y-2">
      <div className="text-sm font-semibold">Jauna shēma</div>
      <div className="grid grid-cols-2 gap-2">
        <input type="date" value={f.period_from} onChange={(e) => setF({ ...f, period_from: e.target.value })} className={field} />
        <input type="date" value={f.period_to} onChange={(e) => setF({ ...f, period_to: e.target.value })} className={field} />
      </div>
      <input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Nosaukums (neobligāts)" className={field} />
      <select value={f.copy_from} onChange={(e) => setF({ ...f, copy_from: e.target.value })} className={field}>
        <option value="">Tukša shēma (importēt no datnes)</option>
        {schemes.map((s) => <option key={s.id} value={s.id}>Kopēt no {s.period_from} – {s.period_to} ({STATUS_LV[s.status]})</option>)}
      </select>
      <button onClick={create} className="text-sm px-4 py-2 bg-emerald-600 text-white rounded">Izveidot</button>
    </div>);
}

function ImportBox({ api, notify, scheme, onDone }) {
  const [file, setFile] = useState(null);
  const [prev, setPrev] = useState(null);
  const send = async (dry) => {
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api(`/archive/schemes/${scheme.id}/import?izmeginajums=${dry ? 1 : 0}`, { method: "POST", body: fd });
      if (dry) setPrev(r); else { notify(`Importēts: ${r.kopsavilkums.lietas} lietas`); setPrev(null); setFile(null); onDone(); }
    } catch (e) { notify(e.message, "error"); }
  };
  return (
    <div className="bg-white border rounded-lg p-3 space-y-2">
      <div className="text-sm font-semibold">Importēt no datnes</div>
      <p className="text-xs text-gray-500">.xlsx vai .csv ar ailēm "Indekss", "Lietas nosaukums", "Glabāšanas termiņš" (neobligāti: pants, atbildīgā
        struktūrvienība, informācijas vide, piezīmes) vai .xml (ark:KlasifikacijasShema). Rindas bez termiņa ir līmeņi. Imports aizstāj šīs shēmas ierakstus.</p>
      <input type="file" accept=".xlsx,.csv,.xml" onChange={(e) => { setFile(e.target.files[0]); setPrev(null); }} className="text-sm" />
      {file && !prev && <button onClick={() => send(true)} className="text-sm px-3 py-1.5 bg-sky-600 text-white rounded">Priekšskatīt</button>}
      {prev && <div className="space-y-2">
        <div className="text-sm">Līmeņi: <b>{prev.kopsavilkums.limeni}</b> · lietas: <b>{prev.kopsavilkums.lietas}</b> · pastāvīgi: <b>{prev.kopsavilkums.pastavigi}</b>
          {prev.kopsavilkums.bez_termina > 0 && <> · <span className="text-red-600">bez nolasāma termiņa: {prev.kopsavilkums.bez_termina}</span></>}</div>
        {prev.ailes && <div className="text-xs text-gray-500">Atpazītās ailes: {Object.entries(prev.ailes).map(([k, v]) => `${k}="${v}"`).join(", ")}</div>}
        {prev.bridinajumi.length > 0 && <ul className="text-xs text-amber-800 bg-amber-50 rounded p-2 max-h-32 overflow-auto list-disc pl-5">
          {prev.bridinajumi.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        <div className="flex gap-2">
          <button onClick={() => send(false)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded">Importēt</button>
          <button onClick={() => setPrev(null)} className="text-sm px-3 py-1.5 border rounded">Atcelt</button>
        </div>
      </div>}
    </div>);
}

function EntryEditor({ api, notify, scheme, e, onSaved, onClose }) {
  const [f, setF] = useState({ ...e, retention_marks: (e.retention_marks || []).join(" ") });
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.type === "checkbox" ? ev.target.checked : ev.target.value });
  const save = async () => {
    try {
      const body = { name: f.name, retention_kind: f.retention_kind, retention_years: f.retention_kind === "Gadi" ? Number(f.retention_years) || null : null,
        retention_marks: f.retention_marks.split(/\s+/).filter(Boolean), retention_legal_basis: f.retention_legal_basis || null,
        disposition: f.disposition, responsible_unit: f.responsible_unit || null, medium: f.medium || null,
        default_info_status: f.default_info_status || null, access_basis: f.access_basis || null, long_running: !!f.long_running, notes: f.notes || null };
      await api(`/archive/schemes/${scheme.id}/entries/${e.id}`, { method: "PATCH", body: JSON.stringify(body) });
      notify("Saglabāts"); onSaved();
    } catch (err) { notify(err.message, "error"); }
  };
  return (
    <tr><td colSpan={6} className="bg-sky-50 p-3">
      <div className="grid grid-cols-3 gap-2 text-sm">
        <input value={f.name} onChange={set("name")} className={field + " col-span-3"} />
        <select value={f.retention_kind} onChange={set("retention_kind")} className={field}><option value="Gadi">Gadi</option><option value="Pastavigi">Pastāvīgi</option></select>
        <input value={f.retention_years || ""} onChange={set("retention_years")} placeholder="gadi" disabled={f.retention_kind !== "Gadi"} className={field} />
        <input value={f.retention_marks} onChange={set("retention_marks")} placeholder="EK AI" className={field} />
        <select value={f.disposition || ""} onChange={set("disposition")} className={field}>
          {Object.entries(RICIBA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select value={f.medium || ""} onChange={set("medium")} className={field}><option value="">nesējs</option>
          {Object.entries(NESEJS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <input value={f.responsible_unit || ""} onChange={set("responsible_unit")} placeholder="atbildīgā struktūrvienība" className={field} />
        <select value={f.default_info_status || ""} onChange={set("default_info_status")} className={field}>
          <option value="">statuss pēc noklusējuma</option><option value="Visparpieejama">vispārpieejama</option>
          <option value="IerobezotasPieejamibas">ierobežotas pieejamības</option><option value="DienestaVajadzibam">dienesta vajadzībām</option></select>
        <input value={f.access_basis || ""} onChange={set("access_basis")} placeholder="ierobežojuma tiesiskais pamatojums" className={field + " col-span-2"} />
        <input value={f.retention_legal_basis || ""} onChange={set("retention_legal_basis")} placeholder="termiņa pamatojums (pants)" className={field + " col-span-2"} />
        <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.long_running} onChange={set("long_running")} /> ilgstoša lieta</label>
        <input value={f.notes || ""} onChange={set("notes")} placeholder="piezīmes" className={field + " col-span-3"} />
      </div>
      <div className="flex gap-2 mt-2">
        <button onClick={save} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded">Saglabāt</button>
        <button onClick={onClose} className="text-sm px-3 py-1.5 border rounded">Aizvērt</button>
      </div>
    </td></tr>);
}

function StatusBox({ api, notify, scheme, onDone }) {
  const [to, setTo] = useState(null);
  const [f, setF] = useState({ datums: new Date().toISOString().slice(0, 10), atsauce: "", piezimes: "" });
  const go = async () => {
    try {
      await api(`/archive/schemes/${scheme.id}/status`, { method: "POST", body: JSON.stringify({ statuss: to, datums: f.datums,
        atsauce: f.atsauce || null, piezimes: f.piezimes || null }) });
      notify(STATUS_LV[to]); setTo(null); onDone();
    } catch (e) { notify(e.message, "error"); }
  };
  if (!scheme.next.length) return null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">{scheme.next.map((n) =>
        <button key={n} onClick={() => setTo(n)} className={`text-xs px-3 py-1.5 rounded border ${to === n ? "bg-sky-600 text-white" : "bg-white"}`}>{NEXT_LABEL[n] || n}</button>)}</div>
      {to && <div className="flex flex-wrap gap-2 items-center">
        <input type="date" value={f.datums} onChange={(e) => setF({ ...f, datums: e.target.value })} className="text-sm px-2 py-1 border rounded" />
        <input value={f.atsauce} onChange={(e) => setF({ ...f, atsauce: e.target.value })}
               placeholder={["SaskanotsLNA", "NoraiditsLNA", "IesniegtsLNA"].includes(to) ? "LNA vēstules / lēmuma Nr." : "EK protokola Nr. vai atsauce"}
               className="text-sm px-2 py-1 border rounded" />
        <input value={f.piezimes} onChange={(e) => setF({ ...f, piezimes: e.target.value })} placeholder="piezīmes" className="text-sm px-2 py-1 border rounded flex-1" />
        <button onClick={go} className="text-sm px-3 py-1 bg-emerald-600 text-white rounded">Apstiprināt</button>
      </div>}
    </div>);
}

function SchemeDetail({ api, notify, id, onChanged }) {
  const [s, setS] = useState(null);
  const [prob, setProb] = useState(null);
  const [edit, setEdit] = useState(null);
  const load = async () => {
    try { setS(await api(`/archive/schemes/${id}`)); setProb(await api(`/archive/schemes/${id}/problems`)); }
    catch (e) { notify(e.message, "error"); }
  };
  useEffect(() => { load(); setEdit(null); }, [id]);
  if (!s) return <div className="text-sm text-gray-400">Ielādē…</div>;
  const refresh = () => { load(); onChanged(); };
  const exportXml = async () => {
    try { const r = await api(`/archive/schemes/${id}/export.xml`); const b = await r.blob(); const a = document.createElement("a");
          a.href = URL.createObjectURL(b); a.download = `klasifikacijas-shema-${s.period_from}-${s.period_to}.xml`; a.click(); }
    catch (e) { notify(e.message, "error"); }
  };
  const del = async () => { if (!confirm("Dzēst šo shēmas projektu?")) return;
    try { await api(`/archive/schemes/${id}`, { method: "DELETE" }); notify("Dzēsts"); onChanged(null); } catch (e) { notify(e.message, "error"); } };
  const depth = {};
  s.entries.forEach((e) => { depth[e.id] = e.parent_id ? (depth[e.parent_id] ?? 0) + 1 : 0; });
  return (
    <div className="space-y-3">
      <div className="bg-white border rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="font-semibold">{s.title || "Lietu klasifikācijas shēma"} · {s.period_from} – {s.period_to}</div>
            <div className="text-xs text-gray-500">versija {s.version}{s.sector ? " · nozares shēma" : ""}{s.source?.datne ? ` · avots: ${s.source.datne}` : ""}</div>
          </div>
          <Pill s={s.status} />
        </div>
        <StatusBox api={api} notify={notify} scheme={s} onDone={refresh} />
        {prob?.problemas?.length > 0 && <div className="text-xs bg-amber-50 border border-amber-200 rounded p-2">
          <b>Pirms apstiprināšanas jānovērš:</b><ul className="list-disc pl-5">{prob.problemas.slice(0, 12).map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
        <div className="flex gap-2">
          <button onClick={exportXml} className="text-xs px-3 py-1.5 border rounded">Eksportēt XML (LNA saskaņošanai)</button>
          {s.status === "Projekts" && <button onClick={del} className="text-xs px-3 py-1.5 border rounded text-red-600">Dzēst projektu</button>}
        </div>
        {s.history?.length > 0 && <details className="text-xs text-gray-600"><summary className="cursor-pointer">Vēsture ({s.history.length})</summary>
          <ul className="mt-1 space-y-0.5">{s.history.map((h, i) => <li key={i}>{h.datums} · {STATUS_LV[h.statuss] || h.statuss}
            {h.atsauce ? ` · ${h.atsauce}` : ""}{h.piezimes ? ` · ${h.piezimes}` : ""}{h.kas ? ` · ${h.kas}` : ""}</li>)}</ul></details>}
      </div>
      {s.editable && <ImportBox api={api} notify={notify} scheme={s} onDone={refresh} />}
      <div className="bg-white border rounded-lg overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500"><tr>
            <th className="text-left px-3 py-2">Indekss</th><th className="text-left px-3 py-2">Nosaukums</th><th className="text-left px-3 py-2">Termiņš</th>
            <th className="text-left px-3 py-2">Rīcība</th><th className="text-left px-3 py-2">Atbildīgais</th><th className="text-left px-3 py-2">Nesējs</th></tr></thead>
          <tbody className="divide-y">
            {s.entries.map((e) => [
              <tr key={e.id} onClick={() => s.editable && e.kind === "lieta" && setEdit(edit === e.id ? null : e.id)}
                  className={e.kind === "limenis" ? "bg-gray-50 font-medium" : (s.editable ? "cursor-pointer hover:bg-sky-50" : "")}>
                <td className="px-3 py-1.5 whitespace-nowrap font-mono text-xs">{e.idx}</td>
                <td className="px-3 py-1.5" style={{ paddingLeft: 12 + depth[e.id] * 16 }}>{e.name}
                  {e.long_running && <span className="ml-2 text-xs text-sky-700">ilgstoša</span>}
                  {e.notes?.includes("JĀPRECIZĒ") && <span className="ml-2 text-xs text-red-600">termiņš jāprecizē</span>}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{e.kind === "lieta" ? <span className={e.retention_kind === "Pastavigi" ? "text-emerald-700 font-medium" : ""}>{termins(e)}</span> : ""}</td>
                <td className="px-3 py-1.5 text-xs">{e.kind === "lieta" ? RICIBA[e.disposition] || "" : ""}</td>
                <td className="px-3 py-1.5 text-xs">{e.responsible_unit || ""}</td>
                <td className="px-3 py-1.5 text-xs">{NESEJS[e.medium] || ""}</td>
              </tr>,
              edit === e.id && <EntryEditor key={"ed" + e.id} api={api} notify={notify} scheme={s} e={e} onSaved={() => { setEdit(null); refresh(); }} onClose={() => setEdit(null)} />,
            ])}
            {!s.entries.length && <tr><td colSpan={6} className="p-6 text-center text-gray-400">Shēmā vēl nav ierakstu — importējiet no datnes.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>);
}

function Schemes({ api, notify }) {
  const [list, setList] = useState([]);
  const [sel, setSel] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const load = async (pick) => {
    try { const l = await api("/archive/schemes"); setList(l);
          if (pick !== undefined) setSel(pick); else if (!sel && l.length) setSel(l[0].id); }
    catch (e) { notify(e.message, "error"); }
  };
  useEffect(() => { load(); }, []);
  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-4 space-y-3">
        <button onClick={() => setShowNew(!showNew)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded">+ Jauna shēma</button>
        {showNew && <NewScheme api={api} notify={notify} schemes={list} onCreated={(id) => { setShowNew(false); load(id); }} />}
        <div className="bg-white border rounded-lg divide-y">
          {list.map((s) => (
            <button key={s.id} onClick={() => setSel(s.id)} className={`w-full text-left px-3 py-2 ${sel === s.id ? "bg-sky-50" : "hover:bg-gray-50"}`}>
              <div className="flex items-center justify-between"><span className="text-sm font-medium">{s.period_from} – {s.period_to}</span><Pill s={s.status} /></div>
              <div className="text-xs text-gray-500">{s.lietas} lietas · {s.pastavigi} pastāvīgi{s.title ? ` · ${s.title}` : ""}</div>
            </button>))}
          {!list.length && <div className="p-4 text-sm text-gray-400">Klasifikācijas shēmas vēl nav. Izveidojiet jaunu un importējiet iestādes nomenklatūru.</div>}
        </div>
      </div>
      <div className="col-span-8">{sel ? <SchemeDetail api={api} notify={notify} id={sel} onChanged={(pick) => load(pick)} /> : null}</div>
    </div>);
}

// ───────────────────────── vecā eksporta partija ─────────────────────────
function LegacyBatches({ api, notify }) {
  const [batches, setBatches] = useState([]); const [docIds, setDocIds] = useState(""); const [name, setName] = useState("");
  const load = async () => { try { setBatches(await api("/archive/batches")); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); }, []);
  const create = async () => { try { const ids = docIds.split(",").map((s) => parseInt(s.trim())).filter((n) => !isNaN(n));
    await api("/archive/batches", { method: "POST", body: JSON.stringify({ name, document_ids: ids }) }); notify("Partija izveidota"); load(); } catch (e) { notify(e.message, "error"); } };
  const exp = async (id) => { try { const r = await api(`/archive/batches/${id}/export`, { method: "POST" }); const blob = await r.blob();
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `archive-${id}.zip`; a.click(); } catch (e) { notify(e.message, "error"); } };
  return (<div className="max-w-2xl space-y-3">
    <p className="text-xs text-gray-500">Vienkāršs ZIP eksports ar JSON metadatiem. Neatbilst MK 282 un LNA prasībām — tiks aizstāts ar aprakstīšanu un OPEX nodošanu.</p>
    <div className="bg-white border rounded-lg p-4 space-y-2">
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Partijas nosaukums" className={field} />
      <input value={docIds} onChange={(e) => setDocIds(e.target.value)} placeholder="Dokumentu ID (atdalīti ar komatu)" className={field} />
      <button onClick={create} className="text-sm px-4 py-2 bg-gray-600 text-white rounded">Izveidot partiju</button>
    </div>
    <div className="bg-white rounded-lg border divide-y">
      {batches.map((b) => (<div key={b.id} className="px-4 py-3 flex items-center justify-between">
        <div><div className="text-sm font-medium">{b.name}</div><div className="text-xs text-gray-400">{b.document_count} dok. · {b.status}</div></div>
        <button onClick={() => exp(b.id)} className="text-xs px-3 py-1 border rounded">Lejupielādēt ZIP</button></div>))}
      {!batches.length && <div className="p-6 text-center text-gray-400 text-sm">Nav partiju</div>}
    </div>
  </div>);
}

export default function ArchivePage({ api, notify }) {
  const [tab, setTab] = useState("shema");
  const tabs = [["shema", "Klasifikācijas shēma"], ["iestatijumi", "Iestatījumi"], ["partijas", "Vecā eksporta partija"]];
  return (
    <div>
      <h2 className="text-xl font-bold">Arhīvs</h2>
      <p className="text-sm text-gray-500 mb-4">Dokumentu dzīves cikls līdz iznīcināšanai vai nodošanai LNA — MK 07.05.2024. noteikumi Nr. 282.</p>
      <div className="flex gap-1 border-b mb-4">{tabs.map(([k, l]) =>
        <button key={k} onClick={() => setTab(k)} className={`text-sm px-4 py-2 -mb-px border-b-2 ${tab === k ? "border-emerald-600 text-emerald-700 font-medium" : "border-transparent text-gray-500"}`}>{l}</button>)}</div>
      {tab === "shema" && <Schemes api={api} notify={notify} />}
      {tab === "iestatijumi" && <Settings api={api} notify={notify} />}
      {tab === "partijas" && <LegacyBatches api={api} notify={notify} />}
    </div>);
}
