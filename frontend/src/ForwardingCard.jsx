// Pārsūtīšana citai iestādei e-adresē (DIV) un saņemtā sūtījuma izcelsme.
// Pieprasījumu izpilda process vdvc/dokumenta-parsutisana (trigeris document.forwarding).

import { useEffect, useState } from "react";

const REASONS = [["piekritiba", "Pēc piekritības"], ["informacijai", "Informācijai"], ["viedoklim", "Viedokļa sniegšanai"]];
const STATUS = {
  pieprasits: ["Pieprasīts", "bg-gray-100 text-gray-700"],
  apstrade: ["Process sagatavo sūtījumu", "bg-sky-100 text-sky-800"],
  nosutits: ["Nosūtīts e-adresē", "bg-sky-100 text-sky-800"],
  sanemts: ["Adresāts saņēma", "bg-emerald-100 text-emerald-800"],
  apstiprinats: ["Adresāts apstiprināja saņemšanu", "bg-emerald-100 text-emerald-800"],
  kluda: ["Kļūda", "bg-red-100 text-red-800"],
};

async function call(path, opts = {}) {
  const token = localStorage.getItem("opendms_token") || "";
  const r = await fetch("/api" + path, { ...opts, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`);
  return d;
}

function Row({ k, children }) {
  return <><dt className="text-gray-500">{k}</dt><dd className="break-all">{children}</dd></>;
}

export default function ForwardingCard({ doc, files, notify, onAction }) {
  const p = doc?.metadata?.parsutisana;
  const got = doc?.metadata?.ievade?.div;
  const [open, setOpen] = useState(false);
  const [div, setDiv] = useState(null);
  const [q, setQ] = useState("");
  const [list, setList] = useState([]);
  const [to, setTo] = useState(null);
  const [reason, setReason] = useState("piekritiba");
  const [note, setNote] = useState("");
  const [sel, setSel] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => { call("/div/statuss").then(setDiv).catch(() => setDiv({ konfigurets: false })); }, []);
  useEffect(() => { setSel((files || []).map(f => f.id)); }, [files]);
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => call(`/div/adreses?q=${encodeURIComponent(q)}`).then(d => setList(d.adreses)).catch(e => notify?.(e.message, "error")), 250);
    return () => clearTimeout(t);
  }, [q, open]); // eslint-disable-line react-hooks/exhaustive-deps
  const moving = p && ["pieprasits", "apstrade", "nosutits", "sanemts"].includes(p.statuss);
  useEffect(() => {
    if (!moving) return;
    const t = setInterval(() => onAction?.(), 5000);
    return () => clearInterval(t);
  }, [moving]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    setBusy(true);
    try {
      await call(`/documents/${doc.id}/parsutit`, { method: "POST", body: JSON.stringify({ adresats: to["E-Address"], iemesls: reason, pavadteksts: note, datnes: sel }) });
      notify?.("Pārsūtīšana uzsākta");
      setOpen(false); onAction?.();
    } catch (e) { notify?.(e.message, "error"); } finally { setBusy(false); }
  };

  if (!div?.konfigurets && !p && !got) return null;
  const [label, cls] = STATUS[p?.statuss] || [p?.statuss, "bg-gray-100 text-gray-700"];

  return (
    <div className="border rounded-lg p-3 bg-white text-sm">
      <div className="flex items-center justify-between mb-2">
        <div className="font-semibold text-gray-900">E-adrese</div>
        {div?.konfigurets && !moving && !open && (
          <button onClick={() => setOpen(true)} className="text-xs px-3 py-1.5 bg-emerald-700 text-white rounded-md">Pārsūtīt citai iestādei</button>
        )}
      </div>

      {got && (
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5 text-xs mb-2">
          <Row k="Saņemts no">{got.sutitajaNosaukums} ({got.sutitajs})</Row>
          <Row k="Sūtījuma veids">{got.sutijumaVeids}{got.izcelsme?.IemeslsTeksts ? ` — ${got.izcelsme.IemeslsTeksts}` : ""}</Row>
          <Row k="DIV atsauce">{got.serverRefNumber}</Row>
          <Row k="Sūtītāja reģ. Nr.">{got.izcelsme?.SutitajaRegNr || got.sutitajaAtsauce}</Row>
          {got.izcelsme?.DokumentaID && <Row k="Dokumenta ID">{got.izcelsme.DokumentaID}</Row>}
        </dl>
      )}

      {p && (
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5 text-xs">
          <Row k="Statuss"><span className={`px-1.5 py-0.5 rounded ${cls}`}>{label}</span></Row>
          <Row k="Adresāts">{p.adresataNosaukums} ({p.adresats})</Row>
          <Row k="Iemesls">{(REASONS.find(r => r[0] === p.iemesls) || [])[1] || p.iemesls}</Row>
          {p.serverRefNumber && <Row k="DIV atsauce">{p.serverRefNumber}</Row>}
          {p.nosutitasDatnes && <Row k="Datnes">{p.nosutitasDatnes.join(", ")}</Row>}
          {p.registraNotikums !== undefined && <Row k="Reģistrā">{p.registraNotikums ? "nosūtīšana reģistrēta (DocumentSent)" : "nav reģistrēta"}</Row>}
          {p.iesniedzejsInformets && <Row k="Iesniedzējs">informēts {new Date(p.iesniedzejsInformets).toLocaleString("lv-LV")}</Row>}
          {p.kluda && <Row k="Kļūda"><span className="text-red-700">{p.kluda}</span></Row>}
        </dl>
      )}

      {open && (
        <div className="mt-2 space-y-3">
          <div>
            <div className="text-xs font-medium text-gray-700 mb-1">Adresāts (e-adrešu katalogs)</div>
            {to ? (
              <div className="flex items-center gap-2"><span className="flex-1">{to.Name} <span className="text-gray-500 text-xs">{to["E-Address"]}</span></span>
                <button className="text-xs underline text-gray-500" onClick={() => setTo(null)}>mainīt</button></div>
            ) : (
              <>
                <input className="w-full px-3 py-1.5 border rounded-md" placeholder="Meklēt iestādi…" value={q} onChange={e => setQ(e.target.value)} />
                <div className="border rounded-md mt-1 max-h-40 overflow-auto">
                  {list.map(a => (
                    <button key={a["E-Address"]} onClick={() => setTo(a)} className="block w-full text-left px-3 py-1.5 hover:bg-gray-50">
                      {a.Name} <span className="text-gray-500 text-xs">{a["E-Address"]}</span>
                    </button>
                  ))}
                  {!list.length && <div className="px-3 py-2 text-gray-500 text-xs">Nav atrasts.</div>}
                </div>
              </>
            )}
          </div>
          <div>
            <div className="text-xs font-medium text-gray-700 mb-1">Iemesls</div>
            <div className="flex gap-3">{REASONS.map(([v, l]) => (
              <label key={v} className="flex items-center gap-1"><input type="radio" checked={reason === v} onChange={() => setReason(v)} /> {l}</label>
            ))}</div>
          </div>
          <div>
            <div className="text-xs font-medium text-gray-700 mb-1">Pavadvēstule</div>
            <textarea rows={3} maxLength={2000} className="w-full px-3 py-1.5 border rounded-md" value={note} onChange={e => setNote(e.target.value)} />
          </div>
          <div>
            <div className="text-xs font-medium text-gray-700 mb-1">Datnes</div>
            {(files || []).map(f => (
              <label key={f.id} className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={sel.includes(f.id)} onChange={e => setSel(e.target.checked ? [...sel, f.id] : sel.filter(x => x !== f.id))} />
                {f.file_name}{f.is_primary ? " (galvenā)" : ""}
              </label>
            ))}
            <div className="text-[11px] text-gray-500 mt-1">Pievieno arī metadati.xml (dokumenta identitāte), ja to nosaka process.</div>
          </div>
          <div className="flex gap-2">
            <button disabled={!to || !sel.length || busy} onClick={submit} className="px-3 py-1.5 bg-emerald-700 text-white rounded-md text-xs disabled:opacity-50">{busy ? "Sūta…" : "Pārsūtīt"}</button>
            <button onClick={() => setOpen(false)} className="px-3 py-1.5 border rounded-md text-xs">Atcelt</button>
          </div>
        </div>
      )}
    </div>
  );
}
