// Arhīvs — dokumentu arhivēšana pēc MK 282 un kisc/dokumentu-arhivesanas-standarts.
// Sadaļas: lietas (atvēršana, slēgšana, sējumi), klasifikācijas shēma (periodi, statusi, imports, eksports), arhīva iestatījumi, vecā eksporta partija.
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
      <EnginePanel api={api} notify={notify} />
      <LnaPanel api={api} notify={notify} />
    </div>);
}

const LNA_KIND = { akts: "Iznīcināšanas akts", saraksts: "Uzskaites saraksts", plans: "Nodošanas vienošanās", nodosana: "Nodošana (OPEX)" };
function LnaPanel({ api, notify }) {
  const [l, setL] = useState(null);
  const load = async () => { try { setL(await api("/archive/lna")); } catch { setL(null); } };
  useEffect(() => { load(); }, []);
  const poll = async () => { try { const r = await api("/archive/lna/poll", { method: "POST" }); notify(`Pārbaudīti ${r.parbauditi ?? 0}, turpināti ${r.turpinati ?? 0}`); load(); } catch (e) { notify(e.message, "error"); } };
  if (!l) return null;
  return (<div className="bg-white border rounded-lg p-4 space-y-2 text-sm">
    <div className="font-medium">LNA savienojums</div>
    {l.konfigurets
      ? <div className="text-emerald-700">Savienots: {l.adrese} · iestāde {l.iestade}{l.s3 ? " · S3 ievades krātuve" : " · bez S3"} <span className="text-xs text-gray-500">(laboratorijas simulators)</span></div>
      : <div className="text-amber-700">Nav konfigurēts — LNA lēmumus ievada lietotājs.</div>}
    {l.konfigurets && <button onClick={poll} className="text-xs px-3 py-1 border rounded">Nolasīt LNA lēmumus tagad</button>}
    {l.iesniegumi.length > 0 && <div className="border rounded divide-y text-xs">{l.iesniegumi.slice(0, 15).map((x) =>
      <div key={x.id} className="px-2 py-1 flex justify-between gap-2"><span>{String(x.created_at).slice(0, 16).replace("T", " ")} · {LNA_KIND[x.kind] || x.kind} {x.object_id}</span>
        <span className={x.status === "Noraidits" ? "text-red-700" : x.status === "Sanemts" ? "text-amber-700" : "text-emerald-700"}>{x.status}{x.decision?.atsauce ? ` · ${x.decision.atsauce}` : ""}{x.resumed_at ? " · process turpināts" : ""}{x.error ? ` · ${x.error.slice(0, 80)}` : ""}</span></div>)}</div>}
  </div>);
}

