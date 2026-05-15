// UAPF Processes — admin dashboard.
// Four tabs: Demo Console, Triggers, Sessions, Package Library.
// Single file ~600 lines; matches the existing OpenDMS App.jsx style
// (tailwind utility classes, hooks-only, no router).

import { useState, useEffect, useCallback, useRef } from "react";

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

export default function UapfPage({ notify, user }) {
  const [tab, setTab] = useState("demo");

  const tabs = [
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

      {tab === "demo"     && <DemoConsole notify={notify} />}
      {tab === "triggers" && <TriggersTab notify={notify} />}
      {tab === "sessions" && <SessionsTab notify={notify} />}
      {tab === "packages" && <PackagesTab notify={notify} user={user} />}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// Demo console — pick an iesniegums, run UAPF, watch the flow
// ═══════════════════════════════════════════════════════════════

function DemoConsole({ notify }) {
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);

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
    // we replay it visually). 350ms between steps = ~3s total feels intentional.
    let i = 0;
    const tick = () => {
      i += 1;
      setActiveStep(i);
      if (i < PROCESS_STEPS.length) {
        animateTimer.current = setTimeout(tick, 350);
      } else {
        setSessionResult(result?.result || result);
        setRunning(false);
      }
    };
    animateTimer.current = setTimeout(tick, 400);
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
            <button key={d.id} onClick={() => { setSelected(d); resetRun(); }}
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
      <div className="col-span-8">
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

            {/* Flow visualization */}
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
                <FlowVisualization activeStep={activeStep} />
              </div>
            )}

            {/* Result card */}
            {sessionResult && <ClassificationResultCard result={sessionResult} />}
          </div>
        )}
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

function SessionsTab({ notify }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);
  const [detail, setDetail] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try { setSessions(await uapfApi("/uapf/sessions?limit=50")); }
    catch (e) { notify({ t: "error", m: e.message }); }
    setLoading(false);
  }, [notify]);

  useEffect(() => { load(); }, [load]);

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
                      onClick={() => { setExpanded(expanded === s.session_id ? null : s.session_id); loadDetail(s.session_id); }}
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

function PackagesTab({ notify, user }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState({});
  const [showSync, setShowSync] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await uapfApi("/uapf/packages")); }
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

                <div className="mt-3 grid grid-cols-3 gap-4 text-xs">
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
                      {p.processes?.length || 0} process · {p.decisions?.length || 0} DMN
                    </div>
                  </div>
                </div>
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
