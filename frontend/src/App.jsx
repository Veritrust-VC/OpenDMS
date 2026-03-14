import { useState, useEffect, useCallback } from "react";

const API = "/api";
let authToken = localStorage.getItem("opendms_token") || "";

// ── FIX: React-driven logout instead of window.location.reload() ──
let _logoutHandler = null;
let _isLoggingOut = false;
function setLogoutHandler(handler) { _logoutHandler = handler; }

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}) };
  if (opts.body instanceof FormData) { delete headers["Content-Type"]; }
  const res = await fetch(`${API}${path}`, { headers, ...opts });
  if (res.status === 401) {
    if (!_isLoggingOut) {
      _isLoggingOut = true;
      authToken = "";
      localStorage.removeItem("opendms_token");
      if (_logoutHandler) _logoutHandler();
    }
    throw new Error("Session expired");
  }
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

const SUMMARY_FIELD_LABELS = {
  primaryTopic: "Primary Topic", subTopics: "Sub Topics", summary: "Summary",
  documentPurpose: "Document Purpose", requestedAction: "Requested Action",
  involvedPartyTypes: "Involved Party Types", geographicScope: "Geographic Scope",
  sectorTags: "Sector Tags", legalDomain: "Legal Domain",
  estimatedRiskLevel: "Estimated Risk Level", urgencyLevel: "Urgency Level",
  keywords: "Keywords", summarySource: "Summary Source",
  aiConfidenceScore: "AI Confidence Score", aiModelVersion: "AI Model Version",
};
const SENSITIVITY_FIELD_LABELS = {
  allowCentralization: "Allow Centralization", redactionLevel: "Redaction Level",
  personalDataRisk: "Personal Data Risk", accessRestrictionBasis: "Access Restriction Basis",
  classifiedInformation: "Classified Information",
};
const PERSONAL_DATA_RISK_LABELS = { NONE: "None", LOW: "Low", MEDIUM: "Medium", HIGH: "High" };
const BOOL_DISPLAY = (v) => v === true || v === "true" ? "Yes" : v === false || v === "false" ? "No" : "—";

