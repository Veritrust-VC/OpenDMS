// Aģents — plānotājs, atmiņa, rīki, apstiprinājumi.
// Own file, same conventions as ConnectionsPage/UapfPage: hooks only, no
// router, own fetch helper.
//
// The approval sub-tab is the point of this page. Until the planner landed,
// OpenDMS had no oversight surface at all — guardrails arrived at the host
// router and were discarded. Now an irreversible action parks the run and
// waits here.

import { useState, useEffect, useCallback } from "react";

async function agentApi(path, opts = {}) {
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
    let msg = "HTTP " + r.status;
    try { const j = await r.json(); msg = j.detail || j.error || msg; } catch {}
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}

const STATUS = {
  planning:          ["Plāno",           "bg-sky-50 text-sky-700 ring-1 ring-sky-200"],
  running:           ["Darbojas",        "bg-sky-50 text-sky-700 ring-1 ring-sky-200"],
  awaiting_approval: ["Gaida apstiprinājumu", "bg-amber-50 text-amber-800 ring-1 ring-amber-300"],
  completed:         ["Pabeigts",        "bg-brand-50 text-brand-700 ring-1 ring-brand-200"],
  halted:            ["Apturēts",        "bg-ink-100 text-ink-600 ring-1 ring-ink-200"],
  failed:            ["Neizdevās",       "bg-rose-50 text-rose-700 ring-1 ring-rose-200"],
};

const REV = {
  read_only:    ["lasa",         "bg-ink-100 text-ink-600"],
  reversible:   ["atgriezenisks","bg-sky-50 text-sky-700"],
  irreversible: ["NEATGRIEZENISKS","bg-amber-100 text-amber-800 font-semibold"],
};

function Pill({ status }) {
  const [label, cls] = STATUS[status] || [status, "bg-ink-100 text-ink-600"];
  return <span className={"text-xs px-2 py-0.5 rounded-full font-medium " + cls}>{label}</span>;
}

const PHASE_ICON = { act: "▶", observe: "←", think: "·", reflect: "✓", halt: "■" };

// ── one step in the decision log ──────────────────────────────
function Step({ s }) {
  const denied = s.guardrail === "deny";
  const parked = s.guardrail === "require_approval";
  return (
    <div className={"border-l-2 pl-3 py-2 " +
      (parked ? "border-amber-400" : denied ? "border-rose-300" : "border-ink-200")}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-ink-400 font-mono">{PHASE_ICON[s.phase] || "·"} {s.seq}</span>
        {s.capability && <code className="text-xs font-mono text-ink-800">{s.capability}</code>}
        {s.guardrail && s.guardrail !== "allow" && (
          <span className={"text-[10px] px-1.5 py-0.5 rounded " +
            (parked ? "bg-amber-100 text-amber-800" : "bg-rose-100 text-rose-700")}>
            {parked ? "gaida apstiprinājumu" : "bloķēts"}
          </span>
        )}
        {s.latency_ms ? <span className="text-[10px] text-ink-400">{s.latency_ms} ms</span> : null}
      </div>
      {s.thought && (
        <p className="mt-1 text-xs text-ink-700 leading-snug">
          <span className="text-ink-400">pamatojums: </span>{s.thought}
        </p>
      )}
      {s.guardrail_reason && (
        <p className="mt-1 text-[11px] text-amber-800">{s.guardrail_reason}</p>
      )}
      {s.observation && Object.keys(s.observation).length > 0 && (
        <pre className={"mt-1 p-1.5 rounded text-[10px] overflow-x-auto " +
          (s.observation.ok === false ? "bg-rose-50 text-rose-900" : "bg-ink-50 text-ink-700")}>
{JSON.stringify(s.observation, null, 1).slice(0, 900)}
        </pre>
      )}
    </div>
  );
}

