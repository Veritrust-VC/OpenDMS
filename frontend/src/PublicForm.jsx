// Publiskā strukturētā iesnieguma veidlapa — /iesniegt/<kanāls>. Bez pieteikšanās.
// Veidlapas lauki ir datu shēmas lauki (tiesibsargs/iesnieguma-virzisana ievade/iesniegums-1.0.xsd).
// Serveris no tiem uzraksta shēmas XML un pārbauda ar XSD, noteikumiem un klasifikatoru —
// nekāda teksta atpazīšana vai MI pārveide.

import { useEffect, useMemo, useState } from "react";

const STEPS = ["Iesniedzējs", "Jautājums", "Iepriekšējie soļi", "Pielikumi", "Pārskats"];
const inputCls = "w-full px-3 py-2 border rounded-md text-sm";

function Field({ label, children, hint, req }) {
  return (
    <label className="block mb-3">
      <span className="block text-sm font-medium text-gray-800 mb-1">{label}{req && " *"}</span>
      {children}
      {hint && <span className="block text-xs text-gray-500 mt-1">{hint}</span>}
    </label>
  );
}

function Radio({ value, onChange, options }) {
  return (
    <div className="flex flex-wrap gap-3 text-sm">
      {options.map(([v, l]) => (
        <label key={v} className="flex items-center gap-1.5">
          <input type="radio" checked={value === v} onChange={() => onChange(v)} /> {l}
        </label>
      ))}
    </div>
  );
}

