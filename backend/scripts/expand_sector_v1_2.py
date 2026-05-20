#!/usr/bin/env python
"""
expand_sector_v1_2.py — Phase 10: 半导体全产业链KG节点扩展

从云端 API → 下载 PDF → 解析文本 → KG实体抽取 → Neo4j入库。

Pipeline（3种运行模式）:
  --download-only   从云端下载 PDF，更新 document_registry
  --parse-only     解析已下载 PDF，更新 document_registry
  --execute        下载 → 解析 → KG写入（完整流水线）

防重机制（document_registry 驱动）:
  - 下载：SHA256 一致则跳过
  - 解析：parse_status == "success" 则跳过
  - KG写入：kg_written == True 则跳过

云端数据: http://124.221.188.38:8080/api/v1
"""
import argparse
import asyncio
import datetime
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)  # backend/

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CLOUD_API_URL = os.getenv("CLOUD_API_URL", "http://124.221.188.38:8080/api/v1")

SECTOR_SECTORS = ["IC设计", "晶圆制造", "封装测试", "设备", "材料", "终端应用"]

SEMICONDUCTOR_KEYWORDS = [
    "半导体", "芯片", "集成电路", "晶圆", "封装", "测试",
    "光刻", "刻蚀", "沉积", "CMP", "靶材", "前驱体",
    "硅片", "外延", "衬底", "代工", "IDM", "Fab",
    "功率半导体", "化合物半导体", "第三代半导体", "SiC", "GaN",
    "MCU", "CPU", "GPU", "AI芯片", "RISC-V",
]


def _keyword_filter(title: str, abstract: str = "") -> bool:
    text = (title + abstract).lower()
    return any(kw.lower() in text for kw in SEMICONDUCTOR_KEYWORDS)


# ---------------------------------------------------------------------------
# KG 写入阶段（从 parsed/{ann_id}.txt 读取）
# ---------------------------------------------------------------------------
def _load_parsed_text(ann_id: str) -> tuple[str, int]:
    """读取解析后的纯文本文件。"""
    from app.core.data.document_pipeline import parsed_path
    p = parsed_path(ann_id)
    if not p.exists():
        return "", 0
    text = p.read_text(encoding="utf-8")
    return text, len(text)


async def _extract_from_parsed(
    ann_id: str,
    sector: str,
) -> tuple[list[dict], list[dict]]:
    """从已解析文本文件抽取实体（复用 kg_extractor）。"""
    from app.knowledge.kg_extractor import extract_text_async

    text, text_len = _load_parsed_text(ann_id)
    if text_len < 100:
        return [], []

    try:
        result = await extract_text_async(
            text=text,
            ts_code="",
            source_name=ann_id,
            source_type="research_report",
            article_ref=ann_id,
        )
        entities = result.get("entities", [])
        for ent in entities:
            ent["sector"] = sector
            ent["confidence"] = ent.get("confidence", 0.8)
            ent["source_type"] = ent.get("source_type", "research_report")
            ent["source_name"] = "expand_sector"
            ent["source_file"] = ann_id
        relations = result.get("relations", [])
        return entities, relations
    except Exception as e:
        logger.debug("抽取失败 %s: %s", ann_id, e)
        return [], []


def _build_cooccurrence_relations(
    entities: list[dict],
    ann_id: str,
) -> list[dict]:
    """从实体列表生成同文档共现 RELATES 关系。"""
    relations = []
    company_entities = [e for e in entities if e.get("entity_type") == "Company"]
    product_entities = [e for e in entities if e.get("entity_type") == "Product"]

    for i, a in enumerate(company_entities):
        for b in company_entities[i + 1:]:
            if a["entity_id"] != b["entity_id"]:
                relations.append({
                    "from_entity": a["entity_id"],
                    "to_entity": b["entity_id"],
                    "text": f"{a.get('name','')}与{b.get('name','')}同篇文档关联",
                    "weight": 0.6,
                    "source_type": "research_report",
                    "source_name": "expand_sector",
                    "source_file": ann_id,
                })

    for c in company_entities:
        for p in product_entities:
            relations.append({
                "from_entity": c["entity_id"],
                "to_entity": p["entity_id"],
                "text": f"{c.get('name','')}涉及产品{p.get('name','')}",
                "weight": 0.7,
                "source_type": "research_report",
                "source_name": "expand_sector",
                "source_file": ann_id,
            })
    return relations


