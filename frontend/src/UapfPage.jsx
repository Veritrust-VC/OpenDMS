// UAPF Processes — admin dashboard.
// Four tabs: Demo Console, Triggers, Sessions, Package Library.
// Single file ~600 lines; matches the existing OpenDMS App.jsx style
// (tailwind utility classes, hooks-only, no router).

import { useState, useEffect, useCallback, useRef } from "react";
import SystemTab from "./SystemTab.jsx";
import BpmnDiagram from "./components/BpmnDiagram";
import DmnTableView from "./components/DmnTableView";

// ─── API helper (matches App.jsx pattern) ─────────────────────
async function uapfApi(path, opts = {}) {
  const token = localStorage.getItem("opendms_token") || "";
  const r = await fetch("/api" + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...opts.headers,
    },
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const j = await r.json(); msg = j.detail || j.error || msg; } catch {}
    throw new Error(msg);
  }
  if (r.status === 204) return null;
  return r.json();
}

// ─── BPMN step definitions (matches the bundled UAPF package) ─
const PROCESS_STEPS = [
  { id: "Start",                key: "start",       label: "Iesniegums saņemts",       kind: "event" },
  { id: "FetchDocument",        key: "fetch",       label: "Dokumenta saturs",          kind: "service", op: "document.fetch" },
  { id: "RedactPii",            key: "redact",      label: "PII anonimizācija",         kind: "service", op: "ai.redact" },
  { id: "ExtractFacets",        key: "extract",     label: "Faktu izvilkšana",          kind: "service", op: "ai.extract" },
  { id: "ClassifyTopic",        key: "classify",    label: "Tēmas klasifikācija",       kind: "rule",    op: "DMN" },
  { id: "DeterminePriority",    key: "priority",    label: "Prioritātes noteikšana",    kind: "rule",    op: "DMN" },
  { id: "RouteToDepartment",    key: "route",       label: "Maršrutēšana uz nodaļu",    kind: "rule",    op: "DMN" },
  { id: "RecordClassification", key: "record",      label: "Klasifikācijas saglabāšana", kind: "service", op: "data.write" },
  { id: "EmitClassifiedEvent",  key: "emit",        label: "Notikuma publicēšana",      kind: "service", op: "event.emit" },
  { id: "End",                  key: "end",         label: "Klasifikācija pabeigta",    kind: "event" },
];

const TOPIC_LABELS = {
  "child-rights":           "Bērnu tiesības",
  "discrimination":         "Diskriminācija",
  "prisoner-rights":        "Ieslodzīto tiesības",
  "law-enforcement-rights": "Tiesībaizsardzība",
  "health-rights":          "Veselības aprūpe",
  "social-rights":          "Sociālās tiesības",
  "privacy-rights":         "Privātums",
  "good-governance":        "Laba pārvaldība",
  "other":                  "Cits",
};

const PRIORITY_STYLE = {
  urgent: "bg-red-100 text-red-700 border-red-200",
  high:   "bg-orange-100 text-orange-700 border-orange-200",
  normal: "bg-emerald-100 text-emerald-700 border-emerald-200",
  low:    "bg-gray-100 text-gray-600 border-gray-200",
};


// ═══════════════════════════════════════════════════════════════
// Main page
// ═══════════════════════════════════════════════════════════════

export default function UapfPage({ notify, user, route, navigate }) {
  const TAB_IDS = ["system", "demo", "triggers", "sessions", "packages"];
  const tab = TAB_IDS.includes(route && route[1]) ? route[1] : "system";
  const itemId = route && route[2] ? decodeURIComponent(route[2]) : null;
  const setTab = (id) => navigate("/uapf/" + id);

  const tabs = [
    { id: "system",   label: "Sistēma",       icon: "🗺"  },
    { id: "demo",     label: "Demo konsole",  icon: "▶"  },
    { id: "triggers", label: "Trigeri",       icon: "⚙"  },
    { id: "sessions", label: "Sesijas",       icon: "📜" },
    { id: "packages", label: "Pakešu bibliotēka", icon: "📦" },
  ];

  return (
    <div>
      <header className="mb-4">
        <h1 className="text-2xl font-bold text-gray-900">UAPF procesi</h1>
        <p className="text-sm text-gray-500 mt-1">
          Algoritmizēta dokumentu apstrāde — Tiesībsarga iesniegumu klasifikācija pēc UAPF-IP standarta
        </p>
      </header>

      <div className="border-b border-gray-200 mb-5">
        <nav className="flex gap-1">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
                tab === t.id
                  ? "border-emerald-600 text-emerald-700"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}>
              <span className="mr-1.5">{t.icon}</span>{t.label}
            </button>
          ))}
        </nav>
      </div>

      {tab === "system"   && <SystemTab />}
      {tab === "demo"     && <DemoConsole notify={notify} navigate={navigate} selectedRef={itemId} />}
      {tab === "triggers" && <TriggersTab notify={notify} />}
      {tab === "sessions" && <SessionsTab notify={notify} navigate={navigate} selectedId={itemId} />}
      {tab === "packages" && <PackagesTab notify={notify} user={user} />}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// Demo console — pick an iesniegums, run UAPF, watch the flow
// ═══════════════════════════════════════════════════════════════

