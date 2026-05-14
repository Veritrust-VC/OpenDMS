# OpenDMS

Open Document Management System with built-in W3C DID/VC lifecycle tracking.

Every document gets a decentralized identifier. Every lifecycle event — created, sent, received, assigned, decided, archived — is signed as a Verifiable Credential via the VeriDocs SDK and submitted to the central VeriDocs Register. Documents stay local; only trust evidence crosses organizational boundaries.

**Integrates with:** [VeriDocs SDK](https://github.com/Veritrust-VC/VeriDocs-SDK) (sidecar) + [VeriDocs Register](https://github.com/Veritrust-VC/VeriDocs-Register) (central registry)

---

## Features

- **Document CRUD** with registration numbers, metadata, file attachments
- **Lifecycle workflow**: draft → registered → sent → received → assigned → decided → archived
- **VeriDocs SDK integration**: every state transition creates a signed VC (JsonWebSignature2020 / ES256K)
- **Pluggable document storage**: local filesystem, S3-compatible (MinIO/AWS), Azure Blob
- **User management**: superadmin, admin, operator, viewer roles
- **Organization management** with DID registration via SDK
- **Document register structure**: hierarchical, importable/exportable as JSON
- **Classification schema**: hierarchical, importable/exportable as JSON
- **Archive export**: batch documents into ZIP with metadata + files
- **Document tracking**: query VeriDocs Registry for cross-institutional lifecycle
- **Customizable branding**: logo, name, primary color — configurable from admin UI
- **React admin frontend** with login, dashboard, documents workplace, admin settings

## Quick Start

```bash
git clone https://github.com/Veritrust-VC/OpenDMS.git
cd OpenDMS
cp .env.example .env
docker compose up --build
```

- **Frontend**: http://localhost:8080
- **API (Swagger)**: http://localhost:8002/docs
- **Default login**: admin@opendms.local / admin

## Architecture

```
┌──────────────────┐    ┌────────────────┐    ┌──────────────────┐
│  React Frontend   │───▶│  FastAPI API    │───▶│  PostgreSQL      │
│  :8080 (nginx)    │    │  :8002          │    │  :5433           │
└──────────────────┘    │                 │    └──────────────────┘
                        │    ┌─────────┐  │    ┌──────────────────┐
                        │───▶│  Redis   │  │    │  Document Storage │
                        │    │  :6379   │  │    │  Local/S3/Azure   │
                        │    └─────────┘  │    └──────────────────┘
                        │                 │
                        │───▶ VeriDocs SDK sidecar (:3100)
                        │    │  Veramo agent (VeriTrust fork)
                        │    │  DID creation, VC signing
                        │    │  → submits to VeriDocs Register
                        └────┘
```

## SDK and Registry Integration Model

OpenDMS does not talk directly to VeriDocs Register. All DID and VC lifecycle operations are brokered through the VeriDocs SDK sidecar.

**Flow:** `OpenDMS -> VeriDocs SDK -> VeriDocs Register`

- OpenDMS calls SDK APIs only.
- SDK handles authentication to VeriDocs Register.
- VeriDocs Register API is protected by bearer authentication.

## Docker deployment requirements for SDK/Register

The `sdk` service in `docker-compose.yml` must receive these environment variables:

- `REGISTRY_URL`
- `REGISTRY_EMAIL`
- `REGISTRY_PASSWORD`

When VeriDocs Register runs in a separate Compose stack, attach the OpenDMS `sdk` service to the Register Docker network (for example `veridocs-register_default`) so SDK can reach the Register API container directly.

## Storage Configuration

| Backend | Env vars | Description |
|---------|----------|-------------|
| `local` (default) | `OPENDMS_STORAGE_LOCAL_PATH` | Filesystem storage |
| `s3` | `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Any S3-compatible (MinIO, AWS, Wasabi) |
| `azure` | `OPENDMS_STORAGE_AZURE_CONNECTION_STRING`, `OPENDMS_STORAGE_AZURE_CONTAINER` | Azure Blob Storage |

## API Endpoints

### Auth
| `POST` | `/api/auth/login` | Login, returns JWT token |

### Documents
| `GET/POST` | `/api/documents` | List / create documents |
| `GET` | `/api/documents/{id}` | Document detail + events |
| `POST` | `/api/documents/{id}/upload` | Upload file attachment |
| `GET` | `/api/documents/{id}/download` | Download file |
| `POST` | `/api/documents/{id}/send` | Send → DocumentSent VC |
| `POST` | `/api/documents/{id}/receive` | Receive → DocumentReceived VC |
| `POST` | `/api/documents/{id}/assign` | Assign → DocumentAssigned VC |
| `POST` | `/api/documents/{id}/decide` | Decide → DocumentDecided VC |
| `POST` | `/api/documents/{id}/archive` | Archive → DocumentArchived VC |
| `GET` | `/api/documents/{id}/track` | Track via VeriDocs Registry |

### Admin
| `GET/POST` | `/api/users` | User management |
| `GET/POST` | `/api/organizations` | Organization management |
| `POST` | `/api/organizations/{id}/register-did` | Register org DID via SDK |
| `GET/POST` | `/api/registers` | Document register structure |
| `POST/GET` | `/api/registers/import` `/export` | Import/export register schema |
| `GET/POST` | `/api/classifications` | Classification schema |
| `POST/GET` | `/api/classifications/import` `/export` | Import/export classifications |
| `POST` | `/api/archive/batches` | Create archive batch |
| `POST` | `/api/archive/batches/{id}/export` | Export batch as ZIP |
| `GET/PUT` | `/api/settings` | System settings (branding, etc.) |
| `GET` | `/api/settings/branding` | Public branding (no auth) |


## SDK and Registry status

The platform exposes dedicated endpoints to separate application health from SDK onboarding readiness:

- `GET /api/health`: Overall OpenDMS health (database, storage, SDK service status, and aggregated SDK setup snapshot).
- `GET /api/sdk/setup-status`: Direct SDK onboarding and registry connectivity/auth state.
- `POST /api/organizations/{id}/register-did`: Starts/updates organization onboarding in SDK and stores the local organization DID.
- `GET /api/organizations/{id}/did-status`: Compares local OpenDMS org DID with the SDK active org DID and returns match status plus registry auth indicators.

Key SDK setup fields:

- `registry_connected`: SDK can reach VeriDocs Register over network.
- `registry_auth_configured`: SDK has registry credentials configured.
- `registry_authenticated`: SDK successfully authenticated to Register.
- `registry_auth_error`: Auth failure details returned by SDK (if any).

### Partial setup warning

A returned DID alone does **not** prove full end-to-end readiness. A local DID can exist even when the central Register entry is not yet created.

Common partial causes:

1. Registry credentials are missing (`REGISTRY_EMAIL` / `REGISTRY_PASSWORD`).
2. Registry authentication failed (invalid or expired credentials).
3. Registry connectivity problem (SDK cannot reach Register).


## Organizations UI updates

Organizations now include `name`, `code`, and `description` at creation time.
The Organizations page exposes:

- Local DID
- SDK setup status
- Registry connectivity
- Local DID vs SDK DID match status

## Related Repositories

| Repository | Description |
|------------|-------------|
| [VeriDocs-Register](https://github.com/Veritrust-VC/VeriDocs-Register) | Central DID/VC registry |
| [VeriDocs-SDK](https://github.com/Veritrust-VC/VeriDocs-SDK) | SDK sidecar (runs alongside OpenDMS) |

## License

MIT

## Audit logging and trace propagation

OpenDMS now stores an internal integration audit trail in PostgreSQL (`integration_audit_log`) for organization and document operations initiated from OpenDMS.

Each OpenDMS → SDK call propagates a trace identifier using `X-Trace-Id`. If one is not provided, OpenDMS generates a UUID. Actor context (`X-Actor-User-Id`, `X-Actor-Email`) is included for traceability only and is not added to SDK authentication tokens.

### Audit APIs

- `GET /api/audit/logs` — OpenDMS local audit rows
- `GET /api/audit/logs/{id}` — OpenDMS local audit row detail
- `GET /api/audit/sdk-logs` — proxied SDK audit logs
- `GET /api/audit/sdk-logs/{id}` — proxied SDK audit log detail
- `GET /api/audit/summary` — combined high-level counters (OpenDMS + SDK)

Supported local-log filters: `limit`, `offset`, `action`, `success`, `trace_id`, `organization_id`.

## Audit Logs GUI

The admin sidebar includes **Audit Logs** with:

- summary cards for OpenDMS actions, SDK sync calls, and failures
- tabs for OpenDMS logs vs SDK logs
- trace/action/success/org filters
- row detail modal with full trace ID, request/response summaries, and error details

Organizations page also includes **View sync logs** to jump into filtered audit logs by organization and trace context.

## Central registration truth model

A DID should be treated as centrally ready only when all are true:

- `registry_connected`
- `registry_authenticated`
- `org_registered_in_registry`
- `org_verified_in_registry`
- `org_did_configured`

If any of these are false, onboarding is partial (local DID may exist, but central verification is incomplete).

## March 2026 semantic summary review flow (SDK-driven)

OpenDMS now supports an additive SDK-centered AI review workflow:

1. User uploads/selects a file in the **Documents** create form.
2. User clicks **Generate AI Summary** (OpenDMS calls SDK `extract-summary`).
3. Frontend displays editable `semanticSummary` + `sensitivityControl` fields.
4. User reviews/edits and submits document creation.
5. OpenDMS stores reviewed semantic data locally and includes it in SDK document creation metadata.

### New document fields

`documents` table now includes:

- `semantic_summary` (`JSONB`)
- `sensitivity_control` (`JSONB`)
- `ai_summary_status` (`TEXT`, default `PENDING`)

Status behavior:

- `GENERATED`: SDK produced summary and user did not revise it yet.
- `VALIDATED`: user reviewed/edited and submitted.
- `SKIPPED`: created without AI summary.

### New API endpoints

- `POST /api/documents/{id}/extract-summary`
- `POST /api/documents/extract-summary-preview`
- `GET /api/intelligence/topics`
- `GET /api/intelligence/similar/{doc_id}`
- `GET /api/intelligence/warnings`
- `POST /api/intelligence/briefing`

### Privacy note

OpenDMS keeps raw file content local by default. The SDK-centered intelligence flow is designed so only semantic abstractions (summary/sensitivity metadata) are centralized when policy allows it.

## UAPF Integration

OpenDMS embeds as a host in the [UAPF Integration Protocol (UAPF-IP)](https://github.com/UAPFormat/UAPF-IP) ecosystem — see `src/opendms/uapf/`. It both invokes UAPF processes (when document lifecycle events match configured triggers) and serves the host-side capability endpoints the runtime calls back into.

### Architecture

```
                ┌────────────────────────────────────────────┐
                │  OpenDMS API (FastAPI)                     │
                │                                            │
   user ───► POST /api/documents/{id}/receive                │
                  │                                          │
                  │ _transition() succeeds                   │
                  │                                          │
                  ▼                                          │
              on_document_event("document.received", id)     │
                  │                                          │
                  │ matches process_triggers                 │
                  │ asyncio.create_task(...)                 │
                  │                                          │
                  ▼                                          │
              UapfClient.start_session(...)                  │
                  │                                          │
                  └─► POST /uapf/start-session ──────►┌──────┴────────────┐
                                                      │ uapf-engine       │
                                                      │ (Docker service)  │
                                                      │                   │
                                       walks BPMN ◄───┤ /packages/*.uapf  │
                                                      │                   │
                  ┌── POST /uapf/host/capability/*  ◄──┘                   │
                  │                                                       │
                  ▼                                                       │
            handlers.py dispatches:                                       │
              document.fetch → DB + storage                               │
              ai.redact      → LLM via opendms.ai                         │
              ai.extract     → LLM via opendms.ai                         │
              data.write     → complaint_classifications table            │
              event.emit     → document_events table                      │
                                                                          │
            session.completed audit ──► document_events ◄─────────────────┘
                │
                ▼
            User sees document with uapf_classification in metadata
```

### Tables added

- `process_triggers` — configures which lifecycle events fire which UAPF packages
- `uapf_sessions` — log of every triggered session + outcome
- `complaint_classifications` — the structured result of the Tiesibsargs flow

A seed `process_triggers` row is inserted at first DB initialization:

| name | trigger_event | package_id | match_condition |
|---|---|---|---|
| Tiesibsargs iesniegums classification | `document.received` | `lv.tiesibsargs.iesnieguma-izskatisana` | `{}` (matches all) |

To restrict to a specific register or classification, update the row's `match_condition` JSONB.

### Capabilities advertised

OpenDMS offers these via `GET /uapf/host/manifest`:

| Capability | Implementation |
|---|---|
| `document.fetch@1` | Reads from `documents` table + storage backend; extracts text via existing `_extract_text()` |
| `ai.redact@1` | Calls `opendms.ai._complete_json` with Latvian PII-aware prompt; falls back to regex scrub if AI unavailable |
| `ai.extract@1` | Calls `opendms.ai._complete_json` with the Tiesibsargs facet schema; returns all-false defaults on failure |
| `data.write@1` | Inserts into `complaint_classifications`; mirrors to `documents.metadata.uapf_classification` |
| `event.emit@1` | Appends to `document_events` with `event_type=iesniegums.classified` |

### Config

All settings live under the `OPENDMS_` env prefix:

| Variable | Default | Purpose |
|---|---|---|
| `OPENDMS_UAPF_ENABLED` | `true` | Master switch |
| `OPENDMS_UAPF_ENGINE_URL` | `http://uapf-engine:4000` | Reachable URL of the runtime |
| `OPENDMS_UAPF_ENGINE_AUTH_TOKEN` | _(empty)_ | Bearer token for both directions |
| `OPENDMS_OPENDMS_HOST_DID` | `did:web:opendms.local` | Identifier the host advertises |
| `OPENDMS_OPENDMS_HOST_BASE_URL` | `http://api:8002` | Where the runtime should call back to |

### Adding a new UAPF process

1. Drop the `.uapf` package into `./uapf-packages/`.
2. `docker compose restart uapf-engine` so it picks the new file up.
3. Insert a row into `process_triggers` (via SQL or, when the UI is built, the admin panel).

### Disabling

Set `UAPF_ENABLED=false` in `.env`, or set the matching `process_triggers` row's `is_active = false`. The bridge is fail-safe: any exception in the UAPF path is caught and logged; document lifecycle transitions never break because of a UAPF error.
