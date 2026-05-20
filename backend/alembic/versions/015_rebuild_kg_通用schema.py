"""重建知识图谱表（通用Schema）

删除错误的 kg_nodes/kg_edges，重建为 kg_entities/kg_relationships

Revision ID: 015
Revises: 014
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 删除旧表（如果存在）
    op.execute("DROP TABLE IF EXISTS kg_edges CASCADE")
    op.execute("DROP TABLE IF EXISTS kg_nodes CASCADE")

    # ============================================================
    # 实体表：统一存储所有类型实体（Company/Product/Tech/Industry/Metric/Event）
    # ============================================================
    op.execute("""
        CREATE TABLE kg_entities (
            entity_id     VARCHAR(64) PRIMARY KEY,
            entity_type  VARCHAR(32) NOT NULL,
            name         VARCHAR(128) NOT NULL,
            ts_code      VARCHAR(16),
            properties   JSONB NOT NULL DEFAULT '{}',
            confidence   DECIMAL(3,2) DEFAULT 0.80,
            source_type  VARCHAR(48),
            source_name  VARCHAR(128),
            evidence_url TEXT,
            valid_from  DATE DEFAULT '1900-01-01',
            valid_to    DATE,
            superseded_by VARCHAR(64),
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT chk_entity_type CHECK (entity_type IN (
                'Company','Product','Tech','Industry','Metric','Event'
            ))
        )
    """)

    op.execute("COMMENT ON TABLE kg_entities IS '投资知识图谱实体表（通用Schema）'")
    op.execute("""
        COMMENT ON COLUMN kg_entities.entity_type IS
        'Company: 上市/法律实体 | Product: 产品/物料 | Tech: 技术路线 | Industry: 产业环节 | Metric: 指标 | Event: 事件'
    """)
    op.execute("""
        COMMENT ON COLUMN kg_entities.properties IS
        '类型特定属性（JSONB），Company: industry_tags/main_products/customer_base | Product: category/tech_gen/mass_prod_status | Event: event_type/signal_direction'
    """)
    op.execute("""
        COMMENT ON COLUMN kg_entities.valid_from IS
        '有效起始日，AS-OF查询依据。所有实体版本均保留，不覆盖。'
    """)

    # 索引
    op.execute("CREATE INDEX idx_kg_entities_type ON kg_entities(entity_type)")
    op.execute("CREATE INDEX idx_kg_entities_name ON kg_entities(name)")
    op.execute("CREATE INDEX idx_kg_entities_tsc ON kg_entities(ts_code)")
    op.execute("CREATE INDEX idx_kg_entities_valid ON kg_entities(valid_from, valid_to)")

    # ============================================================
    # 关系表：统一存储所有类型关系
    # ============================================================
    op.execute("""
        CREATE TABLE kg_relationships (
            id                BIGSERIAL PRIMARY KEY,
            from_entity       VARCHAR(64) NOT NULL,
            to_entity         VARCHAR(64) NOT NULL,
            relationship_type VARCHAR(32) NOT NULL,
            properties        JSONB DEFAULT '{}',
            confidence        DECIMAL(3,2) DEFAULT 0.80,
            valid_from        DATE DEFAULT '1900-01-01',
            valid_to          DATE,
            superseded_by     BIGINT,
            source_type       VARCHAR(48),
            source_name       VARCHAR(128),
            evidence_url      TEXT,
            article_ref       VARCHAR(256),
            notes             TEXT,
            created_at        TIMESTAMPTZ DEFAULT NOW(),
            updated_at        TIMESTAMPTZ DEFAULT NOW(),

            CONSTRAINT kg_rel_unique UNIQUE (from_entity, to_entity, relationship_type, valid_from),
            CONSTRAINT chk_rel_type CHECK (relationship_type IN (
                'BELONGS_TO','PRODUCES','SUPPLIES_TO','USES','APPLIES_TO',
                'CATALYZES','CONSTRAINS','DISCLOSES','SUBSTITUTES',
                'COMPETES_WITH','STATE_TRANSITION'
            ))
        )
    """)

    op.execute("COMMENT ON TABLE kg_relationships IS '投资知识图谱关系表（通用Schema）'")
    op.execute("""
        COMMENT ON COLUMN kg_relationships.properties IS
        'Reification: 同一边类型通过属性覆盖无限场景。
         SUPPLIES_TO: {product, contract_type, lock_ratio, volume, price, substitute_risk}
         PRODUCES: {status, capacity, spec, tech_route}
         COMPETES_WITH: {market, tech_route, market_share_est}
         SUBSTITUTES: {substitute_prob, cost_delta, tech_gap}
         CATALYZES: {lag_period, intensity, affected_scope}
         STATE_TRANSITION: {from_state, to_state, trigger_event, preconditions}
         DISCLOSES: {metric_name, metric_value, unit, period, audit_status}'
    """)
    op.execute("""
        COMMENT ON COLUMN kg_relationships.valid_from IS
        '关系生效起始日。不覆盖历史边，只追加新版本。'
    """)

    # 索引
    op.execute("CREATE INDEX idx_kg_rel_from ON kg_relationships(from_entity)")
    op.execute("CREATE INDEX idx_kg_rel_to ON kg_relationships(to_entity)")
    op.execute("CREATE INDEX idx_kg_rel_type ON kg_relationships(relationship_type)")
    op.execute("CREATE INDEX idx_kg_rel_valid ON kg_relationships(valid_from, valid_to)")
    op.execute("CREATE INDEX idx_kg_rel_conf ON kg_relationships(confidence)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kg_relationships CASCADE")
    op.execute("DROP TABLE IF EXISTS kg_entities CASCADE")
