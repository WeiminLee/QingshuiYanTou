"""
数据库初始化脚本

执行所有 alembic 迁移来创建表结构。
"""
import sys
from pathlib import Path

# 添加 backend 目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = "postgresql://qingshui:qingshui123@localhost:5433/qingshui"

# 迁移 SQL（按顺序执行）
MIGRATIONS = [
    # 001 - 初始化表
    """
    CREATE TABLE IF NOT EXISTS stocks (
        ts_code VARCHAR(20) PRIMARY KEY,
        symbol VARCHAR(10) NOT NULL,
        name VARCHAR(50) NOT NULL,
        area VARCHAR(50),
        industry VARCHAR(50),
        market VARCHAR(20),
        list_date DATE,
        is_hs VARCHAR(1)
    );

    CREATE TABLE IF NOT EXISTS daily_data (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL REFERENCES stocks(ts_code),
        trade_date DATE NOT NULL,
        open FLOAT,
        high FLOAT,
        low FLOAT,
        close FLOAT,
        pre_close FLOAT,
        change FLOAT,
        pct_chg FLOAT,
        vol FLOAT,
        amount FLOAT,
        is_suspended BOOLEAN DEFAULT FALSE
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_ts_date ON daily_data(ts_code, trade_date);

    CREATE TABLE IF NOT EXISTS watchlist (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL REFERENCES stocks(ts_code),
        added_at TIMESTAMP DEFAULT now(),
        note VARCHAR(200)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_ts_code ON watchlist(ts_code);

    CREATE TABLE IF NOT EXISTS monitor_rules (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL,
        rule_type VARCHAR(20) NOT NULL,
        threshold FLOAT NOT NULL,
        enabled BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS alerts (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL,
        rule_type VARCHAR(20) NOT NULL,
        message TEXT NOT NULL,
        triggered_at TIMESTAMP DEFAULT now(),
        is_read BOOLEAN DEFAULT FALSE
    );

    CREATE TABLE IF NOT EXISTS analysis_reports (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL,
        agent_type VARCHAR(50) NOT NULL,
        report_content TEXT NOT NULL,
        trend VARCHAR(20),
        score INTEGER,
        created_at TIMESTAMP DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_report_ts_created ON analysis_reports(ts_code, created_at);

    CREATE TABLE IF NOT EXISTS research_documents (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL,
        title VARCHAR(200) NOT NULL,
        content TEXT,
        file_path VARCHAR(500),
        source VARCHAR(50),
        uploaded_at TIMESTAMP DEFAULT now()
    );
    """,

    # 002 - 概念和指数表
    """
    CREATE TABLE IF NOT EXISTS concept (
        id SERIAL PRIMARY KEY,
        concept_code VARCHAR(50) NOT NULL UNIQUE,
        concept_name VARCHAR(200) NOT NULL,
        created_at TIMESTAMP DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS index_daily (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL,
        trade_date DATE NOT NULL,
        open FLOAT,
        high FLOAT,
        low FLOAT,
        close FLOAT,
        pre_close FLOAT,
        change FLOAT,
        pct_chg FLOAT,
        vol FLOAT,
        amount FLOAT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_index_ts_date ON index_daily(ts_code, trade_date);
    """,

    # 003 - 唯一约束
    """
    ALTER TABLE stocks ADD CONSTRAINT stocks_symbol_unique UNIQUE (symbol);
    """,

    # 004 - 概念涨停表
    """
    CREATE TABLE IF NOT EXISTS concept_limit (
        id SERIAL PRIMARY KEY,
        concept_code VARCHAR(50) NOT NULL,
        concept_name VARCHAR(200) NOT NULL,
        trade_date DATE NOT NULL,
        up_nums INTEGER,
        pct_chg FLOAT,
        created_at TIMESTAMP DEFAULT now(),
        UNIQUE(concept_code, trade_date)
    );
    """,

    # 005 - THS 概念表
    """
    CREATE TABLE IF NOT EXISTS ths_index_component (
        id SERIAL PRIMARY KEY,
        index_code VARCHAR(50) NOT NULL,
        index_name VARCHAR(200) NOT NULL,
        ts_code VARCHAR(20) NOT NULL,
        stock_name VARCHAR(50) NOT NULL,
        trade_date DATE NOT NULL,
        weight FLOAT,
        created_at TIMESTAMP DEFAULT now(),
        UNIQUE(index_code, ts_code, trade_date)
    );

    CREATE TABLE IF NOT EXISTS ths_index_daily (
        id SERIAL PRIMARY KEY,
        index_code VARCHAR(50) NOT NULL,
        index_name VARCHAR(200) NOT NULL,
        trade_date DATE NOT NULL,
        open FLOAT,
        high FLOAT,
        low FLOAT,
        close FLOAT,
        change FLOAT,
        pct_chg FLOAT,
        volume FLOAT,
        amount FLOAT,
        created_at TIMESTAMP DEFAULT now(),
        UNIQUE(index_code, trade_date)
    );
    """,

    # 006 - 资讯表
    """
    CREATE TABLE IF NOT EXISTS information (
        id SERIAL PRIMARY KEY,
        title VARCHAR(500) NOT NULL,
        content TEXT,
        source VARCHAR(100),
        url VARCHAR(1000),
        pub_date DATE,
        ts_code VARCHAR(20),
        category VARCHAR(50),
        created_at TIMESTAMP DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_information_ts ON information(ts_code);
    CREATE INDEX IF NOT EXISTS idx_information_date ON information(pub_date);
    """,

    # 007 - 研报元数据表
    """
    CREATE TABLE IF NOT EXISTS research_report_meta (
        id SERIAL PRIMARY KEY,
        trade_date DATE NOT NULL,
        ts_code VARCHAR(20),
        file_name VARCHAR(200) NOT NULL,
        title VARCHAR(500),
        author VARCHAR(100),
        inst_csname VARCHAR(200),
        source_type VARCHAR(50),
        source_name VARCHAR(100),
        confidence_tier VARCHAR(20),
        created_at TIMESTAMP DEFAULT now(),
        UNIQUE(trade_date, file_name)
    );
    CREATE INDEX IF NOT EXISTS idx_report_ts ON research_report_meta(ts_code);
    CREATE INDEX IF NOT EXISTS idx_report_date ON research_report_meta(trade_date);
    """,

    # 008 - 公告表
    """
    CREATE TABLE IF NOT EXISTS announcements (
        id SERIAL PRIMARY KEY,
        ann_date DATE,
        ts_code VARCHAR(20),
        name VARCHAR(100),
        title VARCHAR(500),
        type TEXT,
        cninfo_id VARCHAR(200) UNIQUE,
        announcement_type VARCHAR(100),
        source_type VARCHAR(50),
        source_name VARCHAR(100),
        confidence_tier VARCHAR(20),
        created_at TIMESTAMP DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_ann_ts ON announcements(ts_code);
    CREATE INDEX IF NOT EXISTS idx_ann_date ON announcements(ann_date);
    """,

    # 009 - 股票池
    """
    CREATE TABLE IF NOT EXISTS stock_pool (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL,
        pool_type VARCHAR(50) NOT NULL,
        added_at TIMESTAMP DEFAULT now(),
        note TEXT,
        UNIQUE(ts_code, pool_type)
    );
    """,

    # 010 - 扩展公告字段
    """
    ALTER TABLE announcements ADD COLUMN IF NOT EXISTS content TEXT;
    ALTER TABLE announcements ADD COLUMN IF NOT EXISTS file_path VARCHAR(500);
    ALTER TABLE announcements ADD COLUMN IF NOT EXISTS pdf_url VARCHAR(1000);
    ALTER TABLE announcements ADD COLUMN IF NOT EXISTS org_id VARCHAR(50);
    """,

    # 011 - 公司概况
    """
    CREATE TABLE IF NOT EXISTS company_profiles (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL UNIQUE,
        main_business TEXT,
        product_type VARCHAR(200),
        product_name VARCHAR(500),
        business_scope TEXT,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now()
    );
    """,

    # 012 - 评分表
    """
    CREATE TABLE IF NOT EXISTS concept_scores (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL,
        concept_code VARCHAR(50) NOT NULL,
        score FLOAT,
        trade_date DATE NOT NULL,
        created_at TIMESTAMP DEFAULT now(),
        UNIQUE(ts_code, concept_code, trade_date)
    );

    CREATE TABLE IF NOT EXISTS stock_scores (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL UNIQUE,
        composite_score FLOAT,
        momentum_score FLOAT,
        concept_score FLOAT,
        trade_date DATE NOT NULL,
        created_at TIMESTAMP DEFAULT now()
    );
    """,

    # 013 - ingestion 元数据
    """
    CREATE TABLE IF NOT EXISTS ingestion_metadata (
        id SERIAL PRIMARY KEY,
        file_hash VARCHAR(64) UNIQUE,
        file_name VARCHAR(500) NOT NULL,
        file_path VARCHAR(1000),
        file_size BIGINT,
        source_type VARCHAR(50),
        ts_code VARCHAR(20),
        processed BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT now(),
        processed_at TIMESTAMP
    );
    """,

    # 014 - KG 表（保留结构但暂不使用）
    """
    CREATE TABLE IF NOT EXISTS entities (
        id SERIAL PRIMARY KEY,
        entity_id VARCHAR(100) NOT NULL UNIQUE,
        entity_name VARCHAR(500) NOT NULL,
        entity_type VARCHAR(100),
        description TEXT,
        properties JSONB,
        source_doc_id VARCHAR(100),
        created_at TIMESTAMP DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(entity_name);
    CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type);

    CREATE TABLE IF NOT EXISTS relations (
        id SERIAL PRIMARY KEY,
        source_id VARCHAR(100) NOT NULL,
        target_id VARCHAR(100) NOT NULL,
        relation_type VARCHAR(100) NOT NULL,
        weight FLOAT DEFAULT 1.0,
        properties JSONB,
        source_doc_id VARCHAR(100),
        created_at TIMESTAMP DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_relation_type ON relations(relation_type);
    """,

    # 016 - downloaded_documents
    """
    CREATE TABLE IF NOT EXISTS downloaded_documents (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20),
        title VARCHAR(500),
        file_path VARCHAR(1000) NOT NULL,
        file_hash VARCHAR(64),
        source_type VARCHAR(50),
        source_name VARCHAR(100),
        confidence_tier VARCHAR(20),
        downloaded_at TIMESTAMP DEFAULT now()
    );
    """,

    # 017 - minishare 公告表
    """
    CREATE TABLE IF NOT EXISTS minishare_announcements (
        id SERIAL PRIMARY KEY,
        ann_date DATE NOT NULL,
        ts_code VARCHAR(20),
        name VARCHAR(100),
        title VARCHAR(500),
        type VARCHAR(200),
        ann_types VARCHAR(200),
        content TEXT,
        source_url VARCHAR(1000),
        file_path VARCHAR(1000),
        pdf_url VARCHAR(1000),
        source_type VARCHAR(50) DEFAULT 'minishare',
        created_at TIMESTAMP DEFAULT now(),
        UNIQUE(ann_date, ts_code, title)
    );
    CREATE INDEX IF NOT EXISTS idx_ma_ts ON minishare_announcements(ts_code);
    CREATE INDEX IF NOT EXISTS idx_ma_date ON minishare_announcements(ann_date);
    """,

    # 018 - evidence 追踪表
    """
    CREATE TABLE IF NOT EXISTS evidence_tracking (
        id SERIAL PRIMARY KEY,
        source_table VARCHAR(100) NOT NULL,
        source_id INTEGER NOT NULL,
        evidence_id VARCHAR(100) NOT NULL,
        chunk_index INTEGER DEFAULT 0,
        extraction_status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now(),
        UNIQUE(source_table, source_id, chunk_index),
        UNIQUE(evidence_id)
    );
    CREATE INDEX IF NOT EXISTS idx_et_status ON evidence_tracking(extraction_status);
    CREATE INDEX IF NOT EXISTS idx_et_source ON evidence_tracking(source_table, source_id);
    """,
]


def main():
    engine = create_engine(DATABASE_URL)

    logger.info("开始初始化数据库...")

    with engine.begin() as conn:
        for i, sql in enumerate(MIGRATIONS):
            try:
                for statement in sql.strip().split(';'):
                    statement = statement.strip()
                    if statement:
                        conn.execute(text(statement))
                logger.info(f"迁移 {i+1:03d} 执行完成")
            except Exception as e:
                logger.warning(f"迁移 {i+1:03d} 跳过: {e}")

    # 验证表
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        tables = [r[0] for r in result.fetchall()]

    logger.info(f"数据库初始化完成，共 {len(tables)} 个表:")
    for t in tables:
        logger.info(f"  - {t}")


if __name__ == "__main__":
    main()
