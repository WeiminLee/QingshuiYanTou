"""
公开材料包生成器

按 ts_code 返回该股票的公开材料情报（Markdown 格式）
供推理决策层使用
"""
from datetime import date
from typing import Optional

from app.core.mongodb import get_mongo_db


# ── 互动易 Q&A ─────────────────────────────────────

async def fetch_qa(ts_code: str, limit: int = 50) -> list[dict]:
    """
    获取该股票清洗后的互动易 Q&A（按时间倒序）
    返回字段：question / answer / ann_date / signals
    """
    mongo_db = get_mongo_db()
    coll = mongo_db["qa_interactive"]
    cursor = coll.find({"ts_code": ts_code}).sort("ann_date", -1).limit(limit)
    return await cursor.to_list(length=limit)


def build_qa_section(qa_data: list[dict]) -> list[str]:
    """将 Q&A 数据渲染为 Markdown 列表"""
    lines = []
    if not qa_data:
        lines.append("暂无有效互动信息")
        return lines

    for item in qa_data:
        date_str = item.get("ann_date", "")
        signals = item.get("signals", [])
        signals_str = f"【{', '.join(signals)}】" if signals else ""
        q = item.get("question", "").strip()
        a = item.get("answer", "").strip()
        # 限制回答长度
        if len(a) > 300:
            a = a[:300] + "..."
        lines.append(f"**{date_str}** {signals_str}")
        lines.append(f"- Q：{q}")
        lines.append(f"- A：{a}")
        lines.append("")

    return lines


# ── 主函数 ────────────────────────────────────────

async def build_material_package(ts_code: str) -> str:
    """
    生成公开材料包（Markdown 格式）

    当前包含：
    - 互动易 Q&A（清洗后，近1年）

    后续扩展：
    - 公告摘要
    - 研报摘要
    """
    lines = []
    today_str = date.today().isoformat()

    lines.append(f"# 公开材料 - {ts_code}\n")
    lines.append(f"> 生成时间：{today_str}\n")

    # ── 互动易 Q&A ──────────────────────────────
    qa_data = await fetch_qa(ts_code, limit=50)

    lines.append("## 互动易 Q&A（清洗后，近1年）\n")
    for line in build_qa_section(qa_data):
        lines.append(line)

    if qa_data:
        # 取最早和最新日期
        dates = sorted({item.get("ann_date", "") for item in qa_data})
        lines.append(f"> 共 {len(qa_data)} 条有效互动（数据范围：{dates[0]} 至 {dates[-1]}）")
    lines.append("")

    return "\n".join(lines)
