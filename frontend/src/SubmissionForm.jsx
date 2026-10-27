// Publiskā iesnieguma veidlapa pēc UAS e-submission 0.1 (tiesibsargs/iesnieguma-shema).
// Iesniegums sadalīts sastāvdaļās: izklāsts, fakti (katrs atsevišķi), prasījumi (katrs atsevišķi,
// sasaistīti ar faktiem), iepriekšējie soļi, atklātība, pielikumi kā pierādījumi.
// Serveris uzraksta shēmas XML, pārbauda ar XSD un noteikumiem: kļūdas aptur iesniegšanu,
// brīdinājumi (piem., nav paraksta) dodas līdzi dokumentam uz izvērtēšanu.

import { useEffect, useMemo, useState } from "react";

const STEPS = ["Iesniedzējs", "Kas notika", "Ko lūdzat", "Iepriekšējie soļi", "Pielikumi", "Pārskats"];
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

const CONDUCT = [["action", "rīkojās"], ["omission", "nerīkojās / neatbildēja"], ["decision", "pieņēma lēmumu"],
                 ["statement", "izteicās"], ["event", "notikums"]];
const CLAIM_TYPES = [["investigate", "Pārbaudīt iestādes rīcību (pārbaudes lieta)"], ["remedy", "Panākt, ka pārkāpums tiek novērsts"],
                     ["conciliation", "Palīdzēt panākt izlīgumu"], ["opinion", "Sniegt atzinumu"],
                     ["consultation", "Konsultēt par manām tiesībām"], ["information", "Sniegt informāciju"],
                     ["legislativeChange", "Ierosināt mainīt normatīvo aktu"], ["other", "Cits"]];
const KINDS = [["evidence", "Pierādījums"], ["priorCorrespondence", "Sarakste ar iestādi"], ["authorisation", "Pilnvara"],
               ["courtDocument", "Tiesas dokuments"], ["other", "Cits"]];

const person = () => ({ partyType: "naturalPerson", givenName: "", familyName: "", legalName: "", registrationNo: "" });
const fact = () => ({ laiks: "menesis", date: "", yearMonth: "", from: "", to: "", actor: "", conduct: "action", statement: "" });
const claim = () => ({ type: "investigate", text: "", relatedFact: [] });

const EMPTY = {
  sub: { ...person(), address: "", email: "", phone: "", eAddress: "" },
  replyChannel: "email",
  citas: false, rep: { ...person(), basis: "authorisation", description: "", child: false },
  summary: "", resp: [""], facts: [fact()],
  claims: [claim()], domain: "", code: "",
  vērsies: false, stepDate: "", answered: false, answerSummary: "", court: "no", caseNo: "",
  hideId: false, hideFacts: false,
  decl: { informationTruthful: false, dataProcessingAcknowledged: false },
};

const trim = (s) => (s || "").trim();
const nameOf = (p) => p.partyType === "naturalPerson" ? `${trim(p.givenName)} ${trim(p.familyName)}`.trim() : trim(p.legalName);

function personOut(p) {
  return p.partyType === "naturalPerson"
    ? { partyType: "naturalPerson", givenName: trim(p.givenName), familyName: trim(p.familyName) }
    : { partyType: "legalPerson", legalName: trim(p.legalName), registrationNo: trim(p.registrationNo) || undefined };
}

