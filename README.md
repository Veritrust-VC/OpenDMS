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
- `GET /api/sdk/setup-status`: Direct SDK onboarding and registry connectivity state (mothership ping/status).
- `POST /api/organizations/{id}/register-did`: Starts/updates organization onboarding in SDK and stores the local organization DID.
- `GET /api/organizations/{id}/did-status`: Compares local OpenDMS org DID with the SDK active org DID and returns match status.

### Partial setup warning

A returned DID alone does **not** prove full end-to-end readiness. Full readiness requires:

1. SDK reachable.
2. Registry connected.
3. SDK org DID configured.

If only a DID is returned while registry connectivity or SDK org DID configuration is missing, onboarding should be treated as **partial**.

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
