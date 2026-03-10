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