function EnginePanel({ api, notify }) {
  const [e, setE] = useState(null); const [busy, setBusy] = useState(false);
  const load = async () => { try { setE(await api("/archive/engine")); } catch { setE(null); } };
  useEffect(() => { load(); }, []);
  const install = async () => { setBusy(true);
    try { const r = await api("/archive/engine/install", { method: "POST" }); notify(`Pakotne ${r.packageId} ${r.version} uzstādīta`); load(); }
    catch (x) { notify(x.message, "error"); } finally { setBusy(false); } };
  return (<div className="bg-white border rounded-lg p-4 space-y-2 text-sm">
    <div className="font-medium">Arhivēšanas procesi (UAPF)</div>
    <div className="text-xs text-gray-500">Noteikumi un procesi izpildās no ProcessGit pakotnes <span className="font-mono">kisc/dokumentu-arhivesana</span>. Ja dzinējs nav pieejams, lēmumus rēķina lokālā kopija, un tas tiek norādīts.</div>
    {e && <div>{e.uzstadita ? <span className="text-emerald-700">Uzstādīta: {e.pakotne} {e.versija}</span> : <span className="text-amber-700">Nav uzstādīta</span>}</div>}
    <button disabled={busy} onClick={install} className="text-sm px-3 py-1.5 border rounded disabled:opacity-40">{e?.uzstadita ? "Atjaunināt no ProcessGit" : "Uzstādīt no ProcessGit"}</button>
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

// ───────────────────────── lietas ─────────────────────────
const CASE_STYLE = { Atverta: "bg-sky-100 text-sky-700", Slegta: "bg-gray-200 text-gray-700", Iznicinata: "bg-red-100 text-red-700", GlabaIestade: "bg-teal-100 text-teal-700" };
const download = async (api, notify, path, name) => {
  try { const r = await api(path); const b = await r.blob(); const a = document.createElement("a");
        a.href = URL.createObjectURL(b); a.download = name; a.click(); } catch (e) { notify(e.message, "error"); } };

function CaseDetail({ api, notify, id, onChanged }) {
  const [c, setC] = useState(null); const [docId, setDocId] = useState(""); const [vol, setVol] = useState(null);
  const [sessions, setSessions] = useState([]); const [ended, setEnded] = useState(false);
  const load = async () => { try { setC(await api(`/archive/cases/${id}`)); setSessions(await api(`/archive/cases/${id}/sessions`)); } catch (e) { notify(e.message, "error"); } };
  const runClose = async () => {
    try { const r = await api(`/archive/cases/${id}/process/close`, { method: "POST", body: JSON.stringify({ jautajumsIzbeigts: ended }) });
          const o = r.rezultats || {};
          notify(r.stavoklis === "suspended" ? "Process gaida: nepabeigtie dokumenti jāpabeidz" : `${o.darbiba || r.stavoklis}: ${o.iemesls || ""}`, r.stavoklis === "failed" ? "error" : undefined);
          load(); onChanged(); } catch (e) { notify(e.message, "error"); } };
  const resume = async (sid, output = {}) => { try { const r = await api(`/archive/sessions/${sid}/resume`, { method: "POST", body: JSON.stringify({ output }) }); notify(`Process: ${r.stavoklis}${r.rezultats?.iemesls ? " — " + r.rezultats.iemesls : ""}`); load(); onChanged(); } catch (e) { notify(e.message, "error"); } };
  const appraise = async () => {
    try { const r = await api(`/archive/cases/${id}/process/appraise`, { method: "POST" }); const o = r.rezultats || {};
          notify(r.stavoklis === "suspended" ? "Vajadzīgs ekspertu komisijas lēmums" : `${o.rezultats || r.stavoklis}: ${o.iemesls || ""}`); load(); onChanged(); }
    catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); }, [id]);
  if (!c) return null;
  const act = async (path, body, msg) => {
    try { await api(`/archive/cases/${id}/${path}`, { method: "POST", body: JSON.stringify(body || {}) }); notify(msg); load(); onChanged(); }
    catch (e) { notify(e.message, "error"); } };
  const finish = async (d) => {
    try { await api(`/archive/documents/${d}/finish`, { method: "POST", body: "{}" }); notify("Dokuments atzīmēts kā pabeigts"); load(); onChanged(); }
    catch (e) { notify(e.message, "error"); } };
  const open = c.status === "Atverta";
  return (<div className="bg-white border rounded-lg p-4 space-y-4">
    <div className="flex items-start justify-between gap-3">
      <div><div className="text-lg font-semibold">{c.case_index} {c.case_name}</div>
        <div className="text-xs text-gray-500 font-mono">{c.case_id}</div></div>
      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CASE_STYLE[c.status] || "bg-amber-100 text-amber-800"}`}>{c.status_lv}</span>
    </div>
    <div className="grid grid-cols-3 gap-3 text-sm">
      <div><div className="text-xs text-gray-400">Gads</div>{c.case_year}{c.long_running ? " · turpinās" : ""}</div>
      <div><div className="text-xs text-gray-400">Glabāšanas termiņš</div>{termins(c)}{c.disposition ? ` · ${RICIBA[c.disposition]}` : ""}</div>
      <div><div className="text-xs text-gray-400">Glabā līdz</div>{c.retention_kind === "Pastavigi" ? "pastāvīgi" : (c.retention_end || "pēc slēgšanas")}</div>
      <div><div className="text-xs text-gray-400">Datumu robežas</div>{c.date_from ? `${c.date_from} – ${c.date_to}` : "—"}</div>
      <div><div className="text-xs text-gray-400">Shēmas ieraksts</div>{c.shemas_ieraksts ? `${c.shemas_ieraksts.idx} (${c.shemas_ieraksts.period_from.slice(0, 4)})` : <span className="text-amber-700">nav sasaistīts</span>}</div>
      <div><div className="text-xs text-gray-400">Reģistra SHA-256</div><span className="font-mono text-xs break-all">{c.register_sha256 ? c.register_sha256.slice(0, 16) + "…" : "—"}</span></div>
    </div>
    {["Slegta", "Izverteta", "GlabaIestade"].includes(c.status) && <div className="flex gap-2 items-center">
      <button onClick={appraise} className="text-sm px-3 py-1.5 bg-sky-700 text-white rounded" title="Process p4a-lietas-izvertesana (lēmums ekspertizes-lemums)">Izvērtēt (process)</button>
      <span className="text-xs text-gray-500">glabā līdz {c.retention_end || "pastāvīgi"}</span></div>}
    {open && <div className="flex flex-wrap gap-2">
      <button onClick={runClose} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded"
        title="Process p3-lietas-slegsana: nepabeigtie dokumenti, perioda beigas, ilgstoša lieta">Slēgt lietu (process)</button>
      {c.long_running && <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={ended} onChange={(e) => setEnded(e.target.checked)} />jautājums izbeigts</label>}
      {!c.long_running && <button onClick={() => act("carry-over", {}, "Lieta turpināsies nākamajā periodā")} className="text-sm px-3 py-1.5 border rounded">Ilgstoša — turpināt nākamgad</button>}
      <button onClick={() => setVol(vol ? null : { medium: "P", content_type: "Teksts", page_count: "" })} className="text-sm px-3 py-1.5 border rounded">+ Papīra sējums</button>
      <input value={docId} onChange={(e) => setDocId(e.target.value)} placeholder="Dokumenta DVS ID" className="text-sm px-2 py-1 border rounded w-36" />
      <button onClick={() => { act("documents", { document_id: parseInt(docId) }, "Dokuments pievienots lietai"); setDocId(""); }} className="text-sm px-3 py-1.5 border rounded">Pievienot</button>
    </div>}
    {vol && <div className="flex gap-2 items-center bg-gray-50 p-2 rounded">
      <select value={vol.medium} onChange={(e) => setVol({ ...vol, medium: e.target.value })} className="text-sm border rounded px-2 py-1">
        {Object.entries(NESEJS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      <input value={vol.page_count} onChange={(e) => setVol({ ...vol, page_count: e.target.value })} placeholder="lapas" className="text-sm border rounded px-2 py-1 w-24" />
      <button onClick={() => { act("volumes", { ...vol, page_count: vol.page_count ? parseInt(vol.page_count) : null }, "Sējums pievienots"); setVol(null); }} className="text-sm px-3 py-1 bg-gray-700 text-white rounded">Saglabāt</button>
    </div>}
    {c.nepabeigti > 0 && <div className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
      {c.nepabeigti} dokumenti nav pabeigti — lietu var slēgt, kad visi ir izlemti, nosūtīti vai atzīmēti kā pabeigti (MK 282 47. p.).</div>}
    <div><div className="text-sm font-medium mb-1">Dokumenti ({c.dokumenti.length})</div>
      <div className="border rounded divide-y max-h-80 overflow-auto">
        {c.dokumenti.map((d) => <div key={d.id} className="px-3 py-1.5 flex items-center justify-between text-sm">
          <div className="min-w-0"><span className="font-mono text-xs text-gray-500 mr-2">{d.registration_number || `#${d.id}`}</span>{d.title}</div>
          <div className="flex items-center gap-2 shrink-0"><span className="text-xs text-gray-400">{d.status} · {d.datnes} datnes</span>
            {d.nepabeigts && open && <button onClick={() => finish(d.id)} className="text-xs px-2 py-0.5 border border-amber-300 text-amber-800 rounded">Pabeigts</button>}</div>
        </div>)}
        {!c.dokumenti.length && <div className="p-3 text-sm text-gray-400">Lietā vēl nav dokumentu</div>}
      </div></div>
    {c.sejumi.length > 0 && <div className="text-sm"><div className="font-medium mb-1">Sējumi</div>
      {c.sejumi.map((v) => <div key={v.id} className="text-xs text-gray-600">{v.number}. {NESEJS[v.medium]} · {v.content_type}
        {v.document_count != null ? ` · ${v.document_count} dok.` : ""}{v.file_count != null ? ` · ${v.file_count} datnes` : ""}{v.page_count ? ` · ${v.page_count} lp.` : ""}</div>)}</div>}
    <div className="flex gap-2">
      {c.shemas_ieraksts && <button onClick={() => download(api, notify, `/archive/cases/${id}/lieta.xml`, `lieta-${c.case_index}-${c.case_year}.xml`)} className="text-xs px-3 py-1 border rounded">ark:Lieta XML</button>}
      {c.register_key && <button onClick={() => download(api, notify, `/archive/cases/${id}/register.xml`, `lietas-registrs-${c.case_index}-${c.case_year}.xml`)} className="text-xs px-3 py-1 border rounded">Dokumentu reģistrs XML</button>}
    </div>
    {sessions.length > 0 && <div className="text-xs"><div className="font-medium text-sm mb-1">Procesi</div>
      {sessions.map((x) => <div key={x.session_id} className="flex items-center gap-2 py-0.5">
        <span className="text-gray-500">{String(x.started_at).slice(0, 16).replace("T", " ")}</span>
        <span>{x.process_id}</span>
        <span className={x.state === "completed" ? "text-emerald-700" : x.state === "suspended" ? "text-amber-700" : "text-red-700"}>{x.state}</span>
        {x.rezultats?.darbiba && <span>· {x.rezultats.darbiba}: {x.rezultats.iemesls}</span>}
        {x.error_message && <span className="text-red-700">· {x.error_message.slice(0, 120)}</span>}
        {x.state === "suspended" && x.waiting_for === "ResolveUnfinished" && <button onClick={() => resume(x.session_id)} className="px-2 py-0.5 border border-amber-300 rounded">Pārbaudīt vēlreiz</button>}
        {x.state === "suspended" && x.waiting_for === "EKDecision" && <span className="flex gap-1">EK lēmums:
          {[["Iznicinat", "iznīcināt"], ["Pagarinat", "pagarināt termiņu"], ["NodotArhivam", "arhiviska vērtība"]].map(([k, l]) =>
            <button key={k} onClick={() => resume(x.session_id, { ekLemums: k })} className="px-2 py-0.5 border border-amber-300 rounded">{l}</button>)}</span>}
      </div>)}</div>}
    <details className="text-xs text-gray-500"><summary className="cursor-pointer">Vēsture ({c.history.length})</summary>
      {c.history.map((h, i) => <div key={i}>{h.kad?.slice(0, 16).replace("T", " ")} · {h.darbiba} · {h.kas}</div>)}</details>
  </div>);
}

