import { useState, useEffect } from "react";

// ──────────────────────────────────────────────────────────────────────────
// OpenDMS public landing page.
// Generic, brand-driven (brand_name / brand_primary_color / brand_logo_url from
// GET /api/settings/branding). No deployment-specific content. Ships with core.
// Props: brand, onLoginClick
// ──────────────────────────────────────────────────────────────────────────

const DEFINITION =
  "An open-source, AI-native document management system that effectively automates the organization's document lifecycle through machine-readable, manageable processes and classifiers, so every automated or human-in-the-loop document transaction is safely guardrailed and cryptographically signed for provenance.";

const FEATURES = [
  ["📑", "Document lifecycle", "Created → registered → sent → received → assigned → decided → archived — every transition a first-class, signed event."],
  ["⚙️", "External process packs", "Routing, classification, and extraction are defined in machine-readable UAPF packages, swapped without redeploying."],
  ["🧠", "AI review, human-in-the-loop", "Editable semantic summary and sensitivity assessment before a document is created — reviewed, never auto-applied."],
  ["🗄️", "Pluggable storage", "Local filesystem, any S3-compatible bucket, or Azure Blob — one environment variable."],
  ["🏷️", "Registers & classification", "Hierarchical registers and classification schemas, importable and exportable as JSON."],
  ["🛡️", "Audit trail", "Internal integration audit log with trace propagation across every signing call; combined OpenDMS + SDK viewer."],
  ["🔗", "Signed provenance", "Every lifecycle event signed as a W3C Verifiable Credential — provenance is intrinsic, not bolted on."],
  ["🎨", "Self-hosted & brandable", "Name, logo, and primary color are configuration. Runs on your infrastructure with one command."],
];

