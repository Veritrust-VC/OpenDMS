// Connections — configure and exercise the external-system connectors.
// Single file, matches the existing OpenDMS style (tailwind utilities,
// hooks only, no router, own fetch helper) like UapfPage.jsx.
//
// The form is generated from what the API reports about each driver, not
// hard-coded per connector. Adding a driver in Python therefore makes it
// appear here with its fields, its operations and — for the ones that are not
// implemented — its outstanding questions, with no change to this file.

import { useState, useEffect, useCallback } from "react";

async function connApi(path, opts = {}) {
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
  if (r.status === 204) return null;
  return r.json();
}

const STATUS_STYLE = {
  active:         "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  degraded:       "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  error:          "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
  paused:         "bg-gray-100 text-gray-500 ring-1 ring-gray-200",
  not_configured: "bg-gray-50 text-gray-500 ring-1 ring-gray-200",
};
const STATUS_LABEL = {
  active: "Active", degraded: "Degraded", error: "Error",
  paused: "Paused", not_configured: "Not tested",
};

function Pill({ status }) {
  return (
    <span className={"text-xs px-2 py-0.5 rounded-full font-medium " + (STATUS_STYLE[status] || STATUS_STYLE.not_configured)}>
      {STATUS_LABEL[status] || status}
    </span>
  );
}

