// Vīzas, iepazīšanās atzīmes, rezolūcijas (standarts 08, 8.2.). Ieraksti ir nemaināmi; labojums = jauns ieraksts, kas aizstāj iepriekšējo.
import { useEffect, useState } from "react";
import { call } from "./ArchiveCard.jsx";

const VIZA = { Saskanots: "Saskaņots", SaskanotsArIebildumiem: "Saskaņots ar iebildumiem", Nesaskanots: "Nesaskaņots" };
const fmt = (d) => (d ? String(d).slice(0, 16).replace("T", " ") : "");
const who = (p) => [p?.vardsUzvards, p?.amats].filter(Boolean).join(", ");

function Row({ m, children }) {
  return <div className={`text-xs py-1 ${m.aizstats ? "line-through text-gray-400" : ""}`}><span className="text-gray-500">{fmt(m.datums)}</span> · {who(m.persona)} {children}</div>;
}

export default function MarksCard({ doc, notify }) {
  const [m, setM] = useState(null); const [form, setForm] = useState(null); const [people, setPeople] = useState([]);
  const load = async () => { try { setM(await call(`/archive/documents/${doc.id}/marks`)); } catch { setM(null); } };
  useEffect(() => { if (doc?.id) load(); }, [doc?.id]);
  useEffect(() => { if (form?.k === "res" && !people.length) call("/archive/people").then(setPeople).catch(() => {}); }, [form?.k]);
  if (!m) return null;
  const send = async (path, body, msg) => {
    try { await call(`/archive/documents/${doc.id}/${path}`, { method: "POST", body: JSON.stringify(body) }); notify(msg); setForm(null); load(); }
    catch (e) { notify(e.message, "error"); } };
  const f = form || {};
  const set = (k, v) => setForm({ ...f, [k]: v });
  const task = f.uzdevumi?.[0] || { atbildigie: [], apraksts: "", termins: "" };
  const setTask = (k, v) => set("uzdevumi", [{ ...task, [k]: v }]);
  const total = m.vizas.length + m.iepazisanas.length + m.rezolucijas.length;
  return (<div className="border rounded p-3 text-sm bg-white space-y-2">
    <div className="flex items-center justify-between">
      <span className="font-medium">Vīzas, atzīmes, rezolūcijas{total ? ` (${total})` : ""}</span>
      <div className="flex gap-1">
        <button onClick={() => setForm({ k: "visa", rezultats: "Saskanots" })} className="text-xs px-2 py-1 border rounded">Vizēt</button>
        <button onClick={() => setForm({ k: "ack" })} className="text-xs px-2 py-1 border rounded">Atzīmēt iepazīšanos</button>
        <button onClick={() => setForm({ k: "res" })} className="text-xs px-2 py-1 border rounded">Dot rezolūciju</button>
      </div>
    </div>
    {form && <div className="bg-gray-50 rounded p-2 space-y-2">
      {f.k === "visa" && <select value={f.rezultats} onChange={(e) => set("rezultats", e.target.value)} className="text-sm border rounded px-2 py-1">
        {Object.entries(VIZA).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>}
      {f.k === "res" && <div className="space-y-2">
        <select multiple value={task.atbildigie.map(String)} onChange={(e) => setTask("atbildigie", [...e.target.selectedOptions].map((o) => parseInt(o.value)))}
          className="w-full text-sm border rounded px-2 py-1 h-24">
          {people.map((p) => <option key={p.id} value={p.id}>{p.full_name}{p.department ? ` — ${p.department}` : ""}</option>)}</select>
        <input value={task.apraksts} onChange={(e) => setTask("apraksts", e.target.value)} placeholder="Uzdevums (piem., sagatavot atbildi)" className="w-full text-sm border rounded px-2 py-1" />
        <label className="text-xs text-gray-500">Izpildes termiņš <input type="date" value={task.termins} onChange={(e) => setTask("termins", e.target.value)} className="text-sm border rounded px-2 py-1" /></label>
      </div>}
      <textarea value={f.piezimes || ""} onChange={(e) => set("piezimes", e.target.value)} placeholder={f.k === "visa" && f.rezultats !== "Saskanots" ? "Iebildumi (obligāti)" : "Piezīmes"} rows={2} className="w-full text-sm border rounded px-2 py-1" />
      <input value={f.amats || ""} onChange={(e) => set("amats", e.target.value)} placeholder="Amats (ja nav norādīts lietotāja profilā)" className="w-full text-sm border rounded px-2 py-1" />
      <div className="flex gap-2">
        <button onClick={() => {
          const base = { piezimes: f.piezimes || null, amats: f.amats || null };
          if (f.k === "visa") send("visa", { ...base, rezultats: f.rezultats, aizstaj: f.aizstaj || null }, "Vīza pievienota");
          if (f.k === "ack") send("acknowledge", base, "Iepazīšanās atzīmēta");
          if (f.k === "res") send("resolution", { ...base, aizstaj: f.aizstaj || null, uzdevumi: [{ ...task, termins: task.termins || null }] }, "Rezolūcija pievienota");
        }} className="text-sm px-3 py-1 bg-emerald-600 text-white rounded">Saglabāt</button>
        <button onClick={() => setForm(null)} className="text-sm px-3 py-1 border rounded">Atcelt</button>
        {f.aizstaj && <span className="text-xs text-gray-500 self-center">aizstās ierakstu #{f.aizstaj}</span>}
      </div>
    </div>}
    {m.vizas.map((v) => <Row key={v.id} m={v}>· <b>{VIZA[v.rezultats]}</b>{v.piezimes ? ` — ${v.piezimes}` : ""}
      {!v.aizstats && <button onClick={() => setForm({ k: "visa", rezultats: v.rezultats, aizstaj: v.id })} className="ml-2 text-sky-700">labot</button>}</Row>)}
    {m.iepazisanas.map((v) => <Row key={v.id} m={v}>· iepazinās{v.piezimes ? ` — ${v.piezimes}` : ""}</Row>)}
    {m.rezolucijas.map((v) => <Row key={v.id} m={v}>· rezolūcija{v.piezimes ? ` (${v.piezimes})` : ""}:
      {v.uzdevumi.map((t, i) => <div key={i} className="ml-4">{t.apraksts} → {t.atbildigie.map((p) => p.vardsUzvards).join(", ")}{t.termins ? `, līdz ${t.termins}` : ""}</div>)}
      {!v.aizstats && <button onClick={() => setForm({ k: "res", aizstaj: v.id })} className="ml-4 text-sky-700">labot</button>}</Row>)}
  </div>);
}
