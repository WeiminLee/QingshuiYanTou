"""
Layer 4 — 合规检查模块

负责：
1. 输出内容合规扫描（禁止直接买卖信号/目标价/仓位建议）
2. 自动注入合规声明
3. 报告审计日志
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── 合规红线词 ──────────────────────────────────────

_FORBIDDEN_PATTERNS = [
    # 买卖信号
    (r"建议买入|建议卖出|建议建仓|建议清仓|建议减仓|建议加仓", "禁止买卖建议"),
    (r"强烈推荐买入|强烈建议|买[入入]?|卖出?|做多|做空", "禁止买卖信号"),
    # 目标价
    (r"目标价|目标价位|目标市值|第一目标|第二目标", "禁止目标价"),
    # 仓位
    (r"仓位建议|配置比例|持仓比例|建仓比例", "禁止仓位建议"),
    # 确定性
    (r"必然上涨|必然下跌|一定会涨|一定会跌|保证收益", "禁止确定性预测"),
    # 内幕
    (r"内幕消息|未公开|庄家|主力控盘", "禁止内幕相关"),
]

# ── 警告词（需要提示但不阻断） ───────────────────────

_WARNING_PATTERNS = [
    (r"可能上涨|可能下跌|有望|或将", "推测性措辞，正常"),
    (r"风险提示|风险警示|风险因素", "正常风险提示"),
    (r"不构成投资建议|仅供参考", "合规声明"),
]


class ComplianceResult:
    """合规扫描结果"""

    def __init__(
        self,
        passed: bool,
        violations: list[dict] | None = None,
        warnings: list[dict] | None = None,
        sanitized_content: Optional[str] = None,
    ):
        self.passed = passed
        self.violations = violations or []
        self.warnings = warnings or []
        self.sanitized_content = sanitized_content


def scan_content(content: str) -> ComplianceResult:
    """
    对报告内容进行合规扫描。

    返回：ComplianceResult
        - passed: 是否通过（无红线违规）
        - violations: 红线违规列表（需阻断或脱敏）
        - warnings: 警告词列表（仅提示）
        - sanitized_content: 脱敏后的内容
    """
    violations = []
    warnings = []
    sanitized = content

    for pattern, desc in _FORBIDDEN_PATTERNS:
        matches = re.finditer(pattern, sanitized)
        for match in matches:
            violations.append({
                "pattern": pattern,
                "matched": match.group(),
                "description": desc,
                "position": match.start(),
            })
            # 替换为安全词
            sanitized = sanitized[:match.start()] + "[已脱敏]" + sanitized[match.end():]

    for pattern, desc in _WARNING_PATTERNS:
        matches = re.finditer(pattern, sanitized)
        for match in matches:
            warnings.append({
                "pattern": pattern,
                "matched": match.group(),
                "description": desc,
                "position": match.start(),
            })

    passed = len(violations) == 0

    if violations:
        logger.warning(
            f"[Compliance] {len(violations)} violation(s) found, "
            f"{len(warnings)} warning(s)"
        )

    return ComplianceResult(
        passed=passed,
        violations=violations,
        warnings=warnings,
        sanitized_content=sanitized,
    )


def inject_compliance_declaration(content: str, report_id: str, timestamp: str) -> str:
    """
    在报告末尾注入合规声明。

    如果已有合规声明，跳过。
    """
    declaration = f"""

---

## 合规声明

⚠️ **郑重声明**：本报告由清水投研系统 AI 自动生成，仅供投资研究参考，**不构成任何投资建议**。

本报告内容基于公开信息与历史数据分析，不代表任何机构立场，不构成买卖证券的要约或邀请。投资者据此操作，风险自担。

📎 逻辑溯源：本报告支持溯源，可通过报告ID `{report_id}` 查询原始分析记录。

---
*清水投研系统 | 报告ID: {report_id} | {timestamp}*
"""
    if "不构成投资建议" in content:
        # 已声明，不重复注入
        return content
    return content + declaration


def log_report_audit(report_id: str, topic: str, ts_code: str, result: str) -> None:
    """
    报告审计日志（可扩展为写数据库/ES）。
    当前打印到日志。
    """
    logger.info(
        f"[Compliance] Report generated: id={report_id}, topic={topic!r}, "
        f"ts_code={ts_code!r}, chars={len(result)}"
    )
