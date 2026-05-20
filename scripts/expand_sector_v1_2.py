#!/usr/bin/env python3
"""
expand_sector_v1_2.py — 新赛道扩展脚手架

Phase 9 产出，支持以下赛道：
  - semiconductor

用法：
  python scripts/expand_sector_v1_2.py --sector semiconductor --dry-run
  python scripts/expand_sector_v1_2.py --sector semiconductor --execute

--dry-run 模式：
  - 仅打印统计（实体数/关系数/来源文件列表）
  - 不写数据库，不调用 LLM

--execute 模式：
  - 运行 pipeline（数据采集 → KG 抽取 → UNWIND 写入 Neo4j）
  - 写 JSON 执行日志到 logs/expand_{sector}_{timestamp}.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 将 backend 加入 Python 路径（脚本位于项目根 scripts/）
ROOT = Path(__file__).resolve().parent.parent
BACKEND_SRC = ROOT / "backend"
sys.path.insert(0, str(BACKEND_SRC))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("expand_sector")

# 已知赛道列表（Phase 9 仅支持 semiconductor）
KNOWN_SECTORS = ["semiconductor"]

# 各赛道数据源目录（硬编码）
SECTOR_DATA_DIRS: dict[str, list[str]] = {
    "semiconductor": [
        str(ROOT / "data" / "sector" / "semiconductor"),
    ],
}


def _collect_source_files(sector: str) -> list[dict]:
    """扫描赛道数据目录，返回待处理文件列表。"""
    files = []
    base_dirs = SECTOR_DATA_DIRS.get(sector, [])
    for base_dir in base_dirs:
        if not os.path.isdir(base_dir):
            continue
        for root, _, filenames in os.walk(base_dir):
            for fn in filenames:
                if fn.endswith((".pdf", ".docx", ".txt", ".md", ".csv")):
                    fp = os.path.join(root, fn)
                    files.append({
                        "path": fp,
                        "filename": fn,
                        "size_bytes": os.path.getsize(fp),
                    })
    return files


def _estimate_entities_relations(source_files: list[dict]) -> tuple[int, int]:
    """
    基于来源文件估算实体数和关系数（dry-run 统计用）。
    估算逻辑（硬编码规则）：
    - semiconductor 每份文档约 15 个实体 / 25 条关系
    """
    n = len(source_files)
    return n * 15, n * 25


def dry_run(sector: str) -> dict:
    """Dry-run 模式：只打印统计，不写 DB，不调 LLM。"""
    source_files = _collect_source_files(sector)
    entity_count, relation_count = _estimate_entities_relations(source_files)

    print(f"\n{'='*60}")
    print(f"expand_sector_v1_2.py — DRY RUN (sector={sector})")
    print(f"{'='*60}")
    print(f"  实体数（估算）   : {entity_count}")
    print(f"  关系数（估算）   : {relation_count}")
    print(f"  来源文件数       : {len(source_files)}")
    if source_files:
        print(f"  前 5 个文件:")
        for f in source_files[:5]:
            print(f"    {f['filename']} ({f['size_bytes']} bytes)")
        if len(source_files) > 5:
            print(f"    ... 还有 {len(source_files) - 5} 个文件")
    print(f"\n  [DRY-RUN] 不写入数据库，不调用 LLM\n")

    return {
        "entity_count": entity_count,
        "relation_count": relation_count,
        "source_files": source_files,
    }


def execute(sector: str) -> dict:
    """Execute 模式：运行 pipeline，写入 Neo4j，写 JSON 日志。"""
    from app.knowledge.entity_service import batch_upsert_entities_unwind
    from app.knowledge.relation_service import batch_upsert_relations_unwind

    result = {
        "timestamp": datetime.now().isoformat(),
        "sector": sector,
        "inserted_entities": 0,
        "updated_entities": 0,
        "failed_entities": 0,
        "inserted_relations": 0,
        "updated_relations": 0,
        "failed_relations": 0,
        "errors": [],
    }

    logger.info("开始执行赛道扩展: sector=%s", sector)

    try:
        source_files = _collect_source_files(sector)
        logger.info("找到 %d 个来源文件", len(source_files))

        # Phase 9 placeholder：生成模拟数据演示 pipeline
        entities, relations = _mock_extraction(sector, source_files)

        ent_result = batch_upsert_entities_unwind(entities)
        result["updated_entities"] = ent_result.get("updated", 0)
        result["failed_entities"] = ent_result.get("failed", 0)
        logger.info("实体写入完成: updated=%d failed=%d elapsed=%.2fs",
                    ent_result.get("updated", 0), ent_result.get("failed", 0),
                    ent_result.get("elapsed_seconds", 0))

        rel_result = batch_upsert_relations_unwind(relations)
        result["updated_relations"] = rel_result.get("updated", 0)
        result["failed_relations"] = rel_result.get("failed", 0)
        logger.info("关系写入完成: updated=%d failed=%d elapsed=%.2fs",
                    rel_result.get("updated", 0), rel_result.get("failed", 0),
                    rel_result.get("elapsed_seconds", 0))

    except Exception as exc:
        logger.exception("执行失败: %s", exc)
        result["errors"].append(str(exc))

    # 写 JSON 日志
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"expand_{sector}_{timestamp_str}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("JSON 日志已写入: %s", log_path)
    print(f"\n[EXECUTE] 日志已写入: {log_path}")

    return result


def _mock_extraction(sector: str, source_files: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Phase 9 placeholder：生成模拟实体和关系数据。
    Phase 10 会替换为真正的 LLM 抽取逻辑。
    """
    entities = []
    relations = []

    if sector == "semiconductor":
        companies = [
            ("C:688981.SH", "中芯国际", "688981.SH"),
            ("C:688012.SH", "中微公司", "688012.SH"),
            ("C:002371.SZ", "北方华创", "002371.SZ"),
            ("C:688396.SH", "华润微", "688396.SH"),
            ("C:688008.SH", "澜起科技", "688008.SH"),
        ]
        for entity_id, name, ts_code in companies:
            entities.append({
                "entity_id": entity_id,
                "entity_type": "Company",
                "name": name,
                "ts_code": ts_code,
                "confidence": 0.90,
                "source_type": "sector_research",
                "source_name": f"semiconductor_research_{datetime.now().year}",
            })

        products = [
            ("P:A3F2B8C1D4E5F6A0", "12寸晶圆"),
            ("P:A3F2B8C1D4E5F6A1", "EUV光刻胶"),
            ("P:A3F2B8C1D4E5F6A2", "刻蚀设备"),
            ("P:A3F2B8C1D4E5F6A3", "沉积设备"),
            ("P:A3F2B8C1D4E5F6A4", "清洗设备"),
        ]
        for entity_id, name in products:
            entities.append({
                "entity_id": entity_id,
                "entity_type": "Product",
                "name": name,
                "confidence": 0.85,
                "source_type": "sector_research",
                "source_name": f"semiconductor_research_{datetime.now().year}",
            })

        for i, (comp_id, _, _) in enumerate(companies):
            prod_id = products[i % len(products)][0]
            prod_name = products[i % len(products)][1]
            relations.append({
                "from_entity": comp_id,
                "to_entity": prod_id,
                "text": f"该公司生产{prod_name}",
                "weight": 1.0,
                "direction": "positive",
                "source_type": "sector_research",
                "source_name": f"semiconductor_research_{datetime.now().year}",
            })

    logger.info("模拟 KG 抽取: %d 个实体, %d 条关系", len(entities), len(relations))
    return entities, relations


def main() -> None:
    parser = argparse.ArgumentParser(
        description="expand_sector_v1_2.py — 新赛道扩展脚手架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python scripts/expand_sector_v1_2.py --sector semiconductor --dry-run
  python scripts/expand_sector_v1_2.py --sector semiconductor --execute
        """,
    )
    parser.add_argument(
        "--sector",
        required=True,
        choices=KNOWN_SECTORS,
        help=f"赛道名称（Phase 9 支持: {KNOWN_SECTORS}）",
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印统计信息，不写 DB，不调用 LLM",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="执行完整 pipeline 并写入 Neo4j",
    )

    args = parser.parse_args()

    if args.dry_run:
        dry_run(args.sector)
    elif args.execute:
        result = execute(args.sector)
        print(f"\n执行完成: inserted_entities={result['inserted_entities']}, "
              f"updated_entities={result['updated_entities']}, "
              f"failed_entities={result['failed_entities']}")


if __name__ == "__main__":
    main()
