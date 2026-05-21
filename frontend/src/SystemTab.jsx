import { useState, useEffect } from "react";

/* UAPF "Sistema" tab — architecture overview + real demo run flow.
   Bilingual (LV/EN), ambient SVG animation, play-through, clickable. */

const C = {
  emerald: { fill:"#ecfdf5", stroke:"#6ee7b7", solid:"#059669", text:"#065f46" },
  indigo:  { fill:"#eef2ff", stroke:"#a5b4fc", solid:"#4f46e5", text:"#3730a3" },
  violet:  { fill:"#f5f3ff", stroke:"#c4b5fd", solid:"#7c3aed", text:"#5b21b6" },
  amber:   { fill:"#fffbeb", stroke:"#fcd34d", solid:"#d97706", text:"#92400e" },
  slate:   { fill:"#f8fafc", stroke:"#cbd5e1", solid:"#475569", text:"#1e293b" },
};

const STR = {
  lv: {
    intro: "UAPF (Unified Algorithmic Process Format) atdala procesa definīciju no izpildes. Process tiek glabāts kā versionēta pakete, dzinējs to ielādē un izpilda, bet AI un IT sistēmas pieslēdzas pēc viena kopīga protokola.",
    archTitle: "Sistēmas arhitektūra",
    archHint: "Klikšķiniet uz jebkura komponenta, lai redzētu tā lomu.",
    archDefault: "Izvēlieties komponentu augšā — šeit parādīsies tā apraksts.",
    roleTitle: "Loma sistēmā",
    flowTitle: "Demo plūsma — iesnieguma izskatīšana",
    flowSub: "Reāls process lv.tiesibsargs.iesnieguma-izskatisana: 8 soļi, 3 DMN lēmumu tabulas. Tieši šo palaiž Demo konsole.",
    play: "Atskaņot", pause: "Pauze", reset: "No sākuma",
    step: "Solis", of: "no",
    legend: { ai:"AI solis", decision:"Lēmums (DMN)", io:"Datu solis", event:"Notikums" },
    kindNote: "Katrs solis ir vai nu pakalpojuma uzdevums (serviceTask — izsauc hosta spēju) vai biznesa likuma uzdevums (businessRuleTask — izvērtē DMN tabulu).",
  },
  en: {
    intro: "UAPF (Unified Algorithmic Process Format) separates a process definition from its execution. The process is stored as a versioned package, the engine loads and runs it, and AI and IT systems connect through one shared protocol.",
    archTitle: "System architecture",
    archHint: "Click any component to see its role.",
    archDefault: "Pick a component above — its description will appear here.",
    roleTitle: "Role in the system",
    flowTitle: "Demo flow — complaint triage",
    flowSub: "The real process lv.tiesibsargs.iesnieguma-izskatisana: 8 steps, 3 DMN decision tables. This is exactly what the Demo console runs.",
    play: "Play", pause: "Pause", reset: "Restart",
    step: "Step", of: "of",
    legend: { ai:"AI step", decision:"Decision (DMN)", io:"Data step", event:"Event" },
    kindNote: "Each step is either a service task (serviceTask — calls a host capability) or a business-rule task (businessRuleTask — evaluates a DMN table).",
  },
};

