"""创建知识图谱表（kg_nodes + kg_edges）

Revision ID: 014
Revises: 013_add_ingestion_metadata
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013_add_ingestion_metadata'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================
    # 节点表：统一存储所有类型节点（Industry/Company/Product/Tech/Metric/Event）
    # ============================================================
    op.execute("""
        CREATE TABLE IF NOT EXISTS kg_nodes (
            node_id         VARCHAR(64) PRIMARY KEY,
            node_type       VARCHAR(32) NOT NULL,
            name            VARCHAR(128) NOT NULL,
            segment         VARCHAR(32),
            properties      JSONB NOT NULL DEFAULT '{}',
            confidence_tier VARCHAR(16),
            source_type     VARCHAR(48),
            source_name     VARCHAR(128),
            evidence_url    TEXT,
            trade_date      DATE,
            effective_from  DATE DEFAULT '1900-01-01',
            effective_to    DATE,
            superseded_by   VARCHAR(64),
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute("""
        COMMENT ON TABLE kg_nodes IS '光通信产业链知识图谱节点表'
    """)
    op.execute("COMMENT ON COLUMN kg_nodes.node_type IS 'Industry/Company/Product/Tech/Metric/Event'")
    op.execute("COMMENT ON COLUMN kg_nodes.properties IS '类型特定属性（JSONB）'")

    # ============================================================
    # 关系表：统一存储所有类型关系
    # ============================================================
    op.execute("""
        CREATE TABLE IF NOT EXISTS kg_edges (
            id                BIGSERIAL PRIMARY KEY,
            from_node         VARCHAR(64) NOT NULL,
            to_node           VARCHAR(64) NOT NULL,
            relationship_type VARCHAR(32) NOT NULL,
            properties        JSONB DEFAULT '{}',
            confidence        DECIMAL(3,2) DEFAULT 0.80,
            effective_from    DATE DEFAULT '1900-01-01',
            effective_to      DATE,
            superseded_by     BIGINT,
            source_type       VARCHAR(48),
            source_name       VARCHAR(128),
            evidence_url      TEXT,
            article_ref       VARCHAR(256),
            notes             TEXT,
            created_at        TIMESTAMPTZ DEFAULT NOW(),
            updated_at        TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT edge_unique UNIQUE (from_node, to_node, relationship_type, effective_from)
        )
    """)

    op.execute("""
        COMMENT ON TABLE kg_edges IS '光通信产业链知识图谱关系表'
    """)
    op.execute("""
        COMMENT ON COLUMN kg_edges.relationship_type IS
        'BELONGS_TO/SUPPLIES/TECH_ROUTE/STATUS_TRANSITION/DISCLOSES/CATALYZES/CONSTRAINS/SUBSTITUTES/COMPETES/CORRELATES_WITH'
    """)

    # 索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_nodes_type ON kg_nodes(node_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_nodes_segment ON kg_nodes(segment)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_nodes_name ON kg_nodes(name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_nodes_effective ON kg_nodes(effective_from, effective_to)")

    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_from ON kg_edges(from_node)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_to ON kg_edges(to_node)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_type ON kg_edges(relationship_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_effective ON kg_edges(effective_from, effective_to)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kg_edges")
    op.execute("DROP TABLE IF EXISTS kg_nodes")
