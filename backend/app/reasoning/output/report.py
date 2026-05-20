"""
Layer 4 — 决策输出层

清水投研系统报告输出规范：

报告结构：
1. 核心逻辑链（3句话讲清为什么现在关注/有风险）
2. 关键数据支撑（产业数据 + 财务数据，带时间轴）
3. 催化剂日历（未来3-12个月关键节点）
4. 风险矩阵（技术/供应链/政策/估值/流动性）
5. 情景推演（简化版：Bull/Base/Bear 文字描述）
6. 置信度标注（TIER0-4）
7. 跟踪指标清单（明确的验证指标）
8. 合规声明（不构成投资建议，可溯源）

输出格式：JSON + Markdown 双轨
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Optional
from enum import Enum


class ConfidenceLevel(Enum):
    """置信度等级（对应 TIER0-4）"""
    TIER0_LEGAL = "TIER0_LEGAL"  # 法规文件，≥0.90
    TIER1_OFFICIAL = "TIER1_OFFICIAL"  # 监管背书，0.75-0.90
    TIER2_THIRD_PARTY = "TIER2_THIRD_PARTY"  # 第三方客观数据，0.65-0.85
    TIER3_SELF_DISCLOSED = "TIER3_SELF_DISCLOSED"  # 公司主动披露，0.50-0.75
    TIER4_ANALYSIS = "TIER4_ANALYSIS"  # 研究机构分析，0.40-0.70


@dataclass
class EvidenceRef:
    """证据引用"""
    source_type: str       # source_type 来源类型
    source_name: str      # 来源主体
    content: str          # 原文片段（截取关键句）
    timestamp: str        # 发布时间
    confidence: str      # 置信度 TIER0-4
    url: str = ""         # 原文链接（可选）


@dataclass
class Conclusion:
    """单条分析结论"""
    id: str                       # 结论编号
    statement: str                 # 结论内容
    confidence: str               # TIER0-4
    confidence_score: float        # 0.0-1.0 置信度分值
    evidence: list[EvidenceRef]  # 证据引用列表
    is_inference: bool            # 是否为推断（True = 推断，False = 事实）
    falsification: str = ""       # 反向证伪："什么情况下此结论不成立"


@dataclass
class Catalyst:
    """催化剂/关键节点"""
    event: str            # 事件描述
    expected_date: str    # 预期时间（YYYY-MM 或 YYYY-QX）
    importance: str        # high / medium / low
    source: str           # 信息来源


@dataclass
class RiskItem:
    """风险矩阵项"""
    category: str     # 技术迭代 / 供应链 / 政策 / 估值 / 流动性 / 竞争
    description: str  # 风险描述
    severity: str     # high / medium / low
    evidence: str = ""  # 证据（可选）


@dataclass
class TrackingIndicator:
    """跟踪指标"""
    indicator: str       # 指标名称
    description: str     # 关注什么
    threshold: str = ""  # 触发阈值（如有）


@dataclass
class ScenarioProjection:
    """情景推演（简化版）"""
    scenario: str     # Bull / Base / Bear
    description: str  # 情景描述
    assumption: str   # 关键假设
    outcome: str      # 对应结论/业绩影响


@dataclass
class AnalysisReport:
    """
    完整分析报告结构

    同时生成：
    - to_dict() → JSON 格式
    - to_markdown() → Markdown 格式
    """
    # ── 报告基本信息 ──────────────────────
    report_id: str
    topic: str                  # 分析主题（用户原始问题）
    ts_code: str = ""          # 股票代码（可选）
    company_name: str = ""      # 公司名称（可选）
    generated_at: str = ""      # 生成时间

    # ── 报告正文 ──────────────────────────
    core_logic: str = ""        # 核心逻辑链（3句话）

    conclusions: list[Conclusion] = field(default_factory=list)
    catalysts: list[Catalyst] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    scenarios: list[ScenarioProjection] = field(default_factory=list)
    tracking_indicators: list[TrackingIndicator] = field(default_factory=list)

    # ── 元信息 ────────────────────────────
    overall_confidence: str = "TIER3_ANALYSIS"  # 整体置信度
    overall_confidence_score: float = 0.60
    validity_period: str = ""   # 有效期（如 "下季度财报披露前"）
    update_trigger: str = ""    # 触发更新条件
    traceable: bool = True      # 是否可溯源

    # ── 合规 ─────────────────────────────
    compliance_declared: bool = False

    # ── 原始分析内容 ────────────────────
    raw_analysis: str = ""      # 原始 deliberation 输出
    graph_data: Optional[dict] = None  # 图谱可视化数据 {nodes, edges}

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.report_id:
            import uuid
            self.report_id = str(uuid.uuid4())[:8]
        # 计算整体置信度（从 conclusions 的 evidence 汇聚）
        if self.conclusions and not self.overall_confidence:
            try:
                from app.reasoning.output.confidence import merge_conclusion_confidence
                tier, score = merge_conclusion_confidence(self.conclusions)
                self.overall_confidence = tier
                self.overall_confidence_score = score
            except Exception:
                pass

    # ── JSON 导出 ─────────────────────────

    def to_dict(self) -> dict:
        """转换为 JSON 可序列化的字典"""
        return {
            "report_id": self.report_id,
            "topic": self.topic,
            "ts_code": self.ts_code,
            "company_name": self.company_name,
            "generated_at": self.generated_at,
            "core_logic": self.core_logic,
            "conclusions": [
                {
                    "id": c.id,
                    "statement": c.statement,
                    "confidence": c.confidence,
                    "confidence_score": c.confidence_score,
                    "is_inference": c.is_inference,
                    "falsification": c.falsification,
                    "evidence": [
                        {
                            "source_type": e.source_type,
                            "source_name": e.source_name,
                            "content": e.content,
                            "timestamp": e.timestamp,
                            "confidence": e.confidence,
                            "url": e.url,
                        }
                        for e in c.evidence
                    ],
                }
                for c in self.conclusions
            ],
            "catalysts": [
                {
                    "event": cat.event,
                    "expected_date": cat.expected_date,
                    "importance": cat.importance,
                    "source": cat.source,
                }
                for cat in self.catalysts
            ],
            "risks": [
                {
                    "category": r.category,
                    "description": r.description,
                    "severity": r.severity,
                    "evidence": r.evidence,
                }
                for r in self.risks
            ],
            "scenarios": [
                {
                    "scenario": s.scenario,
                    "description": s.description,
                    "assumption": s.assumption,
                    "outcome": s.outcome,
                }
                for s in self.scenarios
            ],
            "tracking_indicators": [
                {
                    "indicator": t.indicator,
                    "description": t.description,
                    "threshold": t.threshold,
                }
                for t in self.tracking_indicators
            ],
            "overall_confidence": self.overall_confidence,
            "overall_confidence_score": self.overall_confidence_score,
            "validity_period": self.validity_period,
            "update_trigger": self.update_trigger,
            "traceable": self.traceable,
            "compliance_declared": self.compliance_declared,
            "raw_analysis": self.raw_analysis,
            "graph_data": self.graph_data,
        }

    # ── Markdown 导出 ────────────────────

    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        lines = [
            f"# {self.topic}",
            "",
            f"**股票代码**：{self.ts_code or 'N/A'}",
            f"**公司名称**：{self.company_name or 'N/A'}",
            f"**生成时间**：{self.generated_at}",
            f"**报告ID**：{self.report_id}",
            "",
            "---",
            "",
        ]

        # 置信度标签
        conf_icon = self._confidence_icon(self.overall_confidence)
        conf_label = self._confidence_label(self.overall_confidence)
        lines.extend([
            f"## 整体置信度 {conf_icon}",
            f"**{conf_label}**（{self.overall_confidence_score:.0%}）",
            "",
        ])

        # 核心逻辑链
        if self.core_logic:
            lines.extend([
                "## 核心逻辑链",
                "",
                self.core_logic,
                "",
            ])

        # 降级渲染：所有结构化字段都为空时，直接输出 raw_analysis
        has_structured = bool(
            self.conclusions or self.catalysts or self.risks
            or self.scenarios or self.tracking_indicators or self.core_logic
        )
        if not has_structured and self.raw_analysis:
            lines.extend([
                "## 分析内容",
                "",
                self.raw_analysis,
                "",
            ])

        # 结论
        if self.conclusions:
            lines.extend(["## 分析结论", ""])
            for i, c in enumerate(self.conclusions, 1):
                conf_icon_c = self._confidence_icon(c.confidence)
                inf_tag = "【推断】" if c.is_inference else "【事实】"
                lines.append(f"{i}. {conf_icon_c} {inf_tag} {c.statement}")
                if c.evidence:
                    for e in c.evidence[:2]:
                        lines.append(f"   - 来源：{e.source_name}（{e.confidence}）{e.content[:80]}")
                if c.falsification:
                    lines.append(f"   ⚠️ 证伪条件：{c.falsification}")
            lines.append("")

        # 催化剂日历
        if self.catalysts:
            lines.extend(["## 催化剂日历", ""])
            lines.append("| 时间 | 事件 | 重要性 | 来源 |")
            lines.append("|------|------|--------|------|")
            for cat in self.catalysts:
                imp_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(cat.importance, "⚪")
                lines.append(f"| {cat.expected_date} | {cat.event} | {imp_emoji}{cat.importance} | {cat.source} |")
            lines.append("")

        # 风险矩阵
        if self.risks:
            lines.extend(["## 风险矩阵", ""])
            for r in self.risks:
                sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(r.severity, "⚪")
                lines.append(f"- {sev_icon}[{r.severity.upper()}] **{r.category}**：{r.description}")
            lines.append("")

        # 情景推演
        if self.scenarios:
            lines.extend(["## 情景推演", ""])
            for s in self.scenarios:
                icon = {"Bull": "📈", "Bear": "📉", "Base": "➡️"}.get(s.scenario, "⚪")
                lines.append(f"### {icon} {s.scenario} 情景")
                lines.append(f"**假设**：{s.assumption}")
                lines.append(f"**结论**：{s.outcome}")
                if s.description:
                    lines.append(f"**描述**：{s.description}")
                lines.append("")

        # 跟踪指标
        if self.tracking_indicators:
            lines.extend(["## 跟踪指标", ""])
            for t in self.tracking_indicators:
                lines.append(f"- **{t.indicator}**：{t.description}")
                if t.threshold:
                    lines.append(f"  触发阈值：{t.threshold}")
            lines.append("")

        # 有效期
        if self.validity_period:
            lines.extend(["## 有效期", "", f"本报告有效期至：{self.validity_period}", ""])
        if self.update_trigger:
            lines.extend(["## 触发更新条件", "", f"以下情况请重新分析：{self.update_trigger}", ""])

        # 合规声明
        lines.extend(self._compliance_section())

        return "\n".join(lines)

    # ── 辅助方法 ─────────────────────────

    @staticmethod
    def _confidence_icon(tier: str) -> str:
        icons = {
            "TIER0_LEGAL": "🟢",
            "TIER1_OFFICIAL": "🟢",
            "TIER2_THIRD_PARTY": "🟡",
            "TIER3_SELF_DISCLOSED": "🟡",
            "TIER4_ANALYSIS": "🔴",
        }
        return icons.get(tier, "⚪")

    @staticmethod
    def _confidence_label(tier: str) -> str:
        labels = {
            "TIER0_LEGAL": "高置信度（法规文件）",
            "TIER1_OFFICIAL": "高置信度（监管背书）",
            "TIER2_THIRD_PARTY": "中置信度（第三方数据）",
            "TIER3_SELF_DISCLOSED": "中置信度（公司自披露）",
            "TIER4_ANALYSIS": "低置信度（研究分析）",
        }
        return labels.get(tier, "未知置信度")

    def _compliance_section(self) -> list[str]:
        return [
            "---",
            "## 合规声明",
            "",
            "⚠️ **郑重声明**：本报告仅供投资研究参考，**不构成任何投资建议**。",
            "",
            "本报告由清水投研系统 AI 自动生成，结论基于公开信息与历史数据，",
            "不代表任何机构立场，不构成买卖证券的要约或邀请。",
            "",
            "投资者据此操作，风险自担。",
            "",
            f"📎 逻辑溯源：本报告支持溯源，可通过报告ID `{self.report_id}` 查询原始分析记录。",
            "",
            "---",
            f"*清水投研系统 | 报告ID: {self.report_id} | {self.generated_at}*",
        ]


# ── 工厂函数 ──────────────────────────────────────

def build_report_from_analysis(
    topic: str,
    raw_analysis: str,
    ts_code: str = "",
    company_name: str = "",
    overall_confidence: str = "TIER3_ANALYSIS",
    **kwargs,
) -> AnalysisReport:
    """
    从原始 deliberation 输出构建结构化报告。

    后续由 LLM 调用解析 raw_analysis 填充各字段。
    """
    return AnalysisReport(
        report_id="",
        topic=topic,
        ts_code=ts_code,
        company_name=company_name,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        overall_confidence=overall_confidence,
        raw_analysis=raw_analysis,
        compliance_declared=False,
        **kwargs,
    )
