-- 001_add_summary_registry.sql
-- 分层摘要持久化注册表

CREATE TABLE IF NOT EXISTS summary_registry (
    summary_key   TEXT PRIMARY KEY,       -- "L1:C:300308", "L2:P:ABCD1234", "L3:P:ABCD1234:3"
    level         INTEGER NOT NULL,       -- 1 / 2 / 3
    entity_id     TEXT NOT NULL,          -- 锚定实体 ID
    version       INTEGER DEFAULT 1,
    generated_at  TIMESTAMPTZ,
    stale         BOOLEAN DEFAULT FALSE,
    entity_count  INTEGER,               -- 覆盖的实体数
    summary_text  TEXT,                  -- 摘要全文
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_summary_registry_level
    ON summary_registry(level);

CREATE INDEX IF NOT EXISTS idx_summary_registry_entity_id
    ON summary_registry(entity_id);

CREATE INDEX IF NOT EXISTS idx_summary_registry_stale
    ON summary_registry(stale)
    WHERE stale = TRUE;