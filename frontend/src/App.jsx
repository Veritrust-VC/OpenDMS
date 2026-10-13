import { useState, useEffect, useCallback, useRef } from "react";
import UapfPage from "./UapfPage.jsx";
import BpmnDiagram from "./components/BpmnDiagram.jsx";
import LandingPage from "./LandingPage.jsx";
import ConnectionsPage from "./ConnectionsPage.jsx";
import AgentPage from "./AgentPage.jsx";
import StoragePage from "./StoragePage.jsx";
import BrandMark from "./BrandMark.jsx";
import Icon from "./Icon.jsx";
import ForwardingCard from "./ForwardingCard.jsx";
import ActiveClassifiers from "./ClassifiersPage.jsx";

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

// ── Document lifecycle log: compact per-event detail rendering ──
const UAPF_EI = {
  "session.created": "▶️", "step.entered": "▸",
  "capability.invoking": "⚙️", "capability.invoked": "⚙️",
  "decision.evaluated": "⚖️", "session.completed": "✅",
  "session.failed": "⛔",
};
function fmtEventVal(v) {
  if (v == null) return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "object") { try { return JSON.stringify(v); } catch { return "—"; } }
  const str = String(v);
  return str.length > 80 ? str.slice(0, 80) + "…" : str;
}
function uapfEventDetail(eventType, details) {
  const t = eventType || "";
  const d = (details && details.data) || {};
  if (t.includes("session.created"))
    return { line: "Process: " + (d.processId || (details && details.uapfpackageid) || "—") };
  if (t.includes("step.entered"))
    return { line: ((details && details.uapfstepid) || "") + (d.nodeName ? " — " + d.nodeName : "") };
  if (t.includes("capability.invoking"))
    return { line: "Izsauc " + (d.capability || "?") + (d.nodeName ? " — " + d.nodeName : "") };
  if (t.includes("capability.invoked")) {
    const kv = (d.output && typeof d.output === "object")
      ? Object.entries(d.output).filter(function (e) { return !String(e[0]).startsWith("_"); })
          .slice(0, 5).map(function (e) { return e[0] + ": " + fmtEventVal(e[1]); })
      : [];
    return { line: (d.capability || "?") + " ✓", kv: kv };
  }
  if (t.includes("decision.evaluated")) {
    const res = (d.result && typeof d.result === "object") ? d.result : {};
    const kv = Object.entries(res).map(function (e) { return e[0] + ": " + fmtEventVal(e[1]); });
    const rules = Array.isArray(d.rulesFired) ? d.rulesFired.join(", ") : "";
    return { line: "Lēmums: " + (d.decisionId || "?"), kv: kv, rules: rules, accent: true };
  }
  if (t.includes("session.completed"))
    return { line: Array.isArray(d.trace) ? ("Pabeigts — " + d.trace.length + " soļi") : "Pabeigts" };
  if (t.includes("session.failed"))
    return { line: "Neizdevās: " + (d.error || d.reason || "nezināms"), err: true };
  return null;
}


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
  const [route, setRoute] = useState(() => window.location.pathname.split("/").filter(Boolean));
  const navigate = useCallback((path, opts = {}) => {
    let p = (path.startsWith("/") ? path : "/" + path).replace(/\/+$/, "") || "/";
    if (window.location.pathname !== p) {
      window.history[opts.replace ? "replaceState" : "pushState"]({}, "", p);
    }
    setRoute(p.split("/").filter(Boolean));
  }, []);
  const page = route[0] || "dashboard";
  const setPage = (id) => navigate("/" + id);
  const [brand, setBrand] = useState({ brand_name: "Dokumentu vadības aģents", brand_primary_color: "#0d7c66", brand_logo_url: "" });
  const [toast, setToast] = useState(null);
  const [auditFilters, setAuditFilters] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // Accepts notify("text", "error") and notify({ t: "error", m: "text" }) — the
  // UAPF pages use the object form; rendering that object blanked the page.
  const notify = (m, t="success") => {
    if (m && typeof m === "object") { t = m.t === "ok" ? "success" : (m.t || t); m = m.m; }
    setToast({ m: String(m ?? ""), t }); setTimeout(()=>setToast(null),4000);
  };

  useEffect(() => {
    const onPop = () => setRoute(window.location.pathname.split("/").filter(Boolean));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    setLogoutHandler(() => setUser(null));
    return () => setLogoutHandler(null);
  }, []);

  useEffect(() => { api("/settings/branding").then(setBrand).catch(()=>{}); }, []);
  useEffect(() => { if (authToken) { api("/users/me/profile").then(setUser).catch(()=>{ authToken=""; localStorage.removeItem("opendms_token"); }); } }, []);
  useEffect(() => { if (user && route.length === 0) navigate("/dashboard", { replace: true }); }, [user]);

  if (!user) {
    const _onLogin = (u,t)=>{ authToken=t; localStorage.setItem("opendms_token",t); _isLoggingOut = false; setUser(u); navigate("/dashboard", { replace: true }); };
    if (route[0] === "login") return <LoginPage onLogin={_onLogin} brand={brand} />;
    return <LandingPage brand={brand} onLoginClick={()=>navigate("/login")} />;
  }

  const isAdmin = ["superadmin","admin"].includes(user.role);
  // Ordered by how central each area is to what this system now does.
  // The agent leads, then the documents it acts on, then the machinery it
  // acts through, then configuration, then housekeeping.
  // Grouped rather than a flat list of fifteen. Fifteen equal-weight items is
  // a wall — the eye has nowhere to rest and everything looks equally urgent.
  // The groups say what each area is FOR, which is also the information
  // hierarchy: what the agent does, what it runs on, what it keeps, who
  // administers it.
  const navGroups = [
    { title: null, items: [
      { id:"agent",         label:"Aģents",           icon:"agent", roles:["superadmin","admin"] },
      { id:"dashboard",     label:"Pārskats",         icon:"dashboard" },
      { id:"documents",     label:"Dokumenti",        icon:"document" },
      { id:"storage",       label:"Glabātuve",        icon:"folder" },
      { id:"intelligence",  label:"Analīze",          icon:"insight" },
    ]},
    { title: "Procesi", items: [
      { id:"uapf",          label:"UAPF procesi",     icon:"process", roles:["superadmin","admin"] },
      { id:"connections",   label:"Savienojumi",      icon:"plug", roles:["superadmin","admin"] },
      { id:"ai-instructions", label:"MI uzvednes",    icon:"prompt", roles:["superadmin","admin"] },
    ]},
    { title: "Reģistrs", items: [
      { id:"registers",     label:"Reģistri",         icon:"folder", roles:["superadmin","admin"] },
      { id:"classifications", label:"Klasifikatori",  icon:"tag", roles:["superadmin","admin"] },
      { id:"archive",       label:"Arhīvs",           icon:"archive", roles:["superadmin","admin"] },
      { id:"audit",         label:"Audita pieraksti", icon:"audit", roles:["superadmin","admin"] },
    ]},
    { title: "Pārvaldība", items: [
      { id:"organizations", label:"Organizācijas",    icon:"building", roles:["superadmin","admin"] },
      { id:"users",         label:"Lietotāji",        icon:"users", roles:["superadmin","admin"] },
      { id:"settings",      label:"Iestatījumi",      icon:"settings", roles:["superadmin"] },
      { id:"account",       label:"Mans konts",       icon:"user" },
    ]},
  ].map(g => ({ ...g, items: g.items.filter(n => !n.roles || n.roles.includes(user.role)) }))
   .filter(g => g.items.length);

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <aside className={`${sidebarOpen ? "w-60" : "w-16"} bg-white border-r border-ink-200 fixed h-full flex flex-col transition-[width] duration-200 z-30`}>
        <div className={`h-14 flex items-center gap-2.5 border-b border-ink-100 ${sidebarOpen ? "px-3" : "px-0 justify-center"}`}>
          <button onClick={() => setSidebarOpen(!sidebarOpen)}
            aria-label={sidebarOpen ? "Sakļaut izvēlni" : "Izvērst izvēlni"}
            className="rounded-md hover:opacity-80 transition-opacity cursor-pointer">
            {brand.brand_logo_url ? <img src={brand.brand_logo_url} className="h-8 w-8 rounded-md" alt="" /> :
             <BrandMark size={32} color={brand.brand_primary_color} className="rounded-md" />}
          </button>
          {sidebarOpen && (
            <div className="min-w-0">
              <div className="text-sm font-semibold text-ink-900 leading-tight truncate">{brand.brand_name}</div>
              <div className="text-2xs text-ink-400 leading-tight">Lietvedības procesi</div>
            </div>
          )}
        </div>

        <nav className="flex-1 py-3 px-2 overflow-y-auto overflow-x-hidden">
          {navGroups.map((g, gi) => (
            <div key={gi} className={gi ? "mt-5" : ""}>
              {g.title && sidebarOpen && <div className="label-eyebrow px-2.5 mb-1.5">{g.title}</div>}
              {g.title && !sidebarOpen && <div className="mx-3 mb-2 border-t border-ink-100" />}
              <div className="space-y-0.5">
                {g.items.map(n => {
                  const active = page === n.id;
                  return (
                    <button key={n.id} onClick={()=>{ setPage(n.id); if(n.id!=="audit") setAuditFilters(null); }}
                      title={sidebarOpen ? undefined : n.label}
                      aria-current={active ? "page" : undefined}
                      className={`w-full flex items-center gap-2.5 min-h-[36px] rounded-md text-sm transition-colors cursor-pointer
                        ${sidebarOpen ? "px-2.5" : "px-0 justify-center"}
                        ${active ? "bg-brand-50 text-brand-700 font-medium" : "text-ink-600 hover:bg-ink-50 hover:text-ink-900"}`}>
                      <Icon name={n.icon} size={18} className={active ? "text-brand-600" : "text-ink-400"} />
                      {sidebarOpen && <span className="truncate">{n.label}</span>}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className={`border-t border-ink-100 ${sidebarOpen ? "px-3 py-2.5" : "px-1 py-2.5 text-center"}`}>
          {sidebarOpen ? (
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="text-xs font-medium text-ink-700 truncate">{user.full_name}</div>
                <div className="text-2xs text-ink-400">{user.role}</div>
              </div>
              <button onClick={()=>{authToken="";localStorage.removeItem("opendms_token");setUser(null);}}
                className="text-2xs text-ink-400 hover:text-red-600 transition-colors cursor-pointer shrink-0">
                Iziet
              </button>
            </div>
          ) : (
            <button onClick={()=>{authToken="";localStorage.removeItem("opendms_token");setUser(null);}}
              title={`${user.full_name} — iziet`} aria-label="Iziet"
              className="mx-auto flex items-center justify-center text-ink-400 hover:text-red-600 transition-colors cursor-pointer">
              <Icon name="user" size={18} />
            </button>
          )}
        </div>
      </aside>
      <main className={`flex-1 ${sidebarOpen ? "ml-60" : "ml-16"} transition-[margin] duration-200`}>
        <div className="mx-auto max-w-[1400px] px-6 py-6">
        {toast && <div className={`fixed top-3 right-3 z-50 px-4 py-2 rounded-lg shadow text-sm ${toast.t==="error"?"bg-red-50 text-red-700 border border-red-200":"bg-emerald-50 text-emerald-700 border border-emerald-200"}`}>{toast.m}</div>}
        {page==="dashboard" && <DashboardPage notify={notify} user={user} />}
        {page==="documents" && <DocumentsPage notify={notify} user={user} route={route} navigate={navigate} />}
        {page==="intelligence" && <IntelligencePage notify={notify} />}
        {page==="users" && <UsersPage notify={notify} user={user} route={route} navigate={navigate} />}
        {page==="organizations" && <OrgsPage notify={notify} onViewLogs={(filters)=>{ setAuditFilters(filters); setPage("audit"); }} />}
        {page==="registers" && <StructurePage type="registers" notify={notify} />}
        {page==="classifications" && <><ActiveClassifiers notify={notify} />
          <StructurePage type="classifications" notify={notify} /></>}
        {page==="archive" && <ArchivePage notify={notify} />}
        {page==="storage" && <StoragePage notify={notify} route={route} navigate={navigate} />}
        {page==="ai-instructions" && <AIInstructionsPage notify={notify} />}
        {page==="uapf" && <UapfPage notify={notify} user={user} route={route} navigate={navigate} />}
        {page==="connections" && <ConnectionsPage notify={notify} />}
        {page==="agent" && <AgentPage notify={notify} />}
        {page==="audit" && <AuditLogsPage notify={notify} initialFilters={auditFilters} />}
        {page==="settings" && <SettingsPage notify={notify} brand={brand} setBrand={setBrand} />}
        {page==="account" && <AccountPage notify={notify} user={user} />}
        </div>
      </main>
    </div>
  );
}

function LoginPage({ onLogin, brand }) {
  const [email, setEmail] = useState(""); const [pw, setPw] = useState(""); const [err, setErr] = useState("");
    // Offer the organisation's identity provider first where one is configured.
  const [oidc, setOidc] = useState(null);
  useEffect(() => { fetch(`${API}/auth/oidc/config`).then(r => r.ok ? r.json() : null)
    .then(d => { if (d && d.enabled) setOidc(d); }).catch(() => {}); }, []);
const submit = async (e) => { e.preventDefault(); try { const r = await fetch(`${API}/auth/login`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password:pw})}); const d = await r.json(); if(!r.ok) throw new Error(d.detail); onLogin(d.user, d.token); } catch(e) { setErr(e.message); }};
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white rounded-xl shadow-lg p-8 w-96">
        <div className="flex items-center gap-3 mb-6">
          {brand.brand_logo_url ? <img src={brand.brand_logo_url} className="h-10 rounded" alt="" /> :
           <BrandMark size={40} color={brand.brand_primary_color} className="rounded-lg" />}
          <div><div className="font-bold text-lg">{brand.brand_name}</div><div className="text-xs text-gray-400">Lietvedības procesu aģents</div></div>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <input value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email" className="w-full px-3 py-2 border rounded-lg text-sm" />
          <input value={pw} onChange={e=>setPw(e.target.value)} placeholder="Password" type="password" className="w-full px-3 py-2 border rounded-lg text-sm" />
          {err && <div className="text-red-600 text-xs">{err}</div>}
          <button className="w-full py-2 text-white rounded-lg text-sm font-medium" style={{background:brand.brand_primary_color}}>Login</button>
        {oidc && (<><div className="flex items-center gap-3 my-4"><div className="flex-1 h-px bg-gray-200"/><div className="text-xs text-gray-400">vai</div><div className="flex-1 h-px bg-gray-200"/></div><a href={`${API}/auth/oidc/login`} className="block w-full py-2 text-center rounded-lg text-sm font-medium border border-gray-300 hover:bg-gray-50">Pieteikties ar {oidc.label}</a></>)}</form>
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

function DocumentsPage({ notify, user, route, navigate }) {
  const docRef = route && route[1] ? decodeURIComponent(route[1]) : null;
  const [docs, setDocs] = useState([]); const [total, setTotal] = useState(0); const [sel, setSel] = useState(null);
  const [statusF, setStatusF] = useState(""); const [search, setSearch] = useState(""); const [showCreate, setShowCreate] = useState(false);
  const [sdkStatus, setSdkStatus] = useState(null);
  const load = useCallback(async () => { try { const p = new URLSearchParams({page:"1",page_size:"200"}); if(statusF) p.set("status",statusF); if(search) p.set("search",search); const d = await api(`/documents?${p}`); setDocs(d.items); setTotal(d.total); } catch(e){notify(e.message,"error");} }, [statusF,search]);
  useEffect(()=>{load();},[load]);
  useEffect(()=>{ api("/sdk/setup-status").then(setSdkStatus).catch(()=>{}); },[]);
  const loadDetail = async(id) => { try { setSel(await api(`/documents/${id}`)); } catch(e){notify(e.message,"error");} };
  useEffect(() => {
    if (!docRef) { setSel(null); return; }
    if (sel && (String(sel.registration_number) === docRef || String(sel.id) === docRef)) return;
    const m = docs.find(d => String(d.registration_number) === docRef || String(d.id) === docRef);
    if (m) loadDetail(m.id);
    else if (/^\d+$/.test(docRef)) loadDetail(docRef);
  }, [docRef, docs]);

  return (<div>
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-xl font-bold">Documents <span className="text-sm font-normal text-gray-400">({total})</span></h2>
      <div className="flex gap-2">
        <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Meklēt nosaukumā vai numurā…" className="text-sm px-3 py-1.5 border rounded-md w-64" />
        <select value={statusF} onChange={e=>setStatusF(e.target.value)} className="text-sm px-2 py-1.5 border rounded-md">
          {["","draft","registered","sent","received","assigned","decided","archived"].map(s=><option key={s} value={s}>{s||"All"}</option>)}
        </select>
        <button onClick={()=>setShowCreate(!showCreate)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded-md">+ New</button>
      </div>
    </div>
    {showCreate && <CreateDocForm onDone={()=>{setShowCreate(false);load();}} notify={notify} />}
    {!showCreate && <>
    <div className="text-xs text-gray-500 mb-3">
      Workspace: <strong>{sdkStatus?.default_organization?.name || "No default organization selected"}</strong>
    </div>
    <DocumentTable docs={docs} sel={sel} onOpen={(d)=>navigate("/documents/"+encodeURIComponent(d.registration_number||d.id))} />
    <div className="mt-4 bg-white rounded-lg border">
      {sel ? <DocumentDetail doc={sel} onAction={()=>{loadDetail(sel.id);load();}} notify={notify} /> : <div className="p-8 text-center text-gray-400 text-sm">Izvēlieties dokumentu sarakstā</div>}
    </div>
    </>}
  </div>);
}

// Document browser: one row per document with what the processes found out about it.
const fmtDT = (v) => v ? new Date(v).toLocaleString("lv-LV", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
const REVIEW_PILL = {
  gaida: ["Gaida lēmumu", "bg-amber-100 text-amber-800"], apstiprinats: ["Apstiprināts", "bg-green-100 text-green-800"],
  labots: ["Labots", "bg-sky-100 text-sky-800"], noraidits: ["Manuāla virzība", "bg-gray-200 text-gray-700"],
};
const MIME_LV = { "application/pdf": "PDF", "text/plain": "Teksts", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX" };

function DocumentTable({ docs, sel, onOpen }) {
  const [sort, setSort] = useState({ key: "created_at", dir: -1 });
  const [unit, setUnit] = useState(""); const [review, setReview] = useState("");
  const row = (d) => {
    const m = d.metadata || {}; const r = m.uapf_result || {}; const rv = m.uapf_review || {};
    const sem = m.semantika || {}; const reg = m.registraNodosana || {};
    return {
      d, id: d.id, title: d.title || "", number: d.registration_number || "", uid: d.doc_uid || "",
      created_at: d.created_at || "", sender: m.sender?.name || d.creator_name || "",
      channel: m.channel || "", topic: r.kodaNosaukums || r.kategorijasNosaukums || "", code: r.kods || r.kategorija || "",
      joma: r.joma || "", unit: r.vieniba || "", dept: r.department || "", priority: r.priority || "",
      review: rv.status || "", files: Number(d.file_count || 0), mime: d.primary_mime || d.mime_type || "",
      sem: sem.lokals ? (sem.kludas?.length ? "kļūdas" : "ir") : (sem.kludas?.length ? "nav" : ""),
      reg: reg.nodots ? (reg.semantika ? "ar aprakstu" : "metadati") : "", events: Number(d.event_count || 0),
      status: d.status || "",
    };
  };
  const rows = docs.map(row).filter(x => (!unit || x.unit === unit) && (!review || x.review === review));
  const sorted = [...rows].sort((a, b) => (a[sort.key] > b[sort.key] ? 1 : a[sort.key] < b[sort.key] ? -1 : 0) * sort.dir);
  const units = [...new Map(docs.map(row).filter(x => x.unit).map(x => [x.unit, x.dept])).entries()];
  const Th = ({ k, children, className = "" }) => (
    <th onClick={() => setSort(s => ({ key: k, dir: s.key === k ? -s.dir : -1 }))}
      className={`px-3 py-2 text-left font-medium text-gray-500 cursor-pointer select-none whitespace-nowrap ${className}`}>
      {children}{sort.key === k ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </th>
  );
  return (
    <div>
      <div className="flex gap-2 mb-2 text-sm">
        <select value={unit} onChange={e => setUnit(e.target.value)} className="px-2 py-1.5 border rounded-md">
          <option value="">Visas struktūrvienības</option>
          {units.map(([u, n]) => <option key={u} value={u}>{u} — {n}</option>)}
        </select>
        <select value={review} onChange={e => setReview(e.target.value)} className="px-2 py-1.5 border rounded-md">
          <option value="">Visi lēmumi</option>
          {Object.entries(REVIEW_PILL).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span className="text-xs text-gray-500 self-center">{sorted.length} dokumenti · {rows.filter(x => x.review === "gaida").length} gaida lēmumu</span>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white overflow-auto max-h-[46vh]">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 sticky top-0 z-10 text-xs"><tr>
            <Th k="title">Dokuments</Th><Th k="number">Nr.</Th><Th k="created_at">Saņemts</Th><Th k="sender">Iesniedzējs / avots</Th>
            <Th k="topic">Tēma</Th><Th k="unit">Struktūrvienība</Th><Th k="review">Lēmums</Th>
            <Th k="sem">Apraksts</Th><Th k="reg">Reģistrs</Th><Th k="files" className="text-right">Datnes</Th>
          </tr></thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map(x => (
              <tr key={x.id} onClick={() => onOpen(x.d)} className={`cursor-pointer hover:bg-gray-50 ${sel?.id === x.id ? "bg-emerald-50" : ""}`}>
                <td className="px-3 py-2 max-w-[280px]">
                  <div className={`truncate font-medium ${x.title ? "text-gray-900" : "text-gray-400 italic"}`} title={x.title}>
                    <Icon name="document" size={15} className="inline -mt-0.5 mr-1.5 text-gray-400" />{x.title || "Bez nosaukuma"}</div>
                  <div className="text-[11px] text-gray-400 truncate" title={x.uid}>{x.uid || "identifikators vēl nav piešķirts"}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap">{x.number || "—"}<div className="mt-0.5"><Badge s={x.status} /></div></td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-600">{fmtDT(x.created_at)}</td>
                <td className="px-3 py-2 max-w-[170px]"><div className="truncate" title={x.sender}>{x.sender || "—"}</div>
                  {x.channel && <div className="text-[11px] text-gray-400">{x.channel}</div>}</td>
                <td className="px-3 py-2 max-w-[220px]"><div className="truncate" title={x.topic}>{x.code && <span className="text-gray-500 mr-1">{x.code}</span>}{x.topic || "—"}</div>
                  {x.priority && <div className={`text-[11px] ${x.priority === "steidzams" ? "text-red-600" : "text-gray-400"}`}>{x.priority}</div>}</td>
                <td className="px-3 py-2 max-w-[200px]"><div className="truncate" title={x.dept}>{x.dept || "—"}</div>
                  {x.unit && <div className="text-[11px] text-gray-400 font-mono">{x.unit}</div>}</td>
                <td className="px-3 py-2 whitespace-nowrap">{x.review ? <span className={`text-[11px] px-1.5 py-0.5 rounded font-medium ${REVIEW_PILL[x.review]?.[1] || "bg-gray-100"}`}>{REVIEW_PILL[x.review]?.[0] || x.review}</span> : <span className="text-gray-300">—</span>}</td>
                <td className="px-3 py-2 whitespace-nowrap text-xs">{x.sem === "ir" ? <span className="text-green-700">✓ ir</span> : x.sem ? <span className="text-red-600">{x.sem}</span> : <span className="text-gray-300">—</span>}</td>
                <td className="px-3 py-2 whitespace-nowrap text-xs">{x.reg ? <span className="text-gray-700">{x.reg}</span> : <span className="text-gray-300">—</span>}</td>
                <td className="px-3 py-2 text-right text-gray-600 whitespace-nowrap">{x.files || "—"}{x.mime && <div className="text-[11px] text-gray-400">{MIME_LV[x.mime] || x.mime.split("/").pop()}</div>}</td>
              </tr>
            ))}
            {!sorted.length && <tr><td colSpan={10} className="px-5 py-8 text-center text-gray-400">Nav dokumentu</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
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

  const [vizCid, setVizCid] = useState(null);
  const generateMetadata = async () => {
    if (!file) return notify("Please select a file first", "error");
    const cid = (window.crypto?.randomUUID?.() || `run-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    setVizCid(cid);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("metadata", JSON.stringify({ title }));
    fd.append("correlationId", cid);
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
      <SemanticProcessViz correlationId={vizCid} />
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

const UAPF_PKG = "lv.tiesibsargs.iesnieguma-izskatisana";
const UAPF_PROC = "iesnieguma-izskatisana";

// Compact label of a DMN decision's outcome, for diagram node annotations.
function decisionLabel(result) {
  if (!result || typeof result !== "object") return "";
  const parts = Object.entries(result)
    .filter(([k, v]) => v != null && v !== "" && typeof v !== "object"
            && !/confidence|rationale/i.test(k))
    .map(([, v]) => String(v));
  if (!parts.length) return "";
  const str = parts.slice(0, 2).join(" \u00B7 ");
  return str.length > 38 ? str.slice(0, 38) + "\u2026" : str;
}

const SEMANTIC_PKG = "dev.uapf.semantic-document-analysis";
const SEMANTIC_PROC = "semantic-document-analysis";

// Live visualization of the semantic-document-analysis UAPF process.
// Keyed by a correlationId (not a documentId) so it works on the create
// form, before a document exists. Polls /uapf/live-run while the engine
// runs the session and lights up the BPMN node-by-node.
const SEMANTIC_STEPS = [
  { id: "Task_DetectRedactPii",    n: 1, kind: "ai",       name: "Maskēt personas datus" },
  { id: "Decision_AssessRisk",     n: 2, kind: "decision", name: "Novērtēt personas datu risku" },
  { id: "Decision_GdprRoute",      n: 3, kind: "decision", name: "Noteikt GDPR apstrādes maršrutu" },
  { id: "Task_ExtractSemantics",   n: 4, kind: "ai",       name: "Izvilkt semantisko metadatu" },
  { id: "Decision_ValidationGate", n: 5, kind: "decision", name: "Cilvēka validācijas statuss" },
  { id: "Task_EmitResult",         n: 6, kind: "event",    name: "Publicēt analīzes rezultātu" },
];
const SEM_KIND = {
  ai:       { sol: "#7c3aed", fill: "#f5f3ff", txt: "#5b21b6", label: "AI solis" },
  decision: { sol: "#4f46e5", fill: "#eef2ff", txt: "#3730a3", label: "Lēmums (DMN)" },
  event:    { sol: "#d97706", fill: "#fffbeb", txt: "#92400e", label: "Notikums" },
};
const SEM_FIELD_LV = {
  personalDataRisk: "Personas datu risks", processingRoute: "Apstrādes maršruts",
  redactionLevel: "Maskēšanas līmenis", humanValidationStatus: "Validācijas statuss",
  riskLevel: "Riska līmenis", recommendation: "Ieteikums", topic: "Tēma", priority: "Prioritāte",
};

function SemanticProcessViz({ correlationId }) {
  const [bpmnXml, setBpmnXml] = useState(null);
  const [activeStepId, setActiveStepId] = useState(null);
  const [completedStepIds, setCompletedStepIds] = useState([]);
  const [nodeDecisions, setNodeDecisions] = useState({});
  const [phase, setPhase] = useState("idle"); // idle|running|done|failed
  const timer = useRef(null);
  const activeRef = useRef(null);
  const doneRef = useRef([]);
  const finishedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api(`/uapf/packages/${SEMANTIC_PKG}/bpmn/${SEMANTIC_PROC}.xml`);
        const xml = typeof res === "string" ? res : await res.text();
        if (!cancelled) setBpmnXml(xml);
      } catch { /* diagram optional */ }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!correlationId) return;
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    finishedRef.current = false;
    activeRef.current = null;
    doneRef.current = [];
    setActiveStepId(null);
    setCompletedStepIds([]);
    setNodeDecisions({});
    setPhase("running");
    let since = 0;

    const finish = (failed) => {
      if (finishedRef.current) return;
      finishedRef.current = true;
      if (timer.current) { clearTimeout(timer.current); timer.current = null; }
      if (activeRef.current && !doneRef.current.includes(activeRef.current)) {
        doneRef.current.push(activeRef.current);
      }
      setCompletedStepIds([...doneRef.current]);
      setActiveStepId(null);
      setPhase(failed ? "failed" : "done");
    };

    const poll = async () => {
      if (finishedRef.current) return;
      try {
        const r = await api(`/uapf/live-run/${encodeURIComponent(correlationId)}?since=${since}`);
        if (typeof r?.next === "number") since = r.next;
        for (const ev of (r?.events || [])) {
          const t = ev.type || "";
          const d = ev.data || {};
          const sid = ev.uapfstepid || ev.stepId || d.stepId;
          if (t.includes("step.entered")) {
            if (sid) {
              if (activeRef.current && activeRef.current !== sid &&
                  !doneRef.current.includes(activeRef.current)) {
                doneRef.current.push(activeRef.current);
              }
              activeRef.current = sid;
              setCompletedStepIds([...doneRef.current]);
              setActiveStepId(sid);
            }
          } else if (t.includes("decision.evaluated")) {
            const res = d.result || d.outputs || d.output || d.decisionOutput;
            if (res && typeof res === "object" && sid) {
              setNodeDecisions((prev) => ({ ...prev, [sid]: { ...(prev[sid] || {}), ...res } }));
            }
          } else if (t.includes("session.completed")) { finish(false); return; }
          else if (t.includes("session.failed")) { finish(true); return; }
        }
      } catch { /* transient — keep polling */ }
      if (!finishedRef.current) timer.current = setTimeout(poll, 600);
    };
    poll();
    const guard = setTimeout(() => finish(false), 45000);
    return () => {
      if (timer.current) clearTimeout(timer.current);
      clearTimeout(guard);
      finishedRef.current = true;
    };
  }, [correlationId]);

  if (!correlationId) return null;

  const running = phase === "running";
  const nodeAnnotations = Object.fromEntries(
    Object.entries(nodeDecisions)
      .map(([nid, res]) => [nid, decisionLabel(res)])
      .filter(([, lbl]) => lbl),
  );
  const statusLabel = running ? "izpildās…" : phase === "done" ? "pabeigts"
                    : phase === "failed" ? "neizdevās" : "";

  return (
    <div className="border rounded-lg p-3 bg-slate-50 space-y-3">
      <div className="flex items-center gap-2.5">
        {running ? (
          <span className="inline-block w-6 h-6 rounded-full border-[3px] border-emerald-200 border-t-emerald-600 animate-spin" />
        ) : phase === "done" ? (
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-emerald-600 text-white text-sm font-bold">✓</span>
        ) : phase === "failed" ? (
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-red-600 text-white text-sm font-bold">✕</span>
        ) : (
          <span className="inline-block w-6 h-6" />
        )}
        <div>
          <div className="text-sm font-semibold text-gray-800">Semantiskās analīzes process</div>
          <div className="text-xs text-gray-400">
            {SEMANTIC_PKG}{statusLabel ? <span className="text-gray-500"> · {statusLabel}</span> : null}
          </div>
        </div>
      </div>

      <div>
        {SEMANTIC_STEPS.map((s, i) => {
          const k = SEM_KIND[s.kind];
          const done = phase === "done" || completedStepIds.includes(s.id);
          const active = running && activeStepId === s.id;
          const reached = done || active;
          const dec = nodeDecisions[s.id];
          return (
            <div key={s.id} className="flex gap-2.5">
              <div className="flex flex-col items-center">
                <div className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0"
                  style={{
                    background: reached ? k.sol : "#ffffff",
                    color: reached ? "#ffffff" : "#9ca3af",
                    border: `2px solid ${reached ? k.sol : "#d1d5db"}`,
                    boxShadow: active ? `0 0 0 4px ${k.fill}` : "none",
                  }}>
                  {done ? "✓" : active
                    ? <span className="inline-block w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />
                    : s.n}
                </div>
                {i < SEMANTIC_STEPS.length - 1 && (
                  <div className="w-0.5 flex-1" style={{ minHeight: "12px", background: done ? k.sol : "#e5e7eb" }} />
                )}
              </div>
              <div className="flex-1 pb-2.5 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium" style={{ color: reached ? "#111827" : "#9ca3af" }}>{s.name}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded font-medium" style={{ background: k.fill, color: k.txt }}>{k.label}</span>
                </div>
                {dec && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {Object.entries(dec)
                      .filter(([key, v]) => v != null && v !== "" && typeof v !== "object" && !/confidence|rationale/i.test(key))
                      .map(([key, v]) => (
                        <span key={key} className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-100">
                          {SEM_FIELD_LV[key] || key}: <strong>{String(v)}</strong>
                        </span>
                      ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {bpmnXml
        ? <BpmnDiagram xml={bpmnXml} activeStepId={activeStepId}
            completedStepIds={completedStepIds} nodeAnnotations={nodeAnnotations} height={240} />
        : <div className="text-xs text-gray-400">Ielādē procesa diagrammu…</div>}
    </div>
  );
}

// In-pane UAPF process runner + live BPMN visualization for one document.
function DocumentProcessPanel({ doc, notify }) {
  const [sessions, setSessions] = useState([]);
  const [sel, setSel] = useState(null);
  const [bpmnXml, setBpmnXml] = useState(null);
  const [activeStepId, setActiveStepId] = useState(null);
  const [completedStepIds, setCompletedStepIds] = useState([]);
  const [nodeDecisions, setNodeDecisions] = useState({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const timer = useRef(null);
  const activeRef = useRef(null);
  const doneRef = useRef([]);
  const finishedRef = useRef(false);
  const decisionsRef = useRef({});

  const loadSessions = useCallback(async () => {
    try {
      const rows = await api(`/uapf/sessions?doc=${doc.id}`);
      const list = Array.isArray(rows) ? rows : [];
      setSessions(list);
      setSel((prev) => prev || list[0] || null);
    } catch (e) { setError(e.message); }
  }, [doc.id]);
  useEffect(() => { loadSessions(); }, [loadSessions]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api(`/uapf/packages/${UAPF_PKG}/bpmn/${UAPF_PROC}.xml`);
        const xml = await res.text();
        if (!cancelled) setBpmnXml(xml);
      } catch { /* diagram is optional */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const fetchSteps = async (sessionId) => {
    try {
      const d = await api(`/uapf/sessions/${encodeURIComponent(sessionId)}`);
      const chain = d.audit_chain_live || d.audit_chain_persisted || [];
      const ordered = [];
      const decisions = {};
      for (const ev of chain) {
        const sid = ev.uapfstepid || ev.stepId || ev.step_id || (ev.data && ev.data.stepId);
        const t = ev.type || ev.event_type || "";
        if (sid && t.includes("step.entered") && !ordered.includes(sid)) ordered.push(sid);
        if (t.includes("decision.evaluated") && sid && ev.data && ev.data.result) {
          decisions[sid] = ev.data.result;
        }
      }
      return { ordered, decisions };
    } catch { return { ordered: [], decisions: {} }; }
  };

  useEffect(() => {
    if (!sel || running) return;
    let cancelled = false;
    (async () => {
      const { ordered, decisions } = await fetchSteps(sel.session_id);
      if (cancelled) return;
      setActiveStepId(null);
      setCompletedStepIds(sel.state === "completed" ? ordered : []);
      setNodeDecisions(decisions || {});
    })();
    return () => { cancelled = true; };
  }, [sel && sel.session_id]);

  // Real-time process visualization: fire the run un-awaited (it executes
  // server-side while the engine posts step CloudEvents to the host audit
  // endpoint), and concurrently poll /uapf/live to drive the diagram as
  // each BPMN node is actually entered.
  const runProcess = async () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    setError(null);
    setRunning(true);
    setActiveStepId(null);
    setCompletedStepIds([]);
    activeRef.current = null;
    doneRef.current = [];
    decisionsRef.current = {};
    setNodeDecisions({});
    finishedRef.current = false;

    // cursor: highest UAPF audit-event id already on record for this doc
    let since = 0;
    try {
      const cur = await api(`/uapf/live/${doc.id}`);
      since = cur && typeof cur.max_id === "number" ? cur.max_id : 0;
    } catch { /* start from 0 */ }

    // fire the run — do NOT await; the engine streams audit events while it runs
    api(`/uapf/run-now/${doc.id}`, {
      method: "POST",
      body: JSON.stringify({ event_type: "manual", package_id: UAPF_PKG, process_id: UAPF_PROC }),
    }).catch((e) => { if (!finishedRef.current) setError(e.message); });

    const finish = (failed) => {
      if (finishedRef.current) return;
      finishedRef.current = true;
      if (timer.current) { clearTimeout(timer.current); timer.current = null; }
      if (activeRef.current && !doneRef.current.includes(activeRef.current)) {
        doneRef.current.push(activeRef.current);
      }
      setCompletedStepIds([...doneRef.current]);
      setActiveStepId(null);
      setRunning(false);
      if (notify) notify(failed ? "UAPF process neizdevās" : "UAPF process izpildīts");
      loadSessions();
    };

    // poll the live audit feed and light up the diagram in real time
    const poll = async () => {
      if (finishedRef.current) return;
      try {
        const r = await api(`/uapf/live/${doc.id}?since=${since}`);
        const evs = r && Array.isArray(r.events) ? r.events : [];
        for (const ev of evs) {
          if (typeof ev.id === "number") since = Math.max(since, ev.id);
          const d = ev.details || {};
          const t = d.type || ev.event_type || "";
          const sid = d.uapfstepid || d.stepId || d.step_id || (d.data && d.data.stepId);
          if (t.includes("step.entered") && sid) {
            if (activeRef.current && activeRef.current !== sid &&
                !doneRef.current.includes(activeRef.current)) {
              doneRef.current.push(activeRef.current);
            }
            activeRef.current = sid;
            setCompletedStepIds([...doneRef.current]);
            setActiveStepId(sid);
          } else if (t.includes("decision.evaluated") && d.uapfstepid && d.data && d.data.result) {
            decisionsRef.current[d.uapfstepid] = d.data.result;
            setNodeDecisions({ ...decisionsRef.current });
          } else if (t.includes("session.completed")) {
            finish(false); return;
          } else if (t.includes("session.failed")) {
            finish(true); return;
          }
        }
      } catch { /* transient — keep polling */ }
      if (!finishedRef.current) timer.current = setTimeout(poll, 600);
    };
    poll();

    // safety: never spin forever
    setTimeout(() => { if (!finishedRef.current) finish(false); }, 45000);
  };
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const out = sel && sel.output_payload && typeof sel.output_payload === "object" ? sel.output_payload : null;
  const highlight = ["topic", "priority", "slaHours", "department", "languageDetected"];
  const hasCompletedRun = sessions.some((sn) => sn.state === "completed");
  const nodeAnnotations = Object.fromEntries(
    Object.entries(nodeDecisions)
      .map(([nid, res]) => [nid, decisionLabel(res)])
      .filter(([, lbl]) => lbl),
  );

  return (
    <div className="border-t pt-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-gray-500">UAPF process</div>
        <button onClick={runProcess} disabled={running || hasCompletedRun}
          className="text-xs px-3 py-1.5 bg-violet-600 text-white rounded disabled:opacity-50 flex items-center gap-1">
          {running ? (<><span className="animate-spin">⦵</span> Izpildās...</>)
            : hasCompletedRun ? ("✓ Klasifikācija veikta")
            : ("▶ Palaist klasifikācijas procesu")}
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">{error}</div>
      )}

      {sessions.length === 0 && !running && (
        <div className="text-xs text-gray-400">
          Klasifikācija vēl nav veikta. Nospiediet "Palaist klasifikācijas procesu", lai to palaistu.
        </div>
      )}

      {(sessions.length > 0 || running) && bpmnXml && (
        <BpmnDiagram xml={bpmnXml} activeStepId={activeStepId}
          completedStepIds={completedStepIds} nodeAnnotations={nodeAnnotations} height={300} />
      )}

      {out && (
        <div className="bg-gray-50 border border-gray-200 rounded p-2 space-y-1">
          <div className="text-xs font-medium text-gray-600">Klasifikācijas rezultāts</div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
            {highlight.filter((k) => out[k] != null).map((k) => (
              <div key={k}>
                <span className="text-gray-400">{k}: </span>
                <span className="font-medium">{String(out[k])}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {sessions.length > 0 && (
        <div className="space-y-1">
          {sessions.slice(0, 5).map((s) => (
            <button key={s.session_id} onClick={() => setSel(s)}
              className={`w-full text-left text-xs rounded border px-2 py-1 flex items-center justify-between ${
                sel && sel.session_id === s.session_id
                  ? "border-violet-300 bg-violet-50"
                  : "border-gray-200 bg-white hover:border-gray-300"}`}>
              <span className="font-mono text-gray-500">{s.session_id}</span>
              <span className={s.state === "completed" ? "text-emerald-600"
                : s.state === "failed" ? "text-red-600" : "text-amber-600"}>{s.state}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Document package of the Dokumentu metadatu standarts v2.0, shown as a small file browser.
function StandardPackagePanel({ doc, notify }) {
  const info = doc?.metadata?.standartaPakotne;
  const [listing, setListing] = useState(null);
  const [open, setOpen] = useState(null);      // { path, text }
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setListing(null); setOpen(null);
    if (!info?.datnes?.length) return;
    api(`/documents/${doc.id}/package/files`).then(setListing).catch(() => setListing(null));
  }, [doc.id, info?.izveidots]);

  const fetchFile = async (path, download = false) => {
    const res = await fetch(`${API}/documents/${doc.id}/package/files/${path.split("/").map(encodeURIComponent).join("/")}${download ? "?download=true" : ""}`,
      { headers: { Authorization: `Bearer ${authToken}` } });
    if (!res.ok) throw new Error(`Neizdevās nolasīt ${path}`);
    return res;
  };

  const view = async (f) => {
    if (open?.path === f.path) { setOpen(null); return; }
    if (!(f.mediaType.startsWith("text/") || f.mediaType.endsWith("xml"))) { download(f.path); return; }
    try { setLoading(true); const r = await fetchFile(f.path); setOpen({ path: f.path, text: await r.text() }); }
    catch (e) { notify(e.message, "error"); } finally { setLoading(false); }
  };

  const saveBlob = (blob, name) => { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); };

  const download = async (path) => {
    try { const r = await fetchFile(path, true); saveBlob(await r.blob(), path.split("/").pop()); }
    catch (e) { notify(e.message, "error"); }
  };

  const downloadZip = async () => {
    try {
      const res = await fetch(`${API}/documents/${doc.id}/package`, { headers: { Authorization: `Bearer ${authToken}` } });
      if (!res.ok) throw new Error("Pakotnes lejupielāde neizdevās");
      saveBlob(await res.blob(), `${listing?.folder || doc.doc_uid}.zip`);
    } catch (e) { notify(e.message, "error"); }
  };

  const kb = (n) => n == null ? "—" : n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`;

  return (
    <div className="border rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-gray-500">Standarta pakotne · Dokumentu metadatu standarts v2.0</div>
        {info && (
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${info.derigs ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
            {info.derigs ? "✓ atbilst standartam" : "✗ neatbilst standartam"}
          </span>
        )}
      </div>

      {doc.doc_uid ? (
        <div className="text-xs">
          <span className="text-gray-400">Dokumenta ID:</span>{" "}
          <code className="bg-gray-50 px-1 rounded break-all">{doc.doc_uid}</code>
          <button onClick={() => { navigator.clipboard?.writeText(doc.doc_uid); notify("ID nokopēts"); }} className="ml-2 text-[10px] text-sky-600 hover:underline">kopēt</button>
        </div>
      ) : (
        <div className="text-xs text-gray-400">Vienotais identifikators vēl nav piešķirts. To piešķir process „Ienākošā dokumenta reģistrēšana”, kad dokumentam pievieno pirmo datni.</div>
      )}

      {info?.problemas?.length > 0 && (
        <ul className="text-[11px] text-red-700 bg-red-50 rounded px-3 py-2 list-disc list-inside">
          {info.problemas.map((p, i) => <li key={i}>{p}</li>)}
        </ul>
      )}

      {listing && (
        <>
          <div className="font-mono text-xs bg-gray-50 rounded border">
            <div className="px-2 py-1.5 border-b text-gray-600 break-all flex items-center justify-between gap-2">
              <span>📁 {listing.folder}/</span>
              <button onClick={() => { window.history.pushState({}, "", "/storage/" + encodeURIComponent(listing.folder)); window.dispatchEvent(new PopStateEvent("popstate")); }}
                className="font-sans text-[11px] text-sky-600 hover:underline shrink-0">atvērt glabātuvē →</button>
            </div>
            {listing.files.map((f) => {
              const depth = f.path.includes("/") ? 2 : 1;
              const name = f.path.split("/").pop();
              return (
                <div key={f.path}>
                  {f.path.startsWith("datnes/") && f === listing.files.find((x) => x.path.startsWith("datnes/")) && (
                    <div className="px-2 py-1 text-gray-600" style={{ paddingLeft: 20 }}>📁 datnes/</div>
                  )}
                  <div className={`flex items-center justify-between px-2 py-1 hover:bg-white cursor-pointer ${open?.path === f.path ? "bg-white" : ""}`}
                       style={{ paddingLeft: depth * 20 }} onClick={() => view(f)}>
                    <span className={f.missing ? "text-red-600" : "text-gray-800"}>{name.endsWith(".xml") ? "🗎" : "📄"} {name}</span>
                    <span className="flex items-center gap-3 text-gray-400">
                      <span>{kb(f.size)}</span>
                      <button onClick={(e) => { e.stopPropagation(); download(f.path); }} className="text-sky-600 hover:underline">lejupielādēt</button>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          {loading && <div className="text-xs text-gray-400">Ielādē…</div>}
          {open && (
            <div className="border rounded">
              <div className="flex items-center justify-between px-2 py-1 bg-gray-50 border-b text-xs">
                <span className="font-mono">{open.path}</span>
                <button onClick={() => setOpen(null)} className="text-gray-400 hover:text-gray-700">aizvērt ✕</button>
              </div>
              <pre className="text-[11px] leading-snug p-2 overflow-auto max-h-96 whitespace-pre">{open.text}</pre>
            </div>
          )}
          <div className="flex items-center justify-between text-[11px] text-gray-400">
            <span>Izveidota: {info?.izveidots ? new Date(info.izveidots).toLocaleString("lv-LV") : "—"}</span>
            <button onClick={downloadZip} className="text-xs px-2 py-1 bg-sky-600 text-white rounded">⬇ Lejupielādēt pakotni (ZIP)</button>
          </div>
        </>
      )}
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

  const [vizCid, setVizCid] = useState(null);
  const generateMetadata = async () => {
    const cid = (window.crypto?.randomUUID?.() || `run-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    setVizCid(cid);
    try {
      setGenerating(true);
      const r = await api(`/documents/${doc.id}/generate-metadata?correlation_id=${encodeURIComponent(cid)}`, { method: "POST" });
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

  // Processes run after the upload in the background (redaction, classification,
  // description take a minute): refresh until a step waits for a person.
  const recent = doc.created_at && (Date.now() - new Date(doc.created_at).getTime()) < 15 * 60 * 1000;
  const processing = recent && (doc.files?.length || doc.file_name) && !doc.metadata?.uapf_review;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(() => onAction(), 5000);
    return () => clearInterval(t);
  }, [processing, doc.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const source = doc.semantic_summary?.summarySource || "HUMAN";
  const hasFiles = files.length > 0 || doc.file_name;
  const hasMeta = !!doc.semantic_summary;

  return (
    <div className="p-4 space-y-3 overflow-auto max-h-[80vh]">
        {processing && (
          <div className="text-sm bg-sky-50 border border-sky-200 text-sky-900 rounded p-3 flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full border-2 border-sky-600 border-t-transparent animate-spin" />
            Process darbojas: personas datu aizklāšana, klasifikācija, semantiskais apraksts. Lapa atjaunojas pati (~1 min).
          </div>
        )}
        {doc?.metadata?.uapf_result
          ? <ProcessResultCard doc={doc} notify={notify} />
          : doc?.metadata?.uapf_classification && <UapfClassificationCard classification={doc.metadata.uapf_classification} />}
        {doc?.metadata?.semantika && <SemanticDescriptionCard sem={doc.metadata.semantika} docId={doc.id} notify={notify} />}
        <ForwardingCard doc={doc} files={files} notify={notify} onAction={onAction} />

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

      <StandardPackagePanel doc={doc} notify={notify} />

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
      <SemanticProcessViz correlationId={vizCid} />

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

      <DocumentProcessPanel doc={doc} notify={notify} />

      {doc.events?.length > 0 && (
        <div className="border-t pt-3">
          <div className="text-xs font-medium text-gray-500 mb-2">Lifecycle ({doc.events.length} events)</div>
          <div className="space-y-1">
            {[...doc.events].sort((a, b) => (b.id || 0) - (a.id || 0)).map((e, i) => {
              const details = typeof e.details === "string" ? JSON.parse(e.details || "{}") : (e.details || {});
              const isUapf = (e.event_type || "").startsWith("UAPF/");
              const shortType = (e.event_type || "").replace(/^UAPF\/(dev\.uapf\.)?/, "");
              const det = isUapf ? uapfEventDetail(e.event_type, details) : null;
              return (
                <div key={e.id || i} className={`rounded px-3 py-2 text-xs ${det && det.accent ? "bg-violet-50" : "bg-gray-50"}`}>
                  <div className="flex items-center gap-2">
                    <span>{isUapf ? (UAPF_EI[shortType] || "⚙️") : (EI[e.event_type] || "📎")}</span>
                    <span className="font-medium">{isUapf ? shortType : e.event_type}</span>
                    {!isUapf && (e.vc_submitted
                      ? <span className="text-emerald-500">✓ VC</span>
                      : <span className="text-red-400">✗ no VC</span>)}
                    <span className="text-gray-400 ml-auto">{new Date(e.created_at).toLocaleString()}</span>
                  </div>
                  {det && det.line && (
                    <div className={`mt-1 text-[11px] ${det.err ? "text-red-500" : "text-gray-600"}`}>{det.line}</div>
                  )}
                  {det && det.kv && det.kv.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {det.kv.map((kvStr, j) => (
                        <span key={j} className="px-1.5 py-0.5 rounded bg-white border border-gray-200 text-[10px] text-gray-700">{kvStr}</span>
                      ))}
                    </div>
                  )}
                  {det && det.rules && (
                    <div className="mt-0.5 text-[10px] text-gray-400">rules: {det.rules}</div>
                  )}
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

function UsersPage({ notify, user, route, navigate }) {
  const ROLES = ["operator", "viewer", "admin", "superadmin"];
  const userRef = route && route[1] ? route[1] : null;
  const [users, setUsers] = useState([]);
  const [show, setShow] = useState(false);
  const [editId, setEditId] = useState(null);
  const [nf, setNf] = useState({ email: "", password: "", full_name: "", role: "operator" });
  const [edit, setEdit] = useState({});
  const [pw, setPw] = useState("");

  const load = async () => {
    try { const d = await api("/users"); setUsers(d.items || []); }
    catch (e) { notify(e.message, "error"); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!userRef) { setEditId(null); return; }
    const u = users.find(x => String(x.id) === userRef);
    if (u) {
      setEditId(u.id);
      setEdit({ full_name: u.full_name, role: u.role, department: u.department || "", is_active: u.is_active });
    }
  }, [userRef, users]);

  const create = async () => {
    try {
      await api("/users", { method: "POST", body: JSON.stringify(nf) });
      notify("Lietotājs izveidots");
      setShow(false);
      setNf({ email: "", password: "", full_name: "", role: "operator" });
      load();
    } catch (e) { notify(e.message, "error"); }
  };

  const openEdit = (u) => {
    setPw("");
    navigate(editId === u.id ? "/users" : "/users/" + u.id);
  };

  const saveEdit = async (id) => {
    try {
      await api(`/users/${id}`, { method: "PATCH", body: JSON.stringify(edit) });
      notify("Izmaiņas saglabātas");
      navigate("/users");
      load();
    } catch (e) { notify(e.message, "error"); }
  };

  const resetPw = async (id) => {
    if ((pw || "").length < 8) return notify("Parolei jābūt vismaz 8 rakstzīmes", "error");
    try {
      await api(`/users/${id}/reset-password`, { method: "POST", body: JSON.stringify({ new_password: pw }) });
      notify("Parole atiestatīta");
      setPw("");
    } catch (e) { notify(e.message, "error"); }
  };

  return (<div>
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-xl font-bold">Lietotāju pārvaldība</h2>
      <button onClick={() => setShow(!show)} className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded-md">
        {show ? "Aizvērt" : "+ Jauns lietotājs"}
      </button>
    </div>
    {show && (
      <div className="bg-white border rounded-lg p-4 mb-4 grid grid-cols-2 gap-2">
        {[["email", "E-pasts"], ["password", "Parole"], ["full_name", "Pilns vārds"]].map(([k, l]) => (
          <input key={k} value={nf[k]} onChange={e => setNf({ ...nf, [k]: e.target.value })}
            placeholder={l} type={k === "password" ? "password" : "text"}
            className="text-sm px-3 py-2 border rounded" />
        ))}
        <select value={nf.role} onChange={e => setNf({ ...nf, role: e.target.value })}
          className="text-sm px-3 py-2 border rounded">
          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <button onClick={create} className="text-sm px-4 py-2 bg-emerald-600 text-white rounded col-span-2">
          Izveidot lietotāju
        </button>
      </div>
    )}
    <div className="bg-white rounded-lg border divide-y">
      {users.map(u => (
        <div key={u.id}>
          <div className="px-4 py-3 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
            onClick={() => openEdit(u)}>
            <div>
              <div className="text-sm font-medium">
                {u.full_name}
                {u.id === user.id && <span className="ml-2 text-[10px] text-emerald-600">(jūs)</span>}
              </div>
              <div className="text-xs text-gray-400">{u.email}</div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{u.role}</span>
              <span className={`text-[10px] px-2 py-0.5 rounded ${u.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                {u.is_active ? "aktīvs" : "neaktīvs"}
              </span>
              <span className="text-gray-300 text-xs">{editId === u.id ? "▲" : "▼"}</span>
            </div>
          </div>
          {editId === u.id && (
            <div className="px-4 py-3 bg-gray-50 border-t space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500">Pilns vārds</label>
                  <input value={edit.full_name || ""} onChange={e => setEdit({ ...edit, full_name: e.target.value })}
                    className="w-full text-sm px-3 py-1.5 border rounded" />
                </div>
                <div>
                  <label className="text-xs text-gray-500">Nodaļa</label>
                  <input value={edit.department || ""} onChange={e => setEdit({ ...edit, department: e.target.value })}
                    className="w-full text-sm px-3 py-1.5 border rounded" />
                </div>
                <div>
                  <label className="text-xs text-gray-500">Loma</label>
                  <select value={edit.role || "operator"} onChange={e => setEdit({ ...edit, role: e.target.value })}
                    className="w-full text-sm px-3 py-1.5 border rounded">
                    {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                </div>
                <div className="flex items-end">
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={!!edit.is_active}
                      onChange={e => setEdit({ ...edit, is_active: e.target.checked })} />
                    Aktīvs konts
                  </label>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button onClick={() => saveEdit(u.id)}
                  className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded">
                  Saglabāt izmaiņas
                </button>
                <span className="text-gray-300">|</span>
                <input type="password" value={pw} onChange={e => setPw(e.target.value)}
                  placeholder="Jauna parole" className="text-sm px-3 py-1.5 border rounded" />
                <button onClick={() => resetPw(u.id)}
                  className="text-sm px-3 py-1.5 border border-amber-400 text-amber-700 rounded hover:bg-amber-50">
                  Atiestatīt paroli
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  </div>);
}

function AccountPage({ notify, user }) {
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [cf, setCf] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (nw.length < 8) return notify("Jaunajai parolei jābūt vismaz 8 rakstzīmes", "error");
    if (nw !== cf) return notify("Jaunās paroles nesakrīt", "error");
    try {
      setBusy(true);
      await api("/users/me/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: cur, new_password: nw }),
      });
      notify("Parole veiksmīgi nomainīta");
      setCur(""); setNw(""); setCf("");
    } catch (e) { notify(e.message, "error"); }
    finally { setBusy(false); }
  };

  return (<div>
    <h2 className="text-xl font-bold mb-4">Mans konts</h2>
    <div className="space-y-4 max-w-lg">
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-semibold text-sm mb-3">Profils</h3>
        {[["Pilns vārds", user.full_name], ["E-pasts", user.email], ["Loma", user.role]].map(([l, v]) => (
          <div key={l} className="flex text-sm py-1">
            <span className="text-gray-500 w-32">{l}</span>
            <span className="font-medium">{v}</span>
          </div>
        ))}
      </div>
      <div className="bg-white rounded-lg border p-4">
        <h3 className="font-semibold text-sm mb-3">Mainīt paroli</h3>
        <div className="space-y-2">
          {[["Pašreizējā parole", cur, setCur], ["Jaunā parole", nw, setNw], ["Apstipriniet jauno paroli", cf, setCf]].map(([l, v, set]) => (
            <input key={l} type="password" value={v} onChange={e => set(e.target.value)}
              placeholder={l} className="w-full text-sm px-3 py-2 border rounded" />
          ))}
          <button onClick={submit} disabled={busy || !cur || !nw || !cf}
            className="text-sm px-4 py-2 bg-emerald-600 text-white rounded disabled:opacity-50">
            {busy ? "Saglabā..." : "Mainīt paroli"}
          </button>
          <p className="text-xs text-gray-400">Parolei jābūt vismaz 8 rakstzīmes garai.</p>
        </div>
      </div>
    </div>
  </div>);
}

function OrgsPage({ notify, onViewLogs }) {
  // Slug rule mirrors backend ORG_CODE_RE: lowercase, digits, hyphens; no edge hyphens; 2-64 chars
  const ORG_CODE_RE = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;
  const [editing, setEditing] = useState(null);   // org being edited
  const [deleting, setDeleting] = useState(null); // org pending delete
  const [busy, setBusy] = useState({});
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

    {show && (() => {
      const codeEmpty = nf.code.trim() === "";
      const codeValid = codeEmpty || ORG_CODE_RE.test(nf.code);
      const nameValid = nf.name.trim().length > 0;
      const canCreate = !codeEmpty && codeValid && nameValid;
      return (
        <div className="bg-white border rounded-lg p-4 mb-4 space-y-2">
          <div className="flex gap-2">
            <input value={nf.name} onChange={e=>setNf({...nf,name:e.target.value})}
                   placeholder="Name" className="flex-1 text-sm px-3 py-2 border rounded" />
            <input value={nf.code} onChange={e=>setNf({...nf,code:e.target.value.toLowerCase()})}
                   placeholder="slug (e.g. tiesibsargs)"
                   className={`w-48 text-sm px-3 py-2 border rounded font-mono ${
                     codeEmpty ? "" : (codeValid ? "border-emerald-300" : "border-red-300 bg-red-50")
                   }`} />
            <input value={nf.description} onChange={e=>setNf({...nf,description:e.target.value})}
                   placeholder="Description" className="flex-1 text-sm px-3 py-2 border rounded" />
            <button onClick={create} disabled={!canCreate}
                    className="text-sm px-4 py-2 bg-emerald-600 text-white rounded disabled:opacity-50 disabled:cursor-not-allowed">
              Create
            </button>
          </div>
          <div className="text-xs space-y-0.5">
            <div className={`${codeEmpty ? "text-gray-500" : (codeValid ? "text-emerald-700" : "text-red-600")}`}>
              {codeEmpty ? (
                <>Slug becomes part of the DID: <code className="bg-gray-100 px-1">did:web:register.opendms.dev:org:&lt;slug&gt;</code></>
              ) : codeValid ? (
                <>✓ Slug is valid. The DID will be <code className="bg-emerald-50 px-1">did:web:register.opendms.dev:org:{nf.code}</code></>
              ) : (
                <>✗ Invalid slug. Use only lowercase letters, digits and hyphens; 2-64 chars; cannot start or end with a hyphen.</>
              )}
            </div>
            <div className="text-gray-400">
              The slug is permanent — it's embedded in every Verifiable Credential this org will ever issue. Plan accordingly.
            </div>
          </div>
        </div>
      );
    })()}
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
          <div className="flex gap-2 flex-wrap">
            <button onClick={() => setEditing({...o})}
                    className="text-xs px-3 py-1 border rounded text-gray-700 hover:bg-gray-50">Edit</button>
            {!o.is_default && (
              <button onClick={() => setDeleting(o)}
                      className="text-xs px-3 py-1 border border-red-200 rounded text-red-600 hover:bg-red-50">Delete</button>
            )}
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

    {editing && (
      <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={()=>setEditing(null)}>
        <div className="bg-white rounded-lg p-5 w-[500px]" onClick={e=>e.stopPropagation()}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold">Edit Organization</h3>
            <button onClick={()=>setEditing(null)} className="text-gray-400 hover:text-gray-600">✕</button>
          </div>
          <div className="text-xs text-gray-500 mb-3">
            Code and DID are immutable. To rename the slug you must create a new organization and migrate documents.
          </div>
          <div className="space-y-2">
            <div>
              <label className="text-xs text-gray-500">Name</label>
              <input value={editing.name || ""} onChange={e=>setEditing({...editing, name:e.target.value})}
                     className="w-full text-sm px-3 py-2 border rounded" />
            </div>
            <div>
              <label className="text-xs text-gray-500">Code (read-only)</label>
              <input value={editing.code || ""} readOnly
                     className="w-full text-sm px-3 py-2 border rounded font-mono bg-gray-50 text-gray-500" />
            </div>
            <div>
              <label className="text-xs text-gray-500">Description</label>
              <textarea value={editing.description || ""} onChange={e=>setEditing({...editing, description:e.target.value})}
                        rows={3} className="w-full text-sm px-3 py-2 border rounded" />
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button onClick={()=>setEditing(null)} className="text-sm px-3 py-1.5 border rounded text-gray-600">Cancel</button>
            <button disabled={busy[editing.id] || !editing.name?.trim()}
                    onClick={async()=>{
                      setBusy(p=>({...p, [editing.id]:true}));
                      try {
                        await api(`/organizations/${editing.id}`, {
                          method:"PUT",
                          body: JSON.stringify({ name: editing.name, description: editing.description }),
                        });
                        notify("Organization updated");
                        setEditing(null);
                        load();
                      } catch(e) { notify(e.message, "error"); }
                      finally { setBusy(p=>({...p, [editing.id]:false})); }
                    }}
                    className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded disabled:opacity-50">
              {busy[editing.id] ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </div>
    )}

    {deleting && (
      <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={()=>setDeleting(null)}>
        <div className="bg-white rounded-lg p-5 w-[500px]" onClick={e=>e.stopPropagation()}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-red-700">Delete Organization</h3>
            <button onClick={()=>setDeleting(null)} className="text-gray-400 hover:text-gray-600">✕</button>
          </div>
          <div className="text-sm space-y-2">
            <p>Delete <strong>{deleting.name}</strong> (code <code className="bg-gray-100 px-1">{deleting.code}</code>)?</p>
            {deleting.org_did && (
              <p className="text-xs text-gray-500">
                DID <code className="bg-gray-100 px-1 break-all">{deleting.org_did}</code> will remain registered in the central VeriDocs Registry — only the local OpenDMS row is removed.
              </p>
            )}
            <div className="flex items-start gap-2 mt-3 p-2 bg-amber-50 border border-amber-200 rounded">
              <input type="checkbox" id="cascade-cb" checked={!!deleting._cascade}
                     onChange={e=>setDeleting({...deleting, _cascade:e.target.checked})}
                     className="mt-0.5" />
              <label htmlFor="cascade-cb" className="text-xs text-amber-900">
                <strong>Also delete all documents</strong> belonging to this org, including their lifecycle events, classifications, UAPF sessions, and AI logs. This cannot be undone.
              </label>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button onClick={()=>setDeleting(null)} className="text-sm px-3 py-1.5 border rounded text-gray-600">Cancel</button>
            <button disabled={busy[deleting.id]}
                    onClick={async()=>{
                      setBusy(p=>({...p, [deleting.id]:true}));
                      try {
                        const q = deleting._cascade ? "?cascade=true" : "";
                        const r = await api(`/organizations/${deleting.id}${q}`, { method:"DELETE" });
                        notify(`Deleted ${r.name}${r.documents_deleted ? ` and ${r.documents_deleted} documents` : ""}`);
                        setDeleting(null);
                        load();
                      } catch(e) { notify(e.message, "error"); }
                      finally { setBusy(p=>({...p, [deleting.id]:false})); }
                    }}
                    className="text-sm px-3 py-1.5 bg-red-600 text-white rounded disabled:opacity-50">
              {busy[deleting.id] ? "Deleting..." : "Delete"}
            </button>
          </div>
        </div>
      </div>
    )}

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

// Result of a ProcessGit process run on this document (whatever its DMN
// tables decided) and — when a step waits for a person — the decision buttons.
const RESULT_LABELS = {
  joma: "Joma", kategorija: "Kategorija", kategorijasNosaukums: "Kategorijas nosaukums",
  kods: "Klasifikatora kods", kodaNosaukums: "Tēma", klasifikacijasAvots: "Klasificēja",
  klasifikacijasPamatojums: "Klasifikācijas pamatojums",
  topic: "Joma", confidence: "Pārliecība", jurisdiction: "Piekritība", reason: "Pamatojums",
  priority: "Prioritāte", responseDays: "Atbildes termiņš (dienās)", outcome: "Virzības priekšlikums",
  department: "Nodaļa", vieniba: "Struktūrvienības ID", role: "Loma", klasifikacijasIndekss: "Klasifikācijas indekss",
  klasifikacijasNosaukums: "Lieta", strukturvieniba: "Struktūrvienība", loma: "Loma",
  plusma: "Plūsma", termins: "Termiņš (dienās)", glabasanasTermins: "Glabāšanas termiņš",
  templateId: "Atbildes veidne",
};
const VALUE_LABELS = {
  BT: "Bērnu tiesības", PPT: "Pilsoniskās un politiskās tiesības",
  SEK: "Sociālās, ekonomiskās un kultūras tiesības", TV: "Tiesiskā vienlīdzība un diskriminācijas novēršana",
  "bernu-tiesibas": "Bērnu tiesības", "diskriminacijas-noversana": "Diskriminācijas novēršana",
  "laba-parvaldiba": "Laba pārvaldība", "socialas-tiesibas": "Sociālās tiesības",
  "civilas-tiesibas": "Civilās un politiskās tiesības", "neskaidrs": "Neskaidrs",
  "piekritigs": "Piekritīgs", "nav-piekritigs": "Nav piekritīgs",
  "steidzams": "Steidzams", "augsts": "Augsta", "parasts": "Parasta",
  "virzit-izskatisanai": "Virzīt izskatīšanai", "uzsakt-parbaudi": "Uzsākt pārbaudi",
  "parsutit-citai-iestadei": "Pārsūtīt citai iestādei", "atteikt": "Atteikt",
  "manuala-izvertesana": "Manuāla izvērtēšana",
  modelis: "Valodas modelis (ar precedentiem)", precedents: "Darbinieka labojums (precedents)", noteikumi: "Noteikumi (DMN)", "izpilde": "Izpildei", "iepazisanas": "Iepazīšanai",
};
const REVIEW_STATUS = {
  gaida: { label: "Gaida darbinieka lēmumu", cls: "bg-amber-100 text-amber-800" },
  apstiprinats: { label: "Apstiprināts", cls: "bg-green-100 text-green-800" },
  labots: { label: "Labots un apstiprināts", cls: "bg-sky-100 text-sky-800" },
  noraidits: { label: "Noraidīts — manuāla virzība", cls: "bg-gray-200 text-gray-700" },
};

function ProcessResultCard({ doc, notify }) {
  const result = doc.metadata.uapf_result || {};
  const [review, setReview] = useState(doc.metadata.uapf_review || null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [fix, setFix] = useState(null);     // {opts, kods, vieniba, iemesls} while correcting
  const openFix = async () => {
    try {
      const o = await api(`/uapf/review/${doc.id}/options`);
      setFix({ opts: o, kods: result.kods || "", vieniba: result.vieniba || "", iemesls: "" });
    } catch (e) { notify?.(e.message, "error"); }
  };
  const sendFix = async () => {
    const changes = { labojumaIemesls: fix.iemesls };
    if (fix.kods && fix.kods !== (result.kods || "")) changes.labotsKods = fix.kods;
    if (fix.vieniba && fix.vieniba !== (result.vieniba || "")) changes.labotaVieniba = fix.vieniba;
    if (!changes.labotsKods && !changes.labotaVieniba) { notify?.("Nekas nav mainīts", "error"); return; }
    if (!fix.iemesls.trim()) { notify?.("Ierakstiet, kāpēc — no tā sistēma mācās", "error"); return; }
    setBusy(true);
    try {
      const r = await api(`/uapf/review/${doc.id}`, { method: "POST", body: JSON.stringify({ decision: "labots", comment: fix.iemesls, changes }) });
      setReview(r.review); setFix(null);
      notify?.(`Labojums saglabāts kā precedents; process: ${r.state}`);
    } catch (e) { notify?.(e.message, "error"); }
    setBusy(false);
  };
  const rows = Object.keys(RESULT_LABELS).filter((k) => result[k] !== undefined && result[k] !== null && result[k] !== "");
  const show = (k) => {
    const v = result[k];
    if (k === "confidence" && typeof v === "number") return `${Math.round(v * 100)}%`;
    return VALUE_LABELS[v] || String(v);
  };
  const decide = async (decision) => {
    setBusy(true);
    try {
      const r = await api(`/uapf/review/${doc.id}`, { method: "POST", body: JSON.stringify({ decision, comment: comment || null }) });
      setReview(r.review);
      notify?.(`Lēmums saglabāts; process: ${r.state}`);
    } catch (e) { notify?.(e.message, "error"); }
    setBusy(false);
  };
  const st = review ? (REVIEW_STATUS[review.status] || { label: review.status, cls: "bg-gray-100" }) : null;
  const draft = doc.metadata.uapf_draft;
  return (
    <div className="mt-3 bg-gradient-to-br from-emerald-50 to-white border-2 border-emerald-300 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold text-emerald-900">⚙️ Procesa rezultāts</h4>
        {result.sessionId && <span className="text-xs text-gray-500 font-mono">{result.sessionId}</span>}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {rows.map((k) => (
          <div key={k} className={["reason", "klasifikacijasNosaukums", "klasifikacijasPamatojums", "kodaNosaukums"].includes(k) ? "col-span-2" : ""}>
            <dt className="text-xs uppercase tracking-wide text-gray-500">{RESULT_LABELS[k]}</dt>
            <dd className="font-medium text-gray-900">{show(k)}</dd>
          </div>
        ))}
      </dl>
      {draft && (
        <div className="mt-3 pt-3 border-t border-emerald-200">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs uppercase tracking-wide text-gray-500">
              Atbildes projekts · {draft.templateId} v{draft.templateVersion}{draft.templateSynthetic ? " (sintētiska veidne)" : ""}
            </span>
            {Array.isArray(draft.missingElements) && (
              <span className={`text-xs px-2 py-0.5 rounded ${draft.missingElements.length ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`}>
                {draft.missingElements.length ? `Trūkst: ${draft.missingElements.join(", ")}` : "Obligātie elementi ir"}
              </span>
            )}
          </div>
          <pre className="whitespace-pre-wrap text-sm bg-white border rounded p-3 font-sans">{draft.text}</pre>
        </div>
      )}
      {review && (
        <div className="mt-3 pt-3 border-t border-emerald-200 space-y-2">
          <span className={`text-xs px-2 py-0.5 rounded font-semibold ${st.cls}`}>{st.label}</span>
          {review.status === "gaida" && fix ? (
            <div className="space-y-2 bg-sky-50 border border-sky-200 rounded p-3">
              <div className="text-xs text-sky-900">Labojums tiks saglabāts kā precedents: nākamajiem līdzīgajiem dokumentiem sistēma to ņems vērā.</div>
              <label className="block text-xs text-gray-600">Pareizā tēma (klasifikators {fix.opts.versija})
                <select className="mt-1 w-full border rounded p-1.5 text-sm" value={fix.kods} onChange={(e) => setFix({ ...fix, kods: e.target.value })}>
                  <option value="">— nemainīt —</option>
                  {["BT", "PPT", "SEK", "TV"].map((j) => (
                    <optgroup key={j} label={VALUE_LABELS[j] || j}>
                      {fix.opts.kodi.filter((c) => c.joma === j).map((c) => (
                        <option key={c.kods} value={c.kods}>{c.kods} — {c.cels}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-gray-600">Pareizā struktūrvienība (atstājiet, ja to nosaka tēma)
                <select className="mt-1 w-full border rounded p-1.5 text-sm" value={fix.vieniba} onChange={(e) => setFix({ ...fix, vieniba: e.target.value })}>
                  <option value="">— pēc tēmas —</option>
                  {fix.opts.vienibas.map((u) => <option key={u.id} value={u.id}>{u.id} — {u.nosaukums}</option>)}
                </select>
              </label>
              <textarea className="w-full border rounded p-2 text-sm" rows={2} placeholder="Kāpēc sistēmas priekšlikums bija nepareizs? (obligāti)"
                value={fix.iemesls} onChange={(e) => setFix({ ...fix, iemesls: e.target.value })} />
              <div className="flex gap-2">
                <button disabled={busy} onClick={sendFix} className="px-3 py-1.5 rounded bg-sky-600 text-white text-sm disabled:opacity-50">Saglabāt labojumu</button>
                <button disabled={busy} onClick={() => setFix(null)} className="px-3 py-1.5 rounded bg-gray-200 text-gray-800 text-sm">Atcelt</button>
              </div>
            </div>
          ) : review.status === "gaida" ? (
            <div className="space-y-2">
              <textarea className="w-full border rounded p-2 text-sm" rows={2} placeholder="Komentārs (nav obligāts)"
                value={comment} onChange={(e) => setComment(e.target.value)} />
              <div className="flex gap-2">
                <button disabled={busy} onClick={() => decide("apstiprinats")} className="px-3 py-1.5 rounded bg-emerald-600 text-white text-sm disabled:opacity-50">Apstiprināt</button>
                <button disabled={busy} onClick={openFix} className="px-3 py-1.5 rounded bg-sky-600 text-white text-sm disabled:opacity-50">Labot klasifikāciju / nodaļu</button>
                <button disabled={busy} onClick={() => decide("noraidits")} className="px-3 py-1.5 rounded bg-gray-200 text-gray-800 text-sm disabled:opacity-50">Noraidīt — manuāla virzība</button>
              </div>
            </div>
          ) : (
            <div className="text-xs text-gray-600">
              {review.decidedBy && <>Lēma: {review.decidedBy}</>}
              {result.labots && result.ieprieksejais && <> · sistēma bija ieteikusi {result.ieprieksejais.kods || result.ieprieksejais.kategorija || "—"} / {result.ieprieksejais.vieniba || "—"}; labojums saglabāts kā precedents Nr. {result.precedents}</>}
              {review.comment && <> · „{review.comment}”</>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Semantic description (vdvc/dokumentu-semantikas-formats): what the reviewer sees
// before approving, and whether the de-identified central layer was made.
const CLAIM_STATUS = {
  apgalvots: "apgalvo", pieprasits: "lūdz", apliecinats: "apliecina", noliegts: "noliedz", secinats: "secināts",
};
const PREDICATE_LV = {
  "iesnieguma-prieksmets": "Priekšmets", "iespejamais-parkapums": "Iespējamais pārkāpums", "lugums": "Lūgums",
  "notikuma-laiks": "Laiks", "tiesvediba": "Tiesvedība", "kaitejums-turpinas": "Kaitējums turpinās",
  "ieprieksejas-versanas": "Iepriekšējās vēršanās", "normativa-atsauce": "Normatīvā atsauce",
  "dokumenta-merkis": "Mērķis", "termins": "Termiņš", "pielikums": "Pielikums",
};
function SemanticDescriptionCard({ sem: initial, docId, notify }) {
  const [view, setView] = useState("lokals");
  const [sem, setSem] = useState(initial);
  const [busy, setBusy] = useState(false);
  const regenerate = async () => {
    setBusy(true);
    try {
      await api(`/uapf/semantics/${docId}/regenerate`, { method: "POST" });
      const d = await api(`/documents/${docId}`);
      setSem(d.metadata?.semantika || {});
      notify?.("Semantiskais apraksts izveidots no jauna");
    } catch (e) { notify?.(e.message, "error"); }
    setBusy(false);
  };
  const again = (
    <button disabled={busy} onClick={regenerate} className="text-xs px-2 py-0.5 rounded border bg-white text-gray-700 disabled:opacity-50">
      {busy ? "Ģenerē…" : "Ģenerēt vēlreiz"}
    </button>
  );
  const local = sem.lokals;
  const central = sem.centrals || sem.centralaPrieksskatijums;
  const d = view === "centrals" && central ? central : local;
  if (!local) {
    return (
      <div className="mt-3 border rounded-lg p-3 text-sm text-red-700 bg-red-50 flex items-start justify-between gap-3">
        <span>Semantiskais apraksts nav izveidots: {(sem.kludas || []).join("; ")}</span>{again}
      </div>);
  }
  const who = Object.fromEntries((d.dalibnieki || []).map((p) => [p.id, p.nosaukums || p.loma]));
  const proj = sem.projekcija;
  const rev = d.izcelsme?.parskatisana?.statuss;
  return (
    <div className="mt-3 border-2 border-indigo-200 rounded-lg p-4 bg-white">
      <div className="flex items-center justify-between mb-2">
        <h4 className="font-semibold text-indigo-900">Semantiskais apraksts</h4>
        <div className="flex gap-1 text-xs">
          {again}
          {["lokals", "centrals"].map((v) => (
            <button key={v} disabled={v === "centrals" && !central} onClick={() => setView(v)}
              className={`px-2 py-0.5 rounded border ${view === v ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-gray-600"} disabled:opacity-40`}>
              {v === "lokals" ? "Iestādē (lokālais)" : "Reģistram (centrālais)"}
            </button>
          ))}
        </div>
      </div>
      <div className="text-xs text-gray-500 mb-2">
        MI ģenerēts · {rev === "neparskatits" ? "nav pārskatīts" : rev === "labots" ? "pārskatīts un labots" : "pārskatīts"} ·
        profils {d.profils} · formāts {d.formataVersija} · {d.izcelsme?.noteikumuVersija}
      </div>
      <p className="text-sm text-gray-900 leading-relaxed">{d.kopsavilkums?.teksts}</p>
      <div className="flex flex-wrap gap-1 mt-2">
        {(d.temas || []).map((t, i) => (
          <span key={i} title={t.shema} className={`text-xs px-2 py-0.5 rounded ${t.shema?.includes("eurovoc") ? "bg-indigo-50 text-indigo-800" : "bg-emerald-50 text-emerald-800"}`}>
            {t.shema?.includes("eurovoc") ? "EuroVoc" : "Klasifikators"} {t.kods} {t.nosaukums}
          </span>
        ))}
        {(d.pazimes || []).map((p, i) => <span key={"p" + i} className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700">{p.kods}: {p.vertiba}</span>)}
      </div>
      <table className="w-full text-xs mt-3">
        <tbody>
          {(d.apgalvojumi || []).map((a) => (
            <tr key={a.id} className="border-t align-top">
              <td className="py-1 pr-2 text-gray-500 whitespace-nowrap">{PREDICATE_LV[a.predikats] || a.predikats}</td>
              <td className="py-1 pr-2"><span className="text-gray-500">{who[a.apgalvo] || a.apgalvo} {CLAIM_STATUS[a.statuss] || a.statuss}:</span> {a.vertiba}
                {a.laiks?.datums && <span className="text-gray-400"> ({a.laiks.datums})</span>}</td>
              <td className="py-1 text-gray-400 whitespace-nowrap">{(a.pieradijumi || []).map((e) => e.lapa ? `${e.lapa}. lpp.` : "").filter(Boolean).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(d.nenoteiktibas || []).length > 0 && (
        <div className="text-xs text-amber-700 mt-2">Nav noteikts: {d.nenoteiktibas.map((u) => `${u.lauks} (${u.iemesls})`).join("; ")}</div>
      )}
      {(sem.kludas || []).length > 0 && <div className="text-xs text-red-700 mt-2">Formāta pārbaude: {sem.kludas.slice(0, 4).join("; ")}</div>}
      {proj && (
        <div className={`text-xs mt-2 px-2 py-1 rounded ${proj.derigs ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
          Centrālais slānis: {proj.derigs ? "atbilst — var nodot reģistram" : "neatbilst — netiek nodots"} ·
          noņemti {proj.nonemti?.length || 0} lauki, vispārināti {proj.visparinati || 0}, aizstāti {proj.aizstati || 0}
          {(proj.atradumi || []).length > 0 && <> · atrasts: {proj.atradumi.map((f) => f.iemesls).join(", ")}</>}
          {(proj.modelaAtradumi || []).length > 0 && <> · modeļa pārbaude: {proj.modelaAtradumi.map((f) => f.iemesls).join("; ")}</>}
        </div>
      )}
    </div>
  );
}

function UapfClassificationCard({ classification }) {
  if (!classification) return null;
  const TOPIC_LV = {
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
  const PRI = {
    urgent: { bg: "bg-red-100",    text: "text-red-700",     label: "Steidzami" },
    high:   { bg: "bg-orange-100", text: "text-orange-700",  label: "Augsta"    },
    normal: { bg: "bg-emerald-100",text: "text-emerald-700", label: "Normāla"   },
    low:    { bg: "bg-gray-100",   text: "text-gray-600",    label: "Zema"      },
  };
  const c = classification;
  const pri = PRI[c.priority] || { bg: "bg-gray-100", text: "text-gray-600", label: c.priority };
  return (
    <div className="mt-3 bg-gradient-to-br from-emerald-50 to-white border-2 border-emerald-300 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold text-emerald-900 flex items-center gap-2">
          <span>⚙️</span> UAPF klasifikācija
        </h4>
        {c.sessionId && (
          <span className="text-xs text-gray-500 font-mono">{c.sessionId}</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">Tēma</div>
          <div className="font-semibold text-gray-900 mt-0.5">{TOPIC_LV[c.topic] || c.topic}</div>
          {c.topicConfidence != null && (
            <div className="text-xs text-gray-500">Pārliecība: {(c.topicConfidence * 100).toFixed(0)}%</div>
          )}
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">Prioritāte</div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`px-2 py-0.5 rounded text-xs font-semibold ${pri.bg} ${pri.text}`}>
              {pri.label}
            </span>
            {c.slaHours && <span className="text-xs text-gray-500">SLA {c.slaHours}h</span>}
          </div>
        </div>
        <div className="col-span-2 pt-3 border-t border-emerald-200">
          <div className="text-xs uppercase tracking-wide text-gray-500">Maršrutēšana</div>
          <div className="font-medium text-gray-900 mt-0.5">{c.department || "—"}</div>
          <div className="text-xs text-gray-600 font-mono">{c.reviewerRole || "—"}</div>
        </div>
      </div>
    </div>
  );
}