function OpenCase({ api, notify, year, onDone }) {
  const [entries, setEntries] = useState(null); const [pick, setPick] = useState("");
  useEffect(() => { (async () => {
    try { const s = await api(`/archive/schemes/active?on=${year}-06-30`); const full = await api(`/archive/schemes/${s.id}`);
          setEntries(full.entries.filter((e) => e.kind === "lieta")); }
    catch (e) { setEntries([]); notify(e.message, "error"); } })(); }, [year]);
  const one = async () => { try { await api("/archive/cases", { method: "POST", body: JSON.stringify({ entry_id: parseInt(pick), gads: year }) }); notify("Lieta atvērta"); onDone(); } catch (e) { notify(e.message, "error"); } };
  const all = async () => { try { const r = await api("/archive/cases/open-period", { method: "POST", body: JSON.stringify({ gads: year }) });
    notify(`Atvērtas ${r.atvertas} no ${r.lietas} lietām`); onDone(); } catch (e) { notify(e.message, "error"); } };
  if (entries === null) return null;
  if (!entries.length) return <div className="text-xs text-gray-500 bg-white border rounded p-3">{year}. gadam nav apstiprinātas klasifikācijas shēmas.</div>;
  return (<div className="bg-white border rounded-lg p-3 space-y-2">
    <select value={pick} onChange={(e) => setPick(e.target.value)} className={field}>
      <option value="">— shēmas lieta —</option>{entries.map((e) => <option key={e.id} value={e.id}>{e.idx} {e.name}</option>)}</select>
    <div className="flex gap-2"><button disabled={!pick} onClick={one} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded disabled:opacity-40">Atvērt</button>
      <button onClick={all} className="text-sm px-3 py-1.5 border rounded">Atvērt visas {year}. gada lietas</button></div>
  </div>);
}