export default function App() {
  const [user, setUser] = useState(null);
  const [page, setPage] = useState("dashboard");
  const [brand, setBrand] = useState({ brand_name: "OpenDMS", brand_primary_color: "#0d7c66", brand_logo_url: "" });
  const [toast, setToast] = useState(null);
  const [auditFilters, setAuditFilters] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const notify = (m, t="success") => { setToast({m,t}); setTimeout(()=>setToast(null),4000); };

  useEffect(() => {
    setLogoutHandler(() => setUser(null));
    return () => setLogoutHandler(null);
  }, []);

  useEffect(() => { api("/settings/branding").then(setBrand).catch(()=>{}); }, []);
  useEffect(() => { if (authToken) { api("/users/me/profile").then(setUser).catch(()=>{ authToken=""; localStorage.removeItem("opendms_token"); }); } }, []);

  if (!user) return <LoginPage onLogin={(u,t)=>{ authToken=t; localStorage.setItem("opendms_token",t); _isLoggingOut = false; setUser(u); }} brand={brand} />;

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
      { id:"ai-instructions", label:"AI Prompts", icon:"\u{1F4DD}" },
    ] : []),
    ...(user.role === "superadmin" ? [{ id:"settings", label:"Settings", icon:"\u{2699}\uFE0F" }] : []),
  ];

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <aside className={`${sidebarOpen ? "w-52" : "w-14"} bg-white border-r border-gray-200 fixed h-full flex flex-col transition-all duration-200 z-30`}>
        <div className="px-3 py-3 border-b border-gray-100 flex items-center gap-2">
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="w-7 h-7 rounded flex items-center justify-center hover:bg-gray-100 flex-shrink-0" title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}>
            {brand.brand_logo_url ? <img src={brand.brand_logo_url} className="h-7 w-7 rounded" alt="" /> :
             <div className="w-7 h-7 rounded text-white font-bold text-xs flex items-center justify-center" style={{background:brand.brand_primary_color}}>D</div>}
          </button>
          {sidebarOpen && <span className="font-semibold text-sm text-gray-900 truncate">{brand.brand_name}</span>}
        </div>
        <nav className="flex-1 py-2 px-1.5 space-y-0.5 overflow-y-auto overflow-x-hidden">
          {nav.map(n=>(
            <button key={n.id} onClick={()=>{ setPage(n.id); if(n.id!=="audit") setAuditFilters(null); }} title={sidebarOpen ? undefined : n.label}
              className={`w-full flex items-center gap-2 ${sidebarOpen ? "px-3" : "px-0 justify-center"} py-1.5 rounded text-sm ${page===n.id?"bg-emerald-50 text-emerald-700 font-medium":"text-gray-600 hover:bg-gray-50"}`}>
              <span className="flex-shrink-0 text-base">{n.icon}</span>{sidebarOpen && <span className="truncate">{n.label}</span>}
            </button>
          ))}
        </nav>
        <div className={`${sidebarOpen ? "px-3" : "px-1 text-center"} py-2 border-t border-gray-100 text-xs text-gray-400`}>
          {sidebarOpen ? <>{user.full_name} ({user.role})</> : <span title={`${user.full_name} (${user.role})`}>👤</span>}
          <button onClick={()=>{authToken="";localStorage.removeItem("opendms_token");setUser(null);}} className={`${sidebarOpen ? "block" : "block mx-auto"} mt-1 text-red-400 hover:text-red-600`}>{sidebarOpen ? "Logout" : "⏻"}</button>
        </div>
      </aside>
      <main className={`flex-1 ${sidebarOpen ? "ml-52" : "ml-14"} p-5 transition-all duration-200`}>
        {toast && <div className={`fixed top-3 right-3 z-50 px-4 py-2 rounded-lg shadow text-sm ${toast.t==="error"?"bg-red-50 text-red-700 border border-red-200":"bg-emerald-50 text-emerald-700 border border-emerald-200"}`}>{toast.m}</div>}
        {page==="dashboard" && <DashboardPage notify={notify} user={user} />}
        {page==="documents" && <DocumentsPage notify={notify} user={user} />}
        {page==="intelligence" && <IntelligencePage notify={notify} />}
        {page==="users" && <UsersPage notify={notify} />}
        {page==="organizations" && <OrgsPage notify={notify} onViewLogs={(filters)=>{ setAuditFilters(filters); setPage("audit"); }} />}
        {page==="registers" && <StructurePage type="registers" notify={notify} />}
        {page==="classifications" && <StructurePage type="classifications" notify={notify} />}
        {page==="archive" && <ArchivePage notify={notify} />}
        {page==="ai-instructions" && <AIInstructionsPage notify={notify} />}
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
        <span>Last trace ID: <code>{health.sdk_setup?.last_trace_id || health.sdk_setup?.trace_id || "n/a"}</code></span>
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
              <div className="flex items-center justify-between"><span className={`text-sm font-medium truncate max-w-[200px] ${!d.title ? "text-gray-400 italic" : ""}`}>{d.title || "Untitled Document"}</span><Badge s={d.status}/></div>
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

  const handleFileChange = (e) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    if (f && !title.trim()) {
      setTitle(f.name.replace(/\.[^.]+$/, ""));
    }
  };

  const generateMetadata = async () => {
    if (!file) return notify("Please select a file first", "error");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("metadata", JSON.stringify({ title }));
    try {
      setExtracting(true);
      const r = await api("/documents/generate-metadata-preview", { method: "POST", body: fd });
      const normalized = normalizeSummaryPayload(r);
      setAiData(normalized);
      if (!normalized.semanticSummary && !normalized.sensitivityControl) {
        notify("Metadata generation returned no data. Please try again.", "error");
      } else {
        const conf = normalized.semanticSummary?.aiConfidenceScore;
        const route = r.route || "direct";
        notify(`Metadata generated (route: ${route}, confidence: ${conf ? Math.round(conf * 100) + '%' : 'N/A'})`);
      }
    } catch (e) {
      notify(e.message || "Metadata generation failed, please try again.", "error");
    } finally {
      setExtracting(false);
    }
  };

  const submit = async () => {
    try {
      const semanticSummary = aiData.semanticSummary;
      const hasAi = semanticSummary || aiData.sensitivityControl;
      const aiStatus = hasAi ? (["HUMAN", "HYBRID"].includes(semanticSummary?.summarySource) ? "VALIDATED" : "GENERATED") : "SKIPPED";
      const doc = await api("/documents", { method: "POST", body: JSON.stringify({ title, content_summary: summary, metadata: {}, semantic_summary: semanticSummary, sensitivity_control: aiData.sensitivityControl, ai_summary_status: aiStatus }) });
      if (file && doc?.id) {
        try {
          const fd = new FormData();
          fd.append("file", file);
          await api(`/documents/${doc.id}/files`, { method: "POST", body: fd });
        } catch (e) {
          notify("Document created, but file upload failed: " + e.message, "error");
          onDone();
          return;
        }
      }
      if (doc?.vc_submitted) {
        notify(`Document created with DID ${doc.doc_did?.slice(-20) || ''} — VC submitted to Register`);
      } else if (doc?.sdk_error) {
        notify(`Document created locally, but SDK failed: ${doc.sdk_error}`, "error");
      } else if (!doc?.doc_did) {
        notify("Document created locally — no DID assigned (SDK unavailable)", "error");
      } else {
        notify("Document created");
      }
      onDone();
    } catch (e) { notify(e.message, "error"); }
  };

  const renderSensitivityField = (f) => {
    const label = SENSITIVITY_FIELD_LABELS[f] || f;
    const val = aiData.sensitivityControl?.[f];
    if (["allowCentralization", "classifiedInformation"].includes(f)) {
      return (
        <div key={f} className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">{label}</label>
          <select value={val === true || val === "true" ? "true" : val === false || val === "false" ? "false" : ""}
            onChange={e => updateSensitivityField(f, e.target.value === "" ? "" : e.target.value === "true")}
            className="text-xs px-2 py-1 border rounded">
            <option value="">— Select —</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        </div>
      );
    }
    if (f === "personalDataRisk") {
      return (
        <div key={f} className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">{label}</label>
          <select value={val ?? ""} onChange={e => updateSensitivityField(f, e.target.value)} className="text-xs px-2 py-1 border rounded">
            <option value="">— Select —</option>
            {Object.entries(PERSONAL_DATA_RISK_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      );
    }
    return (
      <div key={f} className="flex flex-col gap-0.5">
        <label className="text-[10px] text-gray-500">{label}</label>
        <input value={val ?? ""} onChange={e => updateSensitivityField(f, e.target.value)} className="text-xs px-2 py-1 border rounded" />
      </div>
    );
  };

  return (
    <div className="bg-white border rounded-lg p-4 mb-4 space-y-3">
      <input value={title} onChange={e=>setTitle(e.target.value)} placeholder="Document title" className="w-full text-sm px-3 py-2 border rounded" />
      <input type="file" onChange={handleFileChange} className="text-xs" />
      <div className="flex items-center gap-2">
        <button onClick={generateMetadata} disabled={extracting || !file} className="text-sm px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50">
          {extracting ? "Generating metadata..." : "🧠 Generate Metadata"}
        </button>
        {aiData.semanticSummary?.aiConfidenceScore != null && (
          <span className="text-xs px-2 py-1 rounded bg-blue-50 text-blue-700">Confidence: {Math.round(aiData.semanticSummary.aiConfidenceScore * 100)}%</span>
        )}
      </div>
      {aiData.route && <div className="text-xs text-gray-600 bg-gray-50 rounded p-2">Route: {JSON.stringify(aiData.route)}</div>}
      <textarea value={summary} onChange={e=>setSummary(e.target.value)} placeholder="Content summary" rows={2} className="w-full text-sm px-3 py-2 border rounded" />
      <div className="grid grid-cols-2 gap-2">
        {SUMMARY_FIELDS.map((f) => (
          <div key={f} className="flex flex-col gap-0.5">
            <label className="text-[10px] text-gray-500">{SUMMARY_FIELD_LABELS[f] || f}</label>
            <input
              value={Array.isArray(aiData.semanticSummary?.[f]) ? (aiData.semanticSummary?.[f]||[]).join(",") : (aiData.semanticSummary?.[f] ?? "")}
              onChange={e=>updateSemanticField(f, ["subTopics","involvedPartyTypes","sectorTags","keywords"].includes(f) ? e.target.value.split(",").map(v=>v.trim()).filter(Boolean) : e.target.value)}
              className="text-xs px-2 py-1 border rounded"
            />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {SENSITIVITY_FIELDS.map(renderSensitivityField)}
      </div>
      <div className="flex gap-2 justify-end">
        <button onClick={onDone} className="text-sm px-3 py-1.5 border rounded text-gray-600">Cancel</button>
        <button onClick={submit} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded">Create</button>
      </div>
    </div>
  );
}

function DocumentDetail({ doc, onAction, notify }) {
  const [sendDid, setSendDid] = useState("");
  const [assignId, setAssignId] = useState("");
  const [decision, setDecision] = useState("");
  const [similar, setSimilar] = useState([]);
  const [files, setFiles] = useState(doc.files || []);
  const [generating, setGenerating] = useState(false);
  const [showMetadata, setShowMetadata] = useState(false);
  const [metaTab, setMetaTab] = useState("summary");

  const act = async (path, body) => {
    try {
      await api(`/documents/${doc.id}${path}`, { method: "POST", body: JSON.stringify(body) });
      notify("Action completed");
      onAction();
    } catch (e) { notify(e.message, "error"); }
  };

  const uploadFile = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try {
      await api(`/documents/${doc.id}/files`, { method: "POST", body: fd });
      notify("File added");
      onAction();
    } catch (e) { notify(e.message, "error"); }
  };

  const removeFile = async (fileId) => {
    if (!window.confirm("Remove this file?")) return;
    try {
      await api(`/documents/${doc.id}/files/${fileId}`, { method: "DELETE" });
      notify("File removed");
      onAction();
    } catch (e) { notify(e.message, "error"); }
  };

  const generateMetadata = async () => {
    try {
      setGenerating(true);
      const r = await api(`/documents/${doc.id}/generate-metadata`, { method: "POST" });
      const conf = r.semanticSummary?.aiConfidenceScore;
      const route = r.route || "unknown";
      notify(`Metadati ģenerēti (maršruts: ${route}, ticamība: ${conf ? Math.round(conf * 100) + '%' : 'N/A'})`);
      onAction();
    } catch (e) { notify(e.message, "error"); }
    finally { setGenerating(false); }
  };

  const exportMetadataXml = async () => {
    try {
      const res = await fetch(`/api/documents/${doc.id}/export-metadata`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${doc.registration_number || doc.id}_metadata.xml`;
      a.click();
    } catch (e) { notify(e.message, "error"); }
  };

  useEffect(() => {
    if (doc.files) setFiles(doc.files);
  }, [doc.id, doc.files]);

  useEffect(() => {
    if (!doc.doc_did || !doc.sensitivity_control?.allowCentralization) return;
    api(`/intelligence/similar/${doc.doc_did}`)
      .then((r) => setSimilar(r.items || r.documents || []))
      .catch(() => setSimilar([]));
  }, [doc.id, doc.doc_did, doc.sensitivity_control?.allowCentralization]);

  const source = doc.semantic_summary?.summarySource || "HUMAN";
  const hasFiles = files.length > 0 || doc.file_name;
  const hasMeta = !!doc.semantic_summary;

  return (
    <div className="p-4 space-y-3 overflow-auto max-h-[80vh]">
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-gray-900">{doc.title}</h3>
        <Badge s={doc.status} />
      </div>
      {doc.ai_summary_status && (
        <span className={`text-xs px-2 py-0.5 rounded ${summaryBadgeClass[source] || "bg-gray-100 text-gray-700"}`}>
          {source}
        </span>
      )}

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div><span className="text-gray-400">Reg#</span><div>{doc.registration_number}</div></div>
        <div><span className="text-gray-400">Org</span><div>{doc.org_name || "—"}</div></div>
        <div><span className="text-gray-400">Assigned</span><div>{doc.assigned_name || "—"}</div></div>
      </div>

      {doc.doc_did && (
        <div className="text-xs">
          <span className="text-gray-400">DID:</span>{" "}
          <code className="bg-gray-50 px-1 rounded break-all">{doc.doc_did}</code>
        </div>
      )}
      {!doc.doc_did && doc.status !== "draft" && (
        <div className="text-xs bg-amber-50 border border-amber-200 text-amber-700 rounded px-3 py-2">
          <div className="font-medium">⚠ No DID assigned — document was not registered in VeriDocs Registry</div>
          {doc.metadata?._sdk_error && (
            <div className="mt-1 text-amber-600">SDK error: {doc.metadata._sdk_error}</div>
          )}
          {doc.metadata?._sdk_error_trace_id && (
            <div className="mt-0.5 text-amber-500 text-[10px]">Trace: {doc.metadata._sdk_error_trace_id}</div>
          )}
          {!doc.metadata?._sdk_error && (
            <div className="mt-1 text-amber-600">Check SDK connectivity in Organizations page.</div>
          )}
        </div>
      )}

      <div className="border rounded-lg p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-medium text-gray-500">
            Files ({files.length || (doc.file_name ? 1 : 0)})
          </div>
          <label className="text-xs px-2 py-1 bg-emerald-600 text-white rounded cursor-pointer">
            + Add File
            <input type="file" onChange={uploadFile} className="hidden" />
          </label>
        </div>

        {files.length > 0 ? (
          <div className="space-y-1">
            {files.map((f) => (
              <div key={f.id} className="flex items-center justify-between bg-gray-50 rounded px-2 py-1.5 text-xs">
                <div className="flex items-center gap-2">
                  {f.is_primary && (
                    <span className="text-[10px] px-1 py-0.5 bg-blue-100 text-blue-700 rounded">Primary</span>
                  )}
                  <span className="font-medium">{f.file_name}</span>
                  <span className="text-gray-400">
                    {f.file_size ? `${(f.file_size / 1024).toFixed(1)}KB` : ""}
                  </span>
                  <span className="text-gray-400">{f.mime_type}</span>
                </div>
                <button onClick={() => removeFile(f.id)} className="text-red-400 hover:text-red-600">✕</button>
              </div>
            ))}
          </div>
        ) : doc.file_name ? (
          <div className="text-xs text-gray-500">
            {doc.file_name} ({(doc.file_size / 1024).toFixed(1)}KB)
          </div>
        ) : (
          <div className="text-xs text-gray-400">No files attached</div>
        )}
      </div>

      <div className="flex gap-2 flex-wrap">
        <button
          onClick={generateMetadata}
          disabled={generating || !hasFiles}
          className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50 flex items-center gap-1"
        >
          {generating ? (<><span className="animate-spin">⟳</span> Ģenerē...</>) : ("🧠 Generate Metadata")}
        </button>
        {hasMeta && (
          <>
            <button onClick={() => setShowMetadata(true)} className="text-xs px-3 py-1.5 bg-indigo-600 text-white rounded">👁 View Metadata</button>
            <button onClick={exportMetadataXml} className="text-xs px-3 py-1.5 border border-gray-300 text-gray-700 rounded">📥 Export XML</button>
          </>
        )}
      </div>

      {doc.semantic_summary?.aiConfidenceScore != null && (
        <div className="text-xs flex items-center gap-2">
          <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700">AI Confidence: {Math.round(doc.semantic_summary.aiConfidenceScore * 100)}%</span>
          <span className="text-gray-400">Model: {doc.semantic_summary.aiModelVersion || "—"}</span>
          {doc.semantic_summary.humanValidationStatus === "PENDING" && (
            <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-700">Awaiting validation</span>
          )}
        </div>
      )}

      {doc.content_summary && <div className="text-sm text-gray-700 bg-gray-50 rounded p-2">{doc.content_summary}</div>}

      {similar.length > 0 && (
        <div className="border rounded p-2">
          <div className="text-xs font-medium mb-1">Similar documents</div>
          {similar.map((s, idx) => (<div key={idx} className="text-xs text-gray-600">{s.title || s.docDid || JSON.stringify(s)}</div>))}
        </div>
      )}

      <div className="border-t pt-3 space-y-2">
        <div className="text-xs font-medium text-gray-500">Actions</div>
        {doc.status === "registered" && (
          <div className="flex gap-2">
            <input value={sendDid} onChange={(e) => setSendDid(e.target.value)} placeholder="Recipient org DID" className="flex-1 text-xs px-2 py-1 border rounded" />
            <button onClick={() => act("/send", { recipient_org_did: sendDid })} className="text-xs px-3 py-1 bg-amber-500 text-white rounded">Send</button>
          </div>
        )}
        {doc.status === "received" && (
          <div className="flex gap-2">
            <input value={assignId} onChange={(e) => setAssignId(e.target.value)} placeholder="User ID" className="flex-1 text-xs px-2 py-1 border rounded" />
            <button onClick={() => act("/assign", { user_id: parseInt(assignId) })} className="text-xs px-3 py-1 bg-teal-500 text-white rounded">Assign</button>
          </div>
        )}
        {doc.status === "assigned" && (
          <div className="flex gap-2">
            <input value={decision} onChange={(e) => setDecision(e.target.value)} placeholder="Decision" className="flex-1 text-xs px-2 py-1 border rounded" />
            <button onClick={() => act("/decide", { decision })} className="text-xs px-3 py-1 bg-green-600 text-white rounded">Decide</button>
          </div>
        )}
        {["registered", "decided"].includes(doc.status) && (
          <button onClick={() => act("/archive", {})} className="text-xs px-3 py-1 bg-gray-500 text-white rounded">Archive</button>
        )}
      </div>

      {doc.events?.length > 0 && (
        <div className="border-t pt-3">
          <div className="text-xs font-medium text-gray-500 mb-2">Lifecycle ({doc.events.length} events)</div>
          <div className="space-y-1">
            {doc.events.map((e, i) => {
              const details = typeof e.details === "string" ? JSON.parse(e.details || "{}") : (e.details || {});
              return (
                <div key={i} className="bg-gray-50 rounded px-3 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span>{EI[e.event_type] || "📎"}</span>
                    <span className="font-medium">{e.event_type}</span>
                    {e.vc_submitted ? <span className="text-emerald-500">✓ VC</span> : <span className="text-red-400">✗ no VC</span>}
                    <span className="text-gray-400 ml-auto">{new Date(e.created_at).toLocaleString()}</span>
                  </div>
                  {details.sdk_error && (
                    <div className="mt-1 text-red-500 text-[10px]">SDK error: {details.sdk_error}</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {showMetadata && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setShowMetadata(false)}>
          <div className="bg-white rounded-lg p-5 w-[720px] max-h-[85vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold">Document Metadata</h3>
              <button onClick={() => setShowMetadata(false)} className="text-gray-400 hover:text-gray-600">✕</button>
            </div>

            <div className="flex gap-1 mb-3 border-b">
              {["summary", "sensitivity", "raw"].map((t) => (
                <button key={t} onClick={() => setMetaTab(t)} className={`text-xs px-3 py-1.5 ${metaTab === t ? "border-b-2 border-blue-600 text-blue-700 font-medium" : "text-gray-500"}`}>
                  {t === "summary" ? "Summary" : t === "sensitivity" ? "Sensitivity" : "Raw JSON"}
                </button>
              ))}
            </div>

            {metaTab === "summary" && doc.semantic_summary && (
              <div className="space-y-2 text-xs">
                <div><span className="font-medium text-gray-500">Primary Topic:</span> {doc.semantic_summary.primaryTopic}</div>
                {doc.semantic_summary.subTopics?.length > 0 && <div><span className="font-medium text-gray-500">Sub-topics:</span> {doc.semantic_summary.subTopics.join(", ")}</div>}
                <div className="bg-blue-50 rounded p-2"><span className="font-medium text-blue-700">Summary:</span><div className="mt-1">{doc.semantic_summary.summary}</div></div>
                {doc.semantic_summary.documentPurpose && <div><span className="font-medium text-gray-500">Purpose:</span> {doc.semantic_summary.documentPurpose}</div>}
                {doc.semantic_summary.requestedAction && <div><span className="font-medium text-gray-500">Requested Action:</span> {doc.semantic_summary.requestedAction}</div>}
                {doc.semantic_summary.keywords?.length > 0 && (
                  <div className="flex flex-wrap gap-1">{doc.semantic_summary.keywords.map((k, i) => (<span key={i} className="px-1.5 py-0.5 bg-gray-100 rounded text-[10px]">{k}</span>))}</div>
                )}
                <div className="grid grid-cols-3 gap-2 pt-2 border-t">
                  <div><span className="text-gray-400">Risk:</span> {doc.semantic_summary.estimatedRiskLevel || "—"}</div>
                  <div><span className="text-gray-400">Urgency:</span> {doc.semantic_summary.urgencyLevel || "—"}</div>
                  <div><span className="text-gray-400">Language:</span> {doc.semantic_summary.detectedLanguage || "—"}</div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[10px] text-gray-400 pt-2 border-t">
                  <div>Source: {doc.semantic_summary.summarySource}</div>
                  <div>Confidence: {doc.semantic_summary.aiConfidenceScore != null ? Math.round(doc.semantic_summary.aiConfidenceScore * 100) + "%" : "—"}</div>
                  <div>Model: {doc.semantic_summary.aiModelVersion || "—"}</div>
                  <div>Validation: {doc.semantic_summary.humanValidationStatus || "—"}</div>
                </div>
              </div>
            )}

            {metaTab === "sensitivity" && doc.sensitivity_control && (
              <div className="space-y-2 text-xs">
                <div className={`p-2 rounded ${doc.sensitivity_control.personalDataRisk === "HIGH" ? "bg-red-50 text-red-700" : doc.sensitivity_control.personalDataRisk === "MEDIUM" ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>
                  Personal Data Risk: <strong>{PERSONAL_DATA_RISK_LABELS[doc.sensitivity_control.personalDataRisk] || doc.sensitivity_control.personalDataRisk || "None"}</strong>
                </div>
                <div>Allow Centralization: <strong>{BOOL_DISPLAY(doc.sensitivity_control.allowCentralization)}</strong></div>
                {doc.sensitivity_control.redactionLevel && <div>Redaction Level: <strong>{doc.sensitivity_control.redactionLevel}</strong></div>}
                {doc.sensitivity_control.classifiedInformation && <div className="bg-red-100 text-red-800 p-2 rounded font-medium">⚠ Contains classified information</div>}
                {doc.sensitivity_control.detectedEntityTypes?.length > 0 && (
                  <div>
                    <span className="text-gray-500">Detected entity types:</span>
                    <div className="flex flex-wrap gap-1 mt-1">{doc.sensitivity_control.detectedEntityTypes.map((t, i) => (<span key={i} className="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded text-[10px]">{t}</span>))}</div>
                  </div>
                )}
              </div>
            )}

            {metaTab === "raw" && (
              <pre className="text-xs bg-gray-50 border rounded p-3 overflow-auto max-h-96 whitespace-pre-wrap">
                {JSON.stringify({ semanticSummary: doc.semantic_summary, sensitivityControl: doc.sensitivity_control }, null, 2)}
              </pre>
            )}

            <div className="flex gap-2 mt-4 justify-end">
              <button onClick={exportMetadataXml} className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded">Export XML</button>
              <button onClick={() => setShowMetadata(false)} className="text-xs px-3 py-1.5 border rounded text-gray-600">Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Intelligence Page — FIXED ──
// Bug 1: notify was a dep of useCallback → recreated every render → infinite polling loop
// Bug 2: topics/warnings returned 502 when SDK unavailable → now backend returns empty lists
// Bug 3: briefing was rendered as raw JSON stringify → now uses BriefingDisplay component
function IntelligencePage({ notify }) {
  const [topics, setTopics] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [briefing, setBriefing] = useState(null);
  const [loadingBriefing, setLoadingBriefing] = useState(false);

  // Load once on mount — NO notify in deps (was causing infinite re-render loop)
  useEffect(() => {
    let cancelled = false;
    api("/intelligence/topics")
      .then(t => { if (!cancelled) setTopics(t.items || t.topics || []); })
      .catch(() => { if (!cancelled) setTopics([]); });
    api("/intelligence/warnings")
      .then(w => { if (!cancelled) setWarnings(w.items || w.warnings || []); })
      .catch(() => { if (!cancelled) setWarnings([]); });
    return () => { cancelled = true; };
  }, []); // empty deps — fire once only

  const generateBriefing = async () => {
    setLoadingBriefing(true);
    try {
      const r = await api("/intelligence/briefing", {
        method: "POST",
        body: JSON.stringify({ context: {} }),
      });
      setBriefing(r);
      notify("Briefing generated");
    } catch (e) {
      notify(e.message, "error");
    } finally {
      setLoadingBriefing(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Intelligence</h2>
        <button
          onClick={generateBriefing}
          disabled={loadingBriefing}
          className="text-sm px-3 py-1.5 bg-indigo-600 text-white rounded disabled:opacity-50"
        >
          {loadingBriefing ? "Generating…" : "Generate briefing"}
        </button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {/* Topic trends */}
        <div className="bg-white border rounded p-3">
          <div className="text-xs font-medium text-gray-500 mb-2">Topic trends</div>
          {topics.length ? (
            topics.map((t, i) => (
              <div key={i} className="text-xs py-1 border-b border-gray-50 last:border-0">
                <span className="font-medium">{t.topic || t.primary_topic || "—"}</span>
                {t.documents != null && (
                  <span className="text-gray-400 ml-2">{t.documents} docs</span>
                )}
              </div>
            ))
          ) : (
            <div className="text-xs text-gray-400">No data</div>
          )}
        </div>

        {/* Active warnings */}
        <div className="bg-white border rounded p-3">
          <div className="text-xs font-medium text-gray-500 mb-2">Active warnings</div>
          {warnings.length ? (
            warnings.map((w, i) => (
              <div key={i} className="text-xs py-1 border-b border-gray-50 last:border-0">
                <span className="font-medium text-amber-700">{w.title || w.topic || "Warning"}</span>
                {w.description && (
                  <div className="text-gray-500 mt-0.5">{w.description}</div>
                )}
              </div>
            ))
          ) : (
            <div className="text-xs text-gray-400">No warnings</div>
          )}
        </div>

        {/* Briefing — now rendered as structured UI */}
        <div className="bg-white border rounded p-3">
          <div className="text-xs font-medium text-gray-500 mb-2">Recent clusters / briefing</div>
          {briefing ? (
            <BriefingDisplay briefing={briefing} />
          ) : (
            <div className="text-xs text-gray-400">No briefing generated</div>
          )}
        </div>
      </div>
    </div>
  );
}

// Render briefing as structured UI — handles both markdown and structured JSON formats
function BriefingDisplay({ briefing }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!briefing) return null;

  // Markdown briefing (from VeriDocs Register AI sidecar)
  if (briefing.markdown) {
    return (
      <div className="text-xs space-y-1">
        <pre className="whitespace-pre-wrap text-gray-700 text-[10px] leading-relaxed overflow-auto max-h-64">
          {briefing.markdown}
        </pre>
      </div>
    );
  }

  // Structured briefing (from local AI fallback)
  return (
    <div className="text-xs space-y-2">
      {briefing.summary && (
        <p className="text-gray-700 leading-relaxed">{briefing.summary}</p>
      )}
      {briefing.key_topics?.length > 0 && (
        <div>
          <div className="text-[10px] text-gray-400 uppercase font-medium mb-1">Key topics</div>
          <div className="flex flex-wrap gap-1">
            {briefing.key_topics.map((t, i) => (
              <span key={i} className="px-1.5 py-0.5 bg-indigo-50 text-indigo-700 rounded text-[10px]">{t}</span>
            ))}
          </div>
        </div>
      )}
      {briefing.notable_items?.length > 0 && (
        <div>
          <div className="text-[10px] text-gray-400 uppercase font-medium mb-1">Notable</div>
          <ul className="space-y-0.5">
            {briefing.notable_items.map((item, i) => (
              <li key={i} className="text-gray-600">• {item}</li>
            ))}
          </ul>
        </div>
      )}
      {briefing.document_count != null && (
        <div className="text-[10px] text-gray-400">
          {briefing.document_count} documents analysed
          {briefing.source && ` · ${briefing.source}`}
        </div>
      )}
      <button
        onClick={() => setShowRaw(!showRaw)}
        className="text-[10px] text-gray-400 hover:text-gray-600 underline"
      >
        {showRaw ? "Hide raw JSON" : "Show raw JSON"}
      </button>
      {showRaw && (
        <pre className="text-[10px] bg-gray-50 rounded p-2 overflow-auto max-h-48 whitespace-pre-wrap">
          {JSON.stringify(briefing, null, 2)}
        </pre>
      )}
    </div>
  );
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
  const [didViewer, setDidViewer] = useState(null);
  const [vcViewer, setVcViewer] = useState(null);
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
        <div>SDK service status: <strong className={
          (sdkStatus.status === "ok" || sdkStatus.sdk_service_status === "ok" || (sdkStatus.registry_connected && sdkStatus.org_did_configured))
            ? "text-emerald-600" : "text-amber-600"
        }>{sdkStatus.status || sdkStatus.sdk_service_status || (sdkStatus.registry_connected ? "connected" : "degraded")}</strong></div>
        <div>Registry URL: <strong>{sdkStatus.registry_url || "n/a"}</strong></div>
        <div>Registry connected: <strong className={sdkStatus.registry_connected ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.registry_connected ? "Yes" : "No"}</strong></div>
        <div>Registry authenticated: <strong className={sdkStatus.registry_authenticated ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.registry_authenticated ? "Yes" : "No"}</strong></div>
        <div>SDK org DID configured: <strong className={sdkStatus.org_did_configured ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.org_did_configured ? "Yes" : "No"}</strong></div>
        <div>Org registered in registry: <strong className={sdkStatus.org_registered_in_registry ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.org_registered_in_registry ? "Yes" : "No"}</strong></div>
        <div>Org verified in registry: <strong className={sdkStatus.org_verified_in_registry ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.org_verified_in_registry ? "Yes" : "No"}</strong></div>
        <div>Organization Registration VC: <strong className={sdkStatus.org_registration_vc ? "text-emerald-600" : "text-amber-600"}>{sdkStatus.org_registration_vc ? "Issued" : "Not issued"}</strong></div>
        <div>Last sync error: <strong>{sdkStatus.last_sync_error || "none"}</strong></div>
        <div>Last trace ID: <strong>{sdkStatus.last_trace_id || sdkStatus.trace_id || "n/a"}</strong></div>
      </div>
      {!sdkStatus.registry_auth_configured && (
        <div className="text-xs text-amber-700 mt-2">Set REGISTRY_EMAIL and REGISTRY_PASSWORD in OpenDMS docker-compose for the SDK service.</div>
      )}
      {sdkStatus.registry_auth_error && (
        <div className="text-xs text-amber-700 mt-2">Registry auth error: {sdkStatus.registry_auth_error}</div>
      )}
      {sdkStatus.sdk_auth_ok === false && (
        <div className="text-xs bg-red-50 border border-red-200 text-red-700 rounded p-2 mt-2">
          ⚠ <strong>SDK API key not configured</strong> — all write operations (document create, DID register, lifecycle events) will fail.
          Set <code className="bg-red-100 px-1 rounded">VERAMO_API_KEY</code> in <code className="bg-red-100 px-1 rounded">.env</code> and rebuild.
          {sdkStatus.sdk_auth_error && <span className="block mt-1 text-red-500">{sdkStatus.sdk_auth_error}</span>}
        </div>
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
                <span className="ml-2 text-[11px] px-2 py-0.5 rounded bg-emerald-100 text-emerald-700">Default</span>
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
          </div>
          <div className="flex gap-2">
            {!o.is_default && (
              <button onClick={() => makeDefault(o)} className="text-xs px-3 py-1 border rounded text-emerald-700">Make Default</button>
            )}
            {!o.org_did && <button disabled={registering[o.id]} onClick={()=>regDid(o.id)} className="text-xs px-3 py-1 bg-violet-600 text-white rounded disabled:opacity-60">{registering[o.id] ? "Registering..." : "Register DID"}</button>}
            {o.org_did && <>
              <button disabled={checking[o.id]} onClick={()=>checkDidStatus(o.id)} className="text-xs px-3 py-1 border rounded text-gray-700 disabled:opacity-60">{checking[o.id] ? "Checking..." : "Check status"}</button>
              <button disabled={registering[o.id]} onClick={()=>regDid(o.id)} className="text-xs px-3 py-1 bg-violet-600 text-white rounded disabled:opacity-60">{registering[o.id] ? "Registering..." : "Re-check setup"}</button>
              <button onClick={async()=>{ try { const r = await api(`/organizations/${o.id}/did-document`); setDidViewer(r); } catch(e){ notify(e.message,"error"); }}} className="text-xs px-3 py-1 border rounded text-indigo-700">View DID</button>
              <button onClick={async()=>{ try { const r = await api(`/organizations/${o.id}/registration-vc`); setVcViewer(r); } catch(e){ notify(e.message,"error"); }}} className="text-xs px-3 py-1 border rounded text-purple-700">View VC</button>
              <button onClick={()=>onViewLogs?.({organization_id:o.id, trace_id:orgDidStatus[o.id]?.trace_id || ""})} className="text-xs px-3 py-1 border rounded text-blue-700">View sync logs</button>
            </>}
          </div>
        </div>);
      })}
    </div>

    {didViewer && (
      <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={()=>setDidViewer(null)}>
        <div className="bg-white rounded-lg p-5 w-[720px] max-h-[85vh] overflow-auto" onClick={e=>e.stopPropagation()}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold">DID Document</h3>
            <button onClick={()=>setDidViewer(null)} className="text-gray-400 hover:text-gray-600">✕</button>
          </div>
          <div className="text-xs mb-2"><span className="text-gray-500">Organization:</span> <strong>{didViewer.organization?.name}</strong></div>
          <div className="text-xs mb-3"><span className="text-gray-500">DID:</span> <code className="bg-gray-50 px-1 rounded break-all">{didViewer.organization?.org_did}</code></div>
          {didViewer.didDocument ? (
            <pre className="text-xs bg-gray-50 border rounded p-3 overflow-auto max-h-96 whitespace-pre-wrap">{JSON.stringify(didViewer.didDocument, null, 2)}</pre>
          ) : (
            <div className="text-xs text-amber-600 bg-amber-50 rounded p-3">DID document could not be resolved. The DID may not be published or the SDK agent is unreachable.</div>
          )}
          <div className="flex gap-2 mt-3 justify-end">
            <button onClick={()=>{ navigator.clipboard.writeText(JSON.stringify(didViewer.didDocument, null, 2)); notify("Copied to clipboard"); }} className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded">Copy JSON</button>
            <button onClick={()=>setDidViewer(null)} className="text-xs px-3 py-1.5 border rounded text-gray-600">Close</button>
          </div>
        </div>
      </div>
    )}

    {vcViewer && (
      <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={()=>setVcViewer(null)}>
        <div className="bg-white rounded-lg p-5 w-[720px] max-h-[85vh] overflow-auto" onClick={e=>e.stopPropagation()}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold">Organization Registration VC</h3>
            <button onClick={()=>setVcViewer(null)} className="text-gray-400 hover:text-gray-600">✕</button>
          </div>
          <div className="text-xs mb-2"><span className="text-gray-500">Organization:</span> <strong>{vcViewer.organization?.name}</strong></div>
          <div className="text-xs mb-2"><span className="text-gray-500">DID:</span> <code className="bg-gray-50 px-1 rounded break-all">{vcViewer.organization?.org_did}</code></div>
          <div className="text-xs mb-3 flex gap-3">
            <span>VC present: <strong className={vcViewer.registration_vc_present ? "text-emerald-600" : "text-red-500"}>{vcViewer.registration_vc_present ? "Yes" : "No"}</strong></span>
            {vcViewer.last_setup && <span>Lifecycle ready: <strong className={vcViewer.last_setup.lifecycle_ready ? "text-emerald-600" : "text-amber-600"}>{vcViewer.last_setup.lifecycle_ready ? "Yes" : "No"}</strong></span>}
            {vcViewer.last_setup?.timestamp && <span className="text-gray-400">Setup: {new Date(vcViewer.last_setup.timestamp).toLocaleString()}</span>}
          </div>
          {vcViewer.last_setup?.registry && (
            <div className="text-xs grid grid-cols-2 gap-1 mb-3 bg-gray-50 rounded p-2">
              <div>Connected: <strong>{vcViewer.last_setup.registry.connected ? "Yes" : "No"}</strong></div>
              <div>Authenticated: <strong>{vcViewer.last_setup.registry.authenticated ? "Yes" : "No"}</strong></div>
              <div>Registered: <strong>{vcViewer.last_setup.registry.registered ? "Yes" : "No"}</strong></div>
              <div>Verified: <strong>{vcViewer.last_setup.registry.verified ? "Yes" : "No"}</strong></div>
              {vcViewer.last_setup.registry.error && <div className="col-span-2 text-red-500">Error: {vcViewer.last_setup.registry.error}</div>}
            </div>
          )}
          {vcViewer.registration_vc ? (
            <>
              <div className="text-xs font-medium text-gray-500 mb-1">Registration VC</div>
              <pre className="text-xs bg-gray-50 border rounded p-3 overflow-auto max-h-64 whitespace-pre-wrap">{JSON.stringify(vcViewer.registration_vc, null, 2)}</pre>
            </>
          ) : (
            <div className="text-xs text-amber-600 bg-amber-50 rounded p-3 mb-3">
              No registration VC cached. The VC was not captured during initial registration (org was already in Registry with HTTP 409).
              Click "Recover VC" to attempt re-registration.
            </div>
          )}
          {vcViewer.registry_org_data?.did_document && (
            <>
              <div className="text-xs font-medium text-gray-500 mt-3 mb-1">Registry DID Document (proof of registration)</div>
              <pre className="text-xs bg-blue-50 border border-blue-200 rounded p-3 overflow-auto max-h-64 whitespace-pre-wrap">{JSON.stringify(vcViewer.registry_org_data.did_document, null, 2)}</pre>
            </>
          )}
          <div className="flex gap-2 mt-4 justify-end">
            {!vcViewer.registration_vc && vcViewer.organization?.org_did && (
              <button onClick={async()=>{
                try {
                  const orgId = vcViewer.organization?.id || vcViewer.organization?.org_id;
                  if (!orgId) { notify("Missing org ID", "error"); return; }
                  const r = await api(`/organizations/${orgId}/recover-vc`, { method: "POST" });
                  if (r.registration_vc) {
                    setVcViewer(prev => ({...prev, registration_vc: r.registration_vc, registration_vc_present: true}));
                    notify("Registration VC recovered");
                  } else {
                    notify(r.message || "VC recovery attempted but no VC returned", "error");
                  }
                } catch(e) { notify(e.message, "error"); }
              }} className="text-xs px-3 py-1.5 bg-violet-600 text-white rounded">Recover VC</button>
            )}
            {vcViewer.registration_vc && <button onClick={()=>{ navigator.clipboard.writeText(JSON.stringify(vcViewer.registration_vc, null, 2)); notify("Copied to clipboard"); }} className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded">Copy VC JSON</button>}
            <button onClick={()=>setVcViewer(null)} className="text-xs px-3 py-1.5 border rounded text-gray-600">Close</button>
          </div>
        </div>
      </div>
    )}
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
    <div className="bg-white border rounded overflow-x-auto">
      <table className="w-full text-xs" style={{minWidth:"1100px"}}><thead className="bg-gray-50"><tr><th className="p-2 text-left whitespace-nowrap">timestamp</th><th className="p-2 text-left" style={{minWidth:"120px"}}>trace ID</th><th className="p-2 text-left whitespace-nowrap">action</th><th className="p-2 text-left whitespace-nowrap">actor</th><th className="p-2 text-left whitespace-nowrap">organization</th><th className="p-2 text-left" style={{minWidth:"160px"}}>entity</th><th className="p-2 text-left whitespace-nowrap">target</th><th className="p-2 text-left whitespace-nowrap">status</th><th className="p-2 text-left whitespace-nowrap">success</th><th className="p-2 text-left" style={{minWidth:"200px"}}>error</th></tr></thead>
      <tbody>{rows.map((r,idx)=><tr key={r.id || idx} onClick={()=>setSelected(r)} className="border-t hover:bg-gray-50 cursor-pointer"><td className="p-2 whitespace-nowrap">{new Date(r.created_at || r.timestamp || Date.now()).toLocaleString()}</td><td className="p-2 font-mono text-[10px] break-all">{(r.trace_id || "-").slice(0,13)}</td><td className="p-2 whitespace-nowrap">{r.action}</td><td className="p-2 whitespace-nowrap">{r.actor_email || r.actor || "-"}</td><td className="p-2 whitespace-nowrap">{r.organization_code || r.organization_id || "-"}</td><td className="p-2 break-all">{r.entity_type} / {r.entity_did || r.entity_id || "-"}</td><td className="p-2">{r.target_system}</td><td className="p-2">{r.response_status || "-"}</td><td className={`p-2 ${statusClass(r)}`}>{String(r.success)}</td><td className="p-2 break-words max-w-xs">{r.error_message || "-"}</td></tr>)}</tbody></table>
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


function AIInstructionsPage({ notify }) {
  const [instructions, setInstructions] = useState([]);
  const [selected, setSelected] = useState(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [reason, setReason] = useState("");
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);

  const load = async () => {
    try {
      const d = await api("/ai-instructions");
      setInstructions(d.items || []);
    } catch (e) { notify(e.message, "error"); }
  };

  useEffect(() => { load(); }, []);

  const selectInstruction = async (key) => {
    try {
      const d = await api(`/ai-instructions/${encodeURIComponent(key)}`);
      setSelected(d);
      setDraft(d.content || "");
      setEditing(false);
      setShowHistory(false);
    } catch (e) { notify(e.message, "error"); }
  };

  const saveInstruction = async () => {
    if (!selected) return;
    try {
      await api(`/ai-instructions/${encodeURIComponent(selected.instruction_key)}`, {
        method: "PUT",
        body: JSON.stringify({ content: draft, change_reason: reason || null }),
      });
      notify(`Saved v${selected.version + 1}`);
      setReason("");
      setEditing(false);
      await selectInstruction(selected.instruction_key);
      await load();
    } catch (e) { notify(e.message, "error"); }
  };

  const loadHistory = async () => {
    if (!selected) return;
    try {
      const d = await api(`/ai-instructions/${encodeURIComponent(selected.instruction_key)}/history`);
      setHistory(d.items || []);
      setShowHistory(true);
    } catch (e) { notify(e.message, "error"); }
  };

  const restoreVersion = async (version) => {
    if (!selected || !window.confirm(`Restore version ${version}?`)) return;
    try {
      await api(`/ai-instructions/${encodeURIComponent(selected.instruction_key)}/restore/${version}`, { method: "POST" });
      notify(`Restored version ${version}`);
      await selectInstruction(selected.instruction_key);
      await load();
    } catch (e) { notify(e.message, "error"); }
  };

  const categories = [...new Set(instructions.map((i) => i.category))];

  return (<div>
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-xl font-bold">AI Instructions</h2>
      <div className="text-xs text-gray-400">System prompts, guardrails, and AI configuration — stored in database.</div>
    </div>
    <div className="grid grid-cols-4 gap-4">
      <div className="col-span-1 bg-white border rounded-lg">
        <div className="divide-y max-h-[600px] overflow-y-auto">
          {categories.map((cat) => (
            <div key={cat}>
              <div className="px-3 py-1.5 bg-gray-50 text-[10px] font-semibold text-gray-500 uppercase">{cat}</div>
              {instructions.filter((i) => i.category === cat).map((i) => (
                <div key={i.instruction_key} onClick={() => selectInstruction(i.instruction_key)}
                  className={`px-3 py-2 cursor-pointer hover:bg-gray-50 text-xs ${selected?.instruction_key === i.instruction_key ? "bg-blue-50" : ""}`}>
                  <div className="font-medium">{i.display_name}</div>
                  <div className="text-gray-400 text-[10px]">v{i.version} · {new Date(i.updated_at).toLocaleDateString()}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="col-span-3 bg-white border rounded-lg p-4">
        {selected ? (<div className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-semibold">{selected.display_name}</h3>
              <div className="text-xs text-gray-400">{selected.instruction_key} · v{selected.version} · {selected.content_type}</div>
              {selected.description && <div className="text-xs text-gray-500 mt-1">{selected.description}</div>}
            </div>
            <div className="flex gap-2">
              <button onClick={loadHistory} className="text-xs px-2 py-1 border rounded text-gray-600">History</button>
              {!editing ? <button onClick={() => setEditing(true)} className="text-xs px-3 py-1 bg-blue-600 text-white rounded">Edit</button> : (
                <>
                  <button onClick={() => { setEditing(false); setDraft(selected.content || ""); }} className="text-xs px-2 py-1 border rounded text-gray-600">Cancel</button>
                  <button onClick={saveInstruction} className="text-xs px-3 py-1 bg-emerald-600 text-white rounded">Save</button>
                </>
              )}
            </div>
          </div>
          {editing && <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Change reason (optional, for audit trail)" className="w-full text-xs px-3 py-1.5 border rounded" />}
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} readOnly={!editing} rows={20}
            className={`w-full text-xs px-3 py-2 border rounded font-mono ${editing ? "bg-white" : "bg-gray-50"}`} />
          {showHistory && (
            <div className="border rounded p-3">
              <div className="text-xs font-medium mb-2">Version History</div>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {history.map((h) => (
                  <div key={h.id} className="flex items-center justify-between bg-gray-50 rounded px-2 py-1.5 text-xs">
                    <div>
                      <span className="font-medium">v{h.version}</span>
                      <span className="text-gray-400 ml-2">{h.changed_by_name || "Unknown"} · {new Date(h.created_at).toLocaleString()}</span>
                      {h.change_reason && <span className="text-gray-500 ml-2">— {h.change_reason}</span>}
                    </div>
                    <button onClick={() => restoreVersion(h.version)} className="text-xs px-2 py-0.5 border rounded text-blue-600">Restore</button>
                  </div>
                ))}
                {!history.length && <div className="text-gray-400 text-xs">No previous versions</div>}
              </div>
            </div>
          )}
        </div>) : <div className="text-center text-gray-400 text-sm py-12">Select an instruction to view or edit</div>}
      </div>
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
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-semibold text-sm mb-3">AI</h3>
        <div className="text-sm text-gray-600">Provider: <strong>{settings.ai_provider || "anthropic"}</strong></div>
        <div className="text-sm text-gray-600">API Key: <strong>{settings.ai_key_configured ? "✓ Configured" : "✗ Not set"}</strong></div>
        <div className="text-xs text-gray-400 mt-1">Set OPENDMS_LLM_API_KEY in .env file</div>
      </div>
    </div>
  </div>);
}