function fmtWhen(iso) {
  if (!iso) return "never";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

// ── one generated form input ──────────────────────────────────
function DriverField({ field, value, onChange, secretAlreadySet }) {
  const common = "w-full border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-emerald-400";
  let input;
  if (field.kind === "bool") {
    input = (
      <input type="checkbox" checked={value === undefined ? true : !!value}
             onChange={(e) => onChange(e.target.checked)}
             className="h-4 w-4 accent-emerald-600" />
    );
  } else if (field.kind === "select") {
    input = (
      <select className={common} value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">— not set —</option>
        {(field.choices || []).map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  } else {
    input = (
      <input className={common}
             type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"}
             value={value || ""} placeholder={field.placeholder || ""}
             autoComplete={field.kind === "password" ? "new-password" : "off"}
             onChange={(e) => onChange(e.target.value)} />
    );
  }
  return (
    <div className="mb-3">
      <label className="block text-xs font-medium text-gray-700 mb-1">
        {field.label}
        {field.required && <span className="text-rose-500 ml-0.5">*</span>}
        {secretAlreadySet && (
          <span className="ml-2 text-[10px] text-emerald-600 font-normal">stored — leave blank to keep</span>
        )}
      </label>
      {input}
      {field.help && <p className="mt-1 text-[11px] leading-snug text-gray-500">{field.help}</p>}
    </div>
  );
}

// ── what we still need from the counterparty ──────────────────
function SpecPanel({ driver }) {
  const [copied, setCopied] = useState(false);
  const items = driver.required_from_counterparty || [];
  if (!items.length) return null;

  const asText =
    "Integration requirements — " + driver.display_name + "\n\n" +
    items.map((s, i) => (i + 1) + ". " + s).join("\n\n");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(asText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard unavailable over plain http — the text is on screen anyway */ }
  };

  return (
    <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <h4 className="text-xs font-semibold text-amber-900">
            Not implemented — {items.length} open questions
          </h4>
          <p className="text-[11px] text-amber-800 mt-0.5">
            The connector is registered and callable, and answers every request with a
            structured refusal until these are settled. Send this list to the system owner.
          </p>
        </div>
        <button onClick={copy}
                className="shrink-0 text-[11px] px-2 py-1 rounded bg-white border border-amber-300 text-amber-800 hover:bg-amber-100">
          {copied ? "Copied" : "Copy as text"}
        </button>
      </div>
      <ol className="list-decimal ml-4 space-y-1">
        {items.map((s, i) => (
          <li key={i} className="text-[11px] leading-snug text-amber-900">{s}</li>
        ))}
      </ol>
    </div>
  );
}

// ── create / edit ─────────────────────────────────────────────
function ConnectionForm({ driver, existing, onDone, onCancel, notify }) {
  const [name, setName] = useState(existing ? existing.name : driver.display_name);
  const [description, setDescription] = useState(existing ? existing.description || "" : "");
  const [config, setConfig] = useState(existing ? { ...existing.config } : {});
  const [secret, setSecret] = useState({});
  const [busy, setBusy] = useState(false);
  const secretSet = new Set(existing ? existing.secret_keys_set || [] : []);

  const save = async () => {
    setBusy(true);
    try {
      if (existing) {
        await connApi("/connections/" + existing.id, {
          method: "PATCH",
          body: JSON.stringify({ name, description, config, secret }),
        });
        notify("Connection updated", "success");
      } else {
        await connApi("/connections", {
          method: "POST",
          body: JSON.stringify({ kind: driver.kind, name, description, config, secret }),
        });
        notify("Connection created", "success");
      }
      onDone();
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-emerald-200 bg-emerald-50/40 p-4 mt-3">
      <h4 className="text-sm font-semibold text-gray-800 mb-3">
        {existing ? "Edit" : "New"} — {driver.display_name}
      </h4>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-5">
        <div>
          <DriverField field={{ key: "name", label: "Connection name", required: true }}
                       value={name} onChange={setName} />
          <DriverField field={{ key: "description", label: "Description", required: false,
                                help: "Free text — what this connection is for." }}
                       value={description} onChange={setDescription} />
          {driver.config_fields.map((f) => (
            <DriverField key={f.key} field={f} value={config[f.key]}
                         onChange={(v) => setConfig((c) => ({ ...c, [f.key]: v }))} />
          ))}
        </div>
        <div>
          {driver.secret_fields.length > 0 && (
            <p className="text-[11px] text-gray-600 mb-2 leading-snug">
              Credentials are encrypted before storage and are never returned by the API.
              There is no way to read one back — only to replace it.
            </p>
          )}
          {driver.secret_fields.map((f) => (
            <DriverField key={f.key} field={f} value={secret[f.key]}
                         secretAlreadySet={secretSet.has(f.key)}
                         onChange={(v) => setSecret((s) => ({ ...s, [f.key]: v }))} />
          ))}
        </div>
      </div>

      <div className="flex gap-2 mt-2">
        <button onClick={save} disabled={busy}
                className="text-xs px-3 py-1.5 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50">
          {busy ? "Saving…" : existing ? "Save changes" : "Create connection"}
        </button>
        <button onClick={onCancel}
                className="text-xs px-3 py-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50">
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── run one driver operation by hand ──────────────────────────
function OperationRunner({ conn, driver, notify }) {
  const [operation, setOperation] = useState(driver.operations[0] ? driver.operations[0].name : "");
  const [inputs, setInputs] = useState("{}");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    let parsed;
    try { parsed = JSON.parse(inputs || "{}"); }
    catch { notify("Inputs must be valid JSON", "error"); return; }
    setBusy(true); setResult(null);
    try {
      const r = await connApi("/connections/" + conn.id + "/invoke", {
        method: "POST",
        body: JSON.stringify({ operation, inputs: parsed }),
      });
      setResult(r);
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const selected = driver.operations.find((o) => o.name === operation);

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <h4 className="text-xs font-semibold text-gray-700 mb-2">Run an operation</h4>
      <div className="flex flex-wrap items-start gap-2">
        <select value={operation} onChange={(e) => { setOperation(e.target.value); setResult(null); }}
                className="border border-gray-300 rounded px-2 py-1 text-sm">
          {driver.operations.map((o) => <option key={o.name} value={o.name}>{o.name}</option>)}
        </select>
        <textarea value={inputs} onChange={(e) => setInputs(e.target.value)} rows={2}
                  className="flex-1 min-w-[240px] border border-gray-300 rounded px-2 py-1 font-mono text-xs"
                  placeholder='{"to": "someone@example.lv"}' />
        <button onClick={run} disabled={busy}
                className="text-xs px-3 py-1.5 rounded bg-gray-800 text-white hover:bg-black disabled:opacity-50">
          {busy ? "Running…" : "Run"}
        </button>
      </div>
      {selected && (
        <p className="mt-1 text-[11px] text-gray-500">
          {selected.summary} · UAPF capability <code className="font-mono">{selected.capability}</code>
          {selected.direction === "inbound" && " · inbound"}
        </p>
      )}
      {result && (
        <pre className={"mt-2 p-2 rounded text-[11px] overflow-x-auto " +
                        (result.ok ? "bg-emerald-50 text-emerald-900" : "bg-rose-50 text-rose-900")}>
{JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── one configured connection ─────────────────────────────────
function ConnectionCard({ conn, driver, onChanged, notify }) {
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState(null);

  const runTest = async () => {
    setTesting(true); setTest(null);
    try {
      const r = await connApi("/connections/" + conn.id + "/test", { method: "POST" });
      setTest(r);
      onChanged();
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setTesting(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete \"" + conn.name + "\" and its stored credentials?")) return;
    try {
      await connApi("/connections/" + conn.id, { method: "DELETE" });
      notify("Connection deleted", "success");
      onChanged();
    } catch (e) {
      notify(e.message, "error");
    }
  };

  const cfgEntries = Object.entries(conn.config || {}).filter(([, v]) => v !== "" && v !== null);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-gray-900 truncate">{conn.name}</h3>
            <Pill status={conn.is_enabled ? conn.status : "paused"} />
            {!conn.implemented && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-medium">
                placeholder
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            {conn.display_name}
            {conn.description ? " · " + conn.description : ""}
          </p>
        </div>
        <div className="flex gap-1.5 shrink-0">
          <button onClick={runTest} disabled={testing}
                  className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            {testing ? "Testing…" : "Test"}
          </button>
          <button onClick={() => setEditing((v) => !v)}
                  className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-700 hover:bg-gray-50">
            {editing ? "Close" : "Edit"}
          </button>
          <button onClick={remove}
                  className="text-xs px-2 py-1 rounded border border-rose-200 text-rose-600 hover:bg-rose-50">
            Delete
          </button>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
        {cfgEntries.map(([k, v]) => (
          <div key={k} className="flex gap-2 text-[11px]">
            <dt className="text-gray-500 shrink-0">{k}</dt>
            <dd className="font-mono text-gray-800 truncate">{String(v)}</dd>
          </div>
        ))}
        {(conn.secret_keys_set || []).map((k) => (
          <div key={k} className="flex gap-2 text-[11px]">
            <dt className="text-gray-500 shrink-0">{k}</dt>
            <dd className="text-emerald-700">stored (encrypted)</dd>
          </div>
        ))}
      </dl>

      <p className="mt-2 text-[11px] text-gray-500">
        Last verified {fmtWhen(conn.last_verified_at)}
        {conn.last_error && (
          <span className="text-rose-600"> · last error: {conn.last_error}</span>
        )}
      </p>

      {test && (
        <pre className={"mt-2 p-2 rounded text-[11px] overflow-x-auto " +
                        (test.ok ? "bg-emerald-50 text-emerald-900" : "bg-rose-50 text-rose-900")}>
{JSON.stringify(test, null, 2)}
        </pre>
      )}

      {editing && driver && (
        <ConnectionForm driver={driver} existing={conn} notify={notify}
                        onDone={() => { setEditing(false); onChanged(); }}
                        onCancel={() => setEditing(false)} />
      )}

      {!editing && driver && driver.implemented && driver.operations.length > 0 && (
        <OperationRunner conn={conn} driver={driver} notify={notify} />
      )}
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────
export default function ConnectionsPage({ notify }) {
  const [drivers, setDrivers] = useState([]);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(null); // driver kind being added

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, c] = await Promise.all([
        connApi("/connections/drivers"),
        connApi("/connections"),
      ]);
      setDrivers(d.drivers || []);
      setItems(c.items || []);
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => { load(); }, [load]);

  const driverFor = (kind) => drivers.find((d) => d.kind === kind);
  const addDriver = adding ? driverFor(adding) : null;

  return (
    <div className="max-w-6xl">
      <div className="mb-5">
        <h1 className="text-lg font-semibold text-gray-900">Connections</h1>
        <p className="text-sm text-gray-500 mt-1 max-w-3xl">
          External systems this OpenDMS instance can reach. Every connector is also a
          UAPF capability, so a process can call it directly from BPMN — the capability
          reference is shown next to each operation.
        </p>
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}

      {!loading && (
        <>
          <section className="mb-6">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
              Add a connection
            </h2>
            <div className="flex flex-wrap gap-2">
              {drivers.map((d) => (
                <button key={d.kind} onClick={() => setAdding(adding === d.kind ? null : d.kind)}
                        className={"text-xs px-3 py-1.5 rounded border " +
                          (adding === d.kind
                            ? "border-emerald-400 bg-emerald-50 text-emerald-800"
                            : "border-gray-300 text-gray-700 hover:bg-gray-50")}>
                  {d.display_name}
                  {!d.implemented && <span className="ml-1.5 text-amber-600">•</span>}
                </button>
              ))}
            </div>
            {addDriver && (
              <>
                <p className="mt-2 text-xs text-gray-600">{addDriver.summary}</p>
                <SpecPanel driver={addDriver} />
                <ConnectionForm driver={addDriver} notify={notify}
                                onDone={() => { setAdding(null); load(); }}
                                onCancel={() => setAdding(null)} />
              </>
            )}
          </section>

          <section>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
              Configured ({items.length})
            </h2>
            {items.length === 0 ? (
              <p className="text-sm text-gray-500">
                Nothing configured yet. Pick a connector above.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-3">
                {items.map((c) => (
                  <ConnectionCard key={c.id} conn={c} driver={driverFor(c.kind)}
                                  onChanged={load} notify={notify} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
