// Klasifikatori: the classifiers this DVS actually works with — every ProcessGit
// XML an installed process names in its mappings — read live from ProcessGit.
// Below it, the local classification entries kept in the DVS database.

import { useEffect, useMemo, useState } from "react";
import Icon from "./Icon.jsx";

async function api(path) {
  const token = localStorage.getItem("opendms_token") || "";
  const r = await fetch("/api" + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const j = await r.json(); msg = j.detail || msg; } catch { /* keep status */ }
    throw new Error(msg);
  }
  return r.json();
}

const KIND = { klasifikators: "Tēmu klasifikators", strukturvienibas: "Organizācijas reģistrs", cits: "Cits" };
const LEVEL = { Kategorija: "Kategorija", Apakskategorija: "Apakškategorija", Tema: "Tēma" };

function Pill({ children, cls = "bg-gray-100 text-gray-700" }) {
  return <span className={`text-[11px] px-1.5 py-0.5 rounded font-medium whitespace-nowrap ${cls}`}>{children}</span>;
}

function CodesView({ c }) {
  const [q, setQ] = useState("");
  const [joma, setJoma] = useState("");
  const [onlySel, setOnlySel] = useState(false);
  const ev = useMemo(() => Object.fromEntries((c.eurovoc || []).map(r => [String(r.kods), r])), [c.eurovoc]);
  const jomas = useMemo(() => [...new Map(c.codes.map(x => [x.joma, x.jomasNosaukums])).entries()], [c.codes]);
  const needle = q.trim().toLowerCase();
  const rows = c.codes.filter(x => (!joma || x.joma === joma) && (!onlySel || x.izvelams)
    && (!needle || x.kods.toLowerCase().startsWith(needle) || x.cels.toLowerCase().includes(needle)));
  const depth = (k) => (k.match(/\./g) || []).length;
  return (
    <div>
      <div className="flex gap-2 mb-2 text-sm">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Meklēt kodu vai nosaukumu…" className="px-3 py-1.5 border rounded-md w-64" />
        <select value={joma} onChange={e => setJoma(e.target.value)} className="px-2 py-1.5 border rounded-md">
          <option value="">Visas jomas</option>
          {jomas.map(([k, n]) => <option key={k} value={k}>{k} — {n}</option>)}
        </select>
        <label className="flex items-center gap-1 text-xs text-gray-600">
          <input type="checkbox" checked={onlySel} onChange={e => setOnlySel(e.target.checked)} /> tikai izvēlamie
        </label>
        <span className="text-xs text-gray-500 self-center">{rows.length} no {c.codes.length}</span>
      </div>
      <div className="border rounded-md overflow-auto max-h-[55vh]">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 sticky top-0 text-xs text-gray-500"><tr>
            <th className="px-3 py-2 text-left">Kods</th><th className="px-3 py-2 text-left">Nosaukums</th>
            <th className="px-3 py-2 text-left">Līmenis</th><th className="px-3 py-2 text-left">Joma</th>
            <th className="px-3 py-2 text-left">EuroVoc</th><th className="px-3 py-2 text-left">Izvēlams</th>
          </tr></thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map(x => {
              const m = x.limenis === "Kategorija" ? ev[x.kods] : null;
              return (
                <tr key={x.kods} className={x.limenis === "Kategorija" ? "bg-gray-50/60" : ""}>
                  <td className="px-3 py-1.5 font-mono whitespace-nowrap">{x.kods}</td>
                  <td className="px-3 py-1.5" style={{ paddingLeft: 12 + depth(x.kods) * 16 }}>
                    <span className={x.limenis === "Kategorija" ? "font-medium" : ""}>{x.nosaukums}</span></td>
                  <td className="px-3 py-1.5 text-xs text-gray-500">{LEVEL[x.limenis] || x.limenis}</td>
                  <td className="px-3 py-1.5 text-xs text-gray-500" title={x.jomasNosaukums}>{x.joma}</td>
                  <td className="px-3 py-1.5 text-xs">{m ? <span title={`${m.atbilstiba || ""} · ${m.statuss || ""}`}>{m.eurovoc} {m.eurovoc_nosaukums}</span> : ""}</td>
                  <td className="px-3 py-1.5 text-xs">{x.izvelams ? "jā" : <span className="text-gray-400">nē</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {c.eurovoc && <div className="text-xs text-gray-500 mt-2">EuroVoc kartējums: <code>{c.repo}/kartejumi/eurovoc.csv</code> ({c.eurovoc.length} kategorijas). Statuss pēc kartējuma datnes.</div>}
    </div>
  );
}

function UnitsView({ c }) {
  return (
    <div className="border rounded-md overflow-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-xs text-gray-500"><tr>
          <th className="px-3 py-2 text-left">ID</th><th className="px-3 py-2 text-left">Nosaukums</th><th className="px-3 py-2 text-left">Veids</th>
        </tr></thead>
        <tbody className="divide-y divide-gray-100">
          {c.units.map(u => (
            <tr key={u.id}><td className="px-3 py-1.5 font-mono">{u.id}</td><td className="px-3 py-1.5">{u.nosaukums}</td>
              <td className="px-3 py-1.5 text-xs text-gray-500">{u.veids}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ActiveClassifiers({ notify }) {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  const load = () => api("/uapf/classifiers").then(d => {
    setData(d.classifiers);
    if (!open && d.classifiers.length) setOpen(d.classifiers[0].ref);
  }).catch(e => notify?.(e.message, "error"));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="mb-8">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Klasifikatori</h2>
          <p className="text-sm text-gray-500">Klasifikatori, ko izmanto šīs DVS procesi. Nolasīti no ProcessGit; mainās tikai tur.</p>
        </div>
        <button onClick={load} className="text-sm px-3 py-1.5 bg-white border rounded-md text-gray-600">Atjaunot</button>
      </div>
      {!data && <div className="text-sm text-gray-500">Ielādē…</div>}
      {data && !data.length && <div className="text-sm text-gray-500 bg-white border rounded-lg p-6">Neviens uzstādītais process neatsaucas uz klasifikatoru.</div>}
      <div className="space-y-3">
        {(data || []).map(c => (
          <div key={c.ref} className="bg-white border rounded-lg">
            <button onClick={() => setOpen(open === c.ref ? null : c.ref)} className="w-full text-left px-4 py-3 flex items-start gap-3">
              <Icon name="tag" size={18} className={c.active ? "text-emerald-600 mt-0.5" : "text-gray-400 mt-0.5"} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-gray-900">{KIND[c.kind] || c.root || "Klasifikators"}</span>
                  <code className="text-xs text-gray-500">{c.ref}</code>
                  {c.active ? <Pill cls="bg-green-100 text-green-800">aktīvs</Pill> : <Pill>neaktīvs</Pill>}
                  {c.version && <Pill>versija {c.version}</Pill>}
                  {c.revision && <Pill>revīzija {c.revision.slice(0, 7)}</Pill>}
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {c.kind === "klasifikators" && `${c.codes.length} kodi · ${c.codes.filter(x => x.izvelams).length} izvēlami · `}
                  {c.kind === "strukturvienibas" && `${c.units.length} struktūrvienības · iestāde ${c.institution || "—"} · `}
                  vārdtelpa <code>{c.namespace || "—"}</code>
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  Izmanto: {c.packages.map(p => `${p.id} ${p.version || ""}${p.active ? "" : " (nav aktīva trigera)"}`).join("; ")}
                  {c.steps.length > 0 && <> · soļi: {c.steps.join(", ")}</>}
                </div>
                {c.error && <div className="text-xs text-red-600 mt-1">Neizdevās nolasīt: {c.error}</div>}
              </div>
              <a href={c.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="text-xs text-emerald-700 hover:underline whitespace-nowrap">ProcessGit ↗</a>
            </button>
            {open === c.ref && !c.error && (
              <div className="px-4 pb-4">
                {c.kind === "klasifikators" && <CodesView c={c} />}
                {c.kind === "strukturvienibas" && <UnitsView c={c} />}
                {c.kind === "cits" && <div className="text-sm text-gray-500">XML ar saknes elementu {c.root}; skatīt ProcessGit.</div>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
