// Landing page — bilingual (LV/EN), agent first, register subordinate.
//
// Deliberately NOT a replacement pitch. The previous version opened with
// "Conventional DMS are built around a database — and that is now
// disqualifying", which argues against the system the buyer already owns and
// paid for. The argument here is additive: the agent takes on the work around
// the register, and the register the organisation already runs stays the
// system of record.
//
// The Latvian is written, not translated. Company voice ("mēs" / the product
// as subject), flowing sentences rather than English-style fragments, MI akts
// terminology per the locked glossary.

import { useState } from "react";
import BrandMark from "./BrandMark.jsx";
import Icon from "./Icon.jsx";

const COPY = {
  lv: {
    nav: { what: "Ko tas dara", parts: "Uzbūve", connect: "Savienojumi", trust: "Uzraudzība", login: "Ieiet" },
    tagline: "Lietvedības procesu aģents",
    heroTitle: "Aģents, kas pārņem lietvedības rutīnu",
    heroBody:
      "Dokumentu vadības aģents pats izlemj, kā virzīt konkrētu dokumentu: atrod saistīto, ierosina klasifikāciju, sagatavo uzdevumu atbildīgajai struktūrvienībai. Pirms katras darbības, ko vairs nevar atsaukt, tas apstājas un jautā cilvēkam.",
    heroNote:
      "Aģents strādā blakus iestādes esošajai dokumentu vadības sistēmai. Juridiskais oriģināls paliek tur, kur tas ir šodien.",
    ctaPrimary: "Ieiet sistēmā",
    ctaSecondary: "Skatīt pirmkodu",

    whatEyebrow: "KO AĢENTS DARA",
    whatTitle: "Četras lietas, ar ko tas atšķiras no darbplūsmas",
    what: [
      ["Plāno pats",
       "Aģents nesaņem gatavu soļu sarakstu. Katru nākamo darbību tas izvēlas, redzot iepriekšējās rezultātu — tāpat kā lietvedis, kurš vispirms pārbauda reģistru un tikai pēc tam izlemj, ko darīt tālāk."],
      ["Atceras savu darbu",
       "Faktus, ko aģents noskaidro viena uzdevuma laikā, tas pārnes uz nākamajiem soļiem. Sarunu var turpināt arī pēc pārtraukuma — konteksts nepazūd."],
      ["Rīkojas caur rīkiem",
       "Meklēšana reģistrā, ieraksts pastkastē, uzdevums Jira, dati no SAP — katrs rīks ir atsevišķi pieteikts, un aģents izvēlas no tā, kas tam atļauts."],
      ["Apstājas pirms neatgriezeniskā",
       "Nosūtīt vēstuli vai reģistrēt dokumentu ārējā sistēmā aģents nevar patstāvīgi. Šādas darbības tiek sagatavotas un gaida konkrēta cilvēka apstiprinājumu."],
    ],

    partsEyebrow: "UZBŪVE",
    partsTitle: "Aģenta daļas",
    partsBody:
      "Katrai daļai ir sava funkcija, un bez jebkuras no tām aģents vairs nav aģents — tas kļūst par darbplūsmu, kas izpilda iepriekš uzrakstītu secību.",
    agentic: [
      ["Plānotājs", "process", "Izvēlas nākamo darbību izpildes laikā, balstoties uz mērķi un iepriekšējo soļu rezultātiem."],
      ["Darba atmiņa", "insight", "Soļu vēsture un noskaidroto faktu pieraksts, ko aģents ņem vērā katrā nākamajā lēmumā."],
      ["Rīku brokeris", "plug", "Rīku katalogs, kurā katram norādīts, vai darbība ir atgriezeniska. Nezināms rīks pēc noklusējuma tiek uzskatīts par neatgriezenisku."],
      ["Aizsargmehānismi", "audit", "Pārbaude starp aģenta izvēli un tās izpildi: pilnvarojuma robežas, soļu ierobežojums, atkārtošanās atpazīšana un apstiprinājuma prasība."],
      ["Lēmumu žurnāls", "document", "Katram solim tiek fiksēts ne tikai kas notika, bet arī kāpēc tieši šī darbība un kādas bija alternatīvas."],
      ["MCP mezgls", "building", "Saskarne, caur kuru ar aģentu var sarunāties citas sistēmas un citi aģenti — AI LV Exchange mezgla formātā."],
    ],

    dmsTitle: "Reģistrs zem aģenta",
    dmsBody:
      "Aģentam ir arī pašam savs dokumentu reģistrs. Tas nav produkta galvenā daļa un neaizstāj iestādes lietvedības sistēmu — tas pastāv, lai aģents varētu strādāt arī tur, kur piekļuve esošajai sistēmai vēl nav atvērta, piemēram, pilotprojekta laikā.",
    dms: [
      ["Dokumentu reģistrs", "Ieraksti, reģistri, klasifikatori un dzīves cikla stāvokļi."],
      ["Glabātuve", "Faili vietējā glabātuvē, S3 vai Azure Blob — pēc iestādes izvēles."],
      ["Parakstīti notikumi", "Katra dzīves cikla maiņa tiek apliecināta ar verificējamu akreditāciju."],
      ["Audita pieraksti", "Katrs izsaukums uz ārējo sistēmu tiek fiksēts ar rezultātu un kļūdas iemeslu."],
    ],

    connEyebrow: "SAVIENOJUMI",
    connTitle: "Aģents pieslēdzas tam, kas iestādē jau strādā",
    connBody:
      "Savienotāju slānis ir vienveidīgs: katram savienojumam ir sava konfigurācija, atsevišķi šifrētas piekļuves datnes un veselības pārbaude. Jauna savienotāja pievienošana nemaina ne saskarni, ne procesus.",
    connLive: "Darbojas",
    connPrep: "Sagatavošanā",
    connLiveItems: [
      ["Jira Cloud", "Uzdevumu izveide, statusa maiņa un komentāri."],
      ["E-pasts (IMAP/SMTP)", "Dokumentu saņemšana no koplietojamās pastkastes un atbilžu nosūtīšana."],
    ],
    connPrepItems: [
      ["SAP", "Darījumu partneru un līgumu dati. Gaida saskarnes specifikāciju."],
      ["Dokumentu vadības sistēmas", "Reģistrācijas ieraksta nodošana iestādes DVS. Gaida piekļuvi un saskarnes aprakstu."],
    ],
    connNote:
      "Nesagatavotie savienotāji sistēmā ir redzami un izsaucami — tie atbild ar strukturētu atteikumu un uzskaita tieši to informāciju, kas vēl jāsaņem no sistēmas turētāja. Tas ir arī saraksts, ko sūtīt integrācijas sarunai.",

    ifaceTitle: "Četri veidi, kā ar aģentu strādāt",
    iface: [
      ["Saruna", "Uzdodiet darbu ar vienu teikumu un sekojiet līdzi soļiem. Ja aģents virzās nepareizi, to var izlabot darba gaitā, negaidot beigas."],
      ["Pārvaldības saskarne", "Savienojumi, uzvednes, klasifikatori, reģistri un audita pieraksti vienuviet."],
      ["REST API", "Pilna piekļuve dokumentiem, procesiem un aģenta izpildēm ārējām sistēmām."],
      ["MCP mezgls", "Citi aģenti var noskaidrot, kas šis mezgls ir, ko tas dara un ko tas par sevi neapgalvo."],
    ],

    trustEyebrow: "UZRAUDZĪBA",
    trustTitle: "Kāpēc aģentam var uzticēties",
    trust: [
      ["Cilvēks izlemj to, kas nav atsaucams", "Neatgriezeniskas darbības tiek sagatavotas, parādītas kopā ar pamatojumu un izpildītas tikai pēc konkrēta cilvēka apstiprinājuma. Apstiprināt caur ārējo saskarni nav iespējams."],
      ["Katrs lēmums ir izsekojams", "Lēmumu žurnālā redzams pamatojums, piedāvātās alternatīvas un aizsargmehānismu vērtējums. Secību aģents veido izpildes laikā, tāpēc pamatojums ir vienīgais pierādījums."],
      ["Pilnvarojumu var atsaukt", "Katram savienojumam ir ieslēgšanas slēdzis. Izslēdzot to, aģenta darbības uz attiecīgo sistēmu apstājas ar nākamo izsaukumu."],
      ["Atbilstība MI aktam", "Aģents ir aprakstāms reģistrā kā MI sistēma ar noteiktu nodrošinātāju un uzturētāju, cilvēka virsvadību un dokumentētu pilnvarojuma apjomu."],
    ],

    ctaTitle: "Sākam?",
    ctaBody: "Ieejiet savā vidē vai izvietojiet aģentu savā infrastruktūrā.",
    footNote: "Atvērtā pirmkoda programmatūra. Dati paliek iestādes infrastruktūrā.",
  },

  en: {
    nav: { what: "What it does", parts: "Anatomy", connect: "Connections", trust: "Oversight", login: "Login" },
    tagline: "Records management agent",
    heroTitle: "An agent that takes on the routine of records management",
    heroBody:
      "The Document Management Agent decides for itself how to move a given document forward: it finds what relates, proposes a classification, and prepares the task for the responsible unit. Before anything it cannot take back, it stops and asks a person.",
    heroNote:
      "It works alongside the document management system your organisation already runs. The authoritative record stays exactly where it is today.",
    ctaPrimary: "Login",
    ctaSecondary: "View the source",

    whatEyebrow: "WHAT THE AGENT DOES",
    whatTitle: "Four things that separate it from a workflow",
    what: [
      ["It plans its own steps",
       "The agent is not handed a sequence. It chooses each next action having seen what the previous one returned — the way a clerk checks the register first and only then decides what to do."],
      ["It remembers its own work",
       "Facts established during a task carry into later steps, and a conversation can be picked up after a break without losing its context."],
      ["It acts through declared tools",
       "A register search, a mailbox, a Jira task, a lookup in SAP — every tool is declared separately, and the agent chooses only from what it is permitted."],
      ["It stops before the irreversible",
       "Sending a letter or registering a document in an external system is not something it does alone. Those actions are prepared and wait for a named person to approve them."],
    ],

    partsEyebrow: "ANATOMY",
    partsTitle: "The parts of the agent",
    partsBody:
      "Each part has one job, and without any of them the agent stops being an agent — it becomes a workflow executing a sequence somebody wrote in advance.",
    agentic: [
      ["Planner", "process", "Chooses the next action at runtime from the goal and the results so far."],
      ["Working memory", "insight", "Step history and established facts, carried into every subsequent decision."],
      ["Tool broker", "plug", "The tool catalogue, each entry marked reversible or not. Anything unclassified is treated as irreversible."],
      ["Guardrails", "audit", "A check between the agent's choice and its execution: authority scope, step budget, loop detection and the approval requirement."],
      ["Decision log", "document", "Every step records not only what happened but why that action and what the alternatives were."],
      ["MCP node", "building", "The interface other systems and other agents use to talk to it, in AI LV Exchange node form."],
    ],

    dmsTitle: "The register underneath",
    dmsBody:
      "The agent also carries a document register of its own. It is not the main part of the product and does not replace the organisation's records system — it exists so the agent can work where access to the existing system is not yet open, during a pilot for instance.",
    dms: [
      ["Document register", "Records, registers, classifiers and lifecycle states."],
      ["Storage", "Files on local storage, S3 or Azure Blob, as the organisation prefers."],
      ["Signed events", "Each lifecycle change is attested with a verifiable credential."],
      ["Audit records", "Every call to an external system is recorded with its result and failure reason."],
    ],

    connEyebrow: "CONNECTIONS",
    connTitle: "It plugs into what already runs",
    connBody:
      "The connector layer is uniform: each connection has its own configuration, separately encrypted credentials and a health check. Adding a connector changes neither the interface nor the processes.",
    connLive: "Working",
    connPrep: "In preparation",
    connLiveItems: [
      ["Jira Cloud", "Creating issues, moving status and posting comments."],
      ["Email (IMAP/SMTP)", "Taking documents in from a shared mailbox and sending replies."],
    ],
    connPrepItems: [
      ["SAP", "Counterparty and contract data. Awaiting the interface specification."],
      ["Document management systems", "Passing the registration into the organisation's own DMS. Awaiting access and an interface description."],
    ],
    connNote:
      "Connectors that are not ready are still visible and callable — they answer with a structured refusal listing exactly what is still needed from the system owner. That list doubles as the agenda for the integration conversation.",

    ifaceTitle: "Four ways to work with it",
    iface: [
      ["Conversation", "Give it work in a sentence and watch the steps. If it heads the wrong way you correct it mid-task, rather than after."],
      ["Admin interface", "Connections, prompts, classifiers, registers and audit records in one place."],
      ["REST API", "Full access to documents, processes and agent runs for external systems."],
      ["MCP node", "Other agents can ask what this node is, what it does, and what it does not claim about itself."],
    ],

    trustEyebrow: "OVERSIGHT",
    trustTitle: "Why it can be trusted",
    trust: [
      ["A person decides what cannot be undone", "Irreversible actions are prepared, shown with their reasoning, and executed only after a named person approves. They cannot be approved through the external interface."],
      ["Every decision is traceable", "The log holds the reasoning, the alternatives offered and the guardrail verdict. The agent composes its sequence at runtime, so the reasoning is the only evidence there is."],
      ["Authority can be withdrawn", "Every connection has an enable switch. Turn it off and the agent's actions against that system stop at the next call."],
      ["Describable under the AI Act", "The agent can be entered in a register as an AI system with a named provider and deployer, human oversight, and a documented authority scope."],
    ],

    ctaTitle: "Ready to start?",
    ctaBody: "Sign in to your workspace, or run the agent on your own infrastructure.",
    footNote: "Open source. Data stays on the organisation's own infrastructure.",
  },
};

