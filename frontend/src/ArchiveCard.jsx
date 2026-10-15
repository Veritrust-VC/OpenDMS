// Arhivēšana dokumenta kartītē (UAPF P2): lieta no klasifikācijas shēmas, reģistrācijas minimums, datņu formāti, arhīva ID.
import { useEffect, useState } from "react";

const STATUSI = [["Visparpieejama", "Vispārpieejama"], ["IerobezotasPieejamibas", "Ierobežotas pieejamības"], ["DienestaVajadzibam", "Dienesta vajadzībām"]];
const RICIBA = { Saglabat: "saglabā", KonvertetPDFA: "slēdzot lietu → PDF/A", Noraidit: "neder" };

export async function call(path, opts = {}) {
  const token = localStorage.getItem("opendms_token") || "";
  const r = await fetch("/api" + path, { ...opts, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`);
  return d;
}

// Lietas izvēle jauna dokumenta formā: atvērtās šā gada lietas; obligāta, ja P2 ieslēgts.
export function CasePicker({ value, onChange }) {
  const [cases, setCases] = useState([]); const [required, setRequired] = useState(false);
  useEffect(() => { (async () => {
    try { const s = await call("/archive/settings"); setRequired(!!s.enforce_registration_minimum); } catch { /* nav tiesību vai nav iestatīts */ }
    try { setCases((await call(`/archive/cases?gads=${new Date().getFullYear()}&statuss=Atverta`)).filter((c) => c.scheme_entry_id)); } catch { setCases([]); }
  })(); }, []);
  if (!cases.length && !required) return null;
  return (<div>
    <select value={value || ""} onChange={(e) => onChange(e.target.value ? parseInt(e.target.value) : null)} className="w-full text-sm px-3 py-2 border rounded">
      <option value="">{required ? "— lieta (obligāta) —" : "— lieta (var izvēlēties vēlāk) —"}</option>
      {cases.map((c) => <option key={c.id} value={c.id}>{c.case_index} {c.case_name}</option>)}</select>
    {required && !cases.length && <div className="text-xs text-red-700 mt-1">Šim gadam nav atvērtu lietu — atveriet tās sadaļā Arhīvs → Lietas.</div>}
  </div>);
}

export default function ArchiveCard({ doc, notify }) {
  const [r, setR] = useState(null); const [open, setOpen] = useState(false);
  const [caseId, setCaseId] = useState(""); const [status, setStatus] = useState(""); const [basis, setBasis] = useState("");
  const load = async () => { try { setR(await call(`/archive/documents/${doc.id}/readiness`)); } catch { setR(null); } };
  useEffect(() => { if (doc?.id) load(); }, [doc?.id]);
  if (!r) return null;
  const prepare = async () => {
    try {
      const out = await call(`/archive/documents/${doc.id}/prepare`, { method: "POST", body: JSON.stringify({
        case_id: caseId ? parseInt(caseId) : null, info_status: status || null, access_basis: basis || null }) });
      setR(out); notify(out.gatavs ? "Dokuments sagatavots arhivēšanai" : `Vēl trūkst: ${out.trukumi.join("; ")}`, out.gatavs ? undefined : "error");
    } catch (e) { notify(e.message, "error"); }
  };
  const needCase = !r.lieta || r.lieta.statuss !== "Atverta";
  const needStatus = !r.parbaude.irStatuss || (r.parbaude.statuss !== "Visparpieejama" && !r.parbaude.irPamatojums);
  return (<div className={`border rounded p-3 text-sm ${r.gatavs ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
    <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between">
      <span className="font-medium">Arhivēšana</span>
      <span className="text-xs">{r.gatavs ? `gatavs · arhīva ID ${r.arhivaId?.slice(0, 8)}…` : `${r.trukumi.length} trūkumi`}
        {r.lieta ? ` · lieta ${r.lieta.indekss}/${r.lieta.gads}` : " · bez lietas"}</span>
    </button>
    {open && <div className="mt-2 space-y-2">
      {r.trukumi.length > 0 && <ul className="list-disc ml-5 text-amber-900">{r.trukumi.map((t) => <li key={t}>{t}</li>)}</ul>}
      {r.datnes.length > 0 && <div className="text-xs text-gray-600">{r.datnes.map((f) =>
        <div key={f.datne}>{f.derigs ? "✓" : "✗"} {f.datne} — {RICIBA[f.riciba]}</div>)}</div>}
      {r.arhivaId && <div className="text-xs font-mono break-all text-gray-600">Arhīva ID: {r.arhivaId}</div>}
      {!r.gatavs && <div className="space-y-2">
        {needCase && <select value={caseId} onChange={(e) => setCaseId(e.target.value)} className="w-full text-sm px-2 py-1.5 border rounded bg-white">
          <option value="">— lieta {r.lietuIeteikums?.gads} —</option>
          {(r.lietuIeteikums?.iespejas || []).map((c) => <option key={c.id} value={c.id}>{c.case_index} {c.case_name}{c.id === r.lietuIeteikums.ieteikta ? " (ieteikta)" : ""}</option>)}</select>}
        {needCase && !(r.lietuIeteikums?.iespejas || []).length && <div className="text-xs text-amber-900">Šim gadam nav atvērtu shēmas lietu (Arhīvs → Lietas).</div>}
        {needStatus && <div className="flex gap-2">
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="text-sm px-2 py-1.5 border rounded bg-white">
            <option value="">— informācijas statuss —</option>{STATUSI.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          {status && status !== "Visparpieejama" && <input value={basis} onChange={(e) => setBasis(e.target.value)} placeholder="Tiesiskais pamatojums" className="flex-1 text-sm px-2 py-1.5 border rounded" />}
        </div>}
        <button onClick={prepare} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded">Sagatavot arhivēšanai</button>
      </div>}
    </div>}
  </div>);
}