function DemoConsole({ notify, navigate, selectedRef }) {
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    if (!selectedRef) { setSelected(null); return; }
    const m = docs.find(d => String(d.registration_number) === selectedRef || String(d.id) === selectedRef);
    if (m) setSelected(m);
  }, [selectedRef, docs]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  // Package metadata (name, description, EU AI Act class, decisions, triggers)
  // Loaded once on mount via /api/uapf/packages/{id}/info.
  const [pkgInfo, setPkgInfo] = useState(null);
  const [showDecisions, setShowDecisions] = useState(false);
  // Raw BPMN XML (fed to bpmn-js for diagram rendering)
  const [bpmnXml, setBpmnXml] = useState(null);
  const [algorithmCards, setAlgorithmCards] = useState({});
  // Raw DMN XMLs keyed by decision id
  const [dmnXmls, setDmnXmls] = useState({});
  // Step ids that have completed during the current run (for live highlighting)
  const [completedStepIds, setCompletedStepIds] = useState([]);
  const [activeStepId, setActiveStepId] = useState(null);

  // Run state
  const [running, setRunning] = useState(false);
  const [activeStep, setActiveStep] = useState(-1);
  const [sessionResult, setSessionResult] = useState(null);
  const [runError, setRunError] = useState(null);
  const animateTimer = useRef(null);

  const loadDocs = useCallback(async () => {
    setLoading(true);
    try {
      // Get all demo-fixture documents (registration_number starts DEMO-)
      const all = await uapfApi("/documents?limit=100");
      const demos = (all.items || all).filter(d =>
        d.registration_number && d.registration_number.startsWith("DEMO-")
      );
      setDocs(demos);
    } catch (e) {
      notify({ t: "error", m: "Nevarēja ielādēt dokumentus: " + e.message });
    }
    setLoading(false);
  }, [notify]);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  // Load package info + raw BPMN/DMN XML once on mount. The XMLs drive the
  // bpmn-js diagram and dmn-js decision tables. Refresh after ProcessGit sync.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const PKG = "lv.tiesibsargs.iesnieguma-izskatisana";
      try {
        const info = await uapfApi(`/uapf/packages/${PKG}/info`);
        if (cancelled) return;
        setPkgInfo(info);

        // Fetch raw BPMN — use authorisation header via uapfApi which handles auth
        const procId = info.process?.id || "iesnieguma-izskatisana";
        const bpmnRes = await fetch(`/api/uapf/packages/${PKG}/bpmn/${procId}.xml`, {
          headers: { Authorization: `Bearer ${localStorage.getItem("opendms_token") || ""}` },
        });
        if (bpmnRes.ok && !cancelled) setBpmnXml(await bpmnRes.text());

        // Fetch all DMN XMLs (one per decision)
        const xmls = {};
        for (const d of info.decisions || []) {
          try {
            const r = await fetch(`/api/uapf/packages/${PKG}/dmn/${d.id}.xml`, {
              headers: { Authorization: `Bearer ${localStorage.getItem("opendms_token") || ""}` },
            });
            if (r.ok) xmls[d.id] = await r.text();
          } catch {}
        }
        if (!cancelled) setDmnXmls(xmls);

        // UAPF v2.4.0: fetch algorithm cards for the package, keyed by id.
        // Returns 0 cards for packages without algorithm cards (graceful).
        try {
          const data = await uapfApi(`/uapf/packages/${PKG}/algorithms`);
          if (!cancelled && data && Array.isArray(data.algorithms)) {
            const byRef = {};
            for (const c of data.algorithms) {
              if (c && c.id) byRef[c.id] = c;
            }
            setAlgorithmCards(byRef);
          }
        } catch (e) {
          // Endpoint may not exist on older engines; just skip overlays.
          console.debug("Algorithm cards endpoint unavailable:", e.message);
        }
      } catch (e) {
        console.warn("Could not load package info:", e.message);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const seedDemoData = async () => {
    setSeeding(true);
    try {
      const r = await uapfApi("/uapf/seed-demo-data", { method: "POST", body: "{}" });
      notify({ t: r.created > 0 ? "ok" : "info",
               m: r.created > 0 ? `Izveidoti ${r.created} demo iesniegumi` : r.message });
      await loadDocs();
    } catch (e) {
      notify({ t: "error", m: "Demo datu izveide neizdevās: " + e.message });
    }
    setSeeding(false);
  };

  const resetRun = () => {
    if (animateTimer.current) clearTimeout(animateTimer.current);
    setRunning(false);
    setActiveStep(-1);
    setActiveStepId(null);
    setCompletedStepIds([]);
    setSessionResult(null);
    setRunError(null);
  };

  const runUapf = async () => {
    if (!selected) return;
    resetRun();
    setRunning(true);
    setActiveStep(0);

    let result;
    try {
      result = await uapfApi(`/uapf/run-now/${selected.id}`, {
        method: "POST",
        body: JSON.stringify({
          event_type: "manual",
          package_id: "lv.tiesibsargs.iesnieguma-izskatisana",
          process_id: "iesnieguma-izskatisana",
        }),
      });
    } catch (e) {
      setRunError(e.message);
      setRunning(false);
      return;
    }

    // Animate the step progression for visual effect (real exec is <8s sync;
    // we replay it visually). 500ms between steps = readable on stage.
    let i = 0;
    const completed = [];
    setActiveStepId(PROCESS_STEPS[0].id);
    setCompletedStepIds([]);
    const tick = () => {
      i += 1;
      setActiveStep(i);
      if (i < PROCESS_STEPS.length) {
        // Mark prior step as completed, point active to the next one
        const prev = PROCESS_STEPS[i - 1];
        if (prev && prev.id) completed.push(prev.id);
        setCompletedStepIds([...completed]);
        const next = PROCESS_STEPS[i];
        setActiveStepId(next ? next.id : null);
        animateTimer.current = setTimeout(tick, 500);
      } else {
        // Final step — mark everything completed
        setCompletedStepIds(PROCESS_STEPS.filter(s => s.id).map(s => s.id));
        setActiveStepId(null);
        setSessionResult(result?.result || result);
        setRunning(false);
      }
    };
    animateTimer.current = setTimeout(tick, 500);
  };

  useEffect(() => () => { if (animateTimer.current) clearTimeout(animateTimer.current); }, []);

  return (
    <div className="grid grid-cols-12 gap-4">
      {/* Left: doc picker */}
      <div className="col-span-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-700">Iesniegumu saraksts</h2>
          {docs.length === 0 && (
            <button onClick={seedDemoData} disabled={seeding}
              className="text-xs px-2 py-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 disabled:opacity-50">
              {seeding ? "..." : "+ Izveidot 6 demo iesniegumus"}
            </button>
          )}
        </div>
        {loading && <div className="text-sm text-gray-400">Ielādē...</div>}
        {!loading && docs.length === 0 && (
          <div className="text-sm text-gray-500 bg-gray-50 border border-dashed border-gray-300 rounded p-4">
            Nav demo iesniegumu. Klikšķiniet <em>+ Izveidot 6 demo iesniegumus</em>, lai sāktu.
          </div>
        )}
        <div className="space-y-1.5 max-h-[600px] overflow-y-auto">
          {docs.map(d => (
            <button key={d.id} onClick={() => { navigate("/uapf/demo/" + encodeURIComponent(d.registration_number)); resetRun(); }}
              className={`w-full text-left rounded border p-3 transition-colors ${
                selected?.id === d.id
                  ? "border-emerald-400 bg-emerald-50"
                  : "border-gray-200 bg-white hover:border-gray-300"
              }`}>
              <div className="flex items-start justify-between gap-2">
                <div className="font-medium text-sm text-gray-900">{d.title}</div>
                <span className="text-xs text-gray-400 shrink-0">{d.registration_number}</span>
              </div>
              {d.metadata?.expected_topic && (
                <div className="mt-1 text-xs text-gray-500">
                  Gaidāmā tēma: <span className="font-mono">{d.metadata.expected_topic}</span>
                </div>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Right: detail + run + flow */}
      <div className="col-span-8 space-y-4">
        {/* Process info card — always visible, even without doc selected */}
        {pkgInfo && <ProcessInfoCard info={pkgInfo} />}

        {!selected && (
          <div className="rounded border border-dashed border-gray-300 bg-white p-8 text-center text-gray-400">
            Izvēlieties iesniegumu kreisajā pusē, lai sāktu demo.
          </div>
        )}
        {selected && (
          <div className="space-y-4">
            <div className="bg-white rounded border border-gray-200 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-xs text-gray-400 mb-0.5">{selected.registration_number}</div>
                  <h3 className="font-semibold text-gray-900">{selected.title}</h3>
                </div>
                <button onClick={runUapf} disabled={running}
                  className="px-4 py-2 rounded bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 shrink-0">
                  {running ? "Izpildās..." : "▶ Palaist UAPF procesu"}
                </button>
              </div>
              {selected.content_summary && (
                <p className="mt-3 text-sm text-gray-600 italic border-l-2 border-gray-200 pl-3">
                  {selected.content_summary}
                </p>
              )}
              {runError && (
                <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
                  Kļūda: {runError}
                </div>
              )}
            </div>

            {/* BPMN diagram — real bpmn-js render of the package XML.
                Live-highlights the current step amber and completed steps green. */}
            {(running || sessionResult) && (
              <div className="bg-white rounded border border-gray-200 p-4">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="font-semibold text-sm text-gray-700">BPMN izpilde</h4>
                  {!running && (
                    <button onClick={resetRun}
                      className="text-xs text-gray-500 hover:text-gray-700">
                      ↺ Atiestatīt
                    </button>
                  )}
                </div>
                {bpmnXml ? (
                  <BpmnDiagram
                    xml={bpmnXml}
                    activeStepId={activeStepId}
                    completedStepIds={completedStepIds}
                    algorithmCards={algorithmCards}
                    height={380}
                  />
                ) : (
                  <FlowVisualization activeStep={activeStep} />
                )}
              </div>
            )}

            {/* Result card */}
            {sessionResult && <ClassificationResultCard result={sessionResult} />}

            {/* DMN decisions — collapsible. Shows the actual rules the engine
                evaluated, with the rule that fired highlighted when available. */}
            {pkgInfo && pkgInfo.decisions && pkgInfo.decisions.length > 0 && (
              <div className="bg-white rounded border border-gray-200">
                <button onClick={() => setShowDecisions(s => !s)}
                  className="w-full flex items-center justify-between p-4 hover:bg-gray-50 text-left">
                  <div>
                    <h4 className="font-semibold text-sm text-gray-800">Lēmumu loģika ({pkgInfo.decisions.length} DMN tabulas)</h4>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Šīs ir tās pašas tabulas, kas dzīvo ProcessGit repozitorijā. Tās izmaiņas pēc sinhronizācijas mainīs procesa uzvedību.
                    </p>
                  </div>
                  <span className="text-gray-400 text-sm">{showDecisions ? "▾" : "▸"}</span>
                </button>
                {showDecisions && (
                  <div className="border-t border-gray-200 p-4 space-y-4">
                    {pkgInfo.decisions.map(d => {
                      // Pick which rule fired in this decision, if we have a result
                      let firedRuleId = null;
                      if (sessionResult && sessionResult.output) {
                        const out = sessionResult.output;
                        if (d.id === "classify-topic" && out.topic) {
                          firedRuleId = (d.rules.find(r => r.then[0] === out.topic) || {}).id;
                        } else if (d.id === "determine-priority" && out.priority) {
                          firedRuleId = (d.rules.find(r =>
                            r.then[0] === out.priority && Number(r.then[1]) === Number(out.slaHours)
                          ) || {}).id;
                        } else if (d.id === "route-to-department" && out.department) {
                          firedRuleId = (d.rules.find(r => r.then[0] === out.department) || {}).id;
                        }
                      }
                      const xml = dmnXmls[d.id];
                      return (
                        <div key={d.id}>
                          <div className="flex items-baseline gap-2 mb-1">
                            <h5 className="font-medium text-sm text-gray-800">{d.name}</h5>
                            <span className="text-[10px] text-gray-400 font-mono">{d.id}</span>
                            <span className="text-[10px] text-gray-400">hit policy: {d.hitPolicy}</span>
                            {firedRuleId && (
                              <span className="text-[10px] text-amber-700 ml-auto">
                                Iedarbojās noteikums: <span className="font-mono font-semibold">{firedRuleId}</span>
                              </span>
                            )}
                          </div>
                          {xml
                            ? <DmnTableView xml={xml} firedRuleId={firedRuleId} />
                            : <DecisionTable decision={d} sessionResult={sessionResult} />}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ProcessInfoCard({ info }) {
  const m = info.manifest || {};
  const proc = info.process || {};
  const triggers = info.triggers || { active: [], all: [] };
  const matches_doc_event = triggers.active.some(t =>
    ["document.received", "document.created", "manual"].includes(t.trigger_event)
  );

  // Pull source URL from manifest owners (if present) — best-effort
  const sourceUrl = `https://processgit.org/AI_Sandbox/${proc.id || "iesnieguma-izskatisana"}`;

  return (
    <div className="bg-gradient-to-br from-emerald-50 to-white rounded border border-emerald-200 p-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold">
            UAPF process · v{m.version || "?"} · {m.lifecycle || ""}
          </div>
          <h2 className="font-semibold text-base text-gray-900 mt-0.5">
            {m.name || proc.name || info.packageId}
          </h2>
        </div>
        <a href={sourceUrl} target="_blank" rel="noopener"
           className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-white shrink-0">
          ↗ ProcessGit
        </a>
      </div>

      {m.description && (
        <p className="text-sm text-gray-700 leading-relaxed mb-3">
          {m.description.split(". ").slice(0, 2).join(". ")}{m.description.split(". ").length > 2 ? "." : ""}
        </p>
      )}

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="bg-white rounded border border-gray-200 p-2">
          <div className="text-gray-400 uppercase tracking-wider text-[10px]">Trigeris</div>
          <div className={`mt-1 font-medium ${matches_doc_event ? "text-emerald-700" : "text-gray-500"}`}>
            {matches_doc_event ? "✓ Auto pēc dokumenta saņemšanas" : "Tikai manuāli"}
          </div>
        </div>
        <div className="bg-white rounded border border-gray-200 p-2">
          <div className="text-gray-400 uppercase tracking-wider text-[10px]">Soļi</div>
          <div className="mt-1 font-medium text-gray-700">
            {(proc.steps || []).length} BPMN + {(info.decisions || []).length} DMN
          </div>
        </div>
        <div className="bg-white rounded border border-gray-200 p-2">
          <div className="text-gray-400 uppercase tracking-wider text-[10px]">EU AI akts</div>
          <div className="mt-1 font-medium text-amber-700" title={m.eu_ai_act_classification || ""}>
            {m.eu_ai_act_classification ? "⚠ Augsta riska (Annex III)" : "-"}
          </div>
        </div>
      </div>

      {m.algorithms && m.algorithms.length > 0 && (
        <div className="mt-3 pt-2 border-t border-gray-200">
          <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Algoritmi paketē</div>
          <ul className="space-y-1">
            {m.algorithms.map(a => (
              <li key={a.id} className="text-xs leading-relaxed">
                <code className="font-mono text-emerald-700 font-semibold">{a.id}</code>
                <span className="text-gray-700"> — {a.name}</span>
                {a.prompt && (
                  <div className="text-gray-400 ml-2 mt-0.5">
                    prompt: <code className="font-mono">{a.prompt}</code>
                    {a.output_schema && <> · schema: <code className="font-mono">{a.output_schema}</code></>}
                  </div>
                )}
                {a.consumers && a.consumers.length > 0 && (
                  <div className="text-gray-500 ml-2">
                    izsauc: {a.consumers.join("; ")}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {m.legal_basis && m.legal_basis.length > 0 && (
        <div className="mt-3 pt-2 border-t border-gray-200">
          <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Juridiskais pamats</div>
          <div className="text-xs text-gray-600">{m.legal_basis.join(" · ")}</div>
        </div>
      )}
    </div>
  );
}

function DecisionTable({ decision, sessionResult }) {
  // Figure out which rule fired for this decision (best-effort from sessionResult.output)
  let firedRuleId = null;
  if (sessionResult && sessionResult.output) {
    const out = sessionResult.output;
    if (decision.id === "classify-topic" && out.topic) {
      // Match by output value
      firedRuleId = (decision.rules.find(r => r.then[0] === out.topic) || {}).id;
    } else if (decision.id === "determine-priority" && out.priority) {
      firedRuleId = (decision.rules.find(r =>
        r.then[0] === out.priority && Number(r.then[1]) === Number(out.slaHours)
      ) || {}).id;
    } else if (decision.id === "route-to-department" && out.department) {
      firedRuleId = (decision.rules.find(r => r.then[0] === out.department) || {}).id;
    }
  }

  return (
    <div>
      <div className="flex items-baseline gap-2 mb-1">
        <h5 className="font-medium text-sm text-gray-800">{decision.name}</h5>
        <span className="text-[10px] text-gray-400 font-mono">{decision.id}</span>
        <span className="text-[10px] text-gray-400">hit policy: {decision.hitPolicy}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="text-xs border border-gray-200 rounded">
          <thead>
            <tr className="bg-gray-50">
              <th className="text-left px-2 py-1 border-b border-gray-200 text-gray-500 font-medium">#</th>
              {decision.inputs.map((inp, i) => (
                <th key={i} className="text-left px-2 py-1 border-b border-l border-gray-200 text-gray-500 font-medium">
                  {inp.label}
                </th>
              ))}
              {decision.outputs.map((out, i) => (
                <th key={i} className="text-left px-2 py-1 border-b border-l border-gray-200 bg-emerald-50 text-emerald-800 font-medium">
                  → {out.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {decision.rules.map(r => {
              const isFired = r.id === firedRuleId;
              return (
                <tr key={r.id}
                    className={isFired ? "bg-amber-50 ring-2 ring-amber-300" : "hover:bg-gray-50"}>
                  <td className="px-2 py-1 border-b border-gray-200 text-gray-400 font-mono">{r.id}{isFired ? " ✓" : ""}</td>
                  {r.when.map((v, i) => (
                    <td key={i} className="px-2 py-1 border-b border-l border-gray-200 font-mono text-gray-600">
                      {v === "-" ? <span className="text-gray-300">—</span> : v}
                    </td>
                  ))}
                  {r.then.map((v, i) => (
                    <td key={i} className="px-2 py-1 border-b border-l border-gray-200 font-mono text-emerald-700">{v}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function FlowVisualization({ activeStep }) {
  return (
    <ol className="space-y-1.5">
      {PROCESS_STEPS.map((s, i) => {
        const isDone    = i < activeStep;
        const isActive  = i === activeStep - 1;
        const isPending = i >= activeStep;
        const dot = isDone
          ? "bg-emerald-500 border-emerald-500 text-white"
          : isActive
            ? "bg-emerald-100 border-emerald-500 text-emerald-700 animate-pulse"
            : "bg-white border-gray-300 text-gray-300";
        return (
          <li key={s.id} className="flex items-center gap-3 text-sm">
            <span className={`w-7 h-7 rounded-full border-2 flex items-center justify-center text-xs font-semibold flex-shrink-0 ${dot}`}>
              {isDone ? "✓" : i + 1}
            </span>
            <span className={`font-medium ${isPending ? "text-gray-400" : "text-gray-900"}`}>
              {s.label}
            </span>
            {s.op && (
              <span className={`ml-auto text-xs font-mono ${isPending ? "text-gray-300" : "text-gray-500"}`}>
                {s.op}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function ClassificationResultCard({ result }) {
  const output = result?.output || {};
  const topic = output.topic;
  const priority = output.priority;
  const department = output.department;
  const reviewerRole = output.reviewerRole;
  const slaHours = output.slaHours;
  const confidence = output.topicConfidence;
  const sessionId = result?.sessionId;

  return (
    <div className="bg-gradient-to-br from-emerald-50 to-white rounded border-2 border-emerald-300 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold text-emerald-900">Klasifikācijas rezultāts</h4>
        {sessionId && (
          <span className="text-xs text-gray-500 font-mono">{sessionId}</span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">Tēma</div>
          <div className="text-lg font-semibold text-gray-900">
            {TOPIC_LABELS[topic] || topic || "—"}
          </div>
          {confidence != null && (
            <div className="text-xs text-gray-500 mt-0.5">
              Pārliecība: {(confidence * 100).toFixed(0)}%
            </div>
          )}
        </div>

        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">Prioritāte</div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`px-2 py-0.5 rounded text-sm font-semibold border ${PRIORITY_STYLE[priority] || "bg-gray-100"}`}>
              {priority || "—"}
            </span>
            {slaHours && (
              <span className="text-xs text-gray-500">
                SLA {slaHours}h ({Math.round(slaHours/24)} dn.)
              </span>
            )}
          </div>
        </div>

        <div className="col-span-2 mt-2 pt-3 border-t border-emerald-200">
          <div className="text-xs uppercase tracking-wide text-gray-500">Maršrutēšana</div>
          <div className="text-base font-medium text-gray-900 mt-0.5">{department || "—"}</div>
          <div className="text-sm text-gray-600 font-mono">{reviewerRole || "—"}</div>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// Triggers tab
// ═══════════════════════════════════════════════════════════════

function TriggersTab({ notify }) {
  const [triggers, setTriggers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setTriggers(await uapfApi("/uapf/triggers")); }
    catch (e) { notify({ t: "error", m: e.message }); }
    setLoading(false);
  }, [notify]);

  useEffect(() => { load(); }, [load]);

  const toggleActive = async (t) => {
    try {
      await uapfApi(`/uapf/triggers/${t.id}`, {
        method: "PUT",
        body: JSON.stringify({ is_active: !t.is_active }),
      });
      await load();
    } catch (e) { notify({ t: "error", m: e.message }); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-500">
          Trigeri nosaka, kuri dokumenta lifecycle notikumi palaiž UAPF procesu.
        </p>
        <button onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 rounded bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700">
          + Jauns trigeris
        </button>
      </div>

      {loading && <div className="text-sm text-gray-400">Ielādē...</div>}

      {!loading && triggers.length === 0 && (
        <div className="text-sm text-gray-500 bg-gray-50 border border-dashed border-gray-300 rounded p-4">
          Nav definētu trigeru.
        </div>
      )}

      {!loading && triggers.length > 0 && (
        <table className="w-full text-sm border border-gray-200 bg-white rounded overflow-hidden">
          <thead className="bg-gray-50">
            <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
              <th className="px-3 py-2">Aktīvs</th>
              <th className="px-3 py-2">Nosaukums</th>
              <th className="px-3 py-2">Trigeris</th>
              <th className="px-3 py-2">Pakete / Process</th>
              <th className="px-3 py-2">Filtrs</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {triggers.map(t => (
              <tr key={t.id} className="border-t border-gray-100">
                <td className="px-3 py-2">
                  <button onClick={() => toggleActive(t)}
                    className={`w-9 h-5 rounded-full transition-colors relative ${
                      t.is_active ? "bg-emerald-500" : "bg-gray-300"
                    }`}>
                    <span className={`block w-3.5 h-3.5 bg-white rounded-full absolute top-0.5 transition-transform ${
                      t.is_active ? "translate-x-5" : "translate-x-0.5"
                    }`}/>
                  </button>
                </td>
                <td className="px-3 py-2">
                  <div className="font-medium text-gray-900">{t.name}</div>
                  {t.description && <div className="text-xs text-gray-500 max-w-md">{t.description}</div>}
                </td>
                <td className="px-3 py-2"><span className="font-mono text-xs">{t.trigger_event}</span></td>
                <td className="px-3 py-2">
                  <div className="font-mono text-xs">{t.package_id}</div>
                  <div className="font-mono text-xs text-gray-500">{t.process_id}</div>
                </td>
                <td className="px-3 py-2">
                  <code className="text-xs bg-gray-50 px-1 py-0.5 rounded">
                    {JSON.stringify(t.match_condition || {})}
                  </code>
                </td>
                <td className="px-3 py-2 text-right">
                  <span className="text-xs text-gray-400">#{t.id}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showCreate && (
        <CreateTriggerModal onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); load(); }} notify={notify} />
      )}
    </div>
  );
}

function CreateTriggerModal({ onClose, onCreated, notify }) {
  const [form, setForm] = useState({
    name: "",
    description: "",
    package_id: "lv.tiesibsargs.iesnieguma-izskatisana",
    process_id: "iesnieguma-izskatisana",
    trigger_event: "document.received",
    match_condition: "{}",
    is_active: true,
  });
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      let match_condition;
      try { match_condition = JSON.parse(form.match_condition || "{}"); }
      catch { throw new Error("Filtrs nav korekts JSON"); }
      await uapfApi("/uapf/triggers", {
        method: "POST",
        body: JSON.stringify({ ...form, match_condition }),
      });
      notify({ t: "ok", m: "Trigeris izveidots" });
      onCreated();
    } catch (e) {
      notify({ t: "error", m: e.message });
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg p-5">
        <h3 className="text-lg font-semibold mb-4">Jauns trigeris</h3>
        <div className="space-y-3">
          {[
            ["Nosaukums",   "name",          "Tiesībsargs — DocumentReceived"],
            ["Apraksts",    "description",   ""],
            ["package_id",  "package_id",    ""],
            ["process_id",  "process_id",    ""],
          ].map(([label, key, ph]) => (
            <div key={key}>
              <label className="text-xs text-gray-500 font-medium">{label}</label>
              <input value={form[key]} onChange={e => setForm({...form, [key]: e.target.value})}
                placeholder={ph}
                className="w-full mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded focus:border-emerald-500 focus:outline-none"/>
            </div>
          ))}
          <div>
            <label className="text-xs text-gray-500 font-medium">Notikums</label>
            <select value={form.trigger_event} onChange={e => setForm({...form, trigger_event: e.target.value})}
              className="w-full mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded focus:border-emerald-500 focus:outline-none">
              <option value="document.created">document.created</option>
              <option value="document.received">document.received</option>
              <option value="document.assigned">document.assigned</option>
              <option value="document.decided">document.decided</option>
              <option value="manual">manual</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 font-medium">Filtrs (JSON match_condition)</label>
            <textarea value={form.match_condition} onChange={e => setForm({...form, match_condition: e.target.value})}
              rows={3}
              className="w-full mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded font-mono focus:border-emerald-500 focus:outline-none"/>
            <div className="text-xs text-gray-400 mt-1">Tukšs <code>{`{}`}</code> = atbilst visiem dokumentiem.</div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800">Atcelt</button>
          <button onClick={submit} disabled={submitting || !form.name}
            className="px-3 py-1.5 text-sm bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50">
            Izveidot
          </button>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// Sessions tab
// ═══════════════════════════════════════════════════════════════

function SessionsTab({ notify, navigate, selectedId }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const expanded = selectedId || null;
  const [detail, setDetail] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try { setSessions(await uapfApi("/uapf/sessions?limit=50")); }
    catch (e) { notify({ t: "error", m: e.message }); }
    setLoading(false);
  }, [notify]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (selectedId) loadDetail(selectedId); }, [selectedId]);

  const loadDetail = async (sid) => {
    if (detail[sid]) return;
    try {
      const d = await uapfApi(`/uapf/sessions/${encodeURIComponent(sid)}`);
      setDetail(prev => ({ ...prev, [sid]: d }));
    } catch (e) { notify({ t: "error", m: e.message }); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-500">
          Visu UAPF procesa izpilžu žurnāls. Klikšķiniet uz rindas, lai apskatītu audit chain.
        </p>
        <button onClick={load} className="text-sm text-emerald-700 hover:text-emerald-900">↻ Atjaunot</button>
      </div>

      {loading && <div className="text-sm text-gray-400">Ielādē...</div>}

      {!loading && sessions.length === 0 && (
        <div className="text-sm text-gray-500 bg-gray-50 border border-dashed border-gray-300 rounded p-4">
          Nav vēl nevienas izpildes. Atveriet Demo konsoli un palaidiet UAPF procesu uz kāda iesnieguma.
        </div>
      )}

      {!loading && sessions.length > 0 && (
        <div className="bg-white rounded border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="px-3 py-2">Sākts</th>
                <th className="px-3 py-2">Doc</th>
                <th className="px-3 py-2">Pakete / Process</th>
                <th className="px-3 py-2">Trigeris</th>
                <th className="px-3 py-2">Statuss</th>
                <th className="px-3 py-2 text-right">Session ID</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map(s => (
                <>
                  <tr key={s.session_id}
                      onClick={() => { navigate(expanded === s.session_id ? "/uapf/sessions" : "/uapf/sessions/" + encodeURIComponent(s.session_id)); }}
                      className="border-t border-gray-100 cursor-pointer hover:bg-gray-50">
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {new Date(s.started_at).toLocaleString("lv-LV")}
                    </td>
                    <td className="px-3 py-2 text-xs">#{s.document_id}</td>
                    <td className="px-3 py-2">
                      <div className="font-mono text-xs">{s.package_id}</div>
                      <div className="font-mono text-xs text-gray-500">{s.process_id}</div>
                    </td>
                    <td className="px-3 py-2 text-xs">{s.trigger_name || "—"}</td>
                    <td className="px-3 py-2">
                      <StateBadge state={s.state} />
                    </td>
                    <td className="px-3 py-2 text-right text-xs font-mono text-gray-400">{s.session_id}</td>
                  </tr>
                  {expanded === s.session_id && detail[s.session_id] && (
                    <tr><td colSpan={6} className="bg-gray-50 px-4 py-3 border-t border-gray-100">
                      <SessionDetail data={detail[s.session_id]} />
                    </td></tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StateBadge({ state }) {
  const c = {
    completed: "bg-emerald-100 text-emerald-700",
    active:    "bg-blue-100 text-blue-700",
    starting:  "bg-blue-100 text-blue-700",
    failed:    "bg-red-100 text-red-700",
    aborted:   "bg-gray-100 text-gray-600",
  };
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${c[state] || "bg-gray-100"}`}>{state}</span>;
}

function SessionDetail({ data }) {
  const events = data.audit_chain_persisted || [];
  const output = data.output_payload || {};
  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <div className="text-xs font-semibold text-gray-700 mb-1">Audit chain (persisted)</div>
        {events.length === 0 && <div className="text-xs text-gray-400">Nav notikumu</div>}
        <ol className="space-y-1 max-h-64 overflow-y-auto">
          {events.map(e => (
            <li key={e.id} className="text-xs flex items-start gap-2 bg-white border border-gray-200 rounded p-1.5">
              <span className="text-gray-400 font-mono shrink-0">{new Date(e.created_at).toLocaleTimeString("lv-LV")}</span>
              <span className="font-mono text-emerald-700">{e.event_type}</span>
            </li>
          ))}
        </ol>
      </div>
      <div>
        <div className="text-xs font-semibold text-gray-700 mb-1">Rezultāts</div>
        <pre className="text-xs bg-white border border-gray-200 rounded p-2 overflow-x-auto max-h-64">
          {JSON.stringify(output, null, 2)}
        </pre>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// Packages tab — sync from ProcessGit
// ═══════════════════════════════════════════════════════════════

function PackageContents({ pkg: p, info, expanded, onToggle }) {
  const m = info?.manifest || {};
  const proc = info?.process;
  const decisions = info?.decisions || [];
  const algorithms = m.algorithms || [];
  const docs = info?.docs || [];
  const triggers = info?.triggers || { active: [], all: [] };

  // Counts: prefer parsed info over engine's listPackages summary (which
  // currently returns 0 for both — known engine quirk).
  const procCount = proc ? 1 : (p.processes?.length || 0);
  const dmnCount = decisions.length || (p.decisions?.length || 0);
  const algoCount = algorithms.length;
  const docCount = docs.length;

  return (
    <>
      <div className="mt-3 grid grid-cols-4 gap-4 text-xs">
        <div>
          <div className="text-gray-400 uppercase tracking-wide">Source URL</div>
          <div className="font-mono text-gray-700 break-all">{p.source_url || "—"}</div>
        </div>
        <div>
          <div className="text-gray-400 uppercase tracking-wide">Pēdējoreiz sinhronizēts</div>
          <div className="text-gray-700">{p.last_synced_at
            ? new Date(p.last_synced_at).toLocaleString("lv-LV")
            : "—"}</div>
        </div>
        <div>
          <div className="text-gray-400 uppercase tracking-wide">Saturs</div>
          <div className="text-gray-700">
            {procCount} BPMN · {dmnCount} DMN · {algoCount} algoritmi · {docCount} doc
          </div>
        </div>
        <div>
          <div className="text-gray-400 uppercase tracking-wide">Trigeris</div>
          <div className="text-gray-700">
            {triggers.active.length > 0
              ? <span className="text-emerald-700">✓ {triggers.active.length} aktīvs</span>
              : <span className="text-gray-400">nav aktīvs</span>}
          </div>
        </div>
      </div>

      {m.description && (
        <p className="mt-3 text-xs text-gray-600 leading-relaxed">
          {m.description}
        </p>
      )}

      <button onClick={onToggle}
        className="mt-3 text-xs text-emerald-700 hover:text-emerald-900">
        {expanded ? "▾ Slēpt saturu" : "▸ Rādīt visu saturu"}
      </button>

      {expanded && info && (
        <div className="mt-3 pt-3 border-t border-gray-200 space-y-4 text-xs">
          {/* BPMN process */}
          {proc && (
            <section>
              <div className="font-semibold text-gray-700 mb-1">BPMN process</div>
              <div className="bg-gray-50 rounded p-2">
                <div className="font-mono text-emerald-700">{proc.id}</div>
                <div className="text-gray-700">{proc.name}</div>
                <div className="mt-1 text-gray-500">{proc.steps?.length || 0} soļi:</div>
                <ol className="mt-1 ml-4 space-y-0.5 list-decimal text-gray-700">
                  {(proc.steps || []).map(s => (
                    <li key={s.id}>
                      <span className="font-mono text-gray-500">{s.id}</span>
                      <span> — {s.name}</span>
                      {s.capability && <span className="text-gray-400"> → <code className="font-mono">{s.capability}</code></span>}
                      {s.decisionRef && <span className="text-gray-400"> → DMN <code className="font-mono">{s.decisionRef}</code></span>}
                    </li>
                  ))}
                </ol>
              </div>
            </section>
          )}

          {/* Algorithms (NEW — the semantic-analyze prompt + schema declared in manifest) */}
          {algorithms.length > 0 && (
            <section>
              <div className="font-semibold text-gray-700 mb-1">AI algoritmi paketē</div>
              <div className="space-y-2">
                {algorithms.map(a => (
                  <div key={a.id} className="bg-amber-50 border border-amber-200 rounded p-2">
                    <div className="font-mono text-amber-800 font-semibold">{a.id}</div>
                    <div className="text-gray-700 mt-0.5">{a.name}</div>
                    {a.purpose && <div className="text-gray-600 mt-1">{a.purpose}</div>}
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {a.prompt && (
                        <div>
                          <div className="text-gray-400 uppercase tracking-wide text-[10px]">System prompt</div>
                          <code className="font-mono text-gray-700">{a.prompt}</code>
                        </div>
                      )}
                      {a.output_schema && (
                        <div>
                          <div className="text-gray-400 uppercase tracking-wide text-[10px]">Output schema</div>
                          <code className="font-mono text-gray-700">{a.output_schema}</code>
                        </div>
                      )}
                    </div>
                    {a.consumers && a.consumers.length > 0 && (
                      <div className="mt-2 text-gray-500">
                        Izsauc: {a.consumers.map((c, i) => (
                          <span key={i} className="inline-block bg-white border border-gray-200 rounded px-1.5 py-0.5 mr-1 text-gray-600">{c}</span>
                        ))}
                      </div>
                    )}
                    {a.model_requirements && (
                      <div className="mt-1 text-gray-400 text-[10px]">
                        Modelis: {(a.model_requirements.tested_with || []).join(", ") || "any structured-output capable"}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* DMN decisions */}
          {decisions.length > 0 && (
            <section>
              <div className="font-semibold text-gray-700 mb-1">DMN lēmumu tabulas</div>
              <ul className="space-y-1">
                {decisions.map(d => (
                  <li key={d.id} className="bg-gray-50 rounded p-2">
                    <span className="font-mono text-emerald-700">{d.id}</span>
                    <span className="text-gray-700"> — {d.name}</span>
                    <span className="text-gray-400"> · {d.hitPolicy} hit policy · {d.rules?.length || 0} noteikumi · {d.inputs?.length || 0} ievades · {d.outputs?.length || 0} izvades</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Docs */}
          {docs.length > 0 && (
            <section>
              <div className="font-semibold text-gray-700 mb-1">Dokumentācija</div>
              <ul className="space-y-1">
                {docs.map(d => (
                  <li key={d.file}>
                    <span className="font-mono text-gray-500">{d.file}</span>
                    <span> — {d.title}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Manifest meta */}
          <section className="text-gray-500">
            <div><span className="font-semibold">Owners:</span> {(m.owners || []).map(o => o.id).join(", ")}</div>
            {m.eu_ai_act_classification && (
              <div><span className="font-semibold">EU AI akts:</span> {m.eu_ai_act_classification}</div>
            )}
            {m.legal_basis && m.legal_basis.length > 0 && (
              <div><span className="font-semibold">Juridiskais pamats:</span> {m.legal_basis.join(", ")}</div>
            )}
            {m.changelog && m.changelog.length > 0 && (
              <details className="mt-1">
                <summary className="cursor-pointer text-gray-600 hover:text-gray-900">Changelog</summary>
                <ul className="ml-4 mt-1 space-y-1">
                  {m.changelog.map(c => (
                    <li key={c.version}>
                      <span className="font-mono">v{c.version}</span>
                      <span className="text-gray-400"> ({c.date})</span> — {c.summary}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>
        </div>
      )}
    </>
  );
}


function PackagesTab({ notify, user }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState({});
  const [showSync, setShowSync] = useState(null);
  // Detailed info per package (parsed manifest, BPMN steps, DMN tables,
  // algorithms). Loaded lazily after the engine package list arrives. Keyed
  // by packageId; values may be null while a fetch is in flight.
  const [pkgInfos, setPkgInfos] = useState({});
  const [expanded, setExpanded] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await uapfApi("/uapf/packages");
      setData(d);
      // Fetch /info for each package in parallel — non-blocking
      for (const p of d.packages || []) {
        uapfApi(`/uapf/packages/${p.packageId}/info`)
          .then(info => setPkgInfos(prev => ({ ...prev, [p.packageId]: info })))
          .catch(() => { /* leave undefined; card degrades gracefully */ });
      }
    }
    catch (e) { notify({ t: "error", m: e.message }); }
    setLoading(false);
  }, [notify]);

  useEffect(() => { load(); }, [load]);

  const triggerReload = async () => {
    try {
      await uapfApi("/uapf/packages/reload", { method: "POST", body: "{}" });
      notify({ t: "ok", m: "Engine pārlādēts" });
      await load();
    } catch (e) { notify({ t: "error", m: e.message }); }
  };

  const isAdmin = user && ["admin", "superadmin"].includes(user.role);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-500">
          UAPF paketes, kas ielādētas uapf-engine kopā ar to izcelsmes URL (ProcessGit / GitHub).
        </p>
        {isAdmin && (
          <button onClick={triggerReload}
            className="text-sm text-emerald-700 hover:text-emerald-900">↻ Pārlādēt engine</button>
        )}
      </div>

      {loading && <div className="text-sm text-gray-400">Ielādē...</div>}

      {!loading && data && (
        <>
          <div className="text-xs text-gray-500 mb-2">
            Engine: <span className="font-mono">{data.engine_url}</span>
            {" — "}
            <span className={data.engine_alive ? "text-emerald-600" : "text-red-600"}>
              {data.engine_alive ? "alive" : "unreachable"}
            </span>
          </div>

          <div className="space-y-3">
            {data.packages.length === 0 && (
              <div className="text-sm text-gray-500 bg-gray-50 border border-dashed border-gray-300 rounded p-4">
                Nav ielādētu pakešu. Sinhronizējiet no ProcessGit.
              </div>
            )}
            {data.packages.map(p => (
              <div key={p.packageId} className="bg-white border border-gray-200 rounded p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-mono text-sm font-semibold text-gray-900">{p.packageId}</div>
                    <div className="text-xs text-gray-500 mt-0.5">v{p.version || "—"} · {p.name || ""}</div>
                  </div>
                  {isAdmin && (
                    <button onClick={() => setShowSync(p)}
                      className="text-xs px-2 py-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100">
                      ↻ Sync no ProcessGit
                    </button>
                  )}
                </div>

                <PackageContents
                  pkg={p}
                  info={pkgInfos[p.packageId]}
                  expanded={!!expanded[p.packageId]}
                  onToggle={() => setExpanded(e => ({ ...e, [p.packageId]: !e[p.packageId] }))}
                />
              </div>
            ))}
          </div>
        </>
      )}

      {showSync && (
        <SyncFromProcessGitModal pkg={showSync}
          onClose={() => setShowSync(null)}
          onDone={() => { setShowSync(null); load(); }}
          notify={notify}/>
      )}
    </div>
  );
}

function SyncFromProcessGitModal({ pkg, onClose, onDone, notify }) {
  const defaultUrl = pkg.source_url ||
    "https://processgit.org/AI_Sandbox/iesnieguma-izskatisana/archive/main.zip";
  const [url, setUrl] = useState(defaultUrl);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      const r = await uapfApi("/uapf/packages/sync", {
        method: "POST",
        body: JSON.stringify({ package_id: pkg.packageId, source_url: url }),
      });
      notify({ t: "ok", m: `Pakete sinhronizēta: ${r.packageId}@${r.version || "?"}` });
      onDone();
    } catch (e) {
      notify({ t: "error", m: "Sinhronizācija neizdevās: " + e.message });
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-xl p-5">
        <h3 className="text-lg font-semibold mb-1">Sinhronizēt no ProcessGit</h3>
        <p className="text-sm text-gray-500 mb-4">
          Engine lejupielādēs <code className="font-mono text-xs bg-gray-100 px-1">{pkg.packageId}</code> jaunāko versiju no norādītā URL un automātiski pārlādēs paketi.
        </p>
        <label className="text-xs text-gray-500 font-medium">Source URL</label>
        <input value={url} onChange={e => setUrl(e.target.value)}
          className="w-full mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded font-mono focus:border-emerald-500 focus:outline-none"/>
        <div className="text-xs text-gray-400 mt-1">
          ProcessGit archive URL piemērs: <code>https://processgit.org/owner/repo/archive/main.zip</code>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800">Atcelt</button>
          <button onClick={submit} disabled={submitting || !url}
            className="px-3 py-1.5 text-sm bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50">
            {submitting ? "Sinhronizē..." : "↻ Sinhronizēt"}
          </button>
        </div>
      </div>
    </div>
  );
}