const GH = "https://github.com/Veritrust-VC/OpenDMS";

function Section({ id, children, className = "" }) {
  return <section id={id} className={"px-6 py-16 sm:py-20 " + className}>
    <div className="mx-auto max-w-6xl">{children}</div>
  </section>;
}

function Eyebrow({ children, accent }) {
  return <div className="text-2xs font-semibold tracking-widest mb-2" style={{ color: accent }}>{children}</div>;
}

export default function LandingPage({ brand, onLoginClick }) {
  const [lang, setLang] = useState("lv");
  const t = COPY[lang];
  const accent = brand?.brand_primary_color || "#0d7c66";
  const name = brand?.brand_name || "Dokumentu vadības aģents";

  return (
    <div className="min-h-screen bg-white text-ink-800">
      {/* ── nav ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 bg-white/90 backdrop-blur border-b border-ink-100">
        <div className="mx-auto max-w-6xl px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5 min-w-0">
            {brand?.brand_logo_url
              ? <img src={brand.brand_logo_url} className="h-9 w-9 rounded-md" alt="" />
              : <BrandMark size={36} color={accent} className="rounded-md" />}
            <div className="min-w-0">
              <div className="font-semibold text-ink-900 leading-tight truncate">{name}</div>
              <div className="text-2xs text-ink-400 leading-tight">{t.tagline}</div>
            </div>
          </div>
          <nav className="flex items-center gap-5 text-sm">
            <a href="#what" className="hidden md:inline text-ink-500 hover:text-ink-900 transition-colors">{t.nav.what}</a>
            <a href="#parts" className="hidden md:inline text-ink-500 hover:text-ink-900 transition-colors">{t.nav.parts}</a>
            <a href="#connect" className="hidden md:inline text-ink-500 hover:text-ink-900 transition-colors">{t.nav.connect}</a>
            <a href="#trust" className="hidden md:inline text-ink-500 hover:text-ink-900 transition-colors">{t.nav.trust}</a>
            <div className="flex rounded-md border border-ink-200 overflow-hidden" role="group" aria-label="Valoda / Language">
              {["lv", "en"].map((l) => (
                <button key={l} onClick={() => setLang(l)} aria-pressed={lang === l}
                  className={"px-2 py-1 text-2xs font-semibold uppercase transition-colors cursor-pointer " +
                    (lang === l ? "text-white" : "text-ink-500 hover:bg-ink-50")}
                  style={lang === l ? { background: accent } : undefined}>{l}</button>
              ))}
            </div>
            <button onClick={onLoginClick} className="btn-primary" style={{ background: accent }}>
              {t.nav.login}
            </button>
          </nav>
        </div>
      </header>

      {/* ── hero ────────────────────────────────────────── */}
      <Section className="pt-20 pb-14">
        <div className="max-w-3xl">
          <h1 className="text-3xl sm:text-[2.6rem] font-bold tracking-tight leading-[1.15] text-ink-900">
            {t.heroTitle}
          </h1>
          <p className="mt-5 text-lg text-ink-600 leading-relaxed">{t.heroBody}</p>
          <p className="mt-4 text-base text-ink-500 leading-relaxed border-l-2 pl-4"
             style={{ borderColor: accent }}>
            {t.heroNote}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button onClick={onLoginClick} className="btn-primary px-5 py-2.5" style={{ background: accent }}>
              {t.ctaPrimary}
            </button>
            <a href={GH} target="_blank" rel="noreferrer" className="btn-quiet px-5 py-2.5">
              {t.ctaSecondary} <Icon name="chevron" size={14} />
            </a>
          </div>
        </div>
      </Section>

      {/* ── what it does ────────────────────────────────── */}
      <Section id="what" className="bg-ink-50 border-y border-ink-100">
        <Eyebrow accent={accent}>{t.whatEyebrow}</Eyebrow>
        <h2 className="text-2xl font-bold tracking-tight text-ink-900">{t.whatTitle}</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {t.what.map(([h, b]) => (
            <div key={h} className="card p-5">
              <h3 className="font-semibold text-ink-900">{h}</h3>
              <p className="mt-2 text-sm text-ink-600 leading-relaxed">{b}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* ── anatomy: agentic first, register subordinate ─── */}
      <Section id="parts">
        <Eyebrow accent={accent}>{t.partsEyebrow}</Eyebrow>
        <h2 className="text-2xl font-bold tracking-tight text-ink-900">{t.partsTitle}</h2>
        <p className="mt-3 text-ink-600 max-w-3xl leading-relaxed">{t.partsBody}</p>

        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {t.agentic.map(([h, icon, b]) => (
            <div key={h} className="card p-5">
              <div className="w-9 h-9 rounded-md flex items-center justify-center mb-3"
                   style={{ background: accent + "14", color: accent }}>
                <Icon name={icon} size={19} />
              </div>
              <h3 className="font-semibold text-ink-900">{h}</h3>
              <p className="mt-1.5 text-sm text-ink-600 leading-relaxed">{b}</p>
            </div>
          ))}
        </div>

        {/* the register: visually secondary on purpose */}
        <div className="mt-10 rounded-xl border border-ink-200 bg-ink-50 p-6">
          <h3 className="font-semibold text-ink-900">{t.dmsTitle}</h3>
          <p className="mt-2 text-sm text-ink-600 max-w-3xl leading-relaxed">{t.dmsBody}</p>
          <div className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-2">
            {t.dms.map(([h, b]) => (
              <div key={h} className="flex gap-3">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full shrink-0" style={{ background: accent }} />
                <div>
                  <div className="text-sm font-medium text-ink-800">{h}</div>
                  <div className="text-sm text-ink-500 leading-relaxed">{b}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Section>

      {/* ── connections ─────────────────────────────────── */}
      <Section id="connect" className="bg-ink-50 border-y border-ink-100">
        <Eyebrow accent={accent}>{t.connEyebrow}</Eyebrow>
        <h2 className="text-2xl font-bold tracking-tight text-ink-900">{t.connTitle}</h2>
        <p className="mt-3 text-ink-600 max-w-3xl leading-relaxed">{t.connBody}</p>

        <div className="mt-8 grid gap-6 md:grid-cols-2">
          <div>
            <div className="label-eyebrow mb-2" style={{ color: accent }}>{t.connLive}</div>
            <div className="space-y-3">
              {t.connLiveItems.map(([h, b]) => (
                <div key={h} className="card p-4">
                  <div className="font-medium text-ink-900 text-sm">{h}</div>
                  <div className="text-sm text-ink-500 mt-1 leading-relaxed">{b}</div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="label-eyebrow mb-2 text-ink-400">{t.connPrep}</div>
            <div className="space-y-3">
              {t.connPrepItems.map(([h, b]) => (
                <div key={h} className="rounded-lg border border-dashed border-ink-300 bg-white/60 p-4">
                  <div className="font-medium text-ink-700 text-sm">{h}</div>
                  <div className="text-sm text-ink-500 mt-1 leading-relaxed">{b}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <p className="mt-6 text-sm text-ink-500 max-w-3xl leading-relaxed">{t.connNote}</p>
      </Section>

      {/* ── interfaces ──────────────────────────────────── */}
      <Section>
        <h2 className="text-2xl font-bold tracking-tight text-ink-900">{t.ifaceTitle}</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {t.iface.map(([h, b]) => (
            <div key={h} className="card p-5">
              <h3 className="font-semibold text-ink-900 text-[15px]">{h}</h3>
              <p className="mt-2 text-sm text-ink-600 leading-relaxed">{b}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* ── oversight ───────────────────────────────────── */}
      <Section id="trust" className="bg-ink-50 border-y border-ink-100">
        <Eyebrow accent={accent}>{t.trustEyebrow}</Eyebrow>
        <h2 className="text-2xl font-bold tracking-tight text-ink-900">{t.trustTitle}</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {t.trust.map(([h, b]) => (
            <div key={h} className="card p-5">
              <h3 className="font-semibold text-ink-900">{h}</h3>
              <p className="mt-2 text-sm text-ink-600 leading-relaxed">{b}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* ── cta ─────────────────────────────────────────── */}
      <Section className="text-center">
        <h2 className="text-2xl font-bold tracking-tight text-ink-900">{t.ctaTitle}</h2>
        <p className="mt-3 text-ink-600">{t.ctaBody}</p>
        <div className="mt-6 flex flex-wrap gap-3 justify-center">
          <button onClick={onLoginClick} className="btn-primary px-5 py-2.5" style={{ background: accent }}>
            {t.nav.login}
          </button>
          <a href={GH} target="_blank" rel="noreferrer" className="btn-quiet px-5 py-2.5">{t.ctaSecondary}</a>
        </div>
        <p className="mt-8 text-xs text-ink-400">
          W3C DID / Verifiable Credentials · did:web · MCP · UAPF · FastAPI · React · PostgreSQL
        </p>
      </Section>

      <footer className="border-t border-ink-100 px-6 py-8">
        <div className="mx-auto max-w-6xl flex flex-wrap items-center justify-between gap-4 text-sm text-ink-400">
          <span>{t.footNote}</span>
          <div className="flex gap-5">
            <a href={GH} target="_blank" rel="noreferrer" className="hover:text-ink-700 transition-colors">OpenDMS</a>
            <button onClick={onLoginClick} className="hover:text-ink-700 transition-colors cursor-pointer">{t.nav.login}</button>
          </div>
        </div>
      </footer>
    </div>
  );
}