const NODES = {
  llm: { x:322,y:253,w:176,h:74, color:"violet",
    label:"LLM — Opus 4.7", sub:{lv:"Spriešana + AI soļi",en:"Reasoning + AI steps"},
    role:{lv:"Lielais valodas modelis nodrošina čatbota spriešanu un izpilda procesa AI soļus — personas datu maskēšanu un strukturētu faktu izvilkšanu.",
          en:"The large language model powers the chatbot reasoning and performs the process AI steps — redacting personal data and extracting structured facts."} },
  chatbot: { x:322,y:114,w:176,h:72, color:"amber",
    label:"AI Chatbot", sub:{lv:"Sarunu saskarne",en:"Conversational UI"},
    role:{lv:"AI saskarne, kas ļauj cilvēkam dabiskā valodā palaist un izsekot procesus. Procesa definīciju tā nolasa no ProcessGit caur MCP protokolu.",
          en:"An AI interface that lets a person start and follow processes in natural language. It reads the process definition from ProcessGit over the MCP protocol."} },
  user: { x:554,y:119,w:64,h:62, color:"slate",
    label:"Lietotājs", sub:{lv:"Iesniedzējs",en:"Submitter"},
    role:{lv:"Cilvēks, kas iesniedz dokumentu vai vada procesu — caur DMS vai čatbotu. Lēmumu pieņemšana un atbilde paliek cilvēka rokā.",
          en:"The human who submits a document or drives the process — via the DMS or the chatbot. Final judgement and the reply stay with the human."} },
  processgit: { x:78,y:107,w:180,h:86, color:"indigo",
    label:"ProcessGit", sub:{lv:"Procesu reģistrs (SSOT)",en:"Process registry (SSOT)"},
    role:{lv:"Versionētu procesu pakešu glabātava. Katra .uapf pakete satur BPMN plūsmu, DMN lēmumu tabulas un manifestu. Vienīgais patiesības avots procesiem.",
          en:"A versioned store of process packages. Each .uapf package holds a BPMN flow, DMN decision tables and a manifest. The single source of truth for processes."} },
  engine: { x:150,y:367,w:520,h:62, color:"emerald",
    label:"UAPF Dzinējs", sub:{lv:"Izpildes vide — Runtime / SDK",en:"Execution runtime — Runtime / SDK"},
    role:{lv:"Ielādē paketi no ProcessGit un izpilda to: iziet BPMN soļus, izvērtē DMN lēmumu tabulas un izsauc hosta sistēmas spējas. Katrs solis tiek auditēts.",
          en:"Loads a package from ProcessGit and runs it: walks the BPMN steps, evaluates the DMN decision tables and calls host-system capabilities. Every step is audited."} },
  opendms: { x:150,y:461,w:520,h:62, color:"slate",
    label:"OpenDMS", sub:{lv:"DMS hosts — IT sistēma",en:"DMS host — IT system"},
    role:{lv:"Hosta IT sistēma. Glabā dokumentus, realizē procesa spējas (document.fetch, ai.redact, data.write ...) un saņem rezultātu ar pilnu audita pēdu.",
          en:"The host IT system. Stores documents, implements the process capabilities (document.fetch, ai.redact, data.write ...) and receives the result with a full audit trail."} },
};

const EDGES = [
  { d:"M 554 150 L 500 150", lx:527, ly:141, label:{lv:"lieto",en:"uses"}, color:"slate" },
  { d:"M 410 186 L 410 251", lx:410, ly:219, label:{lv:"spriešana",en:"reasoning"}, color:"violet" },
  { d:"M 322 150 L 260 150", lx:291, ly:141, label:{lv:"MCP",en:"MCP"}, color:"amber" },
  { d:"M 168 193 L 168 365", lx:168, ly:279, label:{lv:"UAPF-IP",en:"UAPF-IP"}, color:"indigo" },
  { d:"M 410 327 L 410 365", lx:410, ly:347, label:{lv:"AI soļi",en:"AI steps"}, color:"violet" },
  { d:"M 410 429 L 410 459", lx:410, ly:444, label:{lv:"spējas",en:"capabilities"}, color:"emerald" },
];

