"""Arhivēšanas tabulas (MK 282 31.–45. p.; standarts 02 un 04)."""

from __future__ import annotations

from opendms.database import get_pool

SQL = """
CREATE TABLE IF NOT EXISTS archive_settings (
    org_id BIGINT PRIMARY KEY REFERENCES organizations(id),
    archive_code TEXT,                       -- LNA arhīva kods, piem. LVA
    archive_name TEXT,                       -- piem. Latvijas Valsts arhīvs
    fonds_number TEXT,
    fonds_name TEXT,
    registration_number TEXT,                -- iestādes reģistrācijas Nr. (UR / nodokļu maksātāja)
    enforce_registration_minimum BOOLEAN NOT NULL DEFAULT FALSE,   -- P2 ieslēgts šajā DVS
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS classification_schemes (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    period_from DATE NOT NULL,
    period_to DATE NOT NULL,
    version TEXT NOT NULL DEFAULT '1',
    status TEXT NOT NULL DEFAULT 'Projekts' CHECK (status IN
        ('Projekts','IzskatitsEK','IesniegtsLNA','SaskanotsLNA','NoraiditsLNA','NavJasaskano','Apstiprinats','Aizstata')),
    sector BOOLEAN NOT NULL DEFAULT FALSE,
    title TEXT,
    history JSONB NOT NULL DEFAULT '[]',     -- [{statuss, datums, atsauce, piezimes, kas, kad}]
    source JSONB NOT NULL DEFAULT '{}',      -- importa avots
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (period_to >= period_from)
);
CREATE INDEX IF NOT EXISTS idx_cschemes_org ON classification_schemes(org_id, period_from);

CREATE TABLE IF NOT EXISTS scheme_entries (
    id BIGSERIAL PRIMARY KEY,
    scheme_id BIGINT NOT NULL REFERENCES classification_schemes(id) ON DELETE CASCADE,
    parent_id BIGINT REFERENCES scheme_entries(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('limenis','lieta')),
    level INTEGER CHECK (level BETWEEN 1 AND 3),
    idx TEXT NOT NULL,
    name TEXT NOT NULL,
    retention_kind TEXT CHECK (retention_kind IN ('Gadi','Pastavigi')),
    retention_years INTEGER CHECK (retention_years > 0),
    retention_marks TEXT[] NOT NULL DEFAULT '{}',          -- EK, AI
    retention_text TEXT,                                    -- kā rakstīts avotā
    retention_legal_basis TEXT,
    retention_trigger TEXT CHECK (retention_trigger IN ('NoDokumentaDatuma','NoLietasSlegsanas','NoIzpildes','NoNotikuma')),
    disposition TEXT CHECK (disposition IN ('Iznicinat','NodotArhivam','Parskatit')),
    responsible_unit TEXT,
    responsible_person TEXT,
    medium TEXT CHECK (medium IN ('E','P','C','H')),
    information_system TEXT,
    default_info_status TEXT CHECK (default_info_status IN ('Visparpieejama','IerobezotasPieejamibas','DienestaVajadzibam')),
    access_basis TEXT,
    access_until DATE,
    long_running BOOLEAN NOT NULL DEFAULT FALSE,
    continues_from_year INTEGER,
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (scheme_id, idx),
    CHECK (kind = 'limenis' OR retention_kind IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_sentries_scheme ON scheme_entries(scheme_id, sort_order);
"""


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SQL)
