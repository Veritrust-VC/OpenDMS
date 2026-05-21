/**
 * DMN decision-table viewer using dmn-js (Camunda's official renderer).
 *
 * Renders a single DMN file as the canonical Camunda decision table.
 * Read-only view; if the user wants to edit the rules they go to ProcessGit.
 *
 * Props:
 *   xml          — DMN 1.3 XML string
 *   firedRuleId  — id of the rule that fired (highlights that row in amber)
 */
import { useEffect, useRef, useState } from "react";
import DmnViewer from "dmn-js/lib/Viewer";
import "dmn-js/dist/assets/diagram-js.css";
import "dmn-js/dist/assets/dmn-js-decision-table.css";
import "dmn-js/dist/assets/dmn-js-decision-table-controls.css";
import "dmn-js/dist/assets/dmn-js-drd.css";
import "dmn-js/dist/assets/dmn-js-literal-expression.css";
import "dmn-js/dist/assets/dmn-js-shared.css";
import "dmn-js/dist/assets/dmn-font/css/dmn.css";

export default function DmnTableView({ xml, firedRuleId }) {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [error, setError] = useState(null);
  const [activeView, setActiveView] = useState(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const viewer = new DmnViewer({
      container: containerRef.current,
    });
    viewerRef.current = viewer;
    return () => {
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!viewerRef.current || !xml) return;
    let cancelled = false;
    setError(null);
    viewerRef.current
      .importXML(xml)
      .then(({ warnings }) => {
        if (cancelled) return;
        // Open the first decision table view (DMN 1.3 supports DRD + tables)
        const views = viewerRef.current.getViews();
        const tableView = views.find((v) => v.type === "decisionTable") || views[0];
        if (tableView) {
          viewerRef.current.open(tableView).then(() => {
            if (!cancelled) setActiveView(tableView);
          });
        }
        if (warnings.length) console.warn("DMN import warnings:", warnings);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || String(err));
      });
    return () => { cancelled = true; };
  }, [xml]);

  // Highlight the fired rule row by id. dmn-js renders rules as <tr> with
  // data-row-id={rule.id}, so we can style them with CSS.
  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const ALL = container.querySelectorAll("tr[data-row-id]");
    ALL.forEach((tr) => tr.classList.remove("uapf-fired-rule"));
    if (firedRuleId) {
      const tr = container.querySelector(`tr[data-row-id="${firedRuleId}"]`);
      if (tr) tr.classList.add("uapf-fired-rule");
    }
  }, [firedRuleId, activeView, xml]);

  return (
    <div className="dmn-table-wrap relative">
      {error && (
        <div className="bg-red-50 text-red-700 text-sm p-3 rounded border border-red-200">
          DMN render error: {error}
        </div>
      )}
      <div ref={containerRef} className="dmn-container" />
      <style>{`
        /* Hide the dmn-js toolbar — it's edit-oriented and we're read-only */
        .dmn-container .decision-table-properties-container,
        .dmn-container .powered-by,
        .dmn-container .dmn-decision-table-container > .toolbar {
          display: none;
        }
        .dmn-container .tjs-table,
        .dmn-container .dmn-decision-table {
          font-size: 12px;
        }
        /* Fired-rule highlight — overrides default row background */
        .dmn-container tr.uapf-fired-rule td {
          background: #fef3c7 !important;
          border-color: #f59e0b !important;
          font-weight: 500;
        }
        .dmn-container tr.uapf-fired-rule td:first-child::after {
          content: " ✓";
          color: #d97706;
          font-weight: bold;
        }
      `}</style>
    </div>
  );
}
