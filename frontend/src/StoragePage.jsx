// Glabātuve — read-only explorer of the document package storage.
// Root: one folder per document (pakotnes/<DokumentaID>/). Inside: metadati.xml,
// izsekosana.xml, SHA256SUMS, datnes/… Click a folder to open it, a file to preview it.
// The path lives in the URL: /storage/<folder>/<sub>…, so back/forward work.

import { useState, useEffect } from "react";
import Icon from "./Icon.jsx";
import StorageSettings from "./StorageSettings.jsx";
import StandardXmlView, { hasReadableView } from "./StandardXmlView.jsx";

const token = () => localStorage.getItem("opendms_token") || "";

async function get(path) {
  const r = await fetch("/api" + path, { headers: { Authorization: `Bearer ${token()}` } });
  if (!r.ok) {
    let msg = `Kļūda ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r;
}

const size = (n) => n == null ? "—" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
const when = (s) => s ? new Date(s).toLocaleString("lv-LV", { dateStyle: "short", timeStyle: "short" }) : "—";
const isText = (m) => m.startsWith("text/") || m.endsWith("xml") || m.endsWith("json");
const isImage = (m) => m.startsWith("image/") && m !== "image/svg+xml";
const fileUrl = (p, dl) => `/storage/file?path=${encodeURIComponent(p)}${dl ? "&download=true" : ""}`;

function fileIcon(name) {
  if (name.endsWith(".xml")) return "🗎";
  if (name === "SHA256SUMS") return "#";
  if (/\.(docx?|odt)$/i.test(name)) return "📝";
  if (/\.pdf$/i.test(name)) return "📕";
  if (/\.(png|jpe?g|gif|webp)$/i.test(name)) return "🖼";
  return "📄";
}

export default function StoragePage({ notify, route, navigate }) {
  const path = (route || []).slice(1).map(decodeURIComponent).join("/");
  const [listing, setListing] = useState(null);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);   // { file, text?, url?, kind }
  const [filter, setFilter] = useState("");
  const [tab, setTab] = useState("readable");     // readable | raw — for metadati.xml / izsekosana.xml

  useEffect(() => {
    let alive = true;
    setListing(null); setError(null); closePreview();
    get(`/storage/browse?path=${encodeURIComponent(path)}`)
      .then((r) => r.json()).then((d) => alive && setListing(d))
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [path]);

  useEffect(() => () => closePreview(), []);

  function closePreview() {
    setPreview((p) => { if (p?.url) URL.revokeObjectURL(p.url); return null; });
  }

  const go = (p) => navigate("/storage" + (p ? "/" + p.split("/").map(encodeURIComponent).join("/") : ""));

  const open = async (f) => {
    if (preview?.file.path === f.path) { closePreview(); return; }
    closePreview();
    try {
      const r = await get(fileUrl(f.path));
      if (isText(f.mediaType)) {
        let text = await r.text();
        if (f.name.endsWith(".xml")) text = prettyXml(text);
        setPreview({ file: f, kind: "text", text });
        setTab("readable");
      } else if (f.mediaType === "application/pdf") {
        setPreview({ file: f, kind: "pdf", url: URL.createObjectURL(await r.blob()) });
      } else if (isImage(f.mediaType)) {
        setPreview({ file: f, kind: "image", url: URL.createObjectURL(await r.blob()) });
      } else {
        setPreview({ file: f, kind: "binary" });
      }
    } catch (e) { notify(e.message, "error"); }
  };

  const download = async (f) => {
    try {
      const blob = await (await get(fileUrl(f.path, true))).blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = f.name; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) { notify(e.message, "error"); }
  };

  const crumbs = path ? path.split("/") : [];
  const doc = listing?.document;
  const q = filter.trim().toLowerCase();
  const folders = (listing?.folders || []).filter((f) => !q || [f.name, f.document?.title, f.document?.registrationNumber]
    .some((v) => v && v.toLowerCase().includes(q)));
  const files = (listing?.files || []).filter((f) => !q || f.name.toLowerCase().includes(q));

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">Glabātuve</h1>
          <p className="text-sm text-ink-500">Dokumentu pakotnes glabātuvē · Dokumentu metadatu standarts v2.0</p>
        </div>
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Meklēt šajā mapē…"
          className="text-sm border rounded-md px-3 py-1.5 w-64" />
      </div>

      {!path && <StorageSettings notify={notify} />}

      {/* breadcrumbs */}
      <div className="flex flex-wrap items-center gap-1 text-sm font-mono bg-white border rounded-lg px-3 py-2">
        <button onClick={() => go("")} className="flex items-center gap-1 text-sky-700 hover:underline">
          <Icon name="folder" size={14} /> {listing?.root || "pakotnes"}
        </button>
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            <span className="text-ink-300">/</span>
            {i === crumbs.length - 1
              ? <span className="text-ink-800 break-all">{c}</span>
              : <button onClick={() => go(crumbs.slice(0, i + 1).join("/"))} className="text-sky-700 hover:underline break-all">{c}</button>}
          </span>
        ))}
      </div>

      {doc && (
        <div className="bg-white border rounded-lg px-4 py-3 flex items-center justify-between gap-4 text-sm">
          <div className="min-w-0">
            <div className="font-medium text-ink-900 truncate">{doc.title}</div>
            <div className="text-xs text-ink-500">
              Reģ. nr. {doc.registrationNumber || "—"} · <code>{doc.docUid}</code>
            </div>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <ValidBadge valid={doc.valid} />
            <button onClick={() => navigate("/documents/" + encodeURIComponent(doc.registrationNumber || doc.documentId))}
              className="text-xs text-sky-700 hover:underline">Atvērt dokumentu →</button>
          </div>
        </div>
      )}

      <div className={`grid gap-4 ${preview ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]" : ""}`}>
        <div className="bg-white border rounded-lg overflow-hidden self-start">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-ink-500">
              <tr>
                <th className="text-left font-medium px-3 py-2">Nosaukums</th>
                {!path && <th className="text-left font-medium px-3 py-2">Dokuments</th>}
                <th className="text-right font-medium px-3 py-2 w-24">Izmērs</th>
                <th className="text-right font-medium px-3 py-2 w-36">{path ? "Mainīts" : "Statuss"}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {path && (
                <tr className="hover:bg-gray-50 cursor-pointer" onClick={() => go(crumbs.slice(0, -1).join("/"))}>
                  <td className="px-3 py-1.5 text-ink-500" colSpan={3}>↰ ..</td>
                </tr>
              )}
              {folders.map((f) => (
                <tr key={f.path} className="hover:bg-gray-50 cursor-pointer" onClick={() => go(f.path)}>
                  <td className="px-3 py-1.5 font-mono text-xs">
                    <span className="flex items-center gap-2 text-ink-800 break-all">
                      <span className="text-amber-500 shrink-0"><Icon name="folder" size={16} /></span>{f.name}/
                    </span>
                  </td>
                  {!path && (
                    <td className="px-3 py-1.5 text-xs">
                      <div className="text-ink-800 truncate max-w-xs">{f.document?.title}</div>
                      <div className="text-ink-400">{f.document?.registrationNumber || "—"} · {when(f.document?.packageBuilt || f.document?.created)}</div>
                    </td>
                  )}
                  <td className="px-3 py-1.5 text-right text-ink-400">—</td>
                  <td className="px-3 py-1.5 text-right">{path ? "" : <ValidBadge valid={f.document?.valid} />}</td>
                </tr>
              ))}
              {files.map((f) => (
                <tr key={f.path} onClick={() => open(f)}
                  className={`cursor-pointer ${preview?.file.path === f.path ? "bg-sky-50" : "hover:bg-gray-50"}`}>
                  <td className="px-3 py-1.5 font-mono text-xs">
                    <span className="flex items-center gap-2 text-ink-800 break-all">
                      <span className="w-4 text-center shrink-0">{fileIcon(f.name)}</span>{f.name}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-right text-xs text-ink-500 whitespace-nowrap">{size(f.size)}</td>
                  <td className="px-3 py-1.5 text-right text-xs text-ink-400 whitespace-nowrap">{when(f.modified)}</td>
                </tr>
              ))}
              {listing && !folders.length && !files.length && (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-sm text-ink-400">
                  {q ? "Nekas neatbilst meklētajam." : path ? "Mape ir tukša." :
                    "Glabātuvē vēl nav dokumentu pakotņu. Tās izveido process „Ienākošā dokumenta reģistrēšana”, kad dokumentam pievieno pirmo datni."}
                </td></tr>
              )}
              {!listing && !error && <tr><td colSpan={4} className="px-3 py-6 text-center text-sm text-ink-400">Ielādē…</td></tr>}
              {error && <tr><td colSpan={4} className="px-3 py-6 text-center text-sm text-red-600">{error}</td></tr>}
            </tbody>
          </table>
          {listing && (
            <div className="px-3 py-1.5 border-t bg-gray-50 text-2xs text-ink-400">
              {folders.length} mapes · {files.length} datnes
              {files.length > 0 && ` · ${size(files.reduce((s, f) => s + (f.size || 0), 0))}`}
            </div>
          )}
        </div>

        {preview && (
          <div className="bg-white border rounded-lg overflow-hidden self-start lg:sticky lg:top-4">
            <div className="flex items-center justify-between gap-3 px-3 py-2 border-b bg-gray-50 text-xs">
              <div className="min-w-0">
                <div className="font-mono text-ink-800 break-all">{preview.file.name}</div>
                <div className="text-ink-400">{preview.file.mediaType} · {size(preview.file.size)}</div>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button onClick={() => download(preview.file)} className="text-sky-700 hover:underline">⬇ lejupielādēt</button>
                <button onClick={closePreview} className="text-ink-400 hover:text-ink-700" aria-label="Aizvērt">✕</button>
              </div>
            </div>
            {preview.kind === "text" && hasReadableView(preview.file.name) && (
              <div className="flex gap-1 px-3 pt-2 border-b text-xs">
                {[["readable", "Pārskats"], ["raw", "XML"]].map(([id, lbl]) => (
                  <button key={id} onClick={() => setTab(id)}
                    className={`px-3 py-1.5 -mb-px border-b-2 ${tab === id ? "border-sky-600 text-sky-700 font-medium" : "border-transparent text-ink-500 hover:text-ink-800"}`}>{lbl}</button>
                ))}
              </div>
            )}
            {preview.kind === "text" && hasReadableView(preview.file.name) && tab === "readable" && <StandardXmlView xml={preview.text} />}
            {preview.kind === "text" && !(hasReadableView(preview.file.name) && tab === "readable") && (
              <pre className="text-[11px] leading-snug p-3 overflow-auto max-h-[70vh] whitespace-pre">{preview.text}</pre>
            )}
            {preview.kind === "pdf" && <iframe title={preview.file.name} src={preview.url} className="w-full h-[70vh]" />}
            {preview.kind === "image" && <img src={preview.url} alt={preview.file.name} className="max-w-full mx-auto p-3" />}
            {preview.kind === "binary" && (
              <div className="p-6 text-sm text-ink-500 text-center space-y-3">
                <div className="text-3xl">{fileIcon(preview.file.name)}</div>
                <div>Šo datnes veidu pārlūkā nevar parādīt.</div>
                <button onClick={() => download(preview.file)} className="text-xs px-3 py-1.5 bg-sky-600 text-white rounded">Lejupielādēt</button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ValidBadge({ valid }) {
  if (valid == null) return <span className="text-2xs text-ink-400">—</span>;
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium whitespace-nowrap ${valid ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
      {valid ? "✓ atbilst standartam" : "✗ neatbilst"}
    </span>
  );
}

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Indent XML for reading. Falls back to the original text if it does not parse.
function prettyXml(text) {
  try {
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) return text;
    const out = [];
    const walk = (n, d) => {
      const pad = "  ".repeat(d);
      if (n.nodeType === 3) { const t = n.nodeValue.trim(); if (t) out.push(pad + esc(t)); return; }
      if (n.nodeType === 8) { out.push(`${pad}<!--${n.nodeValue}-->`); return; }
      if (n.nodeType !== 1) return;
      const attrs = Array.from(n.attributes).map((a) => ` ${a.name}="${esc(a.value).replace(/"/g, "&quot;")}"`).join("");
      const kids = Array.from(n.childNodes).filter((c) => c.nodeType !== 3 || c.nodeValue.trim());
      if (!kids.length) out.push(`${pad}<${n.nodeName}${attrs}/>`);
      else if (kids.length === 1 && kids[0].nodeType === 3) out.push(`${pad}<${n.nodeName}${attrs}>${esc(kids[0].nodeValue.trim())}</${n.nodeName}>`);
      else { out.push(`${pad}<${n.nodeName}${attrs}>`); kids.forEach((c) => walk(c, d + 1)); out.push(`${pad}</${n.nodeName}>`); }
    };
    walk(doc.documentElement, 0);
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + out.join("\n");
  } catch { return text; }
}