async def run_kg_write(
    dry_run: bool = False,
) -> None:
    """从 document_registry 查待 KG 写入的文档 → 抽取 → 入库。"""
    from app.core.data.document_registry import get_registry, ParseStatus

    registry = await get_registry()
    pending = await registry.get_pending_kg_writes(limit=500)
    pending_ids = [p["ann_id"] for p in pending]
    logger.info("待 KG 写入: %d 条", len(pending_ids))

    if not pending_ids:
        logger.info("没有待 KG 写入的文档，退出")
        return

    all_entities: list[dict] = []
    all_relations: list[dict] = []
    sector_counts: dict[str, int] = {s: 0 for s in SECTOR_SECTORS}
    processed = parse_fail = extract_fail = 0

    for i, ann_id in enumerate(pending_ids):
        sector = SECTOR_SECTORS[i % len(SECTOR_SECTORS)]

        if dry_run:
            logger.info("[DRY-RUN] kg_write %s (sector=%s)", ann_id, sector)
            processed += 1
            continue

        # 验证 parsed 文件存在
        from app.core.data.document_pipeline import parsed_path as _pp
        p = _pp(ann_id)
        if not p.exists():
            logger.warning("parsed file missing: %s", ann_id)
            parse_fail += 1
            continue

        entities, rels = await _extract_from_parsed(ann_id, sector)
        if not entities:
            logger.debug("no entities extracted: %s", ann_id)
            extract_fail += 1
            continue

        all_entities.extend(entities)
        all_relations.extend(rels)

        # 更新 sector count
        for ent in entities:
            s = ent.get("sector", sector)
            sector_counts[s] = sector_counts.get(s, 0) + 1

        # 标记 KG 已写入
        entity_ids = [e["entity_id"] for e in entities]
        await registry.upsert_kg_written(ann_id, entity_ids)
        processed += 1
        logger.info("KG写入 %s: %d entities", ann_id, len(entities))

    # 汇总写入 Neo4j
    if not dry_run and all_entities:
        from app.knowledge.entity_service import batch_upsert_entities_unwind
        result = batch_upsert_entities_unwind(all_entities)
        logger.info("实体写入: %s", result)

        if all_relations:
            from app.knowledge.relation_service import batch_upsert_relations_unwind
            result = batch_upsert_relations_unwind(all_relations)
            logger.info("关系写入: %s", result)

    company_count = sum(1 for e in all_entities if e.get("entity_type") == "Company")
    product_count = sum(1 for e in all_entities if e.get("entity_type") == "Product")

    # 尽力而为警告
    for sector in SECTOR_SECTORS:
        count = sector_counts.get(sector, 0)
        if count < 30:
            logger.warning(
                "环节 %s 节点数 %d < 30，数据不足（尽力而为规则）",
                sector, count,
            )

    # 写执行日志
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"logs/expand_semiconductor_{ts}.json"
    os.makedirs("logs", exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": ts,
                "sector": "semiconductor",
                "phase": "kg_write",
                "processed": processed,
                "parse_failed": parse_fail,
                "extract_failed": extract_fail,
                "total_entities": len(all_entities),
                "company_count": company_count,
                "product_count": product_count,
                "relation_count": len(all_relations),
                "sector_counts": sector_counts,
                "executed": not dry_run,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    logger.info("执行日志: %s", log_path)
    logger.info(
        "KG写入完成: processed=%d entities=%d relations=%d",
        processed, len(all_entities), len(all_relations),
    )


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="expand_sector_v1_2.py")
    parser.add_argument(
        "--download-only", action="store_true",
        help="只下载 PDF（调用 document_pipeline）",
    )
    parser.add_argument(
        "--parse-only", action="store_true",
        help="只解析已下载 PDF（调用 document_pipeline）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅打印配置，不连接 Neo4j 或调用 LLM",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="完整流水线：下载 → 解析 → KG写入",
    )
    args = parser.parse_args()

    run_download = args.download_only or args.execute
    run_parse = args.parse_only or args.execute
    run_kg = args.execute
    dry_run = args.dry_run

    if args.download_only and args.parse_only:
        logger.error("--download-only 和 --parse-only 不能同时指定")
        sys.exit(1)

    if not (run_download or run_parse or run_kg or dry_run):
        # 默认打印配置
        dry_run = True
        logger.info("[DRY-RUN] 半导体赛道扩展配置:")
        logger.info("  环节: %s", SECTOR_SECTORS)
        logger.info("  节点目标: 每环节 >= 30")
        logger.info("  云端URL: %s", CLOUD_API_URL)
        logger.info("  关键词数量: %d", len(SEMICONDUCTOR_KEYWORDS))
        return

    if dry_run:
        logger.info("[DRY-RUN] 半导体赛道扩展（dry-run 模式）")
        logger.info("  run_download=%s  run_parse=%s  run_kg=%s", run_download, run_parse, run_kg)

    # ---- 下载阶段 ----
    if run_download:
        from app.core.data.document_pipeline import main as pipeline_main
        # 复用 pipeline 的 run_download
        import asyncio as _asyncio

        sys.argv = [
            "document_pipeline",
            "download",
            "--data-type", "notice",
            "--sector",
            "--max-pages", "3",
            "--limit", "500",
        ]
        if dry_run:
            sys.argv.append("--dry-run")

        _asyncio.run(pipeline_main())
        logger.info("下载阶段完成")

    # ---- 解析阶段 ----
    if run_parse:
        import asyncio as _asyncio
        from app.core.data.document_pipeline import main as pipeline_main

        sys.argv = ["document_pipeline", "parse", "--limit", "500"]
        if dry_run:
            sys.argv.append("--dry-run")

        _asyncio.run(pipeline_main())
        logger.info("解析阶段完成")

    # ---- KG写入阶段 ----
    if run_kg and not dry_run:
        asyncio.run(run_kg_write(dry_run=False))
        logger.info("KG写入阶段完成（尽力而为）")
    elif run_kg and dry_run:
        logger.info("[DRY-RUN] KG写入阶段跳过")


if __name__ == "__main__":
    main()
