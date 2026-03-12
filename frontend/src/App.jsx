import { useState, useEffect, useCallback } from "react";

const API = "/api";
let authToken = localStorage.getItem("opendms_token") || "";

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}) };
  if (opts.body instanceof FormData) { delete headers["Content-Type"]; }
  const res = await fetch(`${API}${path}`, { headers, ...opts });
  if (res.status === 401) { authToken = ""; localStorage.removeItem("opendms_token"); window.location.reload(); }
  if (!res.ok) {
    const e = await res.json().catch(() => ({ detail: res.statusText }));
    const payload = e?.detail && typeof e.detail === "object" ? e.detail : e;
    const message = typeof payload?.detail === "string" ? payload.detail : (payload?.error || res.statusText);
    const err = new Error(message || res.statusText);
    err.payload = payload;
    throw err;
  }
  if (res.headers.get("content-type")?.includes("json")) return res.json();
  return res;
}

function Badge({ s }) { const c = { draft:"bg-gray-100 text-gray-600", registered:"bg-sky-100 text-sky-700", sent:"bg-amber-100 text-amber-700", received:"bg-violet-100 text-violet-700", assigned:"bg-teal-100 text-teal-700", decided:"bg-green-100 text-green-700", archived:"bg-gray-200 text-gray-600" }; return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${c[s]||"bg-gray-100"}`}>{s}</span>; }
const EI = { DocumentCreated:"\u{1F4C4}", DocumentSent:"\u{1F4E4}", DocumentReceived:"\u{1F4E5}", DocumentAssigned:"\u{1F464}", DocumentDecided:"\u{2705}", DocumentArchived:"\u{1F5C4}\uFE0F" };


const SUMMARY_FIELDS = ["primaryTopic","subTopics","summary","documentPurpose","requestedAction","involvedPartyTypes","geographicScope","sectorTags","legalDomain","estimatedRiskLevel","urgencyLevel","keywords","summarySource","aiConfidenceScore","aiModelVersion"];
const SENSITIVITY_FIELDS = ["allowCentralization","redactionLevel","personalDataRisk","accessRestrictionBasis","classifiedInformation"];
const summaryBadgeClass = { AI: "bg-blue-100 text-blue-700", HUMAN: "bg-green-100 text-green-700", HYBRID: "bg-purple-100 text-purple-700" };
function normalizeSummaryPayload(payload) { return { semanticSummary: payload?.semanticSummary || null, sensitivityControl: payload?.sensitivityControl || null, route: payload?.route || null }; }

export default function App() {
  const [user, setUser] = useState(null);
  const [page, setPage] = useState("dashboard");
  const [brand, setBrand] = useState({ brand_name: "OpenDMS", brand_primary_color: "#0d7c66", brand_logo_url: "" });
  const [toast, setToast] = useState(null);
  const [auditFilters, setAuditFilters] = useState(null);
  const notify = (m, t="success") => { setToast({m,t}); setTimeout(()=>setToast(null),4000); };

  useEffect(() => { api("/settings/branding").then(setBrand).catch(()=>{}); }, []);
  useEffect(() => { if (authToken) { api("/users/me/profile").then(setUser).catch(()=>{ authToken=""; localStorage.removeItem("opendms_token"); }); } }, []);

  if (!user) return <LoginPage onLogin={(u,t)=>{ authToken=t; localStorage.setItem("opendms_token",t); setUser(u); }} brand={brand} />;

  const isAdmin = ["superadmin","admin"].includes(user.role);
  const nav = [
    { id:"dashboard", label:"Dashboard", icon:"\u{1F4CA}" },
    { id:"documents", label:"Documents", icon:"\u{1F4C4}" },
    { id:"intelligence", label:"Intelligence", icon:"\u{1F9E0}" },
    ...(isAdmin ? [
      { id:"users", label:"Users", icon:"\u{1F465}" },
      { id:"audit", label:"Audit Logs", icon:"\u{1F4DD}" },
      { id:"organizations", label:"Organizations", icon:"\u{1F3E2}" },
      { id:"registers", label:"Registers", icon:"\u{1F4C1}" },
      { id:"classifications", label:"Classifications", icon:"\u{1F3F7}\uFE0F" },
      { id:"archive", label:"Archive", icon:"\u{1F5C3}\uFE0F" },
    ] : []),
    ...(user.role === "superadmin" ? [{ id:"settings", label:"Settings", icon:"\u{2699}\uFE0F" }] : []),
  ];

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <aside className="w-52 bg-white border-r border-gray-200 fixed h-full flex flex-col">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
          {brand.brand_logo_url ? <img src={brand.brand_logo_url} className="h-7 w-7 rounded" alt="" /> :
           <div className="w-7 h-7 rounded text-white font-bold text-xs flex items-center justify-center" style={{background:brand.brand_primary_color}}>D</div>}
          <span className="font-semibold text-sm text-gray-900">{brand.brand_name}</span>
        </div>
        <nav className="flex-1 py-2 px-2 space-y-0.5">
          {nav.map(n=>(
            <button key={n.id} onClick={()=>{ setPage(n.id); if(n.id!=="audit") setAuditFilters(null); }} className={`w-full flex items-center gap-2 px-3 py-1.5 rounded text-sm ${page===n.id?"bg-emerald-50 text-emerald-700 font-medium":"text-gray-600 hover:bg-gray-50"}`}>
              <span>{n.icon}</span>{n.label}
            </button>
          ))}
        </nav>
        <div className="px-3 py-2 border-t border-gray-100 text-xs text-gray-400">
          {user.full_name} ({user.role})
          <button onClick={()=>{authToken="";localStorage.removeItem("opendms_token");setUser(null);}} className="block mt-1 text-red-400 hover:text-red-600">Logout</button>
        </div>
      </aside>
      <main className="flex-1 ml-52 p-5 max-w-6xl">
        {toast && <div className={`fixed top-3 right-3 z-50 px-4 py-2 rounded-lg shadow text-sm ${toast.t==="error"?"bg-red-50 text-red-700 border border-red-200":"bg-emerald-50 text-emerald-700 border border-emerald-200"}`}>{toast.m}</div>}
        {page==="dashboard" && <DashboardPage notify={notify} user={user} />}
        {page==="documents" && <DocumentsPage notify={notify} user={user} />}
        {page==="intelligence" && <IntelligencePage notify={notify} />}
        {page==="users" && <UsersPage notify={notify} />}
        {page==="organizations" && <OrgsPage notify={notify} onViewLogs={(filters)=>{ setAuditFilters(filters); setPage("audit"); }} />}
        {page==="registers" && <StructurePage type="registers" notify={notify} />}
        {page==="classifications" && <StructurePage type="classifications" notify={notify} />}
        {page==="archive" && <ArchivePage notify={notify} />}
        {page==="audit" && <AuditLogsPage notify={notify} initialFilters={auditFilters} />}
        {page==="settings" && <SettingsPage notify={notify} brand={brand} setBrand={setBrand} />}
      </main>
    </div>
  );
}

function LoginPage({ onLogin, brand }) {
  const [email, setEmail] = useState(""); const [pw, setPw] = useState(""); const [err, setErr] = useState("");
  const submit = async (e) => { e.preventDefault(); try { const r = await fetch(`${API}/auth/login`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password:pw})}); const d = await r.json(); if(!r.ok) throw new Error(d.detail); onLogin(d.user, d.token); } catch(e) { setErr(e.message); }};
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white rounded-xl shadow-lg p-8 w-96">
        <div className="flex items-center gap-3 mb-6">
          {brand.brand_logo_url ? <img src={brand.brand_logo_url} className="h-10 rounded" alt="" /> :
           <div className="w-10 h-10 rounded-lg text-white font-bold text-lg flex items-center justify-center" style={{background:brand.brand_primary_color}}>D</div>}
          <div><div className="font-bold text-lg">{brand.brand_name}</div><div className="text-xs text-gray-400">Document Management System</div></div>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <input value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email" className="w-full px-3 py-2 border rounded-lg text-sm" />
          <input value={pw} onChange={e=>setPw(e.target.value)} placeholder="Password" type="password" className="w-full px-3 py-2 border rounded-lg text-sm" />
          {err && <div className="text-red-600 text-xs">{err}</div>}
          <button className="w-full py-2 text-white rounded-lg text-sm font-medium" style={{background:brand.brand_primary_color}}>Login</button>
        </form>
      </div>
    </div>
  );
}

function DashboardPage({ notify, user }) {
  const [stats, setStats] = useState(null); const [health, setHealth] = useState(null); const [sdkStatus, setSdkStatus] = useState(null);
  useEffect(() => {
    api("/stats").then(setStats).catch(e=>notify(e.message,"error"));
    api("/health").then(setHealth).catch(()=>{});
    api("/sdk/setup-status").then(setSdkStatus).catch(()=>{});
  }, []);

  const statusBadge = (ok, text) => (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ok ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{text}</span>
  );

  return (<div>
    <h2 className="text-xl font-bold text-gray-900 mb-4">Dashboard</h2>
    <div className="text-xs text-gray-500 mb-3">
      Workspace: <strong>{sdkStatus?.default_organization?.name || "No default organization selected"}</strong>
    </div>
    {health && <div className="bg-white border rounded-lg p-3 mb-4">
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600">
        <span>DB: {statusBadge(health.database === "connected", health.database)}</span>
        <span>Storage: <strong>{health.storage_backend}</strong></span>
        <span>SDK service: {statusBadge((health.sdk?.status || "").toLowerCase() === "ok", health.sdk?.status || "unknown")}</span>
        <span>Registry connected: {statusBadge(Boolean(health.sdk_setup?.registry_connected), health.sdk_setup?.registry_connected ? "Yes" : "No")}</span>
        <span>Registry authenticated: {statusBadge(Boolean(health.sdk_setup?.registry_authenticated), health.sdk_setup?.registry_authenticated ? "Yes" : "No")}</span>
        <span>SDK org DID configured: {statusBadge(Boolean(health.sdk_setup?.org_did_configured), health.sdk_setup?.org_did_configured ? "Yes" : "No")}</span>
        <span>Org registered in registry: {statusBadge(Boolean(health.sdk_setup?.org_registered_in_registry), health.sdk_setup?.org_registered_in_registry ? "Yes" : "No")}</span>
        <span>Org verified in registry: {statusBadge(Boolean(health.sdk_setup?.org_verified_in_registry), health.sdk_setup?.org_verified_in_registry ? "Yes" : "No")}</span>
        <span>Last sync error: <strong>{health.sdk_setup?.last_sync_error || "none"}</strong></span>
        <span>Last trace ID: <code>{health.sdk_setup?.trace_id || "n/a"}</code></span>
      </div>
    </div>}
    {stats && <div className="grid grid-cols-4 gap-3 mb-6">
      {[["Documents",stats.documents,"text-blue-600"],["Users",stats.users,"text-emerald-600"],["Organizations",stats.organizations,"text-violet-600"],["Events",stats.events,"text-amber-600"]].map(([l,v,c])=>(
        <div key={l} className="bg-white rounded-lg border p-4"><div className="text-xs text-gray-400">{l}</div><div className={`text-2xl font-bold ${c}`}>{v}</div></div>
      ))}
    </div>}
  </div>);
}

function DocumentsPage({ notify, user }) {
  const [docs, setDocs] = useState([]); const [total, setTotal] = useState(0); const [sel, setSel] = useState(null);
  const [statusF, setStatusF] = useState(""); const [search, setSearch] = useState(""); const [showCreate, setShowCreate] = useState(false);
  const [sdkStatus, setSdkStatus] = useState(null);
  const load = useCallback(async () => { try { const p = new URLSearchParams({page:"1",page_size:"100"}); if(statusF) p.set("status",statusF); if(search) p.set("search",search); const d = await api(`/documents?${p}`); setDocs(d.items); setTotal(d.total); } catch(e){notify(e.message,"error");} }, [statusF,search]);
  useEffect(()=>{load();},[load]);
  useEffect(()=>{ api("/sdk/setup-status").then(setSdkStatus).catch(()=>{}); },[]);
  const loadDetail = async(id) => { try { setSel(await api(`/documents/${id}`)); } catch(e){notify(e.message,"error");} };

  return (<div>
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-xl font-bold">Documents <span className="text-sm font-normal text-gray-400">({total})</span></h2>
      <div className="flex gap-2">
        <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search..." className="text-sm px-3 py-1.5 border rounded-md w-40" />
        <select value={statusF} onChange={e=>setStatusF(e.target.value)} className="text-sm px-2 py-1.5 border rounded-md">
          {["","draft","registered","sent","received","assigned","decided","archived"].map(s=><option key={s} value={s}>{s||"All"}</option>)}
        </select>
        <button onClick={()=>setShowCreate(!showCreate)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded-md">+ New</button>
      </div>
    </div>
    <div className="text-xs text-gray-500 mb-3">
      Workspace: <strong>{sdkStatus?.default_organization?.name || "No default organization selected"}</strong>
    </div>
    {showCreate && <CreateDocForm onDone={()=>{setShowCreate(false);load();}} notify={notify} />}
    <div className="grid grid-cols-5 gap-4">
      <div className="col-span-2 bg-white rounded-lg border">
        <div className="divide-y max-h-[550px] overflow-y-auto">
          {docs.map(d=>(
            <div key={d.id} onClick={()=>loadDetail(d.id)} className={`px-4 py-3 cursor-pointer hover:bg-gray-50 ${sel?.id===d.id?"bg-emerald-50":""}`}>
              <div className="flex items-center justify-between"><span className="text-sm font-medium truncate max-w-[200px]">{d.title}</span><Badge s={d.status}/></div>
              <div className="text-xs text-gray-400 mt-0.5">{d.registration_number} {d.org_name && `\u00b7 ${d.org_name}`}</div>
            </div>
          ))}
          {!docs.length && <div className="p-6 text-center text-gray-400 text-sm">No documents</div>}
        </div>
      </div>
      <div className="col-span-3 bg-white rounded-lg border">
        {sel ? <DocumentDetail doc={sel} onAction={()=>{loadDetail(sel.id);load();}} notify={notify} /> : <div className="p-8 text-center text-gray-400 text-sm">Select a document</div>}
      </div>
    </div>
  </div>);
}

function CreateDocForm({ onDone, notify }) {
  const [title, setTitle] = useState(""); const [summary, setSummary] = useState("");
  const [file, setFile] = useState(null); const [extracting, setExtracting] = useState(false);
  const [aiData, setAiData] = useState({ semanticSummary: null, sensitivityControl: null, route: null });
  const updateSemanticField = (field, value) => setAiData((prev) => { const next = { ...(prev.semanticSummary || {}), [field]: value }; if ((prev.semanticSummary || {}).summarySource === "AI") next.summarySource = "HYBRID"; if (!Object.values(next).some((v) => Array.isArray(v) ? v.length : (v ?? "") !== "")) next.summarySource = "HUMAN"; return { ...prev, semanticSummary: next }; });
  const updateSensitivityField = (field, value) => setAiData((prev) => ({ ...prev, sensitivityControl: { ...(prev.sensitivityControl || {}), [field]: value } }));
  const generateSummary = async () => { if (!file) return notify("Please select a file first", "error"); const fd = new FormData(); fd.append("file", file); fd.append("metadata", JSON.stringify({ title })); try { setExtracting(true); const r = await api("/documents/extract-summary-preview", { method: "POST", body: fd }); setAiData(normalizeSummaryPayload(r)); notify("AI summary generated"); } catch (e) { notify(e.message, "error"); } finally { setExtracting(false); } };
  const submit = async () => { try { const semanticSummary = aiData.semanticSummary; const hasAi = semanticSummary || aiData.sensitivityControl; const aiStatus = hasAi ? (["HUMAN", "HYBRID"].includes(semanticSummary?.summarySource) ? "VALIDATED" : "GENERATED") : "SKIPPED"; await api("/documents",{method:"POST",body:JSON.stringify({title,content_summary:summary,metadata:{},semantic_summary:semanticSummary,sensitivity_control:aiData.sensitivityControl,ai_summary_status:aiStatus})}); notify("Document created"); onDone(); } catch(e){notify(e.message,"error");} };
  return (<div className="bg-white border rounded-lg p-4 mb-4 space-y-3"><input value={title} onChange={e=>setTitle(e.target.value)} placeholder="Document title" className="w-full text-sm px-3 py-2 border rounded" /><input type="file" onChange={e=>setFile(e.target.files?.[0] || null)} className="text-xs" /><div className="flex items-center gap-2"><button onClick={generateSummary} disabled={extracting || !file} className="text-sm px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50">Generate AI Summary</button>{extracting && <span className="text-xs text-gray-500">Processing with SDK...</span>}{aiData.semanticSummary?.aiConfidenceScore != null && <span className="text-xs px-2 py-1 rounded bg-blue-50 text-blue-700">Confidence: {Math.round(aiData.semanticSummary.aiConfidenceScore * 100)}%</span>}</div>{aiData.route && <div className="text-xs text-gray-600 bg-gray-50 rounded p-2">Route: {JSON.stringify(aiData.route)}</div>}<textarea value={summary} onChange={e=>setSummary(e.target.value)} placeholder="Content summary" rows={2} className="w-full text-sm px-3 py-2 border rounded" /><div className="grid grid-cols-2 gap-2">{SUMMARY_FIELDS.map((f)=><input key={f} value={Array.isArray(aiData.semanticSummary?.[f]) ? (aiData.semanticSummary?.[f]||[]).join(",") : (aiData.semanticSummary?.[f] ?? "")} onChange={e=>updateSemanticField(f, ["subTopics","involvedPartyTypes","sectorTags","keywords"].includes(f) ? e.target.value.split(",").map(v=>v.trim()).filter(Boolean) : e.target.value)} placeholder={`AI Summary: ${f}`} className="text-xs px-2 py-1 border rounded" />)}</div><div className="grid grid-cols-2 gap-2">{SENSITIVITY_FIELDS.map((f)=><input key={f} value={typeof aiData.sensitivityControl?.[f] === "boolean" ? String(aiData.sensitivityControl?.[f]) : (aiData.sensitivityControl?.[f] ?? "")} onChange={e=>updateSensitivityField(f, ["allowCentralization","classifiedInformation"].includes(f) ? e.target.value === "true" : e.target.value)} placeholder={`Sensitivity: ${f}`} className="text-xs px-2 py-1 border rounded" />)}</div><div className="text-[11px] text-gray-400">Legacy local AI helper endpoints remain available under /api/ai/*, but this creation flow now uses SDK extract-summary.</div><div className="flex gap-2 justify-end"><button onClick={onDone} className="text-sm px-3 py-1.5 border rounded text-gray-600">Cancel</button><button onClick={submit} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded">Create</button></div></div>);
}

function DocumentDetail({ doc, onAction, notify }) {
  const [sendDid, setSendDid] = useState(""); const [assignId, setAssignId] = useState(""); const [decision, setDecision] = useState(""); const [similar, setSimilar] = useState([]);
  const act = async (path, body) => { try { await api(`/documents/${doc.id}${path}`,{method:"POST",body:JSON.stringify(body)}); notify("Action completed"); onAction(); } catch(e){notify(e.message,"error");} };
  const upload = async (e) => { const f = e.target.files[0]; if(!f) return; const fd = new FormData(); fd.append("file",f); try { await api(`/documents/${doc.id}/upload`,{method:"POST",body:fd}); notify("File uploaded"); onAction(); } catch(e){notify(e.message,"error");} };
  useEffect(()=>{ if (!doc.doc_did || !doc.sensitivity_control?.allowCentralization) return; api(`/intelligence/similar/${doc.doc_did}`).then((r)=>setSimilar(r.items || r.documents || [])).catch(()=>setSimilar([])); }, [doc.id, doc.doc_did, doc.sensitivity_control?.allowCentralization]);
  const source = doc.semantic_summary?.summarySource || "HUMAN";
  return (<div className="p-4 space-y-3"><div className="flex items-center justify-between"><h3 className="font-bold text-gray-900">{doc.title}</h3><Badge s={doc.status}/></div><div>{doc.ai_summary_status && <span className={`text-xs px-2 py-0.5 rounded ${summaryBadgeClass[source] || "bg-gray-100 text-gray-700"}`}>{source}</span>}</div><div className="grid grid-cols-3 gap-2 text-xs"><div><span className="text-gray-400">Reg#</span><div>{doc.registration_number}</div></div><div><span className="text-gray-400">Org</span><div>{doc.org_name||"—"}</div></div><div><span className="text-gray-400">Assigned</span><div>{doc.assigned_name||"—"}</div></div></div>{doc.doc_did && <div className="text-xs"><span className="text-gray-400">DID:</span> <code className="bg-gray-50 px-1 rounded break-all">{doc.doc_did}</code></div>}{doc.content_summary && <div className="text-sm text-gray-700 bg-gray-50 rounded p-2">{doc.content_summary}</div>}{doc.semantic_summary && <pre className="text-xs bg-blue-50 border border-blue-100 rounded p-2 overflow-auto">{JSON.stringify(doc.semantic_summary, null, 2)}</pre>}{doc.sensitivity_control && <pre className="text-xs bg-purple-50 border border-purple-100 rounded p-2 overflow-auto">{JSON.stringify(doc.sensitivity_control, null, 2)}</pre>}{doc.file_name && <div className="text-xs text-gray-500">File: {doc.file_name} ({(doc.file_size/1024).toFixed(1)}KB)</div>}{similar.length > 0 && <div className="border rounded p-2"><div className="text-xs font-medium mb-1">Similar documents</div>{similar.map((s,idx)=><div key={idx} className="text-xs text-gray-600">{s.title || s.docDid || JSON.stringify(s)}</div>)}</div>}<div className="border-t pt-3 space-y-2"><div className="text-xs font-medium text-gray-500">Actions</div><input type="file" onChange={upload} className="text-xs" />{doc.status === "registered" && <div className="flex gap-2"><input value={sendDid} onChange={e=>setSendDid(e.target.value)} placeholder="Recipient org DID" className="flex-1 text-xs px-2 py-1 border rounded" /><button onClick={()=>act("/send",{recipient_org_did:sendDid})} className="text-xs px-3 py-1 bg-amber-500 text-white rounded">Send</button></div>}{doc.status === "received" && <div className="flex gap-2"><input value={assignId} onChange={e=>setAssignId(e.target.value)} placeholder="User ID" className="flex-1 text-xs px-2 py-1 border rounded" /><button onClick={()=>act("/assign",{user_id:parseInt(assignId)})} className="text-xs px-3 py-1 bg-teal-500 text-white rounded">Assign</button></div>}{doc.status === "assigned" && <div className="flex gap-2"><input value={decision} onChange={e=>setDecision(e.target.value)} placeholder="Decision" className="flex-1 text-xs px-2 py-1 border rounded" /><button onClick={()=>act("/decide",{decision})} className="text-xs px-3 py-1 bg-green-600 text-white rounded">Decide</button></div>}{["registered","decided"].includes(doc.status) && <button onClick={()=>act("/archive",{})} className="text-xs px-3 py-1 bg-gray-500 text-white rounded">Archive</button>}</div>{doc.events?.length > 0 && <div className="border-t pt-3"><div className="text-xs font-medium text-gray-500 mb-2">Lifecycle ({doc.events.length} events)</div><div className="space-y-1">{doc.events.map((e,i)=>(<div key={i} className="flex items-center gap-2 bg-gray-50 rounded px-3 py-2 text-xs"><span>{EI[e.event_type]||"\u{1F4CE}"}</span><span className="font-medium">{e.event_type}</span>{e.vc_submitted && <span className="text-emerald-500">\u2713 VC</span>}<span className="text-gray-400 ml-auto">{new Date(e.created_at).toLocaleString()}</span></div>))}</div></div>}</div>);
}

function IntelligencePage({ notify }) {
  const [topics, setTopics] = useState([]); const [warnings, setWarnings] = useState([]); const [briefing, setBriefing] = useState(null);
  const load = useCallback(async () => { try { const [t, w] = await Promise.all([api("/intelligence/topics"), api("/intelligence/warnings")]); setTopics(t.items || t.topics || []); setWarnings(w.items || w.warnings || []); } catch (e) { notify(e.message, "error"); } }, [notify]);
  useEffect(() => { load(); }, [load]);
  const generateBriefing = async () => { try { const r = await api("/intelligence/briefing", { method: "POST", body: JSON.stringify({ context: {} }) }); setBriefing(r); notify("Briefing generated"); } catch (e) { notify(e.message, "error"); } };
  return (<div><div className="flex items-center justify-between mb-4"><h2 className="text-xl font-bold">Intelligence</h2><button onClick={generateBriefing} className="text-sm px-3 py-1.5 bg-indigo-600 text-white rounded">Generate briefing</button></div><div className="grid grid-cols-3 gap-3"><div className="bg-white border rounded p-3"><div className="text-xs text-gray-500 mb-2">Topic trends</div>{topics.length ? topics.map((t,i)=><div key={i} className="text-xs">{t.topic || JSON.stringify(t)}</div>) : <div className="text-xs text-gray-400">No data</div>}</div><div className="bg-white border rounded p-3"><div className="text-xs text-gray-500 mb-2">Active warnings</div>{warnings.length ? warnings.map((w,i)=><div key={i} className="text-xs">{w.title || JSON.stringify(w)}</div>) : <div className="text-xs text-gray-400">No warnings</div>}</div><div className="bg-white border rounded p-3"><div className="text-xs text-gray-500 mb-2">Recent clusters / briefing</div><pre className="text-xs whitespace-pre-wrap">{briefing ? JSON.stringify(briefing, null, 2) : "No briefing generated"}</pre></div></div></div>);
}

function UsersPage({ notify }) {
  const [users, setUsers] = useState([]); const [show, setShow] = useState(false);
  const load = async () => { try { const d = await api("/users"); setUsers(d.items); } catch(e){notify(e.message,"error");} };
  useEffect(()=>{load();},[]);
  const [nf, setNf] = useState({email:"",password:"",full_name:"",role:"operator"});
  const create = async () => { try { await api("/users",{method:"POST",body:JSON.stringify(nf)}); notify("User created"); setShow(false); load(); } catch(e){notify(e.message,"error");} };
  return (<div>
    <div className="flex items-center justify-between mb-4"><h2 className="text-xl font-bold">Users</h2><button onClick={()=>setShow(!show)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded-md">+ New User</button></div>
    {show && <div className="bg-white border rounded-lg p-4 mb-4 grid grid-cols-2 gap-2">
      {[["email","Email"],["password","Password"],["full_name","Full Name"]].map(([k,l])=>(<input key={k} value={nf[k]} onChange={e=>setNf({...nf,[k]:e.target.value})} placeholder={l} type={k==="password"?"password":"text"} className="text-sm px-3 py-2 border rounded" />))}
      <select value={nf.role} onChange={e=>setNf({...nf,role:e.target.value})} className="text-sm px-3 py-2 border rounded">
        {["operator","admin","viewer","superadmin"].map(r=><option key={r} value={r}>{r}</option>)}
      </select>
      <button onClick={create} className="text-sm px-4 py-2 bg-emerald-600 text-white rounded col-span-2">Create</button>
    </div>}
    <div className="bg-white rounded-lg border divide-y">
      {users.map(u=>(<div key={u.id} className="px-4 py-3 flex items-center justify-between">
        <div><div className="text-sm font-medium">{u.full_name}</div><div className="text-xs text-gray-400">{u.email}</div></div>
        <div className="flex items-center gap-2">
          <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{u.role}</span>
          <span className={`w-2 h-2 rounded-full ${u.is_active?"bg-green-400":"bg-red-400"}`}/>
        </div>
      </div>))}
    </div>
  </div>);
}

function OrgsPage({ notify, onViewLogs }) {
  const [orgs, setOrgs] = useState([]); const [show, setShow] = useState(false);
  const [sdkStatus, setSdkStatus] = useState(null); const [orgDidStatus, setOrgDidStatus] = useState({});
  const [registering, setRegistering] = useState({}); const [checking, setChecking] = useState({});

  const load = async () => { try { setOrgs(await api("/organizations")); } catch(e){notify(e.message,"error");} };
  const loadSdkStatus = async () => { try { setSdkStatus(await api("/sdk/setup-status")); } catch(e){ notify(e.message,"error"); } };
  useEffect(()=>{load(); loadSdkStatus();},[]);

  const [nf, setNf] = useState({name:"",code:"",description:""});
  const create = async () => {
    try {
      await api("/organizations",{method:"POST",body:JSON.stringify(nf)});
      notify("Organization created");
      setShow(false);
      setNf({name:"",code:"",description:""});
      load();
      loadSdkStatus();
    } catch(e){notify(e.message,"error");}
  };

  const makeDefault = async (org) => {
    if (!window.confirm(`Make "${org.name}" the default organization for this OpenDMS instance?`)) return;
    try {
      const r = await api(`/organizations/${org.id}/make-default`, { method: "POST" });
      notify(r.message || "Default organization changed");
      await load();
      await loadSdkStatus();
      setOrgDidStatus({});
    } catch (e) {
      notify(e.message, "error");
    }
  };

  const checkDidStatus = async (id) => {
    setChecking(prev => ({...prev, [id]: true}));
    try {
      const status = await api(`/organizations/${id}/did-status`);
      setOrgDidStatus(prev => ({...prev, [id]: status}));
    } catch(e){notify(e.message,"error");}
    finally { setChecking(prev => ({...prev, [id]: false})); }
  };

  const regDid = async (id) => {
    setRegistering(prev => ({...prev, [id]: true}));
    try {
      const r = await api(`/organizations/${id}/register-did`,{method:"POST"});
      if (r.status === "ready") {
        notify(`DID onboarding ready: ${r.did}`);
      } else {
        notify(r.message || "DID created locally, but SDK could not authenticate to central Register.", "error");
      }
      await load();
      await loadSdkStatus();
      await checkDidStatus(id);
    } catch(e){
      const payload = e?.payload;
      if (payload && (payload.error || payload.detail || payload.trace_id)) {
        const parts = [payload.error, payload.detail, payload.trace_id && `trace_id: ${payload.trace_id}`].filter(Boolean);
        notify(parts.join(" | "), "error");
      } else {
        notify(e.message,"error");
      }
    }
    finally { setRegistering(prev => ({...prev, [id]: false})); }
  };

  return (<div>
    <div className="flex items-center justify-between mb-4"><h2 className="text-xl font-bold">Organizations</h2><button onClick={()=>setShow(!show)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded-md">+ New</button></div>

    {sdkStatus && <div className="bg-white border rounded-lg p-4 mb-4">
      <h3 className="text-sm font-semibold mb-2">SDK / Registry Status</h3>
        <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
        <div>Selected organization: <strong>{sdkStatus?.selected_organization?.name || sdkStatus?.default_organization?.name || "none"}</strong></div>
        <div>Default organization DID: <strong>{sdkStatus?.default_organization?.org_did || "not assigned"}</strong></div>
        <div>SDK service status: <strong>{sdkStatus.status || "unknown"}</strong></div>
        <div>Registry URL: <strong>{sdkStatus.registry_url || "n/a"}</strong></div>
        <div>Registry connected: <strong className={sdkStatus.registry_connected ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.registry_connected ? "Yes" : "No"}</strong></div>
        <div>Registry authenticated: <strong className={sdkStatus.registry_authenticated ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.registry_authenticated ? "Yes" : "No"}</strong></div>
        <div>SDK org DID configured: <strong className={sdkStatus.org_did_configured ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.org_did_configured ? "Yes" : "No"}</strong></div>
        <div>Org registered in registry: <strong className={sdkStatus.org_registered_in_registry ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.org_registered_in_registry ? "Yes" : "No"}</strong></div>
        <div>Org verified in registry: <strong className={sdkStatus.org_verified_in_registry ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.org_verified_in_registry ? "Yes" : "No"}</strong></div>
        <div>Organization Registration VC: <strong className={sdkStatus.org_registration_vc ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.org_registration_vc ? "Issued" : "Not issued"}</strong></div>
        <div>Last sync error: <strong>{sdkStatus.last_sync_error || "none"}</strong></div>
        <div>Last trace ID: <strong>{sdkStatus.trace_id || "n/a"}</strong></div>
      </div>
      {!sdkStatus.registry_auth_configured && (
        <div className="text-xs text-amber-700 mt-2">Set REGISTRY_EMAIL and REGISTRY_PASSWORD in OpenDMS docker-compose for the SDK service.</div>
      )}
      {sdkStatus.registry_auth_error && (
        <div className="text-xs text-amber-700 mt-2">Registry auth error: {sdkStatus.registry_auth_error}</div>
      )}
    </div>}

    {show && <div className="bg-white border rounded-lg p-4 mb-4 flex gap-2">
      <input value={nf.name} onChange={e=>setNf({...nf,name:e.target.value})} placeholder="Name" className="flex-1 text-sm px-3 py-2 border rounded" />
      <input value={nf.code} onChange={e=>setNf({...nf,code:e.target.value})} placeholder="Code" className="w-32 text-sm px-3 py-2 border rounded" />
      <input value={nf.description} onChange={e=>setNf({...nf,description:e.target.value})} placeholder="Description" className="flex-1 text-sm px-3 py-2 border rounded" />
      <button onClick={create} className="text-sm px-4 py-2 bg-emerald-600 text-white rounded">Create</button>
    </div>}
    <div className="bg-white rounded-lg border divide-y">
      {orgs.map(o=>{
        const status = orgDidStatus[o.id];
        const setup = status?.sdk_setup_status;
        return (<div key={o.id} className="px-4 py-3 flex items-center justify-between">
          <div>
            <div className="text-sm font-medium flex items-center">
              {o.name}
              {o.is_default && (
                <span className="ml-2 text-[11px] px-2 py-0.5 rounded bg-emerald-100 text-emerald-700">
                  Default
                </span>
              )}
            </div>
            <div className="text-xs text-gray-400">Code: {o.code}</div>
            {o.org_did && <div className="text-xs text-emerald-600 font-mono mt-0.5">{o.org_did}</div>}
            {setup && <div className="text-xs text-gray-500 mt-1 space-y-0.5">
              <div>SDK org DID configured: <strong>{setup.org_did_configured ? "Yes" : "No"}</strong></div>
              <div>Registry connected: <strong>{setup.registry_connected ? "Yes" : "No"}</strong></div>
              <div>Registry auth configured: <strong>{setup.registry_auth_configured ? "Yes" : "No"}</strong></div>
              <div>Registry authenticated: <strong>{setup.registry_authenticated ? "Yes" : "No"}</strong></div>
              {setup.registry_auth_error && <div>Registry auth error: <strong>{setup.registry_auth_error}</strong></div>}
              <div>Local DID matches SDK: <strong>{status.matches_local_org_did ? "Yes" : "No"}</strong></div>
            </div>}
            {o.org_did && (!setup || !setup.org_did_configured || !setup.registry_connected || !setup.registry_auth_configured || !setup.registry_authenticated) && (
              <div className="text-xs text-amber-600 mt-1">
                {!setup || !setup.registry_connected
                  ? "Registry unreachable"
                  : !setup.registry_auth_configured
                  ? "Registry credentials not configured"
                  : !setup.registry_authenticated
                  ? "Registry authentication failed"
                  : "SDK org DID not fully configured"}
              </div>
            )}
          </div>
          <div className="flex gap-2">
            {!o.is_default && (
              <button
                onClick={() => makeDefault(o)}
                className="text-xs px-3 py-1 border rounded text-emerald-700"
              >
                Make Default
              </button>
            )}
            {!o.org_did && <button disabled={registering[o.id]} onClick={()=>regDid(o.id)} className="text-xs px-3 py-1 bg-violet-600 text-white rounded disabled:opacity-60">{registering[o.id] ? "Registering..." : "Register DID"}</button>}
            {o.org_did && <>
              <button disabled={checking[o.id]} onClick={()=>checkDidStatus(o.id)} className="text-xs px-3 py-1 border rounded text-gray-700 disabled:opacity-60">{checking[o.id] ? "Checking..." : "Check status"}</button>
              <button disabled={registering[o.id]} onClick={()=>regDid(o.id)} className="text-xs px-3 py-1 bg-violet-600 text-white rounded disabled:opacity-60">{registering[o.id] ? "Registering..." : "Re-check setup"}</button>
              <button onClick={()=>onViewLogs?.({organization_id:o.id, trace_id:orgDidStatus[o.id]?.trace_id || ""})} className="text-xs px-3 py-1 border rounded text-blue-700">View sync logs</button>
            </>}
          </div>
        </div>);
      })}
    </div>
  </div>);
}


function AuditLogsPage({ notify, initialFilters }) {
  const [summary, setSummary] = useState(null);
  const [openLogs, setOpenLogs] = useState([]);
  const [sdkLogs, setSdkLogs] = useState([]);
  const [activeTab, setActiveTab] = useState("opendms");
  const [selected, setSelected] = useState(null);
  const [filters, setFilters] = useState({ limit:50, offset:0, action:"", success:"", trace_id:"", organization_id:"", ...(initialFilters || {}) });

  const load = useCallback(async()=>{
    try {
      const params = new URLSearchParams();
      params.set("limit", String(filters.limit || 50));
      params.set("offset", String(filters.offset || 0));
      if(filters.action) params.set("action", filters.action);
      if(filters.success !== "") params.set("success", filters.success);
      if(filters.trace_id) params.set("trace_id", filters.trace_id);
      if(filters.organization_id) params.set("organization_id", filters.organization_id);
      const [s, local, sdk] = await Promise.all([
        api("/audit/summary"),
        api(`/audit/logs?${params.toString()}`),
        api(`/audit/sdk-logs?limit=${filters.limit || 50}&offset=${filters.offset || 0}`),
      ]);
      setSummary(s); setOpenLogs(local.items || []); setSdkLogs(sdk.items || sdk.logs || []);
    } catch (e) { notify(e.message, "error"); }
  }, [filters, notify]);

  useEffect(()=>{ load(); }, [load]);

  const statusClass = (row) => row.success ? "text-emerald-700" : (row.action?.includes("requested") ? "text-amber-700" : "text-red-700");

  const rows = activeTab === "opendms" ? openLogs : sdkLogs;
  return <div>
    <h2 className="text-xl font-bold mb-4">Audit Logs</h2>
    {summary && <div className="grid grid-cols-3 gap-3 mb-4">
      {[["OpenDMS actions", summary.opendms_actions],["SDK remote sync calls", summary.sdk_remote_sync_calls],["Failures", summary.failures],["Auth failures", summary.auth_failures],["Org sync failures", summary.org_sync_failures],["Doc sync failures", summary.doc_sync_failures]].map(([k,v])=><div key={k} className="bg-white border rounded p-3"><div className="text-xs text-gray-500">{k}</div><div className="text-xl font-bold">{v}</div></div>)}
    </div>}
    <div className="bg-white border rounded p-3 mb-3 flex gap-2 items-center">
      <button onClick={()=>setActiveTab("opendms")} className={`text-xs px-2 py-1 rounded ${activeTab==='opendms'?'bg-emerald-100 text-emerald-700':'bg-gray-100'}`}>OpenDMS Logs</button>
      <button onClick={()=>setActiveTab("sdk")} className={`text-xs px-2 py-1 rounded ${activeTab==='sdk'?'bg-emerald-100 text-emerald-700':'bg-gray-100'}`}>SDK Logs</button>
      <input value={filters.trace_id} onChange={e=>setFilters({...filters,trace_id:e.target.value})} placeholder="Trace ID" className="text-xs border rounded px-2 py-1" />
      <input value={filters.organization_id} onChange={e=>setFilters({...filters,organization_id:e.target.value})} placeholder="Organization ID" className="text-xs border rounded px-2 py-1 w-28" />
      <input value={filters.action} onChange={e=>setFilters({...filters,action:e.target.value})} placeholder="Action" className="text-xs border rounded px-2 py-1" />
      <select value={filters.success} onChange={e=>setFilters({...filters,success:e.target.value})} className="text-xs border rounded px-2 py-1"><option value="">all</option><option value="true">success</option><option value="false">failed</option></select>
      <button onClick={load} className="text-xs px-3 py-1 bg-blue-600 text-white rounded">Apply</button>
    </div>
    <div className="bg-white border rounded overflow-auto">
      <table className="w-full text-xs"><thead className="bg-gray-50"><tr><th className="p-2 text-left">timestamp</th><th className="p-2 text-left">trace ID</th><th className="p-2 text-left">action</th><th className="p-2 text-left">actor</th><th className="p-2 text-left">organization</th><th className="p-2 text-left">entity</th><th className="p-2 text-left">target</th><th className="p-2 text-left">status</th><th className="p-2 text-left">success</th><th className="p-2 text-left">error</th></tr></thead>
      <tbody>{rows.map((r,idx)=><tr key={r.id || idx} onClick={()=>setSelected(r)} className="border-t hover:bg-gray-50 cursor-pointer"><td className="p-2">{new Date(r.created_at || r.timestamp || Date.now()).toLocaleString()}</td><td className="p-2 font-mono">{r.trace_id || "-"}</td><td className="p-2">{r.action}</td><td className="p-2">{r.actor_email || r.actor || "-"}</td><td className="p-2">{r.organization_code || r.organization_id || "-"}</td><td className="p-2">{r.entity_type} / {r.entity_did || r.entity_id || "-"}</td><td className="p-2">{r.target_system}</td><td className="p-2">{r.response_status || "-"}</td><td className={`p-2 ${statusClass(r)}`}>{String(r.success)}</td><td className="p-2">{r.error_message || "-"}</td></tr>)}</tbody></table>
    </div>
    {selected && <div className="fixed inset-0 bg-black/30 flex items-center justify-center" onClick={()=>setSelected(null)}><div className="bg-white rounded p-4 w-[680px] max-h-[80vh] overflow-auto" onClick={e=>e.stopPropagation()}>
      <h3 className="font-semibold mb-2">Audit details</h3>
      <div className="text-xs space-y-1"><div><strong>Trace ID:</strong> <code>{selected.trace_id}</code></div><div><strong>Target path:</strong> {selected.request_path}</div><div><strong>Payload summary:</strong> <pre className="bg-gray-50 p-2 rounded whitespace-pre-wrap">{selected.request_payload_summary}</pre></div><div><strong>Response summary:</strong> <pre className="bg-gray-50 p-2 rounded whitespace-pre-wrap">{selected.response_summary}</pre></div><div><strong>Error:</strong> {selected.error_message || "none"}</div></div>
      <button onClick={()=>setSelected(null)} className="mt-3 text-xs px-3 py-1 border rounded">Close</button>
    </div></div>}
  </div>;
}

function StructurePage({ type, notify }) {
  const [items, setItems] = useState([]); const [show, setShow] = useState(false);
  const label = type === "registers" ? "Register" : "Classification";
  const load = async () => { try { setItems(await api(`/${type}?flat=true`)); } catch(e){notify(e.message,"error");} };
  useEffect(()=>{load();},[type]);
  const [nf, setNf] = useState({code:"",name:""});
  const create = async () => { try { await api(`/${type}`,{method:"POST",body:JSON.stringify(nf)}); notify(`${label} created`); setShow(false); load(); } catch(e){notify(e.message,"error");} };
  const doImport = async (e) => { const f=e.target.files[0]; if(!f)return; const fd=new FormData(); fd.append("file",f); try { const r=await api(`/${type}/import`,{method:"POST",body:fd}); notify(`Imported ${r.imported}/${r.total}`); load(); } catch(e){notify(e.message,"error");} };
  const doExport = async () => { try { const d=await api(`/${type}/export`); const blob=new Blob([JSON.stringify(d,null,2)],{type:"application/json"}); const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download=`${type}.json`; a.click(); } catch(e){notify(e.message,"error");} };

  return (<div>
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-xl font-bold">{label}s</h2>
      <div className="flex gap-2">
        <label className="text-sm px-3 py-1.5 bg-blue-600 text-white rounded-md cursor-pointer">Import <input type="file" accept=".json" onChange={doImport} className="hidden"/></label>
        <button onClick={doExport} className="text-sm px-3 py-1.5 border rounded-md text-gray-600">Export</button>
        <button onClick={()=>setShow(!show)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded-md">+ New</button>
      </div>
    </div>
    {show && <div className="bg-white border rounded-lg p-4 mb-4 flex gap-2">
      <input value={nf.code} onChange={e=>setNf({...nf,code:e.target.value})} placeholder="Code" className="w-32 text-sm px-3 py-2 border rounded" />
      <input value={nf.name} onChange={e=>setNf({...nf,name:e.target.value})} placeholder="Name" className="flex-1 text-sm px-3 py-2 border rounded" />
      <button onClick={create} className="text-sm px-4 py-2 bg-emerald-600 text-white rounded">Create</button>
    </div>}
    <div className="bg-white rounded-lg border divide-y">
      {items.map(i=>(<div key={i.id} className="px-4 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{i.code}</code>
          <span className="text-sm">{i.name}</span>
          {i.parent_id && <span className="text-xs text-gray-400">(parent: {i.parent_id})</span>}
        </div>
        {i.description && <span className="text-xs text-gray-400 max-w-xs truncate">{i.description}</span>}
      </div>))}
      {!items.length && <div className="p-6 text-center text-gray-400 text-sm">No {type}. Import a schema or create entries.</div>}
    </div>
  </div>);
}

function ArchivePage({ notify }) {
  const [batches, setBatches] = useState([]); const [docIds, setDocIds] = useState(""); const [name, setName] = useState("");
  const load = async () => { try { setBatches(await api("/archive/batches")); } catch(e){notify(e.message,"error");} };
  useEffect(()=>{load();},[]);
  const create = async () => { try { const ids = docIds.split(",").map(s=>parseInt(s.trim())).filter(n=>!isNaN(n)); await api("/archive/batches",{method:"POST",body:JSON.stringify({name,document_ids:ids})}); notify("Batch created"); load(); } catch(e){notify(e.message,"error");} };
  const exp = async (id) => { try { const r = await api(`/archive/batches/${id}/export`,{method:"POST"}); const blob = await r.blob(); const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download=`archive-${id}.zip`; a.click(); notify("Export complete"); } catch(e){notify(e.message,"error");} };

  return (<div>
    <h2 className="text-xl font-bold mb-4">Archive</h2>
    <div className="bg-white border rounded-lg p-4 mb-4 space-y-2">
      <input value={name} onChange={e=>setName(e.target.value)} placeholder="Batch name" className="w-full text-sm px-3 py-2 border rounded" />
      <input value={docIds} onChange={e=>setDocIds(e.target.value)} placeholder="Document IDs (comma-separated)" className="w-full text-sm px-3 py-2 border rounded" />
      <button onClick={create} className="text-sm px-4 py-2 bg-emerald-600 text-white rounded">Create Batch</button>
    </div>
    <div className="bg-white rounded-lg border divide-y">
      {batches.map(b=>(<div key={b.id} className="px-4 py-3 flex items-center justify-between">
        <div><div className="text-sm font-medium">{b.name}</div><div className="text-xs text-gray-400">{b.document_count} docs \u00b7 {b.status}</div></div>
        <button onClick={()=>exp(b.id)} className="text-xs px-3 py-1 bg-blue-600 text-white rounded">Export ZIP</button>
      </div>))}
      {!batches.length && <div className="p-6 text-center text-gray-400 text-sm">No archive batches</div>}
    </div>
  </div>);
}

function SettingsPage({ notify, brand, setBrand }) {
  const [settings, setSettings] = useState({});
  useEffect(()=>{ api("/settings").then(setSettings).catch(e=>notify(e.message,"error")); },[]);
  const save = async (key, value) => { try { await api("/settings",{method:"PUT",body:JSON.stringify({key,value})}); setSettings({...settings,[key]:value}); if(key.startsWith("brand_")) setBrand({...brand,[key]:value}); notify("Saved"); } catch(e){notify(e.message,"error");} };

  return (<div>
    <h2 className="text-xl font-bold mb-4">Settings</h2>
    <div className="space-y-4">
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-semibold text-sm mb-3">Branding</h3>
        <div className="space-y-2">
          {[["brand_name","Application Name"],["brand_logo_url","Logo URL"],["brand_primary_color","Primary Color"]].map(([k,l])=>(
            <div key={k} className="flex items-center gap-3">
              <label className="text-xs text-gray-500 w-32">{l}</label>
              <input value={settings[k]||""} onChange={e=>setSettings({...settings,[k]:e.target.value})}
                className="flex-1 text-sm px-3 py-1.5 border rounded" type={k.includes("color")?"color":"text"} />
              <button onClick={()=>save(k,settings[k]||"")} className="text-xs px-3 py-1 bg-emerald-600 text-white rounded">Save</button>
            </div>
          ))}
        </div>
      </div>
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-semibold text-sm mb-3">Storage</h3>
        <div className="text-sm text-gray-600">Backend: <strong>{settings.storage_backend || "local"}</strong></div>
        <div className="text-xs text-gray-400 mt-1">Configure via environment variables (OPENDMS_STORAGE_*)</div>
      </div>
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-semibold text-sm mb-3">VeriDocs SDK</h3>
        <div className="text-sm text-gray-600">Status: <strong>{settings.sdk_enabled === "true" || settings.sdk_enabled === undefined ? "Enabled" : "Disabled"}</strong></div>
        <div className="text-sm text-gray-600">URL: <strong>{settings.sdk_url || "(default)"}</strong></div>
      </div>
    </div>
  </div>);
}
