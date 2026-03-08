"""OpenDMS — Open Document Management System with VeriDocs DID/VC integration."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opendms.config import get_settings
from opendms.database import init_db, close_db
from opendms.sdk_client import close as close_sdk
from opendms.routers.auth import router as auth_router
from opendms.routers.users import router as users_router
from opendms.routers.documents import router as documents_router
from opendms.routers.structures import org_router, reg_router, cls_router
from opendms.routers.system import archive_router, settings_router, health_router
from opendms.routers.ai import router as ai_router


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db()
        yield
        await close_sdk()
        await close_db()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
                  docs_url="/docs", redoc_url="/redoc")

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    for r in [auth_router, users_router, documents_router, org_router, reg_router,
              cls_router, archive_router, settings_router, health_router, ai_router]:
        app.include_router(r)

    return app


app = create_app()
