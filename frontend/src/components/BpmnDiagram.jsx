/**
 * BPMN diagram viewer with live step highlighting.
 *
 * Uses bpmn-js (Camunda's own renderer) to display the actual BPMN XML
 * from the .uapf package as an SVG diagram. The same renderer Camunda
 * Modeler uses — we get the same visual fidelity as production tooling.
 *
 * Props:
 *   xml              — BPMN 2.0 XML string
 *   activeStepId     — id of step currently executing (yellow glow)
 *   completedStepIds — set/array of completed step ids (green checkmark)
 *   firedRuleIds     — { decisionId: ruleId } for hover/info, optional
 *   height           — px (default 360)
 *
 * Diagram is read-only; users can't drag boxes. Pan + zoom enabled.
 */
import { useEffect, useRef, useState } from "react";
import BpmnViewer from "bpmn-js/lib/NavigatedViewer";
import { layoutProcess } from "bpmn-auto-layout";
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";

// ── UAPF v2.4.0 algorithm card overlay helpers ───────────────────
// Reads uapf:algorithmCardRef from a bpmn-js businessObject regardless of
// the XML namespace prefix used (uapf:, uapf24:, uapfa:, …). The bpmn-js
// moddle exposes namespaced attributes via $attrs keyed by prefix:local.
const UAPF_NS_V24 = "https://uapf.dev/bpmn/v2.4";
function readAlgorithmCardRef(businessObject) {
  if (!businessObject) return null;
  const attrs = businessObject.$attrs || {};
  // Try common prefixes and the Clark notation form
  const candidates = [
    attrs["uapf:algorithmCardRef"],
    attrs["uapf24:algorithmCardRef"],
    attrs["uapfa:algorithmCardRef"],
    attrs["uapfv24:algorithmCardRef"],
    attrs[`{${UAPF_NS_V24}}algorithmCardRef`],
    attrs["algorithmCardRef"],
  ];
  for (const v of candidates) {
    if (typeof v === "string" && v.length > 0) return v;
  }
  // Fallback: scan all keys for any prefix matching local name
  for (const k of Object.keys(attrs)) {
    if (/(^|:)algorithmCardRef$/.test(k)) {
      const v = attrs[k];
      if (typeof v === "string" && v.length > 0) return v;
    }
  }
  return null;
}

function riskClassFor(meta) {
  if (!meta) return "unknown";
  const ai = meta.risk && meta.risk.aiActRiskClass;
  const ov = meta.risk && meta.risk.humanOversight;
  const det = meta.determinism || "deterministic";
  if (ai === "high" || ov === "mandatory") return "red";
  if (det === "stochastic" || det === "learned") return "amber";
  if (ai === "limited" && ov && ov !== "none") return "amber";
  return "green";
}

const RISK_DOT_COLOR = {
  green: "#1D9E75",
  amber: "#EF9F27",
  red:   "#E24B4A",
  unknown: "#888780",
};

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Returns an HTMLElement (not string) to hand bpmn-js Overlays.add.
function buildAlgorithmOverlayHtml(cardRef, meta) {
  const root = document.createElement("div");
  root.className = "uapf-algo-overlay";
  root.style.cssText =
    "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;" +
    "font-family:Arial,sans-serif;font-size:10px;color:#5F5E5A;";

  // Algorithm icon — three stacked rounded rects + ƒ glyph
  const iconNs = "http://www.w3.org/2000/svg";
  const icon = document.createElementNS(iconNs, "svg");
  icon.setAttribute("width", "34");
  icon.setAttribute("height", "24");
  icon.setAttribute("viewBox", "0 0 34 24");
  icon.style.cssText = "position:absolute;top:4px;left:4px;background:#FFFFFF;border-radius:2px;";
  icon.innerHTML =
    '<rect x="8" y="2"  width="22" height="14" rx="2" fill="#FFFFFF" stroke="#1F2328" stroke-width="1"/>' +
    '<rect x="5" y="5"  width="22" height="14" rx="2" fill="#FFFFFF" stroke="#1F2328" stroke-width="1"/>' +
    '<rect x="2" y="8"  width="22" height="14" rx="2" fill="#FFFFFF" stroke="#1F2328" stroke-width="1"/>' +
    '<text x="13" y="19" text-anchor="middle" font-family="serif" font-size="11" font-style="italic" fill="#1F2328">ƒ</text>';
  root.appendChild(icon);

  // Risk dot top-right
  const risk = riskClassFor(meta);
  const dot = document.createElement("div");
  dot.className = "uapf-risk-dot uapf-risk-" + risk;
  dot.style.cssText =
    "position:absolute;top:6px;right:6px;width:10px;height:10px;border-radius:50%;" +
    "background:" + (RISK_DOT_COLOR[risk] || RISK_DOT_COLOR.unknown) + ";border:1px solid #FFFFFF;";
  dot.title = "Algorithm card: " + cardRef + (meta ? " (risk: " + risk + ")" : "");
  root.appendChild(dot);

  // Two-line label at the bottom: card id, then metadata strip
  const labelBox = document.createElement("div");
  labelBox.style.cssText =
    "position:absolute;bottom:2px;left:0;right:0;text-align:center;padding:0 4px;line-height:1.2;" +
    "background:linear-gradient(to top,#FFFFFF 60%,rgba(255,255,255,0));";

  const idLine = document.createElement("div");
  idLine.style.cssText = "font-size:9px;color:#5F5E5A;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
  idLine.textContent = cardRef;
  idLine.title = cardRef;
  labelBox.appendChild(idLine);

  if (meta) {
    const metaLine = document.createElement("div");
    metaLine.style.cssText = "font-size:9px;color:#888780;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
    const parts = [
      meta.version ? "v" + meta.version : null,
      meta.algorithm_kind || null,
      meta.determinism || "deterministic",
    ].filter(Boolean);
    metaLine.textContent = parts.join(" · ");
    labelBox.appendChild(metaLine);
  }

  root.appendChild(labelBox);
  return root;
}

