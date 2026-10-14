// Datu glabātuve — kur šī DVS glabā datnes, metadatus un zināšanas.
// Aktīvā glabātuve (diskā vai S3) un S3 savienojums ar pārbaudi.
// Pārslēgšana uz S3 notiek pēc datu pārnešanas (atsevišķs solis).

import { useEffect, useState } from "react";

async function call(path, opts = {}) {
  const token = localStorage.getItem("opendms_token") || "";
  const r = await fetch("/api" + path, { ...opts, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(typeof d.detail === "string" ? d.detail : `Kļūda ${r.status}`), { status: r.status });
  return d;
}
const size = (n) => n == null ? "—" : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1073741824).toFixed(2)} GB`;

function TestResult({ r }) {
  if (!r) return null;
  return (
    <div className={`mt-3 border rounded-md p-3 text-sm ${r.ok ? "bg-emerald-50 border-emerald-200" : "bg-red-50 border-red-200"}`}>
      <div className="font-medium mb-1">{r.ok ? "Savienojums darbojas" : "Savienojums nedarbojas"}
        <span className="text-xs text-ink-500 font-normal ml-2">{r.endpoint} · {r.bucket}</span></div>
      <table className="text-xs w-full">
        <tbody>{(r.soli || []).map((s, i) => (
          <tr key={i}><td className="py-0.5 pr-3">{s.ok ? "✓" : "✗"} {s.solis}</td>
            <td className="text-ink-500 pr-3">{s.ok ? s.info : <span className="text-red-700">{s.kluda}</span>}</td>
            <td className="text-ink-400 text-right">{s.ms != null ? `${s.ms} ms` : ""}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function ExportResult({ r }) {
  if (!r) return null;
  const v = r.parbaude;
  const ok = !r.kludas?.length && !r.problemas?.length && (!v || !v.nesakrit?.length);
  return (
    <div className={`mt-3 border rounded-md p-3 text-sm ${ok ? "bg-emerald-50 border-emerald-200" : "bg-amber-50 border-amber-200"}`}>
      <div className="font-medium mb-1">{r["izmēģinājums"] ? "Pārnešanas izmēģinājums (nekas netika rakstīts)" : "Dati pārnesti uz spaini"}
        <span className="text-xs text-ink-500 font-normal ml-2">{r.spainis} · {r.ilgums_s} s</span></div>
      <div className="text-xs grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5">
        <span className="text-ink-500">Dokumenti</span><span>{r.dokumenti}</span>
        <span className="text-ink-500">Objekti</span><span>{r.objekti} · {size(r.baiti)}</span>
        <span className="text-ink-500">{r["izmēģinājums"] ? "Būtu jāraksta" : "Ierakstīti"}</span><span>{r.rakstiti} (nemainīti {r.nemainiti})</span>
        {v && <><span className="text-ink-500">Kontrolsummas</span><span>{v.sakrit} sakrīt{v.nesakrit?.length ? `, ${v.nesakrit.length} nesakrīt` : ""}</span></>}
      </div>
      {[...(r.kludas || []), ...(r.problemas || []), ...((v && v.nesakrit) || [])].slice(0, 20).map((x, i) =>
        <div key={i} className="text-xs text-red-700 font-mono break-all">{x}</div>)}
    </div>
  );
}

export default function StorageSettings({ notify }) {
  const [data, setData] = useState(null);
  const [denied, setDenied] = useState(false);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ endpoint: "", bucket: "", region: "us-east-1", accessKey: "", secretKey: "" });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [exp, setExp] = useState(null);

  const load = () => call("/storage/settings").then(d => {
    setData(d);
    setForm({ endpoint: d.s3.endpoint || "", bucket: d.s3.bucket || "", region: d.s3.region || "us-east-1", accessKey: d.s3.accessKey || "", secretKey: "" });
    setResult(d.s3.lastTest || null);
    setExp(e => e || d.s3.lastExport || null);
  }).catch(e => { if (e.status === 403) setDenied(true); else notify?.(e.message, "error"); });
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (denied || !data) return null;
  const a = data.aktiva, s3 = data.s3;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const test = async (unsaved) => {
    setBusy(true);
    try { setResult(await call("/storage/settings/s3/test", { method: "POST", body: unsaved ? JSON.stringify({ ...form, secretKey: form.secretKey || null }) : undefined })); }
    catch (e) { notify?.(e.message, "error"); } finally { setBusy(false); }
  };
  const runExport = async (dry) => {
    setBusy(true);
    try { setExp(await call(`/storage/settings/s3/eksports?izmeginajums=${dry}`, { method: "POST" })); if (!dry) notify?.("Dati pārnesti uz spaini"); }
    catch (e) { notify?.(e.message, "error"); } finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true);
    try { await call("/storage/settings/s3", { method: "PUT", body: JSON.stringify({ ...form, secretKey: form.secretKey || null }) }); notify?.("S3 savienojums saglabāts"); await load(); setOpen(false); }
    catch (e) { notify?.(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <div className="bg-white border rounded-lg p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold text-ink-900">Datu glabātuve</h2>
          <p className="text-xs text-ink-500">Kur šī DVS glabā datnes, metadatus, vēsturi un zināšanas.</p>
        </div>
        <span className="text-xs px-2 py-0.5 rounded bg-ink-100 text-ink-700">Aktīvā: {a.nosaukums}</span>
      </div>

      <div className="grid md:grid-cols-2 gap-4 mt-3 text-sm">
        <div className="border rounded-md p-3">
          <div className="font-medium mb-1">Diskā {a.backend === "local" && <span className="text-xs text-emerald-700 ml-1">● aktīvā</span>}</div>
          <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5 text-xs">
            <dt className="text-ink-500">Vieta</dt><dd className="font-mono">{a.backend === "local" ? a.vieta : "—"}</dd>
            <dt className="text-ink-500">Dokumenti</dt><dd>{a.dokumenti} · pakotnes {a.pakotnes}</dd>
            <dt className="text-ink-500">Datnes</dt><dd>{a.datnes} · {size(a.datnuApjoms)}</dd>
          </dl>
        </div>
        <div className="border rounded-md p-3">
          <div className="flex items-center justify-between">
            <div className="font-medium">S3 savienojums {a.backend === "s3" && <span className="text-xs text-emerald-700 ml-1">● aktīvā</span>}</div>
            {!open && <button className="text-xs underline text-ink-500" onClick={() => setOpen(true)}>Mainīt</button>}
          </div>
          {!open ? (
            <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5 text-xs mt-1">
              <dt className="text-ink-500">Adrese</dt><dd className="font-mono break-all">{s3.endpoint || "nav iestatīta"}</dd>
              <dt className="text-ink-500">Spainis</dt><dd className="font-mono">{s3.bucket || "—"}</dd>
              <dt className="text-ink-500">Piekļuves atslēga</dt><dd className="font-mono">{s3.accessKey || "—"}</dd>
              <dt className="text-ink-500">Slepenā atslēga</dt><dd>{s3.secretSet ? "iestatīta" : "nav"}</dd>
              <dt className="text-ink-500">Avots</dt><dd>{s3.source}</dd>
            </dl>
          ) : (
            <div className="space-y-2 mt-2 text-xs">
              {[["endpoint", "Adrese (S3 endpoint)", "http://10.20.30.160:8333"], ["bucket", "Spainis", "dvs-…"], ["region", "Reģions", "us-east-1"], ["accessKey", "Piekļuves atslēga", ""]].map(([k, l, ph]) => (
                <label key={k} className="block"><span className="text-ink-500">{l}</span>
                  <input className="w-full border rounded px-2 py-1 font-mono" value={form[k]} placeholder={ph} onChange={set(k)} /></label>
              ))}
              <label className="block"><span className="text-ink-500">Slepenā atslēga {s3.secretSet && "(tukšs — paturēt esošo)"}</span>
                <input type="password" autoComplete="new-password" className="w-full border rounded px-2 py-1 font-mono" value={form.secretKey} onChange={set("secretKey")} /></label>
              <div className="flex gap-2 pt-1">
                <button disabled={busy} onClick={() => test(true)} className="px-3 py-1.5 border rounded">Pārbaudīt</button>
                <button disabled={busy} onClick={save} className="px-3 py-1.5 bg-emerald-700 text-white rounded">Saglabāt</button>
                <button onClick={() => { setOpen(false); load(); }} className="px-3 py-1.5 text-ink-500">Atcelt</button>
              </div>
            </div>
          )}
          {!open && (
            <button disabled={busy || !s3.endpoint} onClick={() => test(false)} className="mt-2 text-xs px-3 py-1.5 border rounded disabled:opacity-50">
              {busy ? "Pārbauda…" : "Pārbaudīt savienojumu"}</button>
          )}
        </div>
      </div>
      <TestResult r={result} />
      {s3.endpoint && result?.ok && (
        <div className="mt-3 border rounded-md p-3 text-sm">
          <div className="font-medium">Pārnest datus uz spaini</div>
          <p className="text-xs text-ink-500">Visi dokumenti ar pakotnēm (metadati.xml, izsekosana.xml, kontrolsummas, datnes), DVS ieraksts (metadati, semantika, notikumi, procesi), ievades žurnāls un precedenti. Esošie dati diskā paliek; nemainītie objekti netiek rakstīti atkārtoti.</p>
          <div className="flex gap-2 mt-2">
            <button disabled={busy} onClick={() => runExport(true)} className="text-xs px-3 py-1.5 border rounded">Izmēģināt</button>
            <button disabled={busy} onClick={() => runExport(false)} className="text-xs px-3 py-1.5 bg-emerald-700 text-white rounded disabled:opacity-50">{busy ? "Notiek…" : "Pārnest"}</button>
          </div>
          <ExportResult r={exp} />
        </div>
      )}
      <p className="text-[11px] text-ink-400 mt-3">Pārslēgt aktīvo glabātuvi uz S3 varēs pēc pārnešanas un atjaunošanas pārbaudes.</p>
    </div>
  );
}
