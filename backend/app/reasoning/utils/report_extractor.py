"""
报告内容提取工具

从 AI 生成的报告内容中提取：
- 参考文献引用
- 股票ID信息
"""

import re
from typing import Any


def extract_references(report_content: str) -> dict[str, dict[str, Any]]:
    """
    从报告内容中提取参考文献信息

    支持格式：
    - [^1]: 标题 - 来源
    - [^1]: 标题

    Args:
        report_content: Markdown 格式的报告内容

    Returns:
        Dict[str, Dict]: {ref_id: {title, source, url}}
    """
    references = {}

    # 匹配引用定义 [^N]: 标题 - 来源
    pattern = r"\[\^(\d+)\]:\s*(.+?)(?:\s*-\s*(.+))?$"
    matches = re.findall(pattern, report_content, re.MULTILINE)

    for match in matches:
        ref_id, title, source = match
        references[ref_id] = {
            "title": title.strip(),
            "source": source.strip() if source else "未知来源",
            "url": None,  # 可从知识图谱获取
        }

    return references


def extract_stock_ids(report_content: str) -> dict[str, dict[str, Any]]:
    """
    从报告内容中提取股票ID

    支持格式：
    - 600519.SH (上交所)
    - 000001.SZ (深交所)

    Args:
        report_content: Markdown 格式的报告内容

    Returns:
        Dict[str, Dict]: {stock_id: {name, price, change, kline_url}}
    """
    stock_info = {}

    # 匹配股票ID (6位数字 + .SH/.SZ)
    pattern = r"(\d{6}\.(?:SH|SZ))"
    stock_ids = set(re.findall(pattern, report_content))

    for stock_id in stock_ids:
        # 占位数据，实际应从 API 获取
        stock_info[stock_id] = {
            "name": stock_id,  # 应替换为实际股票名称
            "price": 0,
            "change": 0,
            "kline_url": f"/api/v1/stock/kline/{stock_id}",
        }

    return stock_info


def get_report_metadata(report_content: str) -> dict[str, Any]:
    """
    获取报告的元数据（引用 + 股票ID）

    Args:
        report_content: Markdown 格式的报告内容

    Returns:
        Dict: {references, stock_info, timestamp}
    """
    from datetime import datetime

    return {
        "references": extract_references(report_content),
        "stock_info": extract_stock_ids(report_content),
        "timestamp": datetime.now().isoformat(),
    }