function hexToRgba(hex, a) {
  const h = (hex || "#0d7c66").replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export default function LandingPage({ brand, onLoginClick }) {
  const accent = brand?.brand_primary_color || "#0d7c66";
  const name = brand?.brand_name || "OpenDMS";
  const logo = brand?.brand_logo_url || "";
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const Logo = () =>
    logo ? (
      <img src={logo} alt="" className="h-9 rounded" />
    ) : (
      <div className="w-9 h-9 rounded-lg text-white font-bold text-lg flex items-center justify-center shrink-0" style={{ background: accent }}>
        {name.charAt(0).toUpperCase()}
      </div>
    );

  return (
    <div className="min-h-screen bg-white text-gray-800">
      {/* Nav */}
      <header className={`sticky top-0 z-30 transition-shadow ${scrolled ? "shadow-sm" : ""}`} style={{ background: "rgba(255,255,255,0.85)", backdropFilter: "blur(8px)" }}>
        <div className="max-w-6xl mx-auto px-5 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Logo />
            <div className="leading-tight">
              <div className="font-bold text-base">{name}</div>
              <div className="text-[11px] text-gray-400 -mt-0.5">AI-native document management</div>
            </div>
          </div>
          <nav className="flex items-center gap-2 sm:gap-5 text-sm">
            <a href="#problem" className="hidden sm:inline text-gray-500 hover:text-gray-900">Why</a>
            <a href="#architecture" className="hidden sm:inline text-gray-500 hover:text-gray-900">Architecture</a>
            <a href="#run" className="hidden sm:inline text-gray-500 hover:text-gray-900">Run it</a>
            <a href="https://github.com/Veritrust-VC/OpenDMS" target="_blank" rel="noreferrer" className="hidden sm:inline text-gray-500 hover:text-gray-900">GitHub</a>
            <button onClick={onLoginClick} className="px-4 py-1.5 rounded-lg text-white text-sm font-medium hover:opacity-90 transition" style={{ background: accent }}>Login</button>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section style={{ background: `linear-gradient(180deg, ${hexToRgba(accent, 0.06)} 0%, rgba(255,255,255,0) 70%)` }}>
        <div className="max-w-4xl mx-auto px-5 pt-20 pb-16 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium mb-6" style={{ background: hexToRgba(accent, 0.1), color: accent }}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: accent }} />
            Open source · AI-native · Process-driven
          </div>
          <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight leading-tight">
            Document management built around <span style={{ color: accent }}>processes and events</span> — not a database.
          </h1>
          <p className="mt-6 text-lg text-gray-500 leading-relaxed">{DEFINITION}</p>
          <div className="mt-8 flex items-center justify-center gap-3 flex-wrap">
            <button onClick={onLoginClick} className="px-6 py-3 rounded-xl text-white text-sm font-semibold hover:opacity-90 transition shadow-sm" style={{ background: accent }}>Login to your instance</button>
            <a href="https://github.com/Veritrust-VC/OpenDMS" target="_blank" rel="noreferrer" className="px-6 py-3 rounded-xl text-sm font-semibold border border-gray-200 text-gray-700 hover:bg-gray-50 transition">View on GitHub →</a>
          </div>
        </div>
      </section>

      {/* Problem */}
      <section id="problem" className="max-w-5xl mx-auto px-5 py-20">
        <div className="text-center mb-10">
          <h2 className="text-3xl font-bold tracking-tight">Conventional DMS are built around a database</h2>
          <p className="mt-3 text-gray-500 max-w-2xl mx-auto">And that is now disqualifying for two reasons.</p>
        </div>
        <div className="grid md:grid-cols-2 gap-5">
          <div className="rounded-2xl border border-gray-100 p-6">
            <h3 className="font-semibold">They store what happened, not what it means</h3>
            <p className="mt-2 text-sm text-gray-500 leading-relaxed">A row holds an id, a status, a date. Why it was classified that way, which rule applied, whether it was handled correctly — all implicit, living in a clerk's memory. Nothing for AI to reason over; nothing to audit but the records.</p>
          </div>
          <div className="rounded-2xl border border-gray-100 p-6">
            <h3 className="font-semibold">Their processes are hardcoded</h3>
            <p className="mt-2 text-sm text-gray-500 leading-relaxed">Routing, classification, and retention are compiled into the app. Changing a procedure means a ticket, a release, a redeploy — and the system can't be reused across organizations without forking the code.</p>
          </div>
        </div>
      </section>

      {/* Architecture — USP */}
      <section id="architecture" className="bg-gray-50 border-y border-gray-100">
        <div className="max-w-5xl mx-auto px-5 py-20">
          <div className="text-center mb-12">
            <div className="text-xs font-semibold tracking-widest mb-2" style={{ color: accent }}>THE CORE IDEA</div>
            <h2 className="text-3xl font-bold tracking-tight">Events and processes at the center</h2>
            <p className="mt-3 text-gray-500 max-w-2xl mx-auto">Lifecycle events are first-class and signed; the processes that decide what happens to a document live outside the core. AI proposes, the process governs, a human approves, the event records.</p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              ["External process packs", "Machine-readable BPMN/DMN/CMMN (UAPF), loaded at runtime, swappable without redeploy."],
              ["Signed event log", "Every transition recorded append-only and signed as a Verifiable Credential."],
              ["Document registry", "Current state and classifications — heading toward a regenerable projection over the event log."],
              ["Guardrailed AI", "Proposals are governed by the active process and reviewed by a human where required."],
            ].map(([t, d], i) => (
              <div key={t} className="rounded-2xl bg-white border border-gray-100 p-5">
                <div className="w-7 h-7 rounded-full text-white text-xs font-bold flex items-center justify-center mb-3" style={{ background: accent }}>{i + 1}</div>
                <div className="font-semibold text-sm">{t}</div>
                <div className="mt-1.5 text-sm text-gray-500 leading-relaxed">{d}</div>
              </div>
            ))}
          </div>
          <p className="mt-8 text-center text-sm text-gray-500 max-w-2xl mx-auto italic">Legacy systems store what happened; OpenDMS understands what it means — so audit becomes "check the reasoning," not "check the records."</p>
        </div>
      </section>

      {/* Differentiator: external processes */}
      <section className="max-w-5xl mx-auto px-5 py-20">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <div className="text-xs font-semibold tracking-widest mb-2" style={{ color: accent }}>THE DIFFERENTIATOR</div>
            <h2 className="text-3xl font-bold tracking-tight">Change behavior without touching the system</h2>
            <p className="mt-4 text-gray-500 leading-relaxed">How documents are analyzed, classified, routed, retained, and exchanged is not compiled into OpenDMS. It lives in external, machine-readable process &amp; classifier packs — Process-as-Code — that are versioned, signed, and loaded at runtime.</p>
            <ul className="mt-6 space-y-3 text-sm">
              {[
                "Publish a new pack to change a procedure — no code change, no redeploy.",
                "Reviewable, signed, version-tagged artifacts — not buried if-statements.",
                "The engine is generic; the domain lives entirely in the packs.",
                "Vendor- and model-neutral — nothing locked to one engine or AI model.",
              ].map((t) => (
                <li key={t} className="flex gap-3"><span className="mt-0.5" style={{ color: accent }}>✓</span><span className="text-gray-600">{t}</span></li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-gray-100 bg-gray-50 p-6 text-sm">
            <div className="text-xs font-medium text-gray-400 mb-4">RUNTIME FLOW</div>
            {[
              ["Document event", "e.g. received"],
              ["Matches a trigger", "fires a process pack"],
              ["UAPF runtime walks it", "calls host capabilities"],
              ["AI proposes · human approves", "guardrailed"],
              ["Signed event recorded", "provenance"],
            ].map(([a, b], i) => (
              <div key={a}>
                <div className="rounded-xl bg-white border border-gray-100 px-4 py-3 flex items-center justify-between">
                  <span className="font-medium">{a}</span><span className="text-gray-400 text-xs">{b}</span>
                </div>
                {i < 4 && <div className="flex justify-center text-gray-300 leading-none">↓</div>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Two ways to run it */}
      <section id="run" className="bg-gray-50 border-y border-gray-100">
        <div className="max-w-5xl mx-auto px-5 py-20">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold tracking-tight">Two ways to run it</h2>
            <p className="mt-3 text-gray-500 max-w-2xl mx-auto">The same product, standalone or networked. The central trust node is optional and additive.</p>
          </div>
          <div className="grid md:grid-cols-2 gap-5">
            <div className="rounded-2xl bg-white border border-gray-100 p-6">
              <h3 className="font-semibold">Standalone node</h3>
              <p className="mt-2 text-sm text-gray-500 leading-relaxed">One self-contained instance. Full DMS, full AI pipeline, signed lifecycle events anchored to its own DID. No external dependency, no central server.</p>
            </div>
            <div className="rounded-2xl bg-white border border-gray-100 p-6">
              <h3 className="font-semibold">Trust network</h3>
              <p className="mt-2 text-sm text-gray-500 leading-relaxed">Several nodes register their organization DIDs with a shared, optional VeriDocs Register. Signed events resolve into one verifiable chain across nodes — each keeps its own data. Start standalone, add the Register later; no migration.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-6xl mx-auto px-5 py-20">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight">What you get</h2>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {FEATURES.map(([icon, title, body]) => (
            <div key={title} className="rounded-2xl border border-gray-100 bg-white p-6 hover:shadow-md transition">
              <div className="w-11 h-11 rounded-xl flex items-center justify-center text-xl mb-4" style={{ background: hexToRgba(accent, 0.1) }}>{icon}</div>
              <h3 className="font-semibold text-[15px]">{title}</h3>
              <p className="mt-2 text-sm text-gray-500 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
        <p className="mt-10 text-center text-sm text-gray-400">W3C DID / Verifiable Credentials · did:web over HTTPS · eIDAS 2.0 aligned · FastAPI · React · PostgreSQL · Redis · no lock-in</p>
      </section>

      {/* CTA */}
      <section className="border-t border-gray-100" style={{ background: `linear-gradient(180deg, rgba(255,255,255,0) 0%, ${hexToRgba(accent, 0.05)} 100%)` }}>
        <div className="max-w-5xl mx-auto px-5 py-16 text-center">
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">Ready to sign in?</h2>
          <p className="mt-3 text-gray-500">Access your {name} workspace, or spin up your own instance.</p>
          <div className="mt-7 flex items-center justify-center gap-3 flex-wrap">
            <button onClick={onLoginClick} className="px-6 py-3 rounded-xl text-white text-sm font-semibold hover:opacity-90 transition shadow-sm" style={{ background: accent }}>Login</button>
            <a href="https://github.com/Veritrust-VC/OpenDMS#quick-start" target="_blank" rel="noreferrer" className="px-6 py-3 rounded-xl text-sm font-semibold border border-gray-200 text-gray-700 hover:bg-gray-50 transition">Self-host in 5 minutes</a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-100">
        <div className="max-w-6xl mx-auto px-5 py-10 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-gray-400">
          <div className="flex items-center gap-2"><Logo /><span>© {new Date().getFullYear()} {name}</span></div>
          <div className="flex items-center gap-5">
            <a href="https://github.com/Veritrust-VC/OpenDMS" target="_blank" rel="noreferrer" className="hover:text-gray-700">OpenDMS</a>
            <a href="https://github.com/Veritrust-VC/VeriDocs-SDK" target="_blank" rel="noreferrer" className="hover:text-gray-700">VeriDocs SDK</a>
            <a href="https://github.com/Veritrust-VC/VeriDocs-Register" target="_blank" rel="noreferrer" className="hover:text-gray-700">Register</a>
            <button onClick={onLoginClick} className="hover:text-gray-700">Login</button>
          </div>
        </div>
      </footer>
    </div>
  );
}