const FLOW = [
  { id:"FetchDocument", kind:"io", arch:"opendms", n:1, chip:"document.fetch@1",
    name:{lv:"Saņemt dokumentu no DMS",en:"Fetch document from DMS"},
    desc:{lv:"Dzinējs pieprasa dokumenta saturu, metadatus un pielikumus no OpenDMS, izmantojot spēju document.fetch.",
          en:"The engine requests the document content, metadata and attachments from OpenDMS through the document.fetch capability."} },
  { id:"RedactPii", kind:"ai", arch:"llm", n:2, chip:"ai.redact@1",
    name:{lv:"Maskēt personas datus",en:"Redact personal data"},
    desc:{lv:"AI solis: aizklāj vārdus, personas kodus un adreses pirms tālākas apstrādes — privātums pēc noklusējuma.",
          en:"AI step: masks names, national IDs and addresses before any further processing — privacy by default."} },
  { id:"ExtractFacets", kind:"ai", arch:"llm", n:3, chip:"ai.extract@1",
    name:{lv:"Izvilkt strukturētus faktus",en:"Extract structured facts"},
    desc:{lv:"AI solis: no maskētā teksta izvelk strukturētas pazīmes — vai minēti bērni, diskriminācija, veselība, policija u.c.",
          en:"AI step: from the redacted text it extracts structured signals — whether children, discrimination, health, police etc. are mentioned."} },
  { id:"ClassifyTopic", kind:"decision", arch:"engine", n:4, chip:"classify-topic",
    name:{lv:"Klasificēt tematu",en:"Classify topic"},
    desc:{lv:"DMN lēmumu tabula classify-topic pārvērš pazīmes par tēmu (bērnu tiesības, diskriminācija, veselība ...). Deterministiski un izsekojami.",
          en:"The classify-topic DMN table turns the signals into a topic (children rights, discrimination, health ...). Deterministic and traceable."} },
  { id:"DeterminePriority", kind:"decision", arch:"engine", n:5, chip:"determine-priority",
    name:{lv:"Noteikt prioritāti",en:"Determine priority"},
    desc:{lv:"DMN tabula determine-priority piešķir steidzamību pēc tēmas un satura pazīmēm.",
          en:"The determine-priority DMN table assigns urgency based on the topic and content signals."} },
  { id:"RouteToDepartment", kind:"decision", arch:"engine", n:6, chip:"route-to-department",
    name:{lv:"Maršrutēt uz nodaļu",en:"Route to department"},
    desc:{lv:"DMN tabula route-to-department izvēlas atbildīgo Tiesībsarga biroja nodaļu.",
          en:"The route-to-department DMN table picks the responsible unit of the Ombudsman office."} },
  { id:"RecordClassification", kind:"io", arch:"opendms", n:7, chip:"data.write@1",
    name:{lv:"Saglabāt klasifikāciju",en:"Record classification"},
    desc:{lv:"Dzinējs ieraksta klasifikācijas rezultātu atpakaļ OpenDMS, izmantojot spēju data.write.",
          en:"The engine writes the classification result back into OpenDMS via the data.write capability."} },
  { id:"EmitClassifiedEvent", kind:"event", arch:"engine", n:8, chip:"event.emit@1",
    name:{lv:"Publicēt notikumu",en:"Emit event"},
    desc:{lv:"Tiek publicēts domēna notikums «iesniegums klasificēts». Cilvēka piesaiste un atbildes sagatavošana paliek DMS rokā.",
          en:"A domain event complaint-classified is published. Assigning a person and drafting the reply stay with the DMS."} },
];

const KIND_COLOR = { ai:"violet", decision:"indigo", io:"emerald", event:"amber" };