export default function BpmnDiagram({
  xml,
  activeStepId,
  completedStepIds = [],
  nodeAnnotations = {},
  algorithmCards = null,
  height = 360,
}) {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [error, setError] = useState(null);

  // Initialize viewer once
  useEffect(() => {
    if (!containerRef.current) return;
    const viewer = new BpmnViewer({
      container: containerRef.current,
      // Disable navigation features that interfere with the parent page scroll
      keyboard: { bindTo: null },
    });
    viewerRef.current = viewer;
    return () => {
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  // Load XML when it changes. If the file has no BPMN-DI (diagram layout)
  // section, run bpmn-auto-layout first to synthesize one — the package
  // ships semantic BPMN only, like most hand-authored process files.
  useEffect(() => {
    if (!viewerRef.current || !xml) return;
    let cancelled = false;
    setError(null);
    (async () => {
      try {
        let bpmnXml = xml;
        const hasDi = /BPMNDiagram|BPMNPlane/.test(xml);
        if (!hasDi) {
          bpmnXml = await layoutProcess(xml);
        }
        if (cancelled) return;
        const { warnings } = await viewerRef.current.importXML(bpmnXml);
        if (cancelled) return;
        viewerRef.current.get("canvas").zoom("fit-viewport", "auto");
        if (warnings.length) console.warn("BPMN import warnings:", warnings);
      } catch (err) {
        if (!cancelled) setError(err.message || String(err));
      }
    })();
    return () => { cancelled = true; };
  }, [xml]);

  // Re-fit the diagram whenever the container resizes. Covers the common
  // case where the container has zero width at viewer-init time, which
  // otherwise leaves the canvas blank until a manual zoom.
  useEffect(() => {
    if (!containerRef.current) return;
    const refit = () => {
      try { viewerRef.current?.get("canvas")?.zoom("fit-viewport", "auto"); } catch {}
    };
    const ro = new ResizeObserver(refit);
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Update highlights (active step + completed steps) — uses bpmn-js Overlays
  // and CSS class additions on shape elements.
  useEffect(() => {
    if (!viewerRef.current) return;
    let canvas;
    let overlays;
    try {
      canvas = viewerRef.current.get("canvas");
      overlays = viewerRef.current.get("overlays");
    } catch {
      return;
    }
    if (!canvas) return;

    // Clear any prior step markers
    try {
      const elements = viewerRef.current.get("elementRegistry").getAll();
      for (const el of elements) {
        canvas.removeMarker(el.id, "uapf-active");
        canvas.removeMarker(el.id, "uapf-completed");
      }
      overlays.remove({ type: "uapf-step-overlay" });
    } catch {}

    // Apply new ones
    for (const sid of completedStepIds || []) {
      try {
        canvas.addMarker(sid, "uapf-completed");
        overlays.add(sid, "uapf-step-overlay", {
          position: { top: -8, right: 8 },
          html: '<div class="uapf-tick">✓</div>',
        });
      } catch {}
    }
    if (activeStepId) {
      try {
        canvas.addMarker(activeStepId, "uapf-active");
        overlays.add(activeStepId, "uapf-step-overlay", {
          position: { top: -8, right: 8 },
          html: '<div class="uapf-spinner">⟳</div>',
        });
      } catch {}
    }
  }, [activeStepId, completedStepIds]);

  // Decision/value annotations: a labelled badge under specific nodes,
  // showing the outcome each decision produced.
  useEffect(() => {
    if (!viewerRef.current) return;
    let overlays;
    try { overlays = viewerRef.current.get("overlays"); } catch { return; }
    if (!overlays) return;
    try { overlays.remove({ type: "uapf-annotation" }); } catch {}
    const esc = (x) => String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    for (const [nid, text] of Object.entries(nodeAnnotations || {})) {
      if (!text) continue;
      try {
        overlays.add(nid, "uapf-annotation", {
          position: { bottom: -8, left: 0 },
          html: `<div class="uapf-annotation-badge">${esc(text)}</div>`,
        });
      } catch { /* node not in this diagram */ }
    }
  }, [nodeAnnotations, xml]);

  // ── UAPF v2.4.0 algorithm card overlays ──────────────────────────
  // For every serviceTask/task carrying a uapf:algorithmCardRef attribute
  // (any prefix, what matters is the namespace https://uapf.dev/bpmn/v2.4),
  // overlay an algorithm icon, the card id label, a metadata strip
  // (version · kind · determinism) and a risk-class dot (green / amber / red
  // per UAPF v2.4.0 chapter 13.10).
  //
  // Card metadata comes from the `algorithmCards` prop — a map keyed by card
  // id; the parent typically fetches it from
  // GET /api/uapf/packages/{id}/algorithms after package info loads.
  // If the prop is null/empty, the overlays simply don't render (graceful
  // degradation for packages that don't carry cards).
  useEffect(() => {
    if (!viewerRef.current || !xml) return;
    let overlays;
    let elementRegistry;
    try {
      overlays = viewerRef.current.get("overlays");
      elementRegistry = viewerRef.current.get("elementRegistry");
    } catch { return; }
    if (!overlays || !elementRegistry) return;

    // Clear any prior algorithm overlays
    try { overlays.remove({ type: "uapf-algo-card" }); } catch {}

    const cards = algorithmCards || {};
    const elements = elementRegistry.getAll();
    for (const element of elements) {
      const bo = element.businessObject;
      if (!bo) continue;
      const type = bo.$type;
      if (type !== "bpmn:ServiceTask" && type !== "bpmn:Task" && type !== "bpmn:BusinessRuleTask") continue;
      const cardRef = readAlgorithmCardRef(bo);
      if (!cardRef) continue;
      const meta = cards[cardRef] || null;
      try {
        overlays.add(element.id, "uapf-algo-card", {
          position: { top: 0, left: 0 },
          html: buildAlgorithmOverlayHtml(cardRef, meta),
        });
      } catch (err) {
        // shape missing or other render error — skip silently
      }
    }
  }, [xml, algorithmCards]);

  return (
    <div className="relative bg-white">
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-red-50 text-red-700 text-sm p-4 z-10">
          BPMN render error: {error}
        </div>
      )}
      <div
        ref={containerRef}
        style={{ height: `${height}px`, width: "100%" }}
        className="bpmn-diagram-container border border-gray-200 rounded"
      />
      <style>{`
        /* Step state colouring overlaid on bpmn-js's standard rendering */
        .bpmn-diagram-container .djs-element.uapf-completed .djs-visual > :nth-child(1) {
          stroke: #059669 !important;
          stroke-width: 2.5px !important;
          fill: #ecfdf5 !important;
        }
        .bpmn-diagram-container .djs-element.uapf-active .djs-visual > :nth-child(1) {
          stroke: #d97706 !important;
          stroke-width: 3px !important;
          fill: #fef3c7 !important;
          animation: uapf-pulse 1.4s ease-in-out infinite;
        }
        @keyframes uapf-pulse {
          0%, 100% { opacity: 1; }
          50%      { opacity: 0.6; }
        }
        .uapf-tick {
          background: #059669;
          color: white;
          border-radius: 9999px;
          width: 20px; height: 20px;
          display: flex; align-items: center; justify-content: center;
          font-size: 12px; font-weight: bold;
          box-shadow: 0 1px 4px rgba(0,0,0,0.2);
        }
        .uapf-spinner {
          background: #d97706;
          color: white;
          border-radius: 9999px;
          width: 22px; height: 22px;
          display: flex; align-items: center; justify-content: center;
          font-size: 14px; font-weight: bold;
          animation: uapf-rotate 1.5s linear infinite;
          box-shadow: 0 1px 4px rgba(0,0,0,0.2);
        }
        @keyframes uapf-rotate {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        .uapf-annotation-badge {
          background: #6d28d9;
          color: white;
          border-radius: 6px;
          padding: 2px 7px;
          font-size: 10px;
          font-weight: 600;
          white-space: nowrap;
          box-shadow: 0 1px 4px rgba(0,0,0,0.28);
        }
      `}</style>
    </div>
  );
}
