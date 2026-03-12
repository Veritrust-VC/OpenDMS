"""Database connection pool and schema management."""

import json, logging
from typing import Optional
import asyncpg
from opendms.config import get_settings

logger = logging.getLogger(__name__)
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("Database not initialized")
    return _pool


async def init_db():
    global _pool
    s = get_settings()
    _pool = await asyncpg.create_pool(s.database_url, min_size=s.db_pool_min, max_size=s.db_pool_max)
    async with _pool.acquire() as conn:
        await _create_schema(conn)
    # Ensure superadmin exists
    await _ensure_superadmin()
    logger.info("Database initialized")
    return _pool


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def _ensure_superadmin():
    import hashlib
    s = get_settings()
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT id FROM users WHERE email = $1", s.superadmin_email)
        if not existing:
            pw_hash = hashlib.sha256(s.superadmin_password.encode()).hexdigest()
            await conn.execute(
                """INSERT INTO users (email, password_hash, full_name, role, is_active)
                   VALUES ($1, $2, $3, $4, TRUE)""",
                s.superadmin_email, pw_hash, "System Administrator", "superadmin",
            )
            logger.info("Created superadmin: %s", s.superadmin_email)


async def _create_schema(conn):
    await conn.execute("""
        -- Users and authentication
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator'
                CHECK (role IN ('superadmin','admin','operator','viewer')),
            org_id BIGINT,
            department TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Organizations
        CREATE TABLE IF NOT EXISTS organizations (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            org_did TEXT,
            description TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        ALTER TABLE organizations ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE organizations
        SET is_default = TRUE
        WHERE id = (
            SELECT id FROM organizations
            ORDER BY created_at, id
            LIMIT 1
        )
        AND NOT EXISTS (
            SELECT 1 FROM organizations WHERE is_default = TRUE
        );
        ALTER TABLE users ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES organizations(id);

        -- Document registers (hierarchical structure)
        CREATE TABLE IF NOT EXISTS registers (
            id BIGSERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            parent_id BIGINT REFERENCES registers(id),
            description TEXT,
            retention_years INTEGER DEFAULT 5,
            access_level TEXT DEFAULT 'internal',
            sort_order INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Classification schema
        CREATE TABLE IF NOT EXISTS classifications (
            id BIGSERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            parent_id BIGINT REFERENCES classifications(id),
            description TEXT,
            sort_order INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Documents
        CREATE TABLE IF NOT EXISTS documents (
            id BIGSERIAL PRIMARY KEY,
            registration_number TEXT,
            title TEXT NOT NULL,
            doc_did TEXT,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','registered','sent','received','assigned','decided','archived')),
            org_id BIGINT REFERENCES organizations(id),
            register_id BIGINT REFERENCES registers(id),
            classification_id BIGINT REFERENCES classifications(id),
            assigned_to BIGINT REFERENCES users(id),
            content_summary TEXT,
            metadata JSONB DEFAULT '{}',
            semantic_summary JSONB,
            sensitivity_control JSONB,
            ai_summary_status TEXT NOT NULL DEFAULT 'PENDING',
            storage_key TEXT,
            storage_backend TEXT,
            file_name TEXT,
            file_size BIGINT,
            mime_type TEXT,
            created_by BIGINT REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        ALTER TABLE documents ADD COLUMN IF NOT EXISTS semantic_summary JSONB;
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS sensitivity_control JSONB;
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS ai_summary_status TEXT NOT NULL DEFAULT 'PENDING';


        -- Document events (local log + VC references)
        CREATE TABLE IF NOT EXISTS document_events (
            id BIGSERIAL PRIMARY KEY,
            document_id BIGINT NOT NULL REFERENCES documents(id),
            event_type TEXT NOT NULL,
            actor_id BIGINT REFERENCES users(id),
            vc_submitted BOOLEAN DEFAULT FALSE,
            vc_json JSONB,
            details JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Archive batches
        CREATE TABLE IF NOT EXISTS archive_batches (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending','exporting','completed','failed')),
            document_count INTEGER DEFAULT 0,
            export_format TEXT DEFAULT 'zip',
            export_path TEXT,
            created_by BIGINT REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS archive_batch_documents (
            batch_id BIGINT REFERENCES archive_batches(id),
            document_id BIGINT REFERENCES documents(id),
            PRIMARY KEY (batch_id, document_id)
        );



        -- Integration audit trail
        CREATE TABLE IF NOT EXISTS integration_audit_log (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            trace_id TEXT,
            actor_user_id BIGINT,
            actor_email TEXT,
            actor_role TEXT,
            organization_id BIGINT,
            organization_code TEXT,
            organization_did TEXT,
            entity_type TEXT,
            entity_id TEXT,
            entity_did TEXT,
            action TEXT NOT NULL,
            target_system TEXT NOT NULL,
            request_method TEXT,
            request_path TEXT,
            request_payload_summary TEXT,
            response_status INTEGER,
            response_summary TEXT,
            success BOOLEAN NOT NULL DEFAULT FALSE,
            error_message TEXT
        );

        -- System settings (key-value for branding, config)
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_docs_org ON documents(org_id);
        CREATE INDEX IF NOT EXISTS idx_docs_status ON documents(status);
        CREATE INDEX IF NOT EXISTS idx_docs_register ON documents(register_id);
        CREATE INDEX IF NOT EXISTS idx_docs_classification ON documents(classification_id);
        CREATE INDEX IF NOT EXISTS idx_docs_assigned ON documents(assigned_to);
        CREATE INDEX IF NOT EXISTS idx_docs_created_by ON documents(created_by);
        CREATE INDEX IF NOT EXISTS idx_events_doc ON document_events(document_id);
        CREATE INDEX IF NOT EXISTS idx_registers_parent ON registers(parent_id);
        CREATE INDEX IF NOT EXISTS idx_classifications_parent ON classifications(parent_id);
        CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id);


        CREATE INDEX IF NOT EXISTS idx_audit_created_at ON integration_audit_log(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_trace_id ON integration_audit_log(trace_id);
        CREATE INDEX IF NOT EXISTS idx_audit_action ON integration_audit_log(action);
        CREATE INDEX IF NOT EXISTS idx_audit_success ON integration_audit_log(success);

        -- Updated_at trigger
        CREATE OR REPLACE FUNCTION update_updated_at() RETURNS TRIGGER AS $$
        BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_docs_updated ON documents;
        CREATE TRIGGER trg_docs_updated BEFORE UPDATE ON documents
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
        DROP TRIGGER IF EXISTS trg_users_updated ON users;
        CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    """)