export default function SystemTab() {
  const [lang, setLang] = useState("lv");
  const [node, setNode] = useState(null);
  const [step, setStep] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const t = STR[lang];

  useEffect(() => {
    if (!playing) return;
    if (step >= FLOW.length - 1) { setPlaying(false); return; }
    const id = setTimeout(() => setStep(s => s + 1), 2100);
    return () => clearTimeout(id);
  }, [playing, step]);

  const onPlay = () => {
    if (playing) { setPlaying(false); return; }
    if (step < 0 || step >= FLOW.length - 1) setStep(0);
    setPlaying(true);
  };
  const onReset = () => { setPlaying(false); setStep(-1); };

  const activeArch = step >= 0 ? FLOW[step].arch : null;
  const sel = node ? NODES[node] : null;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-gray-600 max-w-3xl leading-relaxed">{t.intro}</p>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden shrink-0">
          {["lv","en"].map(l => (
            <button key={l} onClick={() => setLang(l)}
              className={`px-3 py-1.5 text-xs font-semibold ${lang===l ? "bg-emerald-600 text-white" : "bg-white text-gray-500 hover:bg-gray-50"}`}>
              {l.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <section className="bg-white rounded-lg border border-gray-200 p-4">
        <h3 className="font-bold text-gray-900">{t.archTitle}</h3>
        <p className="text-xs text-gray-500 mt-0.5 mb-3">{t.archHint}</p>
        <div className="grid md:grid-cols-3 gap-4">
          <div className="md:col-span-2">
            <svg viewBox="0 0 710 540" className="w-full h-auto select-none">
              <defs>
                <marker id="uapf-ah" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">
                  <path d="M0,0 L7,3 L0,6 Z" fill="#94a3b8" />
                </marker>
              </defs>
              {EDGES.map((e,i) => {
                const ec = C[e.color];
                const lbl = e.label[lang];
                return (
                  <g key={i}>
                    <path d={e.d} fill="none" stroke="#cbd5e1" strokeWidth="2" markerEnd="url(#uapf-ah)" />
                    <circle r="4.5" fill={ec.solid}>
                      <animateMotion dur={`${2.4 + i*0.22}s`} repeatCount="indefinite" path={e.d} />
                    </circle>
                    <rect x={e.lx - (lbl.length*3.5+7)} y={e.ly-9} width={lbl.length*7+14} height="18" rx="9"
                      fill="#ffffff" stroke="#e2e8f0" />
                    <text x={e.lx} y={e.ly+3.5} textAnchor="middle" fontSize="10.5" fontWeight="600" fill={ec.solid}>{lbl}</text>
                  </g>
                );
              })}
              {Object.entries(NODES).map(([id,n]) => {
                const nc = C[n.color];
                const isSel = node === id;
                const isHot = activeArch === id;
                return (
                  <g key={id} onClick={() => setNode(id)} style={{cursor:"pointer"}}>
                    {isHot && (
                      <rect x={n.x-5} y={n.y-5} width={n.w+10} height={n.h+10} rx="15" fill="none" stroke={nc.solid} strokeWidth="2">
                        <animate attributeName="opacity" values="0.15;0.65;0.15" dur="1.4s" repeatCount="indefinite" />
                      </rect>
                    )}
                    <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="12"
                      fill={nc.fill} stroke={isSel||isHot ? nc.solid : nc.stroke} strokeWidth={isSel||isHot ? 2.5 : 1.5} />
                    <text x={n.x+n.w/2} y={n.y+n.h/2-4} textAnchor="middle" fontSize="14.5" fontWeight="700" fill={nc.text}>{n.label}</text>
                    <text x={n.x+n.w/2} y={n.y+n.h/2+13} textAnchor="middle" fontSize="10.5" fill={nc.solid}>{n.sub[lang]}</text>
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="bg-gray-50 rounded-lg border border-gray-200 p-3.5">
            {sel ? (
              <div>
                <div className="inline-flex px-2 py-0.5 rounded text-xs font-semibold mb-2"
                  style={{background:C[sel.color].fill, color:C[sel.color].text, border:`1px solid ${C[sel.color].stroke}`}}>
                  {sel.label}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-gray-400 font-semibold mb-1">{t.roleTitle}</div>
                <p className="text-sm text-gray-700 leading-relaxed">{sel.role[lang]}</p>
              </div>
            ) : (
              <p className="text-sm text-gray-400">{t.archDefault}</p>
            )}
          </div>
        </div>
      </section>

      <section className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h3 className="font-bold text-gray-900">{t.flowTitle}</h3>
            <p className="text-xs text-gray-500 mt-0.5 max-w-2xl">{t.flowSub}</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onPlay} className="px-3 py-1.5 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700">
              {playing ? `\u23F8 ${t.pause}` : `\u25B6 ${t.play}`}
            </button>
            <button onClick={onReset} className="px-3 py-1.5 rounded-md border border-gray-300 text-sm text-gray-600 hover:bg-gray-50">
              {`\u21BB ${t.reset}`}
            </button>
            {step >= 0 && <span className="text-xs text-gray-400 tabular-nums">{t.step} {step+1} {t.of} {FLOW.length}</span>}
          </div>
        </div>

        <div className="flex flex-wrap gap-3 mt-3 mb-1">
          {Object.entries(t.legend).map(([k,lbl]) => (
            <span key={k} className="inline-flex items-center gap-1.5 text-xs text-gray-500">
              <span className="w-2.5 h-2.5 rounded-full" style={{background:C[KIND_COLOR[k]].solid}} />
              {lbl}
            </span>
          ))}
        </div>
        <p className="text-[11px] text-gray-400 mb-3">{t.kindNote}</p>

        <div>
          {FLOW.map((s,i) => {
            const sc = C[KIND_COLOR[s.kind]];
            const active = step === i;
            const done = step > i;
            return (
              <div key={s.id} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-all"
                    style={{
                      background: active||done ? sc.solid : sc.fill,
                      color: active||done ? "#ffffff" : sc.text,
                      border: `2px solid ${sc.solid}`,
                      boxShadow: active ? `0 0 0 4px ${sc.fill}` : "none",
                    }}>
                    {done ? "\u2713" : s.n}
                  </div>
                  {i < FLOW.length-1 && (
                    <div className="w-0.5 flex-1 my-1" style={{background: done ? sc.solid : "#e5e7eb", minHeight:"14px"}} />
                  )}
                </div>
                <div onClick={() => { setStep(i); setPlaying(false); }}
                  className={`flex-1 mb-2 rounded-lg border p-3 cursor-pointer transition-all ${active ? "shadow-sm" : "hover:bg-gray-50"}`}
                  style={{ borderColor: active ? sc.solid : "#e5e7eb", background: active ? sc.fill : "#ffffff" }}>
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-gray-900">{s.name[lang]}</span>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-medium" style={{background:sc.fill,color:sc.text}}>
                        {t.legend[s.kind]}
                      </span>
                      <code className="text-[10px] text-gray-400">{s.chip}</code>
                    </div>
                  </div>
                  {active && <p className="text-xs text-gray-600 mt-2 leading-relaxed">{s.desc[lang]}</p>}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