function Counter({ v, max }) {
  const n = (v || "").length;
  return <span className={`text-xs ${n > max ? "text-red-600" : "text-gray-400"}`}>{n}/{max}</span>;
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

const EMPTY = {
  Iesniedzejs: { PusesTips: "FiziskaPersona", Vards: "", Uzvards: "", Nosaukums: "", RegistracijasNr: "",
                 Kontakti: { Epasts: "", Talrunis: "", EAdrese: "", PastaAdrese: "" }, AtbildesVeids: "EPasts" },
  Parstavis: { ParstavamaPersona: { PusesTips: "FiziskaPersona", Vards: "", Uzvards: "", Nosaukums: "", RegistracijasNr: "" },
               Pamats: "Pilnvara", PamatsApraksts: "" },
  Jautajums: { Joma: "", Kods: "", Iestade: [{ Nosaukums: "" }], laiks: "menesis", NotikumaDatums: "", NotikumaMenesis: "",
               Apraksts: "", Lugums: "" },
  IeprieksejieSoli: { VersiesIestade: false, VersanasDatums: "", AtbildeSanemta: false, AtbildesKopsavilkums: "", Tiesvediba: "Ne" },
  Apliecinajumi: { InformacijaPatiesa: false, IepaziniesArDatuApstradi: false },
};

function PersonFields({ p, set }) {
  return (
    <>
      <Field label="Veids" req>
        <Radio value={p.PusesTips} onChange={v => set({ PusesTips: v })}
          options={[["FiziskaPersona", "Fiziska persona"], ["JuridiskaPersona", "Juridiska persona"]]} />
      </Field>
      {p.PusesTips === "FiziskaPersona" ? (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Vārds" req><input className={inputCls} maxLength={200} value={p.Vards} onChange={e => set({ Vards: e.target.value })} /></Field>
          <Field label="Uzvārds" req><input className={inputCls} maxLength={200} value={p.Uzvards} onChange={e => set({ Uzvards: e.target.value })} /></Field>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Nosaukums" req><input className={inputCls} maxLength={200} value={p.Nosaukums} onChange={e => set({ Nosaukums: e.target.value })} /></Field>
          <Field label="Reģistrācijas numurs" req><input className={inputCls} maxLength={11} value={p.RegistracijasNr} onChange={e => set({ RegistracijasNr: e.target.value.replace(/\D/g, "") })} /></Field>
        </div>
      )}
    </>
  );
}

// Only filled values go to the server, in schema field names.
function payload(f, citas) {
  const clean = (o) => {
    if (Array.isArray(o)) return o.map(clean).filter(x => x !== undefined);
    if (o && typeof o === "object") {
      const r = {};
      for (const [k, v] of Object.entries(o)) { const c = clean(v); if (c !== undefined) r[k] = c; }
      return Object.keys(r).length ? r : undefined;
    }
    if (typeof o === "string") return o.trim() || undefined;
    return o;
  };
  const i = { ...f.Iesniedzejs };
  if (i.PusesTips === "FiziskaPersona") { delete i.Nosaukums; delete i.RegistracijasNr; } else { delete i.Vards; delete i.Uzvards; }
  const j = { ...f.Jautajums };
  if (j.laiks === "datums") delete j.NotikumaMenesis; else if (j.laiks === "menesis") delete j.NotikumaDatums; else { delete j.NotikumaDatums; delete j.NotikumaMenesis; }
  delete j.laiks;
  const s = { ...f.IeprieksejieSoli };
  if (!s.VersiesIestade) { delete s.VersanasDatums; delete s.AtbildeSanemta; delete s.AtbildesKopsavilkums; }
  else if (!s.AtbildeSanemta) delete s.AtbildesKopsavilkums;
  const out = { Iesniedzejs: i, Jautajums: j, IeprieksejieSoli: s, Apliecinajumi: f.Apliecinajumi };
  if (citas) {
    const p = { ...f.Parstavis, ParstavamaPersona: { ...f.Parstavis.ParstavamaPersona } };
    const pp = p.ParstavamaPersona;
    if (pp.PusesTips === "FiziskaPersona") { delete pp.Nosaukums; delete pp.RegistracijasNr; } else { delete pp.Vards; delete pp.Uzvards; }
    if (p.Pamats !== "Cits") delete p.PamatsApraksts;
    out.Parstavis = p;
  }
  const c = clean(out);
  c.Iesniedzejs.Kontakti = c.Iesniedzejs.Kontakti || {};
  return c;
}

function stepProblems(step, f, citas) {
  const p = [];
  const i = f.Iesniedzejs, j = f.Jautajums, s = f.IeprieksejieSoli;
  if (step === 0) {
    if (i.PusesTips === "FiziskaPersona" && (!i.Vards.trim() || !i.Uzvards.trim())) p.push("Norādiet vārdu un uzvārdu.");
    if (i.PusesTips === "JuridiskaPersona" && (!i.Nosaukums.trim() || i.RegistracijasNr.length !== 11)) p.push("Norādiet nosaukumu un 11 ciparu reģistrācijas numuru.");
    const need = { EPasts: ["Epasts", "e-pasta adresi"], EAdrese: ["EAdrese", "e-adreses identifikatoru"], Pasts: ["PastaAdrese", "pasta adresi"] }[i.AtbildesVeids];
    if (need && !i.Kontakti[need[0]].trim()) p.push(`Atbildei norādiet ${need[1]}.`);
    if (citas) {
      const pp = f.Parstavis.ParstavamaPersona;
      if (pp.PusesTips === "FiziskaPersona" && (!pp.Vards.trim() || !pp.Uzvards.trim())) p.push("Norādiet pārstāvamās personas vārdu un uzvārdu.");
      if (f.Parstavis.Pamats === "Cits" && !f.Parstavis.PamatsApraksts.trim()) p.push("Aprakstiet pārstāvības pamatu.");
    }
  }
  if (step === 1) {
    if (!j.Joma) p.push("Izvēlieties jomu.");
    if (j.Apraksts.trim().length < 20) p.push("Aprakstam jābūt vismaz 20 zīmēm.");
    if (j.Apraksts.length > 2000) p.push("Apraksts — ne vairāk kā 2000 zīmes.");
    if (!j.Lugums.trim()) p.push("Norādiet, ko lūdzat.");
    if (j.Lugums.length > 500) p.push("Lūgums — ne vairāk kā 500 zīmes.");
  }
  if (step === 2 && s.VersiesIestade && !s.VersanasDatums) p.push("Norādiet, kad vērsāties iestādē.");
  return p;
}

export default function PublicForm({ channel }) {
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [step, setStep] = useState(0);
  const [f, setF] = useState(EMPTY);
  const [citas, setCitas] = useState(false);
  const [files, setFiles] = useState([]);  // [{file, apraksts}]
  const [kodsQ, setKodsQ] = useState("");

  useEffect(() => {
    fetch(`/api/ievade/forma/${channel}`).then(async r => {
      if (!r.ok) throw new Error("Forma nav pieejama.");
      setInfo(await r.json());
    }).catch(e => setErr([e.message]));
  }, [channel]);

  const up = (part, patch) => setF(o => ({ ...o, [part]: { ...o[part], ...patch } }));
  const upK = (patch) => setF(o => ({ ...o, Iesniedzejs: { ...o.Iesniedzejs, Kontakti: { ...o.Iesniedzejs.Kontakti, ...patch } } }));
  const upP = (patch) => setF(o => ({ ...o, Parstavis: { ...o.Parstavis, ParstavamaPersona: { ...o.Parstavis.ParstavamaPersona, ...patch } } }));
  const kodi = useMemo(() => {
    const q = kodsQ.trim().toLowerCase();
    return (info?.kodi || []).filter(k => k.joma === f.Jautajums.Joma && (!q || k.kods.toLowerCase().startsWith(q) || k.cels.toLowerCase().includes(q))).slice(0, 50);
  }, [info, f.Jautajums.Joma, kodsQ]);
  const kodsInfo = (info?.kodi || []).find(k => k.kods === f.Jautajums.Kods);

  const next = () => {
    const p = stepProblems(step, f, citas);
    setErr(p);
    if (!p.length) setStep(step + 1);
  };

  const submit = async () => {
    setBusy(true); setErr([]);
    try {
      const fd = new FormData();
      fd.append("iesniegums", JSON.stringify(payload(f, citas)));
      fd.append("apraksti", JSON.stringify(files.map(x => x.apraksts || "")));
      files.forEach(x => fd.append("datnes", x.file));
      const r = await fetch(`/api/ievade/forma/${channel}`, { method: "POST", body: fd });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        const k = d?.detail?.kludas;
        throw Object.assign(new Error("x"), { list: k || [typeof d.detail === "string" ? d.detail : `Kļūda (${r.status})`] });
      }
      setDone(d);
    } catch (ex) { setErr(ex.list || [ex.message]); } finally { setBusy(false); }
  };

  const i = f.Iesniedzejs, j = f.Jautajums, s = f.IeprieksejieSoli;
  const jomaName = (info?.jomas || []).find(x => x.kods === j.Joma)?.nosaukums;

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto bg-white border rounded-lg p-6">
        <div className="text-xs text-gray-500 mb-1">{info?.iestade}</div>
        <h1 className="text-xl font-bold text-gray-900 mb-1">{info?.nosaukums || "Iesniegums"}</h1>
        <p className="text-xs text-gray-500 mb-4">Strukturēta veidlapa. Iesniegums tiek saglabāts tieši tādā formā, kādā to aizpildāt.</p>

        {done ? (
          <div>
            <p className="text-sm text-gray-800 mb-4">Iesniegums saņemts un reģistrēts. Saglabājiet šo lapu vai reģistrācijas numuru.</p>
            <Status token={done.statusaKods} />
          </div>
        ) : info && (
          <>
            <ol className="flex flex-wrap gap-1 mb-5 text-xs">
              {STEPS.map((t, n) => (
                <li key={t} className={`px-2 py-1 rounded ${n === step ? "bg-emerald-700 text-white" : n < step ? "bg-emerald-50 text-emerald-800" : "bg-gray-100 text-gray-500"}`}>{n + 1}. {t}</li>
              ))}
            </ol>

            {step === 0 && (
              <div>
                <PersonFields p={i} set={patch => up("Iesniedzejs", patch)} />
                <div className="grid grid-cols-2 gap-3">
                  <Field label="E-pasts"><input className={inputCls} type="email" maxLength={200} value={i.Kontakti.Epasts} onChange={e => upK({ Epasts: e.target.value })} /></Field>
                  <Field label="Tālrunis"><input className={inputCls} maxLength={16} value={i.Kontakti.Talrunis} onChange={e => upK({ Talrunis: e.target.value })} /></Field>
                  <Field label="E-adrese"><input className={inputCls} maxLength={200} value={i.Kontakti.EAdrese} onChange={e => upK({ EAdrese: e.target.value })} /></Field>
                  <Field label="Pasta adrese"><input className={inputCls} maxLength={200} value={i.Kontakti.PastaAdrese} onChange={e => upK({ PastaAdrese: e.target.value })} /></Field>
                </div>
                <Field label="Kā vēlaties saņemt atbildi" req>
                  <Radio value={i.AtbildesVeids} onChange={v => up("Iesniedzejs", { AtbildesVeids: v })}
                    options={[["EPasts", "E-pastā"], ["EAdrese", "E-adresē"], ["Pasts", "Pa pastu"]]} />
                </Field>
                <label className="flex items-center gap-2 text-sm mt-4 mb-2">
                  <input type="checkbox" checked={citas} onChange={e => setCitas(e.target.checked)} /> Iesniedzu citas personas interesēs
                </label>
                {citas && (
                  <div className="border-l-2 border-gray-200 pl-4">
                    <PersonFields p={f.Parstavis.ParstavamaPersona} set={upP} />
                    <Field label="Pārstāvības pamats" req>
                      <Radio value={f.Parstavis.Pamats} onChange={v => up("Parstavis", { Pamats: v })}
                        options={[["Pilnvara", "Pilnvara"], ["LikumiskaisParstavis", "Likumiskais pārstāvis"], ["Cits", "Cits"]]} />
                    </Field>
                    {f.Parstavis.Pamats === "Pilnvara" && <p className="text-xs text-gray-500 mb-2">Pilnvaru pievienojiet 4. solī.</p>}
                    {f.Parstavis.Pamats === "Cits" && <Field label="Pamata apraksts" req><input className={inputCls} maxLength={500} value={f.Parstavis.PamatsApraksts} onChange={e => up("Parstavis", { PamatsApraksts: e.target.value })} /></Field>}
                  </div>
                )}
              </div>
            )}

            {step === 1 && (
              <div>
                <Field label="Joma" req>
                  <select className={inputCls} value={j.Joma} onChange={e => { up("Jautajums", { Joma: e.target.value, Kods: "" }); setKodsQ(""); }}>
                    <option value="">— izvēlieties —</option>
                    {info.jomas.map(x => <option key={x.kods} value={x.kods}>{x.nosaukums}</option>)}
                  </select>
                </Field>
                {j.Joma && (
                  <Field label="Tēma (ja zināt)" hint="Nav obligāti. Ja neizvēlaties, tēmu noteiks birojs.">
                    {kodsInfo ? (
                      <div className="flex items-center gap-2 text-sm">
                        <span className="font-mono">{kodsInfo.kods}</span><span className="flex-1">{kodsInfo.cels}</span>
                        <button type="button" className="text-xs text-gray-500 underline" onClick={() => up("Jautajums", { Kods: "" })}>noņemt</button>
                      </div>
                    ) : (
                      <>
                        <input className={inputCls} placeholder="Meklēt tēmu…" value={kodsQ} onChange={e => setKodsQ(e.target.value)} />
                        {kodsQ && (
                          <div className="border rounded-md mt-1 max-h-48 overflow-auto text-sm">
                            {kodi.map(k => (
                              <button type="button" key={k.kods} onClick={() => { up("Jautajums", { Kods: k.kods }); setKodsQ(""); }}
                                className="block w-full text-left px-3 py-1.5 hover:bg-gray-50"><span className="font-mono text-xs mr-2">{k.kods}</span>{k.cels}</button>
                            ))}
                            {!kodi.length && <div className="px-3 py-2 text-gray-500">Nav atrasts.</div>}
                          </div>
                        )}
                      </>
                    )}
                  </Field>
                )}
                <Field label="Iestāde vai persona, par kuras rīcību iesniegums" hint="Līdz 3.">
                  {j.Iestade.map((x, n) => (
                    <div key={n} className="flex gap-2 mb-1">
                      <input className={inputCls} maxLength={200} value={x.Nosaukums}
                        onChange={e => up("Jautajums", { Iestade: j.Iestade.map((y, m) => m === n ? { Nosaukums: e.target.value } : y) })} />
                      {j.Iestade.length > 1 && <button type="button" className="text-xs text-gray-500" onClick={() => up("Jautajums", { Iestade: j.Iestade.filter((_, m) => m !== n) })}>×</button>}
                    </div>
                  ))}
                  {j.Iestade.length < 3 && <button type="button" className="text-xs text-emerald-700" onClick={() => up("Jautajums", { Iestade: [...j.Iestade, { Nosaukums: "" }] })}>+ vēl viena</button>}
                </Field>
                <Field label="Kad tas notika">
                  <Radio value={j.laiks} onChange={v => up("Jautajums", { laiks: v })} options={[["menesis", "Mēnesis"], ["datums", "Precīzs datums"], ["nav", "Nenorādīt"]]} />
                  {j.laiks === "menesis" && <input type="month" className={inputCls + " mt-2"} value={j.NotikumaMenesis} onChange={e => up("Jautajums", { NotikumaMenesis: e.target.value })} />}
                  {j.laiks === "datums" && <input type="date" className={inputCls + " mt-2"} value={j.NotikumaDatums} onChange={e => up("Jautajums", { NotikumaDatums: e.target.value })} />}
                </Field>
                <Field label={<>Kas notika <Counter v={j.Apraksts} max={2000} /></>} req hint="Īsi un pēc būtības: kas, kad, kā tas skar jūs.">
                  <textarea rows={7} className={inputCls} maxLength={2000} value={j.Apraksts} onChange={e => up("Jautajums", { Apraksts: e.target.value })} />
                </Field>
                <Field label={<>Ko lūdzat <Counter v={j.Lugums} max={500} /></>} req>
                  <textarea rows={3} className={inputCls} maxLength={500} value={j.Lugums} onChange={e => up("Jautajums", { Lugums: e.target.value })} />
                </Field>
              </div>
            )}

            {step === 2 && (
              <div>
                <Field label="Vai jau vērsāties attiecīgajā iestādē?" req>
                  <Radio value={s.VersiesIestade ? "ja" : "ne"} onChange={v => up("IeprieksejieSoli", { VersiesIestade: v === "ja" })} options={[["ja", "Jā"], ["ne", "Nē"]]} />
                </Field>
                {s.VersiesIestade && (
                  <>
                    <Field label="Kad" req><input type="date" className={inputCls} value={s.VersanasDatums} onChange={e => up("IeprieksejieSoli", { VersanasDatums: e.target.value })} /></Field>
                    <Field label="Vai saņēmāt atbildi?">
                      <Radio value={s.AtbildeSanemta ? "ja" : "ne"} onChange={v => up("IeprieksejieSoli", { AtbildeSanemta: v === "ja" })} options={[["ja", "Jā"], ["ne", "Nē"]]} />
                    </Field>
                    {s.AtbildeSanemta && (
                      <Field label={<>Atbildes būtība <Counter v={s.AtbildesKopsavilkums} max={500} /></>}>
                        <textarea rows={3} className={inputCls} maxLength={500} value={s.AtbildesKopsavilkums} onChange={e => up("IeprieksejieSoli", { AtbildesKopsavilkums: e.target.value })} />
                      </Field>
                    )}
                  </>
                )}
                <Field label="Vai jautājums tiek vai ir ticis izskatīts tiesā?" req>
                  <Radio value={s.Tiesvediba} onChange={v => up("IeprieksejieSoli", { Tiesvediba: v })} options={[["Ne", "Nē"], ["Ja", "Jā"], ["NavZinams", "Nezinu"]]} />
                </Field>
              </div>
            )}

            {step === 3 && (
              <div>
                <p className="text-sm text-gray-600 mb-3">Pierādījumi: lēmumi, sarakste, fotogrāfijas, pilnvara. Līdz 10 datnēm, kopā līdz {info.maxMb} MB. Pielikumi papildina iesniegumu, bet neaizstāj to.</p>
                {files.map((x, n) => (
                  <div key={n} className="flex gap-2 items-center mb-2 text-sm">
                    <span className="flex-1 truncate">{x.file.name}</span>
                    <input className="px-2 py-1 border rounded text-sm w-56" placeholder="Kas tas ir?" maxLength={200} value={x.apraksts}
                      onChange={e => setFiles(files.map((y, m) => m === n ? { ...y, apraksts: e.target.value } : y))} />
                    <button type="button" className="text-xs text-gray-500" onClick={() => setFiles(files.filter((_, m) => m !== n))}>×</button>
                  </div>
                ))}
                {files.length < 10 && <input type="file" multiple className="text-sm" onChange={e => { setFiles([...files, ...[...e.target.files].map(file => ({ file, apraksts: "" }))].slice(0, 10)); e.target.value = ""; }} />}
              </div>
            )}

            {step === 4 && (
              <div className="text-sm">
                <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 mb-4">
                  <dt className="text-gray-500">Iesniedzējs</dt><dd>{i.PusesTips === "FiziskaPersona" ? `${i.Vards} ${i.Uzvards}` : `${i.Nosaukums} (${i.RegistracijasNr})`}</dd>
                  {citas && <><dt className="text-gray-500">Pārstāvamā persona</dt><dd>{f.Parstavis.ParstavamaPersona.Vards} {f.Parstavis.ParstavamaPersona.Uzvards}{f.Parstavis.ParstavamaPersona.Nosaukums}</dd></>}
                  <dt className="text-gray-500">Atbilde</dt><dd>{{ EPasts: "e-pastā", EAdrese: "e-adresē", Pasts: "pa pastu" }[i.AtbildesVeids]}</dd>
                  <dt className="text-gray-500">Joma / tēma</dt><dd>{jomaName}{kodsInfo ? ` — ${kodsInfo.kods} ${kodsInfo.nosaukums}` : ""}</dd>
                  <dt className="text-gray-500">Iestāde</dt><dd>{j.Iestade.map(x => x.Nosaukums).filter(Boolean).join("; ") || "—"}</dd>
                  <dt className="text-gray-500">Apraksts</dt><dd className="whitespace-pre-wrap">{j.Apraksts}</dd>
                  <dt className="text-gray-500">Lūgums</dt><dd className="whitespace-pre-wrap">{j.Lugums}</dd>
                  <dt className="text-gray-500">Pielikumi</dt><dd>{files.length || "nav"}</dd>
                </dl>
                <label className="flex items-start gap-2 mb-2">
                  <input type="checkbox" checked={f.Apliecinajumi.InformacijaPatiesa} onChange={e => up("Apliecinajumi", { InformacijaPatiesa: e.target.checked })} />
                  <span>Apliecinu, ka sniegtā informācija ir patiesa.</span>
                </label>
                <label className="flex items-start gap-2 mb-4">
                  <input type="checkbox" checked={f.Apliecinajumi.IepaziniesArDatuApstradi} onChange={e => up("Apliecinajumi", { IepaziniesArDatuApstradi: e.target.checked })} />
                  <span>Esmu iepazinies ar to, kā tiks apstrādāti iesniegumā norādītie personas dati.</span>
                </label>
              </div>
            )}
          </>
        )}

        {err.length > 0 && (
          <ul className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3 my-3 list-disc pl-6">
            {err.map((e, n) => <li key={n}>{e}</li>)}
          </ul>
        )}

        {info && !done && (
          <div className="flex justify-between mt-4">
            <button type="button" disabled={step === 0} onClick={() => { setErr([]); setStep(step - 1); }} className="px-3 py-2 text-sm border rounded-md disabled:opacity-40">Atpakaļ</button>
            {step < 4
              ? <button type="button" onClick={next} className="px-4 py-2 bg-emerald-700 text-white rounded-md text-sm">Tālāk</button>
              : <button type="button" onClick={submit} disabled={busy || !f.Apliecinajumi.InformacijaPatiesa || !f.Apliecinajumi.IepaziniesArDatuApstradi}
                  className="px-4 py-2 bg-emerald-700 text-white rounded-md text-sm disabled:opacity-50">{busy ? "Iesniedz…" : "Iesniegt"}</button>}
          </div>
        )}
        <input name="web" tabIndex={-1} autoComplete="off" className="hidden" aria-hidden="true" />
        {info?.shema && <p className="text-[11px] text-gray-400 mt-6">Datu shēma: {info.shema}</p>}
      </div>
    </div>
  );
}
