"""OpenDMS — Open Document Management System with VeriDocs DID/VC integration."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opendms.config import get_settings
from opendms.database import init_db, close_db
from opendms.sdk_client import close as close_sdk
from opendms.routers.auth import router as auth_router
from opendms.routers.oidc import router as oidc_router
from opendms.routers.users import router as users_router
from opendms.routers.documents import router as documents_router
from opendms.routers.intake import router as intake_router
from opendms.routers.forwarding import router as forwarding_router
from opendms.routers.structures import org_router, reg_router, cls_router
from opendms.routers.system import archive_router, settings_router, health_router
from opendms.routers.archive_scheme import router as archive_scheme_router
from opendms.routers.ai import router as ai_router
from opendms.routers.audit import router as audit_router
from opendms.routers.intelligence import router as intelligence_router
from opendms.routers.ai_instructions import router as ai_instructions_router
from opendms.routers.org_tools import router as org_tools_router
from opendms.routers.connections import router as connections_router
from opendms.routers.agent import router as agent_router
from opendms.routers.tasks import router as tasks_router
from opendms.mcp import router as mcp_router
from opendms.uapf import uapf_host_router
from opendms.routers.uapf_admin import router as uapf_admin_router
from opendms.routers.storage_browser import router as storage_router


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    # storage client libraries: no per-request debug lines (they also carry the access key id)
    for noisy in ("botocore", "boto3", "s3transfer", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db()
        from opendms.archive.schema import ensure_schema as _archive_schema
        await _archive_schema()
        from opendms.archive.engine import ensure_schema as _archive_engine_schema
        await _archive_engine_schema()
        from opendms.archive.destruction import ensure_schema as _archive_destruction_schema
        await _archive_destruction_schema()
        from opendms.archive.finding_aid import ensure_schema as _archive_fa_schema
        await _archive_fa_schema()
        from opendms.archive.transfer import ensure_schema as _archive_tr_schema
        await _archive_tr_schema()
        import asyncio as _asyncio
        from opendms.intake.email_channel import run_forever as _intake_loop
        intake_task = _asyncio.create_task(_intake_loop())
        from opendms.archive.lna_client import ensure_schema as _lna_schema, run_forever as _lna_loop
        await _lna_schema()
        lna_task = _asyncio.create_task(_lna_loop())
        from opendms.storage.sync import run_forever as _storage_sync
        sync_task = _asyncio.create_task(_storage_sync())
        yield
        intake_task.cancel()
        sync_task.cancel()
        lna_task.cancel()
        await close_sdk()
        await close_db()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
                  docs_url="/docs", redoc_url="/redoc")

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    for r in [auth_router, oidc_router, users_router, documents_router, org_router, reg_router,
              cls_router, archive_router, archive_scheme_router, settings_router, health_router, ai_router, audit_router, intelligence_router,
              ai_instructions_router, org_tools_router, connections_router, agent_router,
              uapf_host_router, uapf_admin_router, storage_router, mcp_router, intake_router, forwarding_router, tasks_router]:
        app.include_router(r)

    return app


app = create_app()
