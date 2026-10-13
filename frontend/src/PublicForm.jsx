// Publiskā tiešsaistes forma — /iesniegt/<kanāls>. Bez pieteikšanās.
// Iesniegums nonāk DVS caur to pašu ievadi kā e-pasts (POST /api/ievade/forma/<kanāls>).

import { useEffect, useState } from "react";

function Field({ label, children, hint }) {
  return (
    <label className="block mb-4">
      <span className="block text-sm font-medium text-gray-800 mb-1">{label}</span>
      {children}
      {hint && <span className="block text-xs text-gray-500 mt-1">{hint}</span>}
    </label>
  );
}

function Status({ token }) {
  const [st, setSt] = useState(null);
  useEffect(() => {
    let stop = false;
    const tick = () => fetch(`/api/ievade/statuss/${token}`).then(r => r.ok ? r.json() : null).then(d => {
      if (stop || !d) return;
      setSt(d);
      if (!d.nodotsRegistram) setTimeout(tick, 5000);
    }).catch(() => {});
    tick();
    return () => { stop = true; };
  }, [token]);
  if (!st) return <p className="text-sm text-gray-500">Ielādē statusu…</p>;
  return (
    <dl className="text-sm grid grid-cols-[auto,1fr] gap-x-4 gap-y-1">
      <dt className="text-gray-500">Reģistrācijas numurs</dt><dd className="font-mono">{st.registracijasNr}</dd>
      <dt className="text-gray-500">Dokumenta identifikators</dt><dd className="font-mono break-all">{st.dokumentaId || "tiek piešķirts…"}</dd>
      <dt className="text-gray-500">Centrālais reģistrs</dt>
      <dd>{st.nodotsRegistram && st.izsekosanasSaite
        ? <a className="text-emerald-700 underline" href={st.izsekosanasSaite} target="_blank" rel="noreferrer">sekot virzībai ({st.izsekosanasKods})</a>
        : "tiek nodots…"}</dd>
    </dl>
  );
}

export default function PublicForm({ channel }) {
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    fetch(`/api/ievade/forma/${channel}`).then(async r => {
      if (!r.ok) throw new Error("Forma nav pieejama.");
      setInfo(await r.json());
    }).catch(e => setErr(e.message));
  }, [channel]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await fetch(`/api/ievade/forma/${channel}`, { method: "POST", body: new FormData(e.target) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `Kļūda (${r.status})`);
      setDone(d);
    } catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-xl mx-auto bg-white border rounded-lg p-6">
        <div className="text-xs text-gray-500 mb-1">{info?.iestade}</div>
        <h1 className="text-xl font-bold text-gray-900 mb-1">{info?.nosaukums || "Iesniegums"}</h1>
        {info?.apraksts && <p className="text-sm text-gray-600 mb-4">{info.apraksts}</p>}
        {err && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3 mb-4">{err}</div>}

        {done ? (
          <div>
            <p className="text-sm text-gray-800 mb-4">Iesniegums saņemts un reģistrēts. Saglabājiet šo lapu vai reģistrācijas numuru.</p>
            <Status token={done.statusaKods} />
            {(done.edoc || []).map(e => (
              <p key={e.konteiners} className="text-xs text-gray-600 mt-3">
                eDoc {e.konteiners}: {e.paraksti ?? 0} paraksti; {e.integritate ? "datnes atbilst parakstiem" : "integritāte nav apstiprināta"}.
              </p>
            ))}
          </div>
        ) : info && (
          <form onSubmit={submit}>
            <Field label="Vārds, uzvārds vai nosaukums *"><input name="vards" required maxLength={200} className="w-full px-3 py-2 border rounded-md text-sm" /></Field>
            <Field label="E-pasts" hint="Uz to nosūtīsim reģistrācijas numuru."><input name="epasts" type="email" maxLength={200} className="w-full px-3 py-2 border rounded-md text-sm" /></Field>
            <Field label="Temats"><input name="temats" maxLength={300} className="w-full px-3 py-2 border rounded-md text-sm" /></Field>
            <Field label="Iesnieguma teksts"><textarea name="teksts" rows={7} className="w-full px-3 py-2 border rounded-md text-sm" /></Field>
            <Field label="Datnes" hint={`PDF, DOCX, eDoc u.c.; kopā līdz ${info.maxMb} MB. Parakstītu dokumentu pievienojiet kā .edoc.`}>
              <input name="datnes" type="file" multiple className="text-sm" />
            </Field>
            <input name="web" tabIndex={-1} autoComplete="off" className="hidden" aria-hidden="true" />
            <button disabled={busy} className="px-4 py-2 bg-emerald-700 text-white rounded-md text-sm disabled:opacity-50">
              {busy ? "Iesniedz…" : "Iesniegt"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