// Form state -> e-submission payload (schema shape). Ids: p1 submitter, p2 represented person, r1… respondents,
// f1… facts, c1… claims, a1… attachments (the server numbers files in the same order).
function toPayload(f, files) {
  const resp = f.resp.map(trim).filter(Boolean);
  const factIds = f.facts.map((_, n) => `f${n + 1}`);
  const evidenceFor = (n) => files.map((x, k) => (x.facts || []).includes(n) ? `a${k + 1}` : null).filter(Boolean);
  const auth = files.findIndex(x => x.kind === "authorisation");
  const p1 = { id: "p1", role: f.citas ? ["submitter", "representative"] : ["submitter", "affectedPerson"], ...personOut(f.sub),
               address: trim(f.sub.address) || undefined,
               contact: { email: trim(f.sub.email) || undefined, phone: trim(f.sub.phone) || undefined, eAddress: trim(f.sub.eAddress) || undefined } };
  if (f.citas) p1.representation = { represents: "p2", basis: f.rep.basis, description: trim(f.rep.description) || undefined,
                                     evidence: auth >= 0 ? `a${auth + 1}` : undefined };
  const parties = [p1];
  if (f.citas) parties.push({ id: "p2", role: ["affectedPerson"], ...personOut(f.rep), vulnerability: f.rep.child ? ["PZ-BE"] : undefined });
  resp.forEach((r, n) => parties.push({ id: `r${n + 1}`, role: ["respondent"], partyType: "institution", legalName: r }));
  const when = (x) => x.laiks === "datums" && x.date ? { date: x.date } : x.laiks === "menesis" && x.yearMonth ? { yearMonth: x.yearMonth }
    : x.laiks === "periods" && x.from ? { period: { from: x.from, to: x.to || undefined } } : x.laiks === "turpinas" ? { ongoing: true } : undefined;
  const facts = f.facts.map((x, n) => {
    const ev = evidenceFor(n);
    return { id: factIds[n], when: when(x), actor: x.actor ? [x.actor] : undefined, conduct: x.conduct,
             statement: trim(x.statement), basis: ev.length ? "documented" : "claimed", evidence: ev.length ? ev : undefined };
  });
  const claims = f.claims.map((c, n) => ({ id: `c${n + 1}`, type: c.type, text: trim(c.text),
    addressedTo: resp.length ? "r1" : undefined, relatedFact: c.relatedFact.map(k => factIds[k]).filter(Boolean) }));
  const step = f.vērsies ? [{ type: "contactedRespondent", addressedTo: resp.length ? "r1" : undefined, date: f.stepDate || undefined,
                              responseReceived: f.answered, responseSummary: f.answered ? trim(f.answerSummary) || undefined : undefined }] : [];
  return {
    submissionType: ["sudziba"],
    parties, narrative: { summary: trim(f.summary) }, facts,
    rightsAffected: f.domain ? { domain: [f.domain], classifierCode: f.code ? [f.code] : undefined } : undefined,
    claims,
    priorSteps: { step, court: { status: f.court, caseNo: trim(f.caseNo) || undefined } },
    privacy: { doNotDiscloseIdentity: f.hideId, doNotDiscloseFacts: f.hideFacts, noReplyNeeded: false, replyChannel: f.replyChannel },
    declarations: f.decl,
  };
}

function problems(step, f) {
  const p = [];
  if (step === 0) {
    const s = f.sub;
    if (s.partyType === "naturalPerson" && (!trim(s.givenName) || !trim(s.familyName))) p.push("Norādiet vārdu un uzvārdu.");
    if (s.partyType === "legalPerson" && (!trim(s.legalName) || trim(s.registrationNo).length !== 11)) p.push("Norādiet nosaukumu un 11 ciparu reģistrācijas numuru.");
    if (!trim(s.address)) p.push("Norādiet adresi (Iesniegumu likums 3. p. 2. d.).");
    const need = { email: ["email", "e-pasta adresi"], eAddress: ["eAddress", "e-adreses identifikatoru"] }[f.replyChannel];
    if (need && !trim(s[need[0]])) p.push(`Atbildei norādiet ${need[1]}.`);
    if (f.citas && f.rep.partyType === "naturalPerson" && (!trim(f.rep.givenName) || !trim(f.rep.familyName))) p.push("Norādiet pārstāvamās personas vārdu un uzvārdu.");
    if (f.citas && f.rep.basis === "other" && !trim(f.rep.description)) p.push("Aprakstiet pārstāvības pamatu.");
  }
  if (step === 1) {
    if (trim(f.summary).length < 20) p.push("Īsi aprakstiet situāciju (vismaz 20 zīmes).");
    f.facts.forEach((x, n) => { if (!trim(x.statement)) p.push(`${n + 1}. faktam nav apraksta.`); });
  }
  if (step === 2) {
    if (!f.domain) p.push("Izvēlieties jomu.");
    f.claims.forEach((c, n) => { if (!trim(c.text)) p.push(`${n + 1}. lūgumam nav teksta.`); });
  }
  if (step === 3 && f.vērsies && !f.stepDate) p.push("Norādiet, kad vērsāties iestādē.");
  return p;
}