// ── approval gate ─────────────────────────────────────────────
function ApprovalPanel({ run, onDone, notify }) {
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const a = run.awaiting_approval;
  if (!a) return null;

  const act = async (verb) => {
    setBusy(true);
    try {
      await agentApi(`/agent/runs/${run.id}/${verb}`, {
        method: "POST",
        body: JSON.stringify({ step_id: a.step_id, reason }),
      });
      notify(verb === "approve" ? "Darbība apstiprināta" : "Darbība noraidīta", "success");
      onDone();
    } catch (e) { notify(e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <div className="rounded-lg border-2 border-amber-300 bg-amber-50 p-4 mb-4">
      <h3 className="text-sm font-semibold text-amber-900">Nepieciešams cilvēka lēmums</h3>
      <p className="text-xs text-amber-800 mt-1 leading-snug">
        Plānotājs izvēlējies darbību, kuras sekas nav atgriezeniskas. Darbība nav izpildīta
        un netiks izpildīta, kamēr to neapstiprina.
      </p>
      <div className="mt-3 bg-white rounded border border-amber-200 p-3">
        <div className="text-xs text-ink-500">Darbība</div>
        <code className="text-xs font-mono text-ink-900">{a.capability}</code>
        {a.thought && <p className="mt-2 text-xs text-ink-700">{a.thought}</p>}
        <div className="text-xs text-ink-500 mt-2">Parametri</div>
        <pre className="text-[10px] bg-ink-50 p-2 rounded overflow-x-auto">
{JSON.stringify(a.inputs, null, 1)}
        </pre>
      </div>
      <input value={reason} onChange={(e) => setReason(e.target.value)}
             placeholder="Pamatojums (nav obligāts)"
             className="input mt-3" />
      <div className="flex gap-2 mt-2">
        <button onClick={() => act("approve")} disabled={busy}
                className="btn-primary">
          {busy ? "…" : "Apstiprināt un turpināt"}
        </button>
        <button onClick={() => act("reject")} disabled={busy}
                className="btn bg-red-600 text-white hover:bg-red-700">
          Noraidīt
        </button>
      </div>
    </div>
  );
}

// ── run detail: decision log + memory ─────────────────────────
function RunDetail({ runId, onChanged, notify }) {
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setRun(await agentApi("/agent/runs/" + runId)); }
    catch (e) { notify(e.message, "error"); }
  }, [runId, notify]);

  useEffect(() => { load(); }, [load]);

  if (!run) return <p className="text-sm text-ink-500">Ielādē…</p>;

  const resume = async () => {
    setBusy(true);
    try { await agentApi(`/agent/runs/${run.id}/resume`, { method: "POST" }); await load(); onChanged(); }
    catch (e) { notify(e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-ink-900">{run.goal}</h3>
            <Pill status={run.status} />
          </div>
          <p className="text-xs text-ink-400 mt-0.5 font-mono">{run.run_uuid}</p>
        </div>
        {["halted", "planning", "running"].includes(run.status) && (
          <button onClick={resume} disabled={busy}
                  className="btn-quiet">
            {busy ? "…" : "Turpināt"}
          </button>
        )}
      </div>

      <ApprovalPanel run={run} onDone={() => { load(); onChanged(); }} notify={notify} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
        {[["Soļi", `${run.steps_used} / ${run.max_steps}`],
          ["Pilnvarojums", Array.isArray(run.policy.authority_scope)
            ? `${run.policy.authority_scope.length} rīki` : "viss katalogs"],
          ["Neatgriezeniskas darbības", "prasa apstiprinājumu"],
          ["Cikla slieksnis", run.policy.loop_threshold]].map(([k, v]) => (
          <div key={k} className="card p-2">
            <div className="text-[10px] text-ink-500">{k}</div>
            <div className="text-xs font-medium text-ink-900">{v}</div>
          </div>
        ))}
      </div>

      {Object.keys(run.scratchpad || {}).length > 0 && (
        <div className="mb-4">
          <h4 className="label-eyebrow mb-1">
            Darba atmiņa
          </h4>
          <p className="text-[11px] text-ink-500 mb-1">
            Fakti, ko plānotājs noskaidrojis šajā izpildē un pārnes uz nākamajiem soļiem.
          </p>
          <pre className="card p-2 text-[11px] overflow-x-auto">
{JSON.stringify(run.scratchpad, null, 2)}
          </pre>
        </div>
      )}

      <h4 className="label-eyebrow mb-1">
        Lēmumu žurnāls ({run.steps.length})
      </h4>
      <p className="text-[11px] text-ink-500 mb-2">
        Katram solim fiksēts ne tikai kas tika izdarīts, bet arī kāpēc tieši šī darbība —
        secību plānotājs veido izpildes laikā, tāpēc pamatojums ir vienīgais pierādījums.
      </p>
      <div className="card divide-y divide-ink-100">
        {run.steps.map((s) => <Step key={s.seq} s={s} />)}
      </div>

      {run.outcome && run.outcome.answer && (
        <div className="mt-3 rounded border border-brand-200 bg-brand-50 p-3">
          <div className="text-xs font-semibold text-brand-900 mb-1">Rezultāts</div>
          <p className="text-xs text-brand-900">{run.outcome.answer}</p>
        </div>
      )}
      {run.halt_reason && (
        <p className="mt-3 text-xs text-ink-600">Apturēšanas iemesls: {run.halt_reason}</p>
      )}
    </div>
  );
}

// ── rīku katalogs ─────────────────────────────────────────────
function ToolsTab({ notify }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    agentApi("/agent/tools").then(setData).catch((e) => notify(e.message, "error"));
  }, [notify]);
  if (!data) return <p className="text-sm text-ink-500">Ielādē…</p>;

  return (
    <div>
      <p className="text-sm text-ink-600 mb-3 max-w-3xl">
        Rīki, no kuriem plānotājs izvēlas. Katram norādīts, vai darbība ir atgriezeniska —
        neatgriezeniskās vienmēr nonāk pie cilvēka apstiprināšanai. Nezināmi rīki pēc
        noklusējuma tiek uzskatīti par neatgriezeniskiem.
      </p>
      <div className="flex gap-2 mb-3">
        {Object.entries(data.counts).map(([k, v]) => (
          <span key={k} className={"text-xs px-2 py-1 rounded " + REV[k][1]}>
            {REV[k][0]}: {v}
          </span>
        ))}
      </div>
      <div className="card divide-y divide-ink-100">
        {data.tools.map((t) => (
          <div key={t.capability} className="px-3 py-2 flex items-start gap-3">
            <code className="text-xs font-mono text-ink-900 w-64 shrink-0">{t.capability}</code>
            <span className={"text-[10px] px-1.5 py-0.5 rounded shrink-0 " + REV[t.reversibility][1]}>
              {REV[t.reversibility][0]}
            </span>
            <span className="text-xs text-ink-600 flex-1">{t.summary}</span>
            {!t.implemented && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 shrink-0">
                nav ieviests
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── plānotājs ─────────────────────────────────────────────────
function PlannerTab({ notify }) {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [goal, setGoal] = useState("");
  const [maxSteps, setMaxSteps] = useState(8);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await agentApi("/agent/runs");
      setRuns(d.items || []);
    } catch (e) { notify(e.message, "error"); }
  }, [notify]);

  useEffect(() => { load(); }, [load]);

  const start = async () => {
    if (!goal.trim()) { notify("Norādiet mērķi", "error"); return; }
    setBusy(true);
    try {
      const r = await agentApi("/agent/runs", {
        method: "POST",
        body: JSON.stringify({ goal, max_steps: Number(maxSteps) }),
      });
      setGoal(""); setSelected(r.id); await load();
      notify("Izpilde pabeigta ar statusu: " + r.status, "success");
    } catch (e) { notify(e.message, "error"); }
    finally { setBusy(false); }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
      <div className="lg:col-span-1">
        <div className="card p-3 mb-4">
          <h3 className="label-eyebrow mb-2">
            Jauna izpilde
          </h3>
          <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={3}
                    placeholder="Mērķis, ko aģentam sasniegt…"
                    className="input" />
          <div className="flex items-center gap-2 mt-2">
            <label className="text-xs text-ink-600">Soļu ierobežojums</label>
            <input type="number" min={1} max={40} value={maxSteps}
                   onChange={(e) => setMaxSteps(e.target.value)}
                   className="input w-16" />
          </div>
          <button onClick={start} disabled={busy}
                  className="btn-primary w-full mt-2">
            {busy ? "Darbojas…" : "Sākt"}
          </button>
        </div>

        <h3 className="label-eyebrow mb-2">
          Izpildes ({runs.length})
        </h3>
        <div className="space-y-1.5">
          {runs.map((r) => (
            <button key={r.id} onClick={() => setSelected(r.id)}
                    className={"w-full text-left rounded-md border p-2.5 transition-colors cursor-pointer " +
                      (selected === r.id ? "border-brand-400 bg-brand-50" : "border-ink-200 bg-white hover:border-ink-300 hover:bg-ink-50")}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-ink-500">#{r.id}</span>
                <Pill status={r.status} />
              </div>
              <p className="text-xs text-ink-800 mt-1 line-clamp-2">{r.goal}</p>
              <p className="text-[10px] text-ink-400 mt-0.5">{r.steps_used}/{r.max_steps} soļi</p>
            </button>
          ))}
          {runs.length === 0 && <p className="text-xs text-ink-500">Vēl nav izpilžu.</p>}
        </div>
      </div>

      <div className="lg:col-span-2">
        {selected
          ? <RunDetail runId={selected} onChanged={load} notify={notify} />
          : <p className="text-sm text-ink-500">Izvēlieties izpildi kreisajā pusē.</p>}
      </div>
    </div>
  );
}

// ── plānotājs pēc grafika (vēl nav) ───────────────────────────
function SchedulerTab() {
  return (
    <div className="rounded border border-amber-200 bg-amber-50 p-4 max-w-3xl">
      <h3 className="text-sm font-semibold text-amber-900">Grafiks vēl nav ieviests</h3>
      <p className="text-xs text-amber-800 mt-1 leading-snug">
        Šobrīd izpildi sāk vai nu operators, vai notikums — dokumenta saņemšana caur
        <code className="mx-1 font-mono">process_triggers</code>. Laika grafika nav:
        aģents pats nesāk darbu noteiktā stundā.
      </p>
      <p className="text-xs text-amber-800 mt-2 leading-snug">
        Cilne redzama apzināti, nevis paslēpta — tāpat kā neieviestie savienotāji.
        Sistēma rāda, kā tā patiešām darbojas, nevis kā vajadzētu.
      </p>
    </div>
  );
}

// ── lapa ──────────────────────────────────────────────────────
export default function AgentPage({ notify }) {
  const [tab, setTab] = useState("chat");
  const tabs = [
    ["chat",      "Saruna"],
    ["planner",   "Izpildes"],
    ["tools",     "Rīki"],
    ["scheduler", "Grafiks"],
  ];
  return (
    <div className="max-w-6xl">
      <div className="mb-4">
        <h1 className="text-lg font-semibold text-ink-900">Aģents</h1>
        <p className="text-sm text-ink-500 mt-1 max-w-3xl">
          Plānotājs izvēlas nākamo darbību izpildes laikā, ņemot vērā iepriekšējo soļu
          rezultātus. Neatgriezeniskas darbības nonāk pie cilvēka, un katrs lēmums tiek
          fiksēts kopā ar pamatojumu.
        </p>
      </div>
      <div className="flex gap-1 border-b border-ink-200 mb-4">
        {tabs.map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)}
                  className={"text-sm px-3 py-2 -mb-px border-b-2 transition-colors cursor-pointer " +
                    (tab === id
                      ? "border-brand-600 text-brand-700 font-medium"
                      : "border-transparent text-ink-500 hover:text-ink-700")}>
            {label}
          </button>
        ))}
      </div>
      {tab === "chat" && <ChatTab notify={notify} />}
      {tab === "planner" && <PlannerTab notify={notify} />}
      {tab === "tools" && <ToolsTab notify={notify} />}
      {tab === "scheduler" && <SchedulerTab />}
    </div>
  );
}