function Unfiled({ api, notify, year }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { (async () => { try { setRows(await api(`/archive/unfiled?gads=${year}`)); } catch (e) { notify(e.message, "error"); } })(); }, [year]);
  if (!rows || !rows.length) return null;
  return (<details className="bg-white border border-amber-200 rounded-lg">
    <summary className="px-3 py-2 text-sm cursor-pointer text-amber-900">{rows.length} dokumenti nav sagatavoti arhivēšanai</summary>
    <div className="divide-y max-h-72 overflow-auto">{rows.map((d) => <div key={d.id} className="px-3 py-1.5 text-xs">
      <span className="font-mono text-gray-500 mr-1">{d.registration_number || `#${d.id}`}</span>{d.title}
      <span className="text-gray-400"> · {d.case_index ? `lieta ${d.case_index}, nav arhīva ID` : "bez lietas"}</span></div>)}</div>
  </details>);
}

function Cases({ api, notify }) {
  const [year, setYear] = useState(new Date().getFullYear()); const [list, setList] = useState([]);
  const [sel, setSel] = useState(null); const [showOpen, setShowOpen] = useState(false);
  const load = async () => { try { setList(await api(`/archive/cases?gads=${year}`)); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); }, [year]);
  return (<div className="grid grid-cols-12 gap-4">
    <div className="col-span-4 space-y-3">
      <div className="flex gap-2 items-center">
        <select value={year} onChange={(e) => { setYear(parseInt(e.target.value)); setSel(null); }} className="text-sm border rounded px-2 py-1.5">
          {[0, 1, 2, 3, 4].map((d) => new Date().getFullYear() + 1 - d).map((y) => <option key={y}>{y}</option>)}</select>
        <button onClick={() => setShowOpen(!showOpen)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded">+ Atvērt lietu</button>
      </div>
      {showOpen && <OpenCase api={api} notify={notify} year={year} onDone={() => { setShowOpen(false); load(); }} />}
      <Unfiled api={api} notify={notify} year={year} />
      <div className="bg-white border rounded-lg divide-y">
        {list.map((c) => <button key={c.id} onClick={() => setSel(c.id)} className={`w-full text-left px-3 py-2 ${sel === c.id ? "bg-sky-50" : "hover:bg-gray-50"}`}>
          <div className="flex items-center justify-between"><span className="text-sm font-medium">{c.case_index} {c.case_name}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${CASE_STYLE[c.status] || "bg-amber-100 text-amber-800"}`}>{c.status_lv}</span></div>
          <div className="text-xs text-gray-500">{c.dokumenti} dok.{c.nepabeigti ? ` · ${c.nepabeigti} nepabeigti` : ""} · {termins(c)}{c.scheme_entry_id ? "" : " · bez shēmas"}</div>
        </button>)}
        {!list.length && <div className="p-4 text-sm text-gray-400">{year}. gadā lietu nav.</div>}
      </div>
    </div>
    <div className="col-span-8">{sel ? <CaseDetail api={api} notify={notify} id={sel} onChanged={load} /> : null}</div>
  </div>);
}

// ───────────────────────── iznīcināšana (P4b) ─────────────────────────
function ActDetail({ api, notify, id, onChanged }) {
  const [a, setA] = useState(null); const [f, setF] = useState({}); const [confirm, setConfirm] = useState(false);
  const load = async () => { try { setA(await api(`/archive/acts/${id}`)); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); setF({}); setConfirm(false); }, [id]);
  if (!a) return null;
  const s = a.sesija; const waiting = s?.state === "suspended" ? s.waiting_for : null;
  const resume = async (output) => {
    try { const r = await api(`/archive/sessions/${s.session_id}/resume`, { method: "POST", body: JSON.stringify({ output }) });
          notify(`Process: ${r.stavoklis}${r.gaida ? " — gaida " + r.gaida : ""}`); load(); onChanged(); } catch (e) { notify(e.message, "error"); } };
  return (<div className="bg-white border rounded-lg p-4 space-y-3 text-sm">
    <div className="flex items-center justify-between"><div className="text-lg font-semibold">Iznīcināšanas akts Nr. {a.number}</div>
      <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100">{a.status_lv}</span></div>
    <div className="text-xs text-gray-500">{a.act_date}{a.ek_protocol_no ? ` · EK protokols ${a.ek_protocol_no}` : ""}{a.lna_decision ? ` · LNA: ${a.lna_decision}` : ""}{a.destroyed_at ? ` · iznīcināts ${String(a.destroyed_at).slice(0, 10)}` : ""}</div>
    <div className="border rounded divide-y">{a.lietas.map((c) => <div key={c.id} className="px-3 py-1.5 flex justify-between">
      <span>{c.case_index} {c.case_name} ({c.case_year})</span><span className="text-xs text-gray-500">{c.dokumenti} dok. · {c.datnes} datnes · {c.retention_years} g. · līdz {c.retention_end || "—"}</span></div>)}</div>
    <button onClick={() => download(api, notify, `/archive/acts/${id}/act.xml`, `iznicinasanas-akts-${a.number.replace("/", "-")}.xml`)} className="text-xs px-3 py-1 border rounded">Akts XML (5. pielikums)</button>
    {waiting === "ReviewEK" && <div className="bg-amber-50 border border-amber-200 rounded p-3 space-y-2">
      <div className="font-medium">Ekspertu komisija pārbauda termiņus un apjomu (106. p.)</div>
      <div className="flex gap-2"><input value={f.ekProtokolaNr || ""} onChange={(e) => setF({ ...f, ekProtokolaNr: e.target.value })} placeholder="EK protokola Nr." className="text-sm border rounded px-2 py-1" />
        <input type="date" value={f.ekDatums || ""} onChange={(e) => setF({ ...f, ekDatums: e.target.value })} className="text-sm border rounded px-2 py-1" /></div>
      <div className="flex gap-2"><button onClick={() => resume({ ...f, ekAkcepts: true })} className="px-3 py-1 bg-emerald-600 text-white rounded">EK akceptē</button>
        <button onClick={() => resume({ ekAkcepts: false })} className="px-3 py-1 border rounded">Atgriezt labošanai</button></div></div>}
    {waiting === "CorrectAct" && <div className="bg-amber-50 border border-amber-200 rounded p-3 space-y-2">
      <div>Akts jālabo: mainiet lietu izvērtējumu (Lietas → Izvērtēt) un pārveidojiet aktu.</div>
      <button onClick={() => resume({})} className="px-3 py-1 border rounded">Pārveidot aktu</button></div>}
    {waiting === "AwaitLNA" && <div className="bg-amber-50 border border-amber-200 rounded p-3 space-y-2">
      <div className="font-medium">LNA lēmums par aktu</div><div className="text-xs text-gray-500">Ar LNA savienojumu lēmums tiek ievadīts automātiski (Iestatījumi → LNA savienojums); citādi to reģistrē šeit.</div>
      <input value={f.lnaAtsauce || ""} onChange={(e) => setF({ ...f, lnaAtsauce: e.target.value })} placeholder="LNA vēstules / lēmuma atsauce" className="w-full text-sm border rounded px-2 py-1" />
      <div className="flex gap-2"><button onClick={() => resume({ lnaLemums: "Saskanots", lnaAtsauce: f.lnaAtsauce })} className="px-3 py-1 bg-emerald-600 text-white rounded">LNA saskaņoja</button>
        <button onClick={() => resume({ lnaLemums: "Noraidits", lnaAtsauce: f.lnaAtsauce })} className="px-3 py-1 border rounded">LNA noraidīja</button></div></div>}
    {waiting === "ApproveDestruction" && <div className="bg-red-50 border border-red-300 rounded p-3 space-y-2">
      <div className="font-medium text-red-800">Apstiprināt iznīcināšanu</div>
      <div className="text-xs text-red-800">Pēc apstiprināšanas šo lietu dokumentu datnes tiks neatgriezeniski dzēstas visās glabātuvēs, arī visas versijas. Reģistra ieraksti un akts paliek.</div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />Esmu iestādes vadītājs vai pilnvarotā persona un apstiprinu iznīcināšanu</label>
      <button disabled={!confirm} onClick={() => resume({ apstiprinu: true })} className="px-3 py-1 bg-red-700 text-white rounded disabled:opacity-40">Apstiprināt un iznīcināt</button></div>}
    <details className="text-xs text-gray-500"><summary className="cursor-pointer">Vēsture ({a.history.length})</summary>
      {a.history.map((h, i) => <div key={i}>{String(h.kad).slice(0, 16).replace("T", " ")} · {h.darbiba} · {h.kas}</div>)}</details>
  </div>);
}

function Acts({ api, notify }) {
  const [list, setList] = useState([]); const [sel, setSel] = useState(null);
  const load = async () => { try { setList(await api("/archive/acts")); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); }, []);
  const start = async () => { try { const r = await api("/archive/acts/process/start", { method: "POST" });
    notify(r.gaida ? `Akts sagatavots — gaida: ${r.gaida}` : `Process: ${r.stavoklis}`); load(); } catch (e) { notify(e.message, "error"); } };
  return (<div className="grid grid-cols-12 gap-4">
    <div className="col-span-4 space-y-3">
      <button onClick={start} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded" title="Process p4b-iznicinasanas-akts">+ Sagatavot aktu (process)</button>
      <p className="text-xs text-gray-500">Aktā iekļauj lietas, kuras izvērtēšanā atlasītas iznīcināšanai (MK 282 104.–109. p.).</p>
      <div className="bg-white border rounded-lg divide-y">{list.map((a) => <button key={a.id} onClick={() => setSel(a.id)} className={`w-full text-left px-3 py-2 ${sel === a.id ? "bg-sky-50" : "hover:bg-gray-50"}`}>
        <div className="flex justify-between"><span className="text-sm font-medium">Nr. {a.number}</span><span className="text-xs">{a.status_lv}</span></div>
        <div className="text-xs text-gray-500">{a.act_date} · {a.lietas} lietas</div></button>)}
        {!list.length && <div className="p-4 text-sm text-gray-400">Aktu vēl nav.</div>}</div>
    </div>
    <div className="col-span-8">{sel ? <ActDetail api={api} notify={notify} id={sel} onChanged={load} /> : null}</div>
  </div>);
}

// ───────────────────────── aprakstīšana (P5) un nodošana LNA (P6) ─────────────────────────
function TaskBox({ title, children }) {
  return <div className="bg-amber-50 border border-amber-200 rounded p-3 space-y-2"><div className="font-medium">{title}</div>{children}</div>;
}

function ListDetail({ api, notify, id, onChanged }) {
  const [l, setL] = useState(null); const [f, setF] = useState({});
  const load = async () => { try { setL(await api(`/archive/lists/${id}`)); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); setF({}); }, [id]);
  if (!l) return null;
  const s = l.sesija; const waiting = s?.state === "suspended" ? s.waiting_for : null;
  const resume = async (output) => { try { const r = await api(`/archive/sessions/${s.session_id}/resume`, { method: "POST", body: JSON.stringify({ output }) });
    notify(`Process: ${r.stavoklis}${r.gaida ? " — gaida " + r.gaida : ""}`); load(); onChanged(); } catch (e) { notify(e.message, "error"); } };
  const lastCheck = l.history.slice().reverse().find((h) => h.darbiba === "PārbaudesKļūdas");
  return (<div className="bg-white border rounded-lg p-4 space-y-3 text-sm">
    <div className="flex items-center justify-between"><div className="text-lg font-semibold">{l.title}</div><span className="text-xs px-2 py-0.5 rounded-full bg-gray-100">{l.status_lv}</span></div>
    <div className="border rounded divide-y">{l.lietas.map((c) => <div key={c.id} className="px-3 py-1.5 flex justify-between">
      <span><span className="text-gray-500 mr-2">{c.kartas_numurs}.</span>{c.case_index} {c.case_name} ({c.case_year})</span>
      <span className="text-xs text-gray-500 font-mono">{c.uzskaites_kods || c.status}</span></div>)}</div>
    <button onClick={() => download(api, notify, `/archive/lists/${id}/list.xml`, `uzskaites-saraksts-${l.number}.xml`)} className="text-xs px-3 py-1 border rounded">Uzskaites saraksts XML</button>
    {s?.state === "failed" && <div className="text-xs text-red-700">{s.error_message}</div>}
    {waiting === "Fix" && <TaskBox title="Saraksts jālabo">
      {lastCheck && <div className="text-xs text-red-800">{(lastCheck.kludas || []).map((k, i) => <div key={i}>{k}</div>)}</div>}
      <div className="text-xs">Novērsiet kļūdas (piem., Arhīvs → Iestatījumi: arhīva kods, fonds) un pārbaudiet vēlreiz.</div>
      <button onClick={() => resume({})} className="px-3 py-1 border rounded">Pārveidot un pārbaudīt</button></TaskBox>}
    {waiting === "Sign" && <TaskBox title="Sastādītājs un atbildīgais paraksta (93. p.)">
      <div className="text-xs">Paraksts DVS ar jūsu kontu. Ja LNA prasa drošu e-parakstu, lejupielādējiet XML un parakstiet eParakstā.</div>
      <button onClick={() => resume({ parakstu: true })} className="px-3 py-1 bg-emerald-600 text-white rounded">Parakstīt un iesniegt LNA</button></TaskBox>}
    {waiting === "AwaitLNA" && <TaskBox title="LNA lēmums par sarakstu (96. p.)">
      <input value={f.lnaAtsauce || ""} onChange={(e) => setF({ ...f, lnaAtsauce: e.target.value })} placeholder="LNA lēmuma atsauce" className="w-full text-sm border rounded px-2 py-1" />
      <div className="flex gap-2"><button onClick={() => resume({ lnaLemums: "Apstiprinats", lnaAtsauce: f.lnaAtsauce })} className="px-3 py-1 bg-emerald-600 text-white rounded">LNA apstiprināja</button>
        <button onClick={() => resume({ lnaLemums: "Noraidits", lnaAtsauce: f.lnaAtsauce })} className="px-3 py-1 border rounded">LNA noraidīja</button></div></TaskBox>}
    <details className="text-xs text-gray-500"><summary className="cursor-pointer">Vēsture ({l.history.length})</summary>
      {l.history.map((h, i) => <div key={i}>{String(h.kad).slice(0, 16).replace("T", " ")} · {h.darbiba} · {h.kas}</div>)}</details>
  </div>);
}

function Lists({ api, notify }) {
  const [list, setList] = useState([]); const [sel, setSel] = useState(null);
  const load = async () => { try { setList(await api("/archive/lists")); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); }, []);
  const start = async () => { try { const r = await api("/archive/lists/process/start", { method: "POST" });
    notify(r.gaida ? `Saraksts sagatavots — gaida: ${r.gaida}` : `Process: ${r.stavoklis}`); load(); } catch (e) { notify(e.message, "error"); } };
  return (<div className="grid grid-cols-12 gap-4">
    <div className="col-span-4 space-y-3">
      <button onClick={start} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded" title="Process p5-aprakstisana">+ Sagatavot uzskaites sarakstu (process)</button>
      <p className="text-xs text-gray-500">Sarakstā iekļauj izvērtētās lietas aprakstīšanai, grupējot pēc termiņa un nesēja (MK 282 84. p.). Uzskaites kodus piešķir pēc LNA apstiprinājuma.</p>
      <div className="bg-white border rounded-lg divide-y">{list.map((x) => <button key={x.id} onClick={() => setSel(x.id)} className={`w-full text-left px-3 py-2 ${sel === x.id ? "bg-sky-50" : "hover:bg-gray-50"}`}>
        <div className="flex justify-between"><span className="text-sm font-medium">Nr. {x.number}</span><span className="text-xs">{x.status_lv}</span></div>
        <div className="text-xs text-gray-500">{x.vienibas} vienības</div></button>)}
        {!list.length && <div className="p-4 text-sm text-gray-400">Sarakstu vēl nav.</div>}</div>
    </div>
    <div className="col-span-8">{sel ? <ListDetail api={api} notify={notify} id={sel} onChanged={load} /> : null}</div>
  </div>);
}

function TransferDetail({ api, notify, id, onChanged }) {
  const [p, setP] = useState(null); const [f, setF] = useState({}); const [confirm, setConfirm] = useState(false);
  const load = async () => { try { setP(await api(`/archive/transfers/${id}`)); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); setF({}); setConfirm(false); }, [id]);
  if (!p) return null;
  const s = p.sesija; const waiting = s?.state === "suspended" ? s.waiting_for : null;
  const resume = async (output) => { try { const r = await api(`/archive/sessions/${s.session_id}/resume`, { method: "POST", body: JSON.stringify({ output }) });
    notify(`Process: ${r.stavoklis}${r.gaida ? " — gaida " + r.gaida : ""}`); load(); onChanged(); } catch (e) { notify(e.message, "error"); } };
  const rep = p.report || {};
  return (<div className="bg-white border rounded-lg p-4 space-y-3 text-sm">
    <div className="flex items-center justify-between"><div className="font-semibold font-mono text-sm">{p.package_name}</div><span className="text-xs px-2 py-0.5 rounded-full bg-gray-100">{p.status_lv}</span></div>
    <div className="text-xs text-gray-500">{p.case_ids.length} lietas · {Math.round((p.size_bytes || 0) / 1024)} KB · SHA-256 <span className="font-mono">{(p.sha256 || "").slice(0, 16)}…</span></div>
    <div className="flex gap-2"><button onClick={() => download(api, notify, `/archive/transfers/${id}/package.zip`, `${p.package_name}.zip`)} className="text-xs px-3 py-1 border rounded">Pakotne ZIP</button>
      {p.act_key && <button onClick={() => download(api, notify, `/archive/transfers/${id}/act.xml`, `nodosanas-akts-${id}.xml`)} className="text-xs px-3 py-1 border rounded">Nodošanas akts XML</button>}</div>
    {(rep.kludas || []).length > 0 && <div className="text-xs text-red-800 bg-red-50 border border-red-200 rounded p-2"><div className="font-medium">Kļūdas ({rep.kludas.length})</div>{rep.kludas.slice(0, 20).map((k, i) => <div key={i}>{k}</div>)}</div>}
    {(rep.bridinajumi || []).length > 0 && <details className="text-xs text-amber-800"><summary className="cursor-pointer">Brīdinājumi ({rep.bridinajumi.length})</summary>{rep.bridinajumi.map((k, i) => <div key={i}>{k}</div>)}</details>}
    {waiting === "Fix" && <TaskBox title="Novērst kļūdas"><button onClick={() => resume({})} className="px-3 py-1 border rounded">Veidot pakotni vēlreiz</button></TaskBox>}
    {waiting === "Approve" && <TaskBox title="Atbildīgā persona apstiprina nodošanu">
      <label className="flex items-center gap-2"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />Pakotne pārbaudīta, apstiprinu nodošanu LNA</label>
      <button disabled={!confirm} onClick={() => resume({ apstiprinu: true })} className="px-3 py-1 bg-emerald-600 text-white rounded disabled:opacity-40">Apstiprināt un nodot</button></TaskBox>}
    {waiting === "AwaitLNA" && <TaskBox title="LNA pieņemšanas rezultāts">
      <div className="text-xs text-gray-500">Ar LNA savienojumu pakotne tiek augšupielādēta LNA S3 ievades krātuvē un rezultāts atgriežas automātiski; citādi to reģistrē šeit.</div>
      <input value={f.lnaAtsauce || ""} onChange={(e) => setF({ ...f, lnaAtsauce: e.target.value })} placeholder="LNA pieņemšanas akta atsauce" className="w-full text-sm border rounded px-2 py-1" />
      <input value={f.piezimes || ""} onChange={(e) => setF({ ...f, piezimes: e.target.value })} placeholder="LNA atbildīgā persona / piezīmes" className="w-full text-sm border rounded px-2 py-1" />
      <div className="flex gap-2"><button onClick={() => resume({ lnaLemums: "Pienemts", ...f })} className="px-3 py-1 bg-emerald-600 text-white rounded">LNA pieņēma</button>
        <button onClick={() => resume({ lnaLemums: "Noraidits", ...f })} className="px-3 py-1 border rounded">LNA noraidīja</button></div></TaskBox>}
    <details className="text-xs text-gray-500"><summary className="cursor-pointer">Vēsture ({p.history.length})</summary>
      {p.history.map((h, i) => <div key={i}>{String(h.kad).slice(0, 16).replace("T", " ")} · {h.darbiba} · {h.kas}</div>)}</details>
  </div>);
}

function Transfers({ api, notify }) {
  const [list, setList] = useState([]); const [sel, setSel] = useState(null); const [plan, setPlan] = useState(null);
  const load = async () => { try { setList(await api("/archive/transfers")); } catch (e) { notify(e.message, "error"); } };
  useEffect(() => { load(); }, []);
  const start = async () => { try { const r = await api("/archive/transfers/process/start", { method: "POST", body: "{}" });
    if (r.gaida === "AgreePlan") setPlan({ sid: r.sesija, planaDatums: "", planaAtsauce: "" });
    notify(r.gaida ? `Process gaida: ${r.gaida}` : `Process: ${r.stavoklis}${r.kluda ? " — " + r.kluda : ""}`); load(); } catch (e) { notify(e.message, "error"); } };
  const agree = async () => { try { const r = await api(`/archive/sessions/${plan.sid}/resume`, { method: "POST", body: JSON.stringify({ output: plan }) });
    setPlan(null); notify(r.gaida ? `Pakotne veidota — gaida: ${r.gaida}` : `Process: ${r.stavoklis}`); load(); } catch (e) { notify(e.message, "error"); } };
  return (<div className="grid grid-cols-12 gap-4">
    <div className="col-span-4 space-y-3">
      <button onClick={start} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded" title="Process p6-nodosana-lna">+ Sagatavot nodošanu LNA (process)</button>
      <p className="text-xs text-gray-500">OPEX/EAD3 pakotne no LNA apstiprināta pastāvīgi glabājamo lietu saraksta; pārbaude ar standarta rīku; biroja datnēm PDF/A atveidojums.</p>
      {plan && <TaskBox title="Gada vienošanās ar LNA (174. p.)">
        <input type="date" value={plan.planaDatums} onChange={(e) => setPlan({ ...plan, planaDatums: e.target.value })} className="text-sm border rounded px-2 py-1" />
        <input value={plan.planaAtsauce} onChange={(e) => setPlan({ ...plan, planaAtsauce: e.target.value })} placeholder="Vienošanās atsauce" className="w-full text-sm border rounded px-2 py-1" />
        <button onClick={agree} className="px-3 py-1 bg-emerald-600 text-white rounded">Saglabāt un turpināt</button></TaskBox>}
      <div className="bg-white border rounded-lg divide-y">{list.map((x) => <button key={x.id} onClick={() => setSel(x.id)} className={`w-full text-left px-3 py-2 ${sel === x.id ? "bg-sky-50" : "hover:bg-gray-50"}`}>
        <div className="text-xs font-mono truncate">{x.package_name}</div><div className="text-xs text-gray-500">{x.status_lv} · {x.lietas} lietas</div></button>)}
        {!list.length && <div className="p-4 text-sm text-gray-400">Nodošanu vēl nav.</div>}</div>
    </div>
    <div className="col-span-8">{sel ? <TransferDetail api={api} notify={notify} id={sel} onChanged={load} /> : null}</div>
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
  const [tab, setTab] = useState("lietas");
  const tabs = [["lietas", "Lietas"], ["iznicinasana", "Iznīcināšana"], ["aprakstisana", "Aprakstīšana"], ["nodosana", "Nodošana LNA"], ["shema", "Klasifikācijas shēma"], ["iestatijumi", "Iestatījumi"], ["partijas", "Vecā eksporta partija"]];
  return (
    <div>
      <h2 className="text-xl font-bold">Arhīvs</h2>
      <p className="text-sm text-gray-500 mb-4">Dokumentu dzīves cikls līdz iznīcināšanai vai nodošanai LNA — MK 07.05.2024. noteikumi Nr. 282.</p>
      <div className="flex gap-1 border-b mb-4">{tabs.map(([k, l]) =>
        <button key={k} onClick={() => setTab(k)} className={`text-sm px-4 py-2 -mb-px border-b-2 ${tab === k ? "border-emerald-600 text-emerald-700 font-medium" : "border-transparent text-gray-500"}`}>{l}</button>)}</div>
      {tab === "lietas" && <Cases api={api} notify={notify} />}
      {tab === "iznicinasana" && <Acts api={api} notify={notify} />}
      {tab === "aprakstisana" && <Lists api={api} notify={notify} />}
      {tab === "nodosana" && <Transfers api={api} notify={notify} />}
      {tab === "shema" && <Schemes api={api} notify={notify} />}
      {tab === "iestatijumi" && <Settings api={api} notify={notify} />}
      {tab === "partijas" && <LegacyBatches api={api} notify={notify} />}
    </div>);
}
