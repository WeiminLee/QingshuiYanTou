"""
使用新 EXTRACTION_PROMPT 对 evidence 采样数据测试抽取质量。

用法:
  uv run --directory backend python scripts/test_new_prompt.py
  uv run --directory backend python scripts/test_new_prompt.py --n 5 --model qwen3:8b
  uv run --directory backend python scripts/test_new_prompt.py --source-type irm --n 3
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 清除代理环境变量（访问 localhost 时不需要）
for _k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from app.knowledge.extraction.rag_prompts import EXTRACTION_PROMPT

# 复用 JSON 解析器
from app.knowledge.extraction.rag_extractor import (
    _parse_json_output,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────────────────────────

load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"),
    verbose=False,
)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017/qingshui")
DEFAULT_MODEL = "qwen3:8b"


# ── Ollama 调用 ────────────────────────────────────────────────────────────────


async def call_ollama(prompt: str, model: str, timeout: int = 120) -> dict:
    """调用 Ollama API，返回 {text, tokens, duration_ms}"""
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 4096},
            },
        )
        resp.raise_for_status()
        data = resp.json()
    elapsed = (time.monotonic() - t0) * 1000
    return {
        "text": data.get("response", ""),
        "tokens": data.get("eval_count", 0),
        "duration_ms": elapsed,
    }


# ── 解析 ──────────────────────────────────────────────────────────────────────


def parse_output(raw_text: str) -> dict:
    """解析 LLM 输出，复用 rag_extractor 的 JSON 解析器。"""
    if raw_text.strip().startswith("NO_EXTRACTABLE"):
        reason = raw_text.strip().split(":", 1)[-1].strip() if ":" in raw_text else ""
        return {"entities": [], "relations": [], "metrics": [], "skipped": True, "reason": reason}

    result = _parse_json_output(raw_text)
    if result is None:
        return {"entities": [], "relations": [], "metrics": [], "skipped": True, "reason": "parse_failed"}

    entities_raw, relations_raw = result

    entities = []
    for e in entities_raw:
        entities.append({
            "name": e["entity_name"],
            "type": e.get("entity_type", ""),
            "description": e.get("description", ""),
            "source": e.get("source_id", ""),
        })

    relations = []
    for r in relations_raw:
        relations.append({
            "source": r["src_id"],
            "relation": r.get("description", ""),
            "target": r["tgt_id"],
            "weight": r.get("weight", 1.0),
            "stmt_type": r.get("stmt_type", "Fact"),
            "source_ref": r.get("source_ids", [""])[0] if r.get("source_ids") else "",
        })

    # 从 entities 中提取 metric 信息
    metrics = [e.get("metric", {}) for e in entities_raw if e.get("metric")]

    return {
        "entities": entities,
        "relations": relations,
        "metrics": metrics,
        "skipped": False,
        "reason": "",
    }


# ── 质量评估 ──────────────────────────────────────────────────────────────────


def evaluate_quality(parsed: dict, raw_text: str, evidence_text: str) -> dict:
    """简单的质量评估指标。"""
    entities = parsed.get("entities", [])
    relations = parsed.get("relations", [])
    metrics = parsed.get("metrics", [])

    issues = []

    # 1. 实体数量检查
    if len(entities) == 0 and not parsed.get("skipped"):
        issues.append("未抽取到任何实体")

    # 2. 实体类型检查
    invalid_types = [e for e in entities if e["type"] not in ("Company", "Product", "Metric")]
    if invalid_types:
        issues.append(f"包含无效实体类型: {invalid_types}")

    # 3. 关系完整性检查
    entity_names = {e["name"] for e in entities}
    for rel in relations:
        if rel["source"] not in entity_names:
            issues.append(f"关系 source='{rel['source']}' 不在实体列表中")
        if rel["target"] not in entity_names:
            issues.append(f"关系 target='{rel['target']}' 不在实体列表中")

    # 4. 关系必须有陈述类型
    missing_stmt = [r for r in relations if not r.get("stmt_type")]
    if missing_stmt:
        issues.append(f"{len(missing_stmt)} 条关系缺少陈述类型")

    # 5. Metric 必须有 period
    missing_period = [m for m in metrics if not m.get("period")]
    if missing_period:
        issues.append(f"{len(missing_period)} 条 Metric 缺少 period")

    # 6. 幻觉检测：随机抽取实体，检查是否在原文中出现
    hallucinations = []
    for e in entities:
        name = e["name"]
        if len(name) >= 3 and name not in evidence_text:
            # 模糊匹配：检查至少 50% 的字符在原文中
            chars_in_text = sum(1 for c in name if c in evidence_text)
            if chars_in_text < len(name) * 0.5:
                hallucinations.append(name)
    if hallucinations:
        issues.append(f"疑似幻觉实体（不在原文中）: {hallucinations}")

    # 质量评分
    score = 100
    if parsed.get("skipped"):
        score = 0  # NO_EXTRACTABLE 单独标记
    else:
        if len(entities) == 0:
            score -= 30
        if invalid_types:
            score -= len(invalid_types) * 10
        if missing_stmt:
            score -= len(missing_stmt) * 5
        if missing_period:
            score -= len(missing_period) * 5
        if hallucinations:
            score -= len(hallucinations) * 10

    return {
        "score": max(0, score),
        "issues": issues,
        "entity_count": len(entities),
        "relation_count": len(relations),
        "metric_count": len(metrics),
        "company_count": sum(1 for e in entities if e["type"] == "Company"),
        "product_count": sum(1 for e in entities if e["type"] == "Product"),
        "metric_entity_count": sum(1 for e in entities if e["type"] == "Metric"),
        "stmt_distribution": {
            "Fact": sum(1 for r in relations if r.get("stmt_type") == "Fact"),
            "Claim": sum(1 for r in relations if r.get("stmt_type") == "Claim"),
            "Estimate": sum(1 for r in relations if r.get("stmt_type") == "Estimate"),
        },
    }


# ── 主流程 ────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="测试新 EXTRACTION_PROMPT 抽取质量")
    parser.add_argument("--n", type=int, default=5, help="采样数量（默认 5）")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"Ollama 模型名（默认 {DEFAULT_MODEL}）")
    parser.add_argument("--source-type", type=str, default=None, help="按 source_type 过滤（如 irm, announcement）")
    parser.add_argument("--output", type=str, default=None, help="结果输出 JSON 文件路径")
    parser.add_argument("--raw", action="store_true", help="打印 LLM 原始输出")
    args = parser.parse_args()

    # ── 1. 连接 MongoDB，采样 evidence ──────────────────────────────────────────
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client.get_default_database()

    query = {"text_excerpt": {"$exists": True, "$ne": ""}}
    if args.source_type:
        query["source_type"] = args.source_type

    # 随机采样
    pipeline = [
        {"$match": query},
        {"$sample": {"size": args.n}},
    ]
    cursor = db.kg_evidence.aggregate(pipeline)
    samples = await cursor.to_list(length=args.n)

    logger.info(
        "采样 %d 条 evidence（source_type=%s），模型: %s",
        len(samples),
        args.source_type or "all",
        args.model,
    )

    if not samples:
        logger.error("未采样到数据，请检查 MongoDB 连接和 kg_evidence 集合")
        return

    # ── 2. 逐条测试 ────────────────────────────────────────────────────────────
    results = []
    total_tokens = 0
    total_duration = 0

    for i, doc in enumerate(samples):
        evidence_id = doc.get("evidence_id", "unknown")
        source_type = doc.get("source_type", "unknown")
        source_name = doc.get("source_name", "")
        text_excerpt = doc.get("text_excerpt", "")
        ts_code = doc.get("subject_hint", {}).get("ts_code", "") if doc.get("subject_hint") else ""

        text_preview = text_excerpt[:100].replace("\n", " ")
        logger.info("─" * 60)
        logger.info("[%d/%d] %s | %s | %s", i + 1, len(samples), evidence_id, source_type, source_name[:40])
        logger.info("  文本预览: %s...", text_preview)

        # 构建 prompt
        prompt = EXTRACTION_PROMPT.format(input_text=text_excerpt)

        # 调用 Ollama
        try:
            llm_result = await call_ollama(prompt, args.model)
        except Exception as e:
            logger.error("  LLM 调用失败: %s", e)
            results.append(
                {
                    "evidence_id": evidence_id,
                    "source_type": source_type,
                    "source_name": source_name,
                    "ts_code": ts_code,
                    "text_preview": text_preview,
                    "error": str(e),
                }
            )
            continue

        raw_output = llm_result["text"]
        tokens = llm_result["tokens"]
        duration = llm_result["duration_ms"]
        total_tokens += tokens
        total_duration += duration

        logger.info("  LLM 输出: %d tokens, %.1fs", tokens, duration / 1000)

        if args.raw:
            print(f"\n{'='*60}")
            print(f"RAW OUTPUT [{evidence_id}]:")
            print(raw_output)
            print(f"{'='*60}\n")

        # 解析
        parsed = parse_output(raw_output)

        # 评估
        quality = evaluate_quality(parsed, raw_output, text_excerpt)

        logger.info(
            "  实体: %d (Company=%d, Product=%d, Metric=%d) | 关系: %d | Metric: %d | 评分: %d/100",
            quality["entity_count"],
            quality["company_count"],
            quality["product_count"],
            quality["metric_entity_count"],
            quality["relation_count"],
            quality["metric_count"],
            quality["score"],
        )
        logger.info(
            "  陈述类型: Fact=%d, Claim=%d, Estimate=%d",
            quality["stmt_distribution"]["Fact"],
            quality["stmt_distribution"]["Claim"],
            quality["stmt_distribution"]["Estimate"],
        )

        if quality["issues"]:
            for issue in quality["issues"]:
                logger.warning("  ⚠ %s", issue)

        results.append(
            {
                "evidence_id": evidence_id,
                "source_type": source_type,
                "source_name": source_name,
                "ts_code": ts_code,
                "text_preview": text_preview,
                "text_length": len(text_excerpt),
                "tokens": tokens,
                "duration_ms": duration,
                "raw_output": raw_output if args.raw else raw_output[:500],
                "parsed": parsed,
                "quality": quality,
            }
        )

    # ── 3. 汇总 ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("📊 测试汇总")
    print("=" * 60)

    scores = [r["quality"]["score"] for r in results if "quality" in r]
    entities = [r["quality"]["entity_count"] for r in results if "quality" in r]
    relations = [r["quality"]["relation_count"] for r in results if "quality" in r]
    metrics = [r["quality"]["metric_count"] for r in results if "quality" in r]
    skipped = sum(1 for r in results if "parsed" in r and r["parsed"].get("skipped"))

    print(f"  样本数:        {len(results)}")
    print(f"  NO_EXTRACTABLE: {skipped}")
    print(f"  平均评分:      {sum(scores) / len(scores):.0f}/100" if scores else "N/A")
    print(f"  平均实体数:    {sum(entities) / len(entities):.1f}" if entities else "N/A")
    print(f"  平均关系数:    {sum(relations) / len(relations):.1f}" if relations else "N/A")
    print(f"  平均 Metric 数: {sum(metrics) / len(metrics):.1f}" if metrics else "N/A")
    print(f"  总 tokens:     {total_tokens}")
    print(f"  总耗时:        {total_duration / 1000:.1f}s")
    if total_tokens:
        print(f"  平均 token/s:  {total_tokens / (total_duration / 1000):.0f}")

    # 按 source_type 分组的统计
    by_source = {}
    for r in results:
        if "quality" not in r:
            continue
        st = r["source_type"]
        if st not in by_source:
            by_source[st] = {"count": 0, "scores": [], "entities": []}
        by_source[st]["count"] += 1
        by_source[st]["scores"].append(r["quality"]["score"])
        by_source[st]["entities"].append(r["quality"]["entity_count"])

    if by_source:
        print("\n  按 source_type 分组:")
        for st, stats in sorted(by_source.items()):
            avg_score = sum(stats["scores"]) / len(stats["scores"])
            avg_ent = sum(stats["entities"]) / len(stats["entities"])
            print(f"    {st}: {stats['count']}条, 均分 {avg_score:.0f}, 均实体 {avg_ent:.1f}")

    # 幻觉统计
    all_hallucinations = []
    for r in results:
        if "quality" in r:
            for issue in r["quality"]["issues"]:
                if "幻觉" in issue:
                    all_hallucinations.append(issue)
    if all_hallucinations:
        print(f"\n  ⚠ 幻觉检测: {len(all_hallucinations)} 条存在疑似幻觉")

    # ── 4. 保存结果 ────────────────────────────────────────────────────────────
    output_path = args.output
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"test_prompt_results_{timestamp}.json"

    # 清理 raw_output 避免 JSON 过大
    for r in results:
        if "raw_output" in r and not args.raw:
            r["raw_output"] = r["raw_output"][:500]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {
                    "model": args.model,
                    "n": args.n,
                    "source_type": args.source_type,
                    "timestamp": datetime.now().isoformat(),
                },
                "summary": {
                    "total": len(results),
                    "skipped": skipped,
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "avg_entities": sum(entities) / len(entities) if entities else 0,
                    "avg_relations": sum(relations) / len(relations) if relations else 0,
                    "avg_metrics": sum(metrics) / len(metrics) if metrics else 0,
                    "total_tokens": total_tokens,
                    "total_duration_ms": total_duration,
                },
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\n📄 详细结果已保存至: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())