// ── saruna ────────────────────────────────────────────────────
// The main communication interface. Everything else on this page is
// instrumentation; this is where the work is actually directed.
//
// The composer stays enabled while the agent is working. That is the whole
// point of interjection: if the planner heads the wrong way on step two, you
// correct it then, not after the budget is spent. A message sent mid-run is
// queued and claimed at the planner's next iteration.

function Bubble({ m }) {
  const mine = m.role === "user";
  return (
    <div className={"flex " + (mine ? "justify-end" : "justify-start")}>
      <div className={"max-w-[46rem] rounded-lg px-3 py-2 text-sm leading-relaxed " +
        (mine ? "bg-brand-600 text-white" : "bg-white border border-ink-200 text-ink-800")}>
        {m.content}
        {m.pending && (
          <div className="mt-1 text-2xs opacity-80">
            gaida — aģents to saņems nākamajā solī
          </div>
        )}
      </div>
    </div>
  );
}

function ChatTab({ notify }) {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(null);
  const [run, setRun] = useState(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [showLog, setShowLog] = useState(false);

  const loadRuns = useCallback(async () => {
    try { setRuns((await agentApi("/agent/runs")).items || []); }
    catch (e) { notify(e.message, "error"); }
  }, [notify]);

  const loadRun = useCallback(async (id) => {
    if (!id) { setRun(null); return; }
    try { setRun(await agentApi("/agent/runs/" + id)); }
    catch (e) { notify(e.message, "error"); }
  }, [notify]);

  useEffect(() => { loadRuns(); }, [loadRuns]);
  useEffect(() => { loadRun(runId); }, [runId, loadRun]);

  const send = async () => {
    const text = draft.trim();
    if (!text) return;
    setBusy(true);
    setDraft("");
    try {
      const r = await agentApi("/agent/chat", {
        method: "POST",
        body: JSON.stringify(runId ? { run_id: runId, message: text } : { message: text }),
      });
      setRunId(r.id);
      setRun(r);
      await loadRuns();
      if (r.note) notify(r.note, "success");
    } catch (e) {
      notify(e.message, "error");
      setDraft(text);
    } finally { setBusy(false); }
  };

  const onKey = (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
  };

  const messages = run?.messages || [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
      {/* conversations */}
      <div className="lg:col-span-1">
        <button onClick={() => { setRunId(null); setRun(null); }}
                className="btn-quiet w-full mb-3">
          Jauna saruna
        </button>
        <div className="label-eyebrow mb-1.5">Sarunas</div>
        <div className="space-y-1">
          {runs.map((r) => (
            <button key={r.id} onClick={() => setRunId(r.id)}
              className={"w-full text-left rounded-md border p-2.5 transition-colors cursor-pointer " +
                (runId === r.id ? "border-brand-400 bg-brand-50"
                                : "border-ink-200 bg-white hover:border-ink-300 hover:bg-ink-50")}>
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-2xs text-ink-400 font-mono">#{r.id}</span>
                <Pill status={r.status} />
              </div>
              <p className="text-xs text-ink-700 line-clamp-2 leading-snug">{r.goal}</p>
            </button>
          ))}
          {runs.length === 0 && <p className="text-xs text-ink-400">Vēl nav sarunu.</p>}
        </div>
      </div>

      {/* thread */}
      <div className="lg:col-span-3 flex flex-col">
        <div className="flex-1 min-h-[22rem] space-y-3 mb-3">
          {!run && (
            <div className="card p-6 text-center">
              <p className="text-sm text-ink-600">
                Pastāstiet, kas jāizdara. Aģents pats izvēlas soļus un pēc katra
                pārliecinās par rezultātu.
              </p>
              <p className="text-xs text-ink-400 mt-2">
                Darbības, kas iznāk ārpus sistēmas, vienmēr gaida jūsu apstiprinājumu.
              </p>
            </div>
          )}
          {messages.map((m) => <Bubble key={m.id} m={m} />)}
          {busy && (
            <div className="flex justify-start">
              <div className="rounded-lg bg-white border border-ink-200 px-3 py-2 text-sm text-ink-400">
                Aģents strādā…
              </div>
            </div>
          )}
        </div>

        {run?.awaiting_approval && (
          <ApprovalPanel run={run} notify={notify}
                         onDone={() => { loadRun(run.id); loadRuns(); }} />
        )}

        {/* composer — stays live while the agent works, on purpose */}
        <div className="card p-2">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey}
                    rows={2} placeholder="Rakstiet aģentam…  (Ctrl+Enter — nosūtīt)"
                    className="w-full resize-none border-0 px-1.5 py-1 text-sm focus:outline-none placeholder:text-ink-400" />
          <div className="flex items-center justify-between gap-2 px-1.5 pb-0.5">
            <span className="text-2xs text-ink-400">
              {run ? `Saruna #${run.id} · ${run.steps_used}/${run.max_steps} soļi` : "Jauna saruna"}
            </span>
            <button onClick={send} disabled={!draft.trim()} className="btn-primary">
              {busy ? "Sūta…" : "Sūtīt"}
            </button>
          </div>
        </div>

        {run && run.steps.length > 0 && (
          <div className="mt-4">
            <button onClick={() => setShowLog((v) => !v)}
                    className="label-eyebrow hover:text-ink-600 transition-colors cursor-pointer">
              {showLog ? "Paslēpt" : "Rādīt"} lēmumu žurnālu ({run.steps.length})
            </button>
            {showLog && (
              <div className="card divide-y divide-ink-100 mt-2">
                {run.steps.map((s) => <Step key={s.seq} s={s} />)}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
