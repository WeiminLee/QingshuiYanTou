"""Evidence builders for announcements (chapter-aggregated) and IRM (unchunked).

公告: 读取本地 PDF → 按章节分块 → 过滤非实质性章节 → 合并为一条 EvidenceInput
互动易: 每条 Q&A → 一个 EvidenceInput（不分块）
"""

from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime
from typing import Any, Literal

from app.knowledge.evidence import EvidenceInput, default_source_confidence
from app.knowledge.ingestion.chunker import SmartChunker
from app.knowledge.ingestion.pdf_parser import extract_text_from_pdf

logger = __import__("logging").getLogger(__name__)

# ── 公告章节过滤规则 ──────────────────────────────────────────────

# 噪音章节标题关键词 → 跳过
_SKIP_CHAPTER_KW = [
    "会计师事务所",
    "审计情况",
    "其他相关说明",
    "特此公告",
    "敬请",
    "广大投资者",
    "风险因素",
    "风险提示",
    "防范投资风险",
    "投资风险",
    "独立董事",
    "独立董事意见",
    "内部控制",
    "累计投票",
    "网络投票",
    "信息披露",
    "暂缓",
    "豁免",
    "募集资金",
    # 程序性/格式性章节
    "关联交易",
    "担保",
    "对外担保",
    "提供担保",
    "董事会决议",
    "监事会决议",
    "股东大会决议",
    "董事会",
    "监事会",
    "股东大会",
    "通知",
    "制度",
    "管理办法",
    "实施细则",
    "提示性公告",
    "股票停牌",
    "延期",
    "补充公告",
    "更正公告",
    "审计报告",
    "法律意见书",
    "保荐机构",
    "核查意见",
    "备查文件",
    "会议通知",
    "网络投票说明",
    "授权委托书",
    "回执",
    "附件",
    "释义",
    "定义",
]

# 实质性章节标题关键词 → 保留
_KEEP_CHAPTER_KW = [
    "业绩说明",
    "业绩变动",
    "业绩增长",
    "业绩下滑",
    "业绩亏损",
    "变动原因",
    "变动说明",
    "本次交易",
    "重组",
    "收购",
    "发行股份",
    "交易对方",
    "交易标的",
    "交易概述",
    "中标",
    "合同",
    "订单",
    "协议",
    "股权",
    "标的资产",
    "出资",
    "增资",
    "参股",
    "备考财务",
    "财务数据",
    "财务指标",
    "业务",
    "产品",
    "市场",
    "盈利",
    "营收",
    "营业收入",
    "营业成本",
    "收入",
    "研发",
    "投资者关系",
    # 新增实质性内容
    "经营情况",
    "主营业务",
    "核心竞争力",
    "研发投入",
    "产能",
    "项目进展",
    "中标项目",
    "合同签订",
    "战略合作",
    "对外投资",
    "分红",
    "利润分配",
    "股本变动",
    "股东人数",
    "前十大股东",
    "回购",
    "增持",
    "减持",
]

# 正文实质性关键词（用于 heading 无匹配时的 body override）
# 注意：关键词必须足够具体，避免"业绩预告"等通用词触发误保留
_RE_SUBSTANTIVE_KW = re.compile(
    r"发行股份|购买资产|募集配套资金|股权|收购|重组|"
    r"交易对方|标的资产|业绩下滑|业绩增长|业绩变动|业绩亏损|业绩驱动|"
    r"业务|产品|市场|收入|研发|"
    r"资产总额|资产净额|净利润|营业收入|营业成本"
)

# 始终保留的公告类型（这类公告内容精炼，不分章节噪音）
_ALWAYS_KEEP_ANN_TYPES = {"investment", "ma_activity", "research_survey"}


def _classify_announcement_chapter(
    heading: str,
    body: str,
    ann_type: str = "",
) -> Literal["keep", "skip"]:
    """判断公告章节是否值得进入 KG 抽取。

    优先级：
    1. research_survey/investment/ma_activity → 始终保留
    2. heading 匹配 SKIP_KEYWORD → skip（除非 body 含实质性关键词）
    3. heading 匹配 KEEP_KEYWORD → keep
    4. 默认 → 检查 body 是否含实质性关键词
    """
    if ann_type in _ALWAYS_KEEP_ANN_TYPES:
        return "keep"

    if heading:
        for kw in _SKIP_CHAPTER_KW:
            if kw in heading:
                if _RE_SUBSTANTIVE_KW.search(body):
                    return "keep"
                return "skip"

        for kw in _KEEP_CHAPTER_KW:
            if kw in heading:
                return "keep"

    if _RE_SUBSTANTIVE_KW.search(body):
        return "keep"
    return "skip"


def _utc_now() -> datetime:
    return datetime.now(UTC)


# 旧路径前缀 → 新路径前缀
PATH_PREFIX_MAP = {
    "/home/lwm/qingshui_data": "/run/media/lwm/0E27099B0E27099B/qingshui_data",
    "/Users/lwm/data/qingshui_data": "/Users/lwm/data/qingshui_data",
}


def _map_file_path(file_path: str | None) -> str | None:
    """将旧路径映射到新路径"""
    if not file_path:
        return None
    for old_prefix, new_prefix in PATH_PREFIX_MAP.items():
        if file_path.startswith(old_prefix):
            return file_path.replace(old_prefix, new_prefix)
    return file_path


def _file_exists(file_path: str | None) -> bool:
    """检查文件是否存在"""
    return bool(file_path and os.path.exists(file_path))


