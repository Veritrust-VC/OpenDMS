# OpenDMS

> **OpenDMS is an open-source, AI-native document management system that effectively automates the organization's document lifecycle through machine-readable, manageable processes and classifiers, so every automated or human-in-the-loop document transaction is safely guardrailed and cryptographically signed for provenance.**

**Companion projects:** [VeriDocs SDK](https://github.com/Veritrust-VC/VeriDocs-SDK) (trust sidecar) · [VeriDocs Register](https://github.com/Veritrust-VC/VeriDocs-Register) (optional central trust node)

---

## The problem

Conventional document management systems are built around a **document database**. Two consequences follow, and both are now disqualifying:

- **They store what happened, not what it means.** A row records a document's id, status, and date. *Why* it was classified that way, *which* rule applied, *whether* the handling was correct — all of that is implicit, living in a clerk's memory and a binder of procedures. There is little for AI to reason over and nothing to audit except the records themselves.
- **Their processes are hardcoded.** How documents are routed, classified, and retained is compiled into the application. Changing a procedure means a ticket, a release, a redeploy — and the system can't be reused across organizations without forking the code.

A modern DMS has to be **AI-native at the core**, which is only possible if it is built around **processes and events** instead of a static document store, with the processes and classifiers held *externally* so they can change without touching the system.

## Architecture — the core idea

OpenDMS is designed around **events and processes**, not around a document database.

- **Lifecycle events are first-class and signed.** Every transition — created → registered → sent → received → assigned → decided → archived — is recorded as an append-only event and signed as a W3C Verifiable Credential (JsonWebSignature2020 / ES256K) via the VeriDocs SDK.
- **Processes and classifiers live outside the core.** What happens to a document is defined in external, machine-readable process packages (BPMN / DMN / CMMN via the UAPF format), loaded by the runtime engine and swappable without redeploying OpenDMS.
- **AI proposes; the process governs; a human approves; the event records.** That pipeline is what makes the AI both native and safe.

> **Current implementation vs. direction.** Today OpenDMS persists current document state in a relational registry **and** records every lifecycle transition in an append-only, signed event log (`document_events`). The direction of travel is full event-sourcing — the event log as the single source of truth with the registry and a knowledge graph as regenerable projections. The concept above describes that design; the README marks where the current build already implements it.

## Features

- **Document lifecycle** — created → registered → sent → received → assigned → decided → archived, every transition a signed VC.
- **External process & classifier packs** — UAPF process packages drive routing, classification, and structured extraction; added without code changes (see [UAPF Integration](#uapf-integration)).
- **AI review (human-in-the-loop)** — generate an editable semantic summary and sensitivity assessment before a document is created; reviewed, never auto-applied.
- **Pluggable storage** — local filesystem, S3-compatible (MinIO/AWS/Wasabi), or Azure Blob.
- **Registers & classification** — hierarchical, importable/exportable as JSON.
- **Users & organizations** — role-based access (superadmin / admin / operator / viewer); per-organization DID registration via the SDK.
- **Audit trail** — internal integration audit log with `X-Trace-Id` propagation across every OpenDMS → SDK call; combined OpenDMS + SDK audit viewer.
- **Document tracking** — query the VeriDocs Register for cross-node lifecycle.
- **Self-hosted & brandable** — name, logo, primary color configurable from the admin UI; one `docker compose up`.

## Two ways to run it

- **Standalone node** — one self-contained instance. Full DMS, full AI pipeline, signed lifecycle events anchored to the instance's own DID. No external dependency, no central server.
- **Trust network** — several OpenDMS nodes (subsidiaries, departments, partner organizations) register their organization DIDs with a shared, **optional** central trust node (VeriDocs Register). Signed events resolve into one verifiable chain across every node; a document is traceable by its originating submitter while each node keeps its own data.

The central node is **optional and additive** — start standalone, add the Register later by pointing nodes at it. No migration, no re-issued identities.

## Quick Start

```bash
git clone https://github.com/Veritrust-VC/OpenDMS.git
cd OpenDMS
cp .env.example .env
docker compose up --build
```

- **Frontend**: http://localhost:8080
- **API (Swagger)**: http://localhost:8002/docs
- **Default login**: admin@opendms.local / admin (change in `.env`)

## Stack

```
┌──────────────────┐    ┌────────────────┐    ┌──────────────────┐
│  React Frontend   │───▶│  FastAPI API    │───▶│  PostgreSQL      │
│  nginx            │    │  business logic │    │  registry + event│
└──────────────────┘    │  + event log    │    │  log             │
                        │    ┌─────────┐  │    └──────────────────┘
                        │───▶│  Redis   │  │    ┌──────────────────┐
                        │    └─────────┘  │    │  Document Storage │
                        │                 │    │  Local/S3/Azure   │
                        │───▶ VeriDocs SDK sidecar (DID/VC signing)
                        │───▶ UAPF runtime engine (external process packs)
                        └─────────────────┘
```

## SDK & Register integration

OpenDMS never talks to the Register directly. All DID/VC operations are brokered through the **VeriDocs SDK sidecar**, so the SDK is the single trust component that gets hardened and audited.

**Flow:** `OpenDMS → VeriDocs SDK → VeriDocs Register`

The `sdk` service needs `REGISTRY_URL`, `REGISTRY_EMAIL`, `REGISTRY_PASSWORD`. When the Register runs as a separate Compose stack, attach the `sdk` service to the Register's Docker network so it can reach the Register API. Health/readiness is exposed via `GET /api/health` and `GET /api/sdk/setup-status`; a returned local DID alone does not prove central registration — treat a DID as centrally ready only when `registry_connected`, `registry_authenticated`, `org_registered_in_registry`, `org_verified_in_registry`, and `org_did_configured` are all true.

## Storage configuration

| Backend | Env vars | Description |
|---------|----------|-------------|
| `local` (default) | `OPENDMS_STORAGE_LOCAL_PATH` | Filesystem storage |
| `s3` | `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Any S3-compatible (MinIO, AWS, Wasabi) |
| `azure` | `OPENDMS_STORAGE_AZURE_CONNECTION_STRING`, `OPENDMS_STORAGE_AZURE_CONTAINER` | Azure Blob Storage |

## API endpoints (selected)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Login, returns JWT |
| `GET/POST` | `/api/documents` | List / create documents |
| `GET` | `/api/documents/{id}` | Document detail + events |
| `POST` | `/api/documents/{id}/upload` `/download` | File attachment in/out |
| `POST` | `/api/documents/{id}/{send\|receive\|assign\|decide\|archive}` | Lifecycle transition → signed VC |
| `GET` | `/api/documents/{id}/track` | Track via VeriDocs Register |
| `POST` | `/api/documents/{id}/extract-summary` | AI semantic summary (review flow) |
| `GET` | `/api/intelligence/{topics\|warnings\|similar/{id}}` | Intelligence over the corpus |
| `GET/POST` | `/api/users`, `/api/organizations` | Admin management |
| `POST` | `/api/organizations/{id}/register-did` | Register org DID via SDK |
| `GET/POST` | `/api/registers`, `/api/classifications` (+ `/import` `/export`) | Structure & schema |
| `POST` | `/api/archive/batches` (+ `/export`) | Archive batches → ZIP |
| `GET/PUT` | `/api/settings`; `GET /api/settings/branding` | System settings / public branding |
| `GET` | `/api/audit/{logs\|sdk-logs\|summary}` | Audit trail |

## AI review flow (human-in-the-loop)

1. Select a file in the **Documents** create form.
2. Click **Generate AI Summary** — OpenDMS calls the SDK to extract a summary.
3. The frontend shows editable `semanticSummary` + `sensitivityControl` fields.
4. Review/edit and submit; the reviewed data is stored locally and included in document metadata.

Document fields: `semantic_summary` (JSONB), `sensitivity_control` (JSONB), `ai_summary_status` (`GENERATED` / `VALIDATED` / `SKIPPED`). Raw file content stays local by default; only semantic abstractions are centralized when policy allows.

## UAPF Integration

OpenDMS is a **host** in the [UAPF Integration Protocol](https://github.com/UAPFormat/UAPF-IP) ecosystem (see `src/opendms/uapf/`). When a document lifecycle event matches a configured trigger, OpenDMS starts a process session on the external **UAPF runtime engine**, which walks the machine-readable process package and calls back into OpenDMS's host capabilities. The bridge is **fail-safe**: any error in the UAPF path is caught and logged; lifecycle transitions never break because of it.

**Host capabilities** advertised via `GET /uapf/host/manifest`:

| Capability | Implementation |
|---|---|
| `document.fetch@1` | Reads from the documents store + storage backend; extracts text |
| `ai.redact@1` | PII-aware redaction via `opendms.ai`; regex fallback if AI unavailable |
| `ai.extract@1` | Structured extraction per the schema declared by the active process package |
| `data.write@1` | Writes the structured result and mirrors it to `documents.metadata` |
| `event.emit@1` | Appends a typed event to the document event log |

**Adding a process:**
1. Drop a `.uapf` package into `./uapf-packages/`.
2. `docker compose restart uapf-engine`.
3. Configure a `process_triggers` row (which lifecycle event fires which package, with an optional match condition).

> **Deployment-specific content stays out of core.** Process packages, their classifiers and result schemas, triggers, and branding are **deployment configuration**, not product code. They belong in a deployment overlay (or a private packages directory), never committed to this repository. A process hardcoded into the application is a bug against this design.

Config (under the `OPENDMS_` env prefix): `OPENDMS_UAPF_ENABLED` (master switch), `OPENDMS_UAPF_ENGINE_URL`, `OPENDMS_UAPF_ENGINE_AUTH_TOKEN`, `OPENDMS_OPENDMS_HOST_DID`, `OPENDMS_OPENDMS_HOST_BASE_URL`. Disable with `UAPF_ENABLED=false` or by setting a trigger's `is_active = false`.

## Standards & no lock-in

W3C DID Core and Verifiable Credentials; `did:web` over HTTPS (no blockchain); eIDAS 2.0 / EUDI-Wallet aligned; standard stack (FastAPI · React · PostgreSQL · Redis); pluggable storage. No lock-in at any layer — not the DMS, the storage, the process engine, the classifier, the AI model, or the trust registry.

## Related repositories

| Repository | Role |
|------------|------|
| [VeriDocs-SDK](https://github.com/Veritrust-VC/VeriDocs-SDK) | Trust sidecar — runs alongside OpenDMS (required for signing) |
| [VeriDocs-Register](https://github.com/Veritrust-VC/VeriDocs-Register) | Optional central trust node for networked deployments |

## License

OpenDMS is **source-available and dual-licensed** — see [LICENSE](LICENSE).

- **Free** for personal, academic, internal non-commercial, and evaluation/trial use.
- **Commercial license required** for SaaS/hosting, redistribution, embedding, provision to external users, rebranding, and any revenue-generating use.
- **Public-sector / government use** requires a commercial license in **all** cases.

Trial freely; for licensing options contact **hello@veritrust.vc**.

> The licensing documents are a draft pending review by legal counsel.

© 2026 VeriTrust.vc