function PersonFields({ p, set }) {
return (
  <>
    <Field label="Veids" req>
      <Radio value={p.partyType} onChange={v => set({ partyType: v })} options={[["naturalPerson", "Fiziska persona"], ["legalPerson", "Juridiska persona"]]} />
    </Field>
    {p.partyType === "naturalPerson" ? (
      <div className="grid grid-cols-2 gap-3">
        <Field label="Vārds" req><input className={inputCls} maxLength={200} value={p.givenName} onChange={e => set({ givenName: e.target.value })} /></Field>
        <Field label="Uzvārds" req><input className={inputCls} maxLength={200} value={p.familyName} onChange={e => set({ familyName: e.target.value })} /></Field>
      </div>
    ) : (
      <div className="grid grid-cols-2 gap-3">
        <Field label="Nosaukums" req><input className={inputCls} maxLength={200} value={p.legalName} onChange={e => set({ legalName: e.target.value })} /></Field>
        <Field label="Reģistrācijas numurs" req><input className={inputCls} maxLength={11} value={p.registrationNo} onChange={e => set({ registrationNo: e.target.value.replace(/\D/g, "") })} /></Field>
      </div>
    )}
  </>
);
}

export default function SubmissionForm({ channel, info }) {
  const [f, setF] = useState(EMPTY);
  const [files, setFiles] = useState([]);   // [{file, apraksts, kind, facts:[index]}]
  const [step, setStep] = useState(0);
  const [err, setErr] = useState([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [kodsQ, setKodsQ] = useState("");

  const up = (patch) => setF(o => ({ ...o, ...patch }));
  const upSub = (patch) => setF(o => ({ ...o, sub: { ...o.sub, ...patch } }));
  const upRep = (patch) => setF(o => ({ ...o, rep: { ...o.rep, ...patch } }));
  const upFact = (n, patch) => setF(o => ({ ...o, facts: o.facts.map((x, k) => k === n ? { ...x, ...patch } : x) }));
  const upClaim = (n, patch) => setF(o => ({ ...o, claims: o.claims.map((x, k) => k === n ? { ...x, ...patch } : x) }));
  const resp = f.resp.map(trim).filter(Boolean);
  const actors = [["", "—"], ["p1", f.citas ? "pārstāvamā persona vai es" : "es"], ...resp.map((r, n) => [`r${n + 1}`, r])];

  const kodi = useMemo(() => {
    const q = kodsQ.trim().toLowerCase();
    return (info.kodi || []).filter(k => k.joma === f.domain && (!q || k.kods.toLowerCase().startsWith(q) || k.cels.toLowerCase().includes(q))).slice(0, 50);
  }, [info, f.domain, kodsQ]);
  const kodsInfo = (info.kodi || []).find(k => k.kods === f.code);

  const next = () => { const p = problems(step, f); setErr(p); if (!p.length) setStep(step + 1); };

  const submit = async () => {
    setBusy(true); setErr([]);
    try {
      const fd = new FormData();
      fd.append("iesniegums", JSON.stringify(toPayload(f, files)));
      fd.append("apraksti", JSON.stringify(files.map(x => x.apraksts || "")));
      fd.append("veidi", JSON.stringify(files.map(x => x.kind || "evidence")));
      files.forEach(x => fd.append("datnes", x.file));
      const r = await fetch(`/api/ievade/forma/${channel}`, { method: "POST", body: fd });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw Object.assign(new Error("x"), { list: d?.detail?.kludas || [typeof d.detail === "string" ? d.detail : `Kļūda (${r.status})`] });
      setDone(d);
    } catch (ex) { setErr(ex.list || [ex.message]); } finally { setBusy(false); }
  };

  if (done) return (
    <div>
      <p className="text-sm text-gray-800 mb-4">Iesniegums saņemts un reģistrēts. Saglabājiet šo lapu vai reģistrācijas numuru.</p>
      <Status token={done.statusaKods} />
    </div>
  );

  return (
    <>
      <ol className="flex flex-wrap gap-1 mb-5 text-xs">
        {STEPS.map((t, n) => (
          <li key={t} className={`px-2 py-1 rounded ${n === step ? "bg-emerald-700 text-white" : n < step ? "bg-emerald-50 text-emerald-800" : "bg-gray-100 text-gray-500"}`}>{n + 1}. {t}</li>
        ))}
      </ol>

      {step === 0 && (
        <div>
          <PersonFields p={f.sub} set={upSub} />
          <Field label="Adrese" req hint="Uz šo adresi var nosūtīt atbildi; bez adreses iesniegumu var atstāt bez izskatīšanas.">
            <input className={inputCls} maxLength={200} value={f.sub.address} onChange={e => upSub({ address: e.target.value })} />
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="E-pasts"><input className={inputCls} type="email" maxLength={200} value={f.sub.email} onChange={e => upSub({ email: e.target.value })} /></Field>
            <Field label="Tālrunis"><input className={inputCls} maxLength={16} value={f.sub.phone} onChange={e => upSub({ phone: e.target.value })} /></Field>
            <Field label="E-adrese"><input className={inputCls} maxLength={200} value={f.sub.eAddress} onChange={e => upSub({ eAddress: e.target.value })} /></Field>
          </div>
          <Field label="Kā vēlaties saņemt atbildi" req>
            <Radio value={f.replyChannel} onChange={v => up({ replyChannel: v })} options={[["email", "E-pastā"], ["eAddress", "E-adresē"], ["post", "Pa pastu"]]} />
          </Field>
          <label className="flex items-center gap-2 text-sm mt-4 mb-2">
            <input type="checkbox" checked={f.citas} onChange={e => up({ citas: e.target.checked })} /> Iesniedzu citas personas interesēs
          </label>
          {f.citas && (
            <div className="border-l-2 border-gray-200 pl-4">
              <PersonFields p={f.rep} set={upRep} />
              <label className="flex items-center gap-2 text-sm mb-3"><input type="checkbox" checked={f.rep.child} onChange={e => upRep({ child: e.target.checked })} /> Persona ir bērns</label>
              <Field label="Pārstāvības pamats" req>
                <Radio value={f.rep.basis} onChange={v => upRep({ basis: v })}
                  options={[["authorisation", "Pilnvara"], ["legalRepresentative", "Likumiskais pārstāvis (piem., vecāks)"], ["none", "Nav pilnvaras"], ["other", "Cits"]]} />
              </Field>
              {f.rep.basis === "authorisation" && <p className="text-xs text-gray-500 mb-2">Pilnvaru pievienojiet 5. solī kā «Pilnvara».</p>}
              {f.rep.basis === "none" && <p className="text-xs text-gray-500 mb-2">Birojs sazināsies ar personu, kuras tiesības skartas.</p>}
              {f.rep.basis === "other" && <Field label="Pamata apraksts" req><input className={inputCls} maxLength={500} value={f.rep.description} onChange={e => upRep({ description: e.target.value })} /></Field>}
            </div>
          )}
        </div>
      )}

      {step === 1 && (
        <div>
          <Field label={<>Īsumā: kas noticis un kāpēc vēršaties <Counter v={f.summary} max={1000} /></>} req>
            <textarea rows={4} className={inputCls} maxLength={1000} value={f.summary} onChange={e => up({ summary: e.target.value })} />
          </Field>
          <Field label="Iestāde vai persona, par kuras rīcību iesniegums" hint="Līdz 3.">
            {f.resp.map((x, n) => (
              <div key={n} className="flex gap-2 mb-1">
                <input className={inputCls} maxLength={200} value={x} onChange={e => up({ resp: f.resp.map((y, m) => m === n ? e.target.value : y) })} />
                {f.resp.length > 1 && <button type="button" className="text-xs text-gray-500" onClick={() => up({ resp: f.resp.filter((_, m) => m !== n) })}>×</button>}
              </div>
            ))}
            {f.resp.length < 3 && <button type="button" className="text-xs text-emerald-700" onClick={() => up({ resp: [...f.resp, ""] })}>+ vēl viena</button>}
          </Field>
          <div className="text-sm font-medium text-gray-800 mt-4 mb-1">Apstākļi un fakti</div>
          <p className="text-xs text-gray-500 mb-2">Katru notikumu aprakstiet atsevišķi: kad, kas, ko izdarīja vai neizdarīja.</p>
          {f.facts.map((x, n) => (
            <div key={n} className="border rounded-md p-3 mb-2">
              <div className="flex justify-between text-xs text-gray-500 mb-2"><span>{n + 1}. fakts</span>
                {f.facts.length > 1 && <button type="button" onClick={() => up({ facts: f.facts.filter((_, m) => m !== n), claims: f.claims.map(c => ({ ...c, relatedFact: c.relatedFact.filter(k => k !== n).map(k => k > n ? k - 1 : k) })) })}>noņemt</button>}
              </div>
              <Field label="Kad">
                <Radio value={x.laiks} onChange={v => upFact(n, { laiks: v })} options={[["menesis", "Mēnesis"], ["datums", "Datums"], ["periods", "Periods"], ["turpinas", "Turpinās"], ["nav", "Nenorādīt"]]} />
                {x.laiks === "menesis" && <input type="month" className={inputCls + " mt-2"} value={x.yearMonth} onChange={e => upFact(n, { yearMonth: e.target.value })} />}
                {x.laiks === "datums" && <input type="date" className={inputCls + " mt-2"} value={x.date} onChange={e => upFact(n, { date: e.target.value })} />}
                {x.laiks === "periods" && <div className="grid grid-cols-2 gap-2 mt-2">
                  <input type="date" className={inputCls} value={x.from} onChange={e => upFact(n, { from: e.target.value })} />
                  <input type="date" className={inputCls} value={x.to} onChange={e => upFact(n, { to: e.target.value })} /></div>}
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Kas"><select className={inputCls} value={x.actor} onChange={e => upFact(n, { actor: e.target.value })}>{actors.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
                <Field label="Ko"><select className={inputCls} value={x.conduct} onChange={e => upFact(n, { conduct: e.target.value })}>{CONDUCT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
              </div>
              <Field label={<>Kas notika <Counter v={x.statement} max={2000} /></>} req>
                <textarea rows={3} className={inputCls} maxLength={2000} value={x.statement} onChange={e => upFact(n, { statement: e.target.value })} />
              </Field>
            </div>
          ))}
          {f.facts.length < 20 && <button type="button" className="text-xs text-emerald-700" onClick={() => up({ facts: [...f.facts, fact()] })}>+ vēl viens fakts</button>}
        </div>
      )}

      {step === 2 && (
        <div>
          {f.claims.map((c, n) => (
            <div key={n} className="border rounded-md p-3 mb-2">
              <div className="flex justify-between text-xs text-gray-500 mb-2"><span>{n + 1}. lūgums</span>
                {f.claims.length > 1 && <button type="button" onClick={() => up({ claims: f.claims.filter((_, m) => m !== n) })}>noņemt</button>}
              </div>
              <Field label="Ko lūdzat Tiesībsargam" req><select className={inputCls} value={c.type} onChange={e => upClaim(n, { type: e.target.value })}>{CLAIM_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
              <Field label={<>Lūgums saviem vārdiem <Counter v={c.text} max={1000} /></>} req>
                <textarea rows={2} className={inputCls} maxLength={1000} value={c.text} onChange={e => upClaim(n, { text: e.target.value })} />
              </Field>
              <div className="text-xs text-gray-600 mb-1">Uz kuriem faktiem lūgums balstās</div>
              <div className="flex flex-wrap gap-3 text-sm">
                {f.facts.map((x, k) => (
                  <label key={k} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={c.relatedFact.includes(k)}
                      onChange={e => upClaim(n, { relatedFact: e.target.checked ? [...c.relatedFact, k] : c.relatedFact.filter(y => y !== k) })} />
                    {k + 1}. {trim(x.statement).slice(0, 40) || "fakts"}{trim(x.statement).length > 40 ? "…" : ""}
                  </label>
                ))}
              </div>
            </div>
          ))}
          {f.claims.length < 10 && <button type="button" className="text-xs text-emerald-700 mb-4" onClick={() => up({ claims: [...f.claims, claim()] })}>+ vēl viens lūgums</button>}
          <Field label="Joma" req>
            <select className={inputCls} value={f.domain} onChange={e => { up({ domain: e.target.value, code: "" }); setKodsQ(""); }}>
              <option value="">— izvēlieties —</option>
              {(info.jomas || []).map(x => <option key={x.kods} value={x.kods}>{x.nosaukums}</option>)}
            </select>
          </Field>
          {f.domain && (
            <Field label="Tēma (ja zināt)" hint="Nav obligāti. Ja neizvēlaties, tēmu noteiks birojs.">
              {kodsInfo ? (
                <div className="flex items-center gap-2 text-sm"><span className="font-mono">{kodsInfo.kods}</span><span className="flex-1">{kodsInfo.cels}</span>
                  <button type="button" className="text-xs text-gray-500 underline" onClick={() => up({ code: "" })}>noņemt</button></div>
              ) : (
                <>
                  <input className={inputCls} placeholder="Meklēt tēmu…" value={kodsQ} onChange={e => setKodsQ(e.target.value)} />
                  {kodsQ && <div className="border rounded-md mt-1 max-h-48 overflow-auto text-sm">
                    {kodi.map(k => <button type="button" key={k.kods} onClick={() => { up({ code: k.kods }); setKodsQ(""); }} className="block w-full text-left px-3 py-1.5 hover:bg-gray-50"><span className="font-mono text-xs mr-2">{k.kods}</span>{k.cels}</button>)}
                    {!kodi.length && <div className="px-3 py-2 text-gray-500">Nav atrasts.</div>}
                  </div>}
                </>
              )}
            </Field>
          )}
        </div>
      )}

      {step === 3 && (
        <div>
          <Field label="Vai jau vērsāties attiecīgajā iestādē?" req>
            <Radio value={f.vērsies ? "ja" : "ne"} onChange={v => up({ vērsies: v === "ja" })} options={[["ja", "Jā"], ["ne", "Nē"]]} />
          </Field>
          {f.vērsies && (
            <>
              <Field label="Kad" req><input type="date" className={inputCls} value={f.stepDate} onChange={e => up({ stepDate: e.target.value })} /></Field>
              <Field label="Vai saņēmāt atbildi?"><Radio value={f.answered ? "ja" : "ne"} onChange={v => up({ answered: v === "ja" })} options={[["ja", "Jā"], ["ne", "Nē"]]} /></Field>
              {f.answered && <Field label={<>Atbildes būtība <Counter v={f.answerSummary} max={1000} /></>}><textarea rows={3} className={inputCls} maxLength={1000} value={f.answerSummary} onChange={e => up({ answerSummary: e.target.value })} /></Field>}
            </>
          )}
          <Field label="Vai jautājums tiek vai ir izskatīts tiesā?" req>
            <Radio value={f.court} onChange={v => up({ court: v })} options={[["no", "Nē"], ["pending", "Jā, tiek izskatīts"], ["decided", "Jā, ir nolēmums"], ["unknown", "Nezinu"]]} />
          </Field>
          {(f.court === "pending" || f.court === "decided") && <Field label="Lietas numurs (ja zināt)"><input className={inputCls} maxLength={60} value={f.caseNo} onChange={e => up({ caseNo: e.target.value })} /></Field>}
          <div className="text-sm font-medium text-gray-800 mt-4 mb-1">Atklātība</div>
          <label className="flex items-start gap-2 text-sm mb-1"><input type="checkbox" checked={f.hideId} onChange={e => up({ hideId: e.target.checked })} /><span>Lūdzu neizpaust manu identitāti iestādei (Iesniegumu likums 9. p. 1. d.)</span></label>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={f.hideFacts} onChange={e => up({ hideFacts: e.target.checked })} /><span>Lūdzu neizpaust iesniegumā minētos faktus (9. p. 2. d.)</span></label>
        </div>
      )}

      {step === 4 && (
        <div>
          <p className="text-sm text-gray-600 mb-3">Pierādījumi: lēmumi, sarakste, fotogrāfijas, pilnvara. Līdz 10 datnēm, kopā līdz {info.maxMb} MB.</p>
          {files.map((x, n) => (
            <div key={n} className="border rounded-md p-2 mb-2 text-sm">
              <div className="flex gap-2 items-center">
                <span className="flex-1 truncate">{x.file.name}</span>
                <select className="px-2 py-1 border rounded text-sm" value={x.kind} onChange={e => setFiles(files.map((y, m) => m === n ? { ...y, kind: e.target.value } : y))}>
                  {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                <button type="button" className="text-xs text-gray-500" onClick={() => setFiles(files.filter((_, m) => m !== n))}>×</button>
              </div>
              <input className="mt-1 px-2 py-1 border rounded text-sm w-full" placeholder="Kas tas ir?" maxLength={200} value={x.apraksts}
                onChange={e => setFiles(files.map((y, m) => m === n ? { ...y, apraksts: e.target.value } : y))} />
              <div className="flex flex-wrap gap-3 mt-1 text-xs text-gray-600">Pierāda:
                {f.facts.map((fx, k) => <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={(x.facts || []).includes(k)}
                  onChange={e => setFiles(files.map((y, m) => m === n ? { ...y, facts: e.target.checked ? [...(y.facts || []), k] : (y.facts || []).filter(z => z !== k) } : y))} />{k + 1}. faktu</label>)}
              </div>
            </div>
          ))}
          {files.length < 10 && <input type="file" multiple className="text-sm" onChange={e => { setFiles([...files, ...[...e.target.files].map(file => ({ file, apraksts: "", kind: "evidence", facts: [] }))].slice(0, 10)); e.target.value = ""; }} />}
        </div>
      )}

      {step === 5 && (
        <div className="text-sm">
          <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 mb-4">
            <dt className="text-gray-500">Iesniedzējs</dt><dd>{nameOf(f.sub)}, {f.sub.address}</dd>
            {f.citas && <><dt className="text-gray-500">Pārstāvamā persona</dt><dd>{nameOf(f.rep)}</dd></>}
            <dt className="text-gray-500">Iestāde</dt><dd>{resp.join("; ") || "—"}</dd>
            <dt className="text-gray-500">Izklāsts</dt><dd className="whitespace-pre-wrap">{f.summary}</dd>
            <dt className="text-gray-500">Fakti</dt><dd><ol className="list-decimal pl-5">{f.facts.map((x, n) => <li key={n}>{x.statement}</li>)}</ol></dd>
            <dt className="text-gray-500">Lūgumi</dt><dd><ol className="list-decimal pl-5">{f.claims.map((c, n) => <li key={n}>{c.text}</li>)}</ol></dd>
            <dt className="text-gray-500">Pielikumi</dt><dd>{files.length || "nav"}</dd>
          </dl>
          <label className="flex items-start gap-2 mb-2"><input type="checkbox" checked={f.decl.informationTruthful} onChange={e => up({ decl: { ...f.decl, informationTruthful: e.target.checked } })} /><span>Apliecinu, ka sniegtā informācija ir patiesa.</span></label>
          <label className="flex items-start gap-2 mb-4"><input type="checkbox" checked={f.decl.dataProcessingAcknowledged} onChange={e => up({ decl: { ...f.decl, dataProcessingAcknowledged: e.target.checked } })} /><span>Esmu iepazinies ar to, kā tiks apstrādāti iesniegumā norādītie personas dati.</span></label>
        </div>
      )}

      {err.length > 0 && <ul className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3 my-3 list-disc pl-6">{err.map((e, n) => <li key={n}>{e}</li>)}</ul>}

      <div className="flex justify-between mt-4">
        <button type="button" disabled={step === 0} onClick={() => { setErr([]); setStep(step - 1); }} className="px-3 py-2 text-sm border rounded-md disabled:opacity-40">Atpakaļ</button>
        {step < STEPS.length - 1
          ? <button type="button" onClick={next} className="px-4 py-2 bg-emerald-700 text-white rounded-md text-sm">Tālāk</button>
          : <button type="button" onClick={submit} disabled={busy || !f.decl.informationTruthful || !f.decl.dataProcessingAcknowledged}
              className="px-4 py-2 bg-emerald-700 text-white rounded-md text-sm disabled:opacity-50">{busy ? "Iesniedz…" : "Iesniegt"}</button>}
      </div>
    </>
  );
}
