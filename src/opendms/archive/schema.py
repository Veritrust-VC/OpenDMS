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

-- Lieta (standarts 03; MK 282 20.–26., 47. p.) — paplašina esošo standard_cases (LV-LIETA ID paliek)
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS scheme_entry_id BIGINT REFERENCES scheme_entries(id) ON DELETE SET NULL;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'Atverta';
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS arrangement TEXT;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS date_from DATE;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS date_to DATE;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS retention_kind TEXT;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS retention_years INTEGER;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS retention_trigger TEXT;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS disposition TEXT;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS retention_end DATE;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS legal_hold BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS long_running BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS document_count INTEGER;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS file_count INTEGER;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS register_key TEXT;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS register_sha256 TEXT;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS uzskaites_kods TEXT;
ALTER TABLE standard_cases ADD COLUMN IF NOT EXISTS history JSONB NOT NULL DEFAULT '[]';
DO $$ BEGIN
  ALTER TABLE standard_cases ADD CONSTRAINT standard_cases_status_check CHECK (status IN
    ('Atverta','Slegta','Izverteta','GlabaIestade','AtlasitaIznicinasanai','Iznicinata','Aprakstita','NodosanaiSagatavota','NodotaLNA'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS case_volumes (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES standard_cases(id) ON DELETE CASCADE,
    number INTEGER NOT NULL CHECK (number > 0),
    medium TEXT NOT NULL CHECK (medium IN ('E','P','C','H')),
    content_type TEXT NOT NULL DEFAULT 'Teksts' CHECK (content_type IN ('Teksts','Foto','Audio','Video','Datubaze','Cits')),
    document_count INTEGER,
    file_count INTEGER,
    page_count INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (case_id, number)
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS case_id BIGINT REFERENCES standard_cases(id);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_documents_case ON documents(case_id);
-- P2: arhīva ID (LNA "Identifikācijas Nr.", 40 hex) piešķir, kad reģistrācijas minimums izpildīts
ALTER TABLE documents ADD COLUMN IF NOT EXISTS archive_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS archive_ready_at TIMESTAMPTZ;
-- Vīzām, atzīmēm, rezolūcijām (standarts 08): amats
ALTER TABLE users ADD COLUMN IF NOT EXISTS position TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_archive_id ON documents(archive_id) WHERE archive_id IS NOT NULL;

-- Esošās saites: dokuments → lieta pēc pakotnes noteikumiem (indekss + reģistrācijas gads)
UPDATE documents d SET case_id = c.id
  FROM standard_cases c
 WHERE d.case_id IS NULL AND c.org_id = d.org_id
   AND c.case_index = d.metadata->'standartaPakotne'->'noteikumi'->>'caseIndex'
   AND c.case_year = EXTRACT(YEAR FROM d.created_at AT TIME ZONE 'Europe/Riga')::int;
UPDATE standard_cases SET opened_at = created_at WHERE opened_at IS NULL;
-- termiņi lietām, kurām tie vēl nav: no pirmā dokumenta procesa noteikumiem
UPDATE standard_cases c SET
       retention_kind = CASE WHEN (r->'retention'->>'permanent')::boolean THEN 'Pastavigi' ELSE 'Gadi' END,
       retention_years = NULLIF(r->'retention'->>'years', '')::numeric::int,
       retention_trigger = r->'retention'->>'trigger',
       disposition = r->'retention'->>'disposition'
  FROM (SELECT DISTINCT ON (case_id) case_id, metadata->'standartaPakotne'->'noteikumi' AS r
          FROM documents WHERE case_id IS NOT NULL AND metadata->'standartaPakotne'->'noteikumi' ? 'retention'
         ORDER BY case_id, id) x
 WHERE c.id = x.case_id AND c.retention_kind IS NULL;
"""


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SQL)
