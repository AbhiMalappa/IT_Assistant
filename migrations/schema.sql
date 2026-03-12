-- IT Assistant — Full Supabase Schema
-- Run once to set up the database. Migrations are applied via Supabase MCP.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- incidents
-- Source: IT_Incidents_v1.csv (510 records loaded)
-- ============================================================
CREATE TABLE incidents (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    number              VARCHAR(20) UNIQUE NOT NULL,
    opened_at           TIMESTAMPTZ,
    opened_by           TEXT,
    state               TEXT CHECK (state IN ('Open', 'Closed', 'In Progress', 'Cancelled', 'On hold')),
    contact_type        TEXT,
    assignment_group    TEXT,
    assigned_to         TEXT,
    priority            VARCHAR(10) CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    configuration_item  TEXT,
    resolution_tier     TEXT,
    short_description   TEXT,
    caller              TEXT,
    label               TEXT,
    resolution_notes    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER incidents_updated_at BEFORE UPDATE ON incidents
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- conversation_messages
-- Stores per-thread conversation history with tool tracking
-- ============================================================
CREATE TABLE conversation_messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id       TEXT NOT NULL,
    role            VARCHAR(10) NOT NULL,       -- "user" or "assistant"
    full_content    TEXT,                       -- always stored, never discarded
    summary         TEXT,                       -- generated when use_summary = TRUE
    use_summary     BOOLEAN DEFAULT FALSE,      -- TRUE → send summary to Claude in buffer
    tool_used       TEXT,                       -- tool Claude called (e.g., sql_query)
    tool_input      JSONB,                      -- parameters passed to the tool
    tool_result     TEXT,                       -- raw result returned by the tool
    sql_query       TEXT,                       -- actual SQL string (sql_query tool only)
    token_count     INTEGER,                    -- stored at write time, used for buffer retrieval
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_thread_id_created ON conversation_messages(thread_id, created_at DESC);

-- ============================================================
-- changes (planned — schema TBD when change data is available)
-- ============================================================
-- CREATE TABLE changes ( ... );
-- CREATE TABLE incident_changes ( ... );