def _split_pdf_chapters(file_path: str) -> list[dict] | None:
    """解析本地 PDF 并按章节切分，返回分块列表"""
    try:
        # 使用 SmartChunker 进行智能分块
        chunker = SmartChunker(max_tokens=4096)
        text = extract_text_from_pdf(file_path)
        if not text.strip():
            return None

        chunks = chunker.chunk(text)

        return [
            {
                "heading": c.heading,
                "body": c.text,
                "tokens": c.tokens,
                "source": c.source,
            }
            for c in chunks
        ]
    except Exception as e:
        logger.warning(f"PDF 解析失败 [{file_path}]: {e}")
        return None


def build_announcement_evidence(
    record: dict[str, Any],
) -> list[EvidenceInput]:
    """从 announcements 记录构建 EvidenceInput 列表。

    同一份公告的所有实质性章节合并为一条 Evidence，让 LLM 能获取全文上下文。

    合并逻辑：
    1. 解析 PDF → 章节列表（SmartChunker）
    2. 逐章分类（keep/skip）
    3. 所有 keep 章节合并为一条 EvidenceInput
    4. 回退：无 PDF 时仅用 title 作为一条 Evidence

    Args:
        record: 数据库行（含 id, ann_date, ts_code, name, title, announcement_type, pdf_url, file_path 等）

    Returns:
        list[EvidenceInput]: 合并后的一条 EvidenceInput（或空列表）
    """
    ann_id = record.get("id") or ""
    title = (record.get("title") or "").strip()
    ts_code = (record.get("ts_code") or "").strip()
    ann_date_raw = record.get("ann_date")
    # Convert date/datetime to ISO string for MongoDB
    if ann_date_raw is None:
        ann_date = None
    elif isinstance(ann_date_raw, date):
        ann_date = ann_date_raw.isoformat()
    elif isinstance(ann_date_raw, datetime):
        ann_date = ann_date_raw.isoformat()
    else:
        ann_date = str(ann_date_raw) if ann_date_raw else None
    ann_type = (record.get("announcement_type") or "").strip()
    pdf_url = (record.get("pdf_url") or "").strip()
    company_name = (record.get("name") or "").strip()

    source_id = str(ann_id)

    # 映射本地 PDF 路径
    raw_path = record.get("file_path")
    local_pdf = _map_file_path(raw_path)
    has_local_pdf = _file_exists(local_pdf)

    # 解析章节
    chapters: list[dict] = []
    if has_local_pdf:
        chapters = _split_pdf_chapters(local_pdf) or []

    # 回退：PDF 不可用时只用 title（单条 evidence，无需聚合）
    if not chapters:
        return [
            EvidenceInput(
                source_type="announcement",
                source_name=f"公告:{ts_code}" if ts_code else "公告",
                source_id=source_id,
                text_excerpt=title,
                subject_hint={
                    "ts_code": ts_code,
                    "name": company_name,
                    "ann_type": ann_type,
                    "title": title,
                },
                publish_date=ann_date,
                observed_at=_utc_now(),
                source_ref={
                    "source_table": "announcements",
                    "ann_id": ann_id,
                    "ann_date": ann_date,
                    "local_pdf": local_pdf if has_local_pdf else None,
                    "pdf_url": pdf_url,
                    "is_aggregated": False,
                    "chapter_index": 0,
                },
                confidence=default_source_confidence("announcement"),
                metadata={"title": title, "has_pdf": has_local_pdf, "is_aggregated": False},
            )
        ]

    # 逐章分类，收集 keep 章节
    keep_chapters: list[dict] = []
    skip_count = 0
    for i, ch in enumerate(chapters):
        decision = _classify_announcement_chapter(
            heading=ch.get("heading", ""),
            body=ch.get("body", ""),
            ann_type=ann_type,
        )
        if decision == "skip":
            skip_count += 1
            continue
        keep_chapters.append({
            "index": i,
            "heading": ch.get("heading", ""),
            "body": ch.get("body", ""),
        })

    if not keep_chapters:
        return []

    # 每一章独立为一条 evidence（不合并），避免年报全文 22 万字塞进一条
    evidence_list: list[EvidenceInput] = []
    for ch in keep_chapters:
        heading = ch.get("heading", "")
        body = ch.get("body", "")
        chapter_text = f"## {heading}\n\n{body}" if heading else body
        evidence_list.append(
            EvidenceInput(
                source_type="announcement",
                source_name=f"公告:{ts_code}" if ts_code else "公告",
                source_id=f"{source_id}#ch{ch['index']}",
                text_excerpt=chapter_text,
                subject_hint={
                    "ts_code": ts_code,
                    "name": company_name,
                    "ann_type": ann_type,
                    "title": title,
                    "chapter": heading,
                },
                publish_date=ann_date,
                observed_at=_utc_now(),
                source_ref={
                    "source_table": "announcements",
                    "ann_id": ann_id,
                    "ann_date": ann_date,
                    "local_pdf": local_pdf if has_local_pdf else None,
                    "pdf_url": pdf_url,
                    "is_aggregated": False,
                    "chapter_index": ch["index"],
                    "chapter_heading": heading,
                    "total_chapters": len(chapters),
                },
                confidence=default_source_confidence("announcement"),
                metadata={
                    "title": title,
                    "has_pdf": has_local_pdf,
                    "is_aggregated": False,
                    "chapter": heading,
                    "chapter_index": ch["index"],
                    "total_chapters": len(chapters),
                },
            )
        )

    return evidence_list


