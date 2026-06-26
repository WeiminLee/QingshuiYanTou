"""
Layer 4 — 决策输出层

模块：
- report.py: AnalysisReport 结构 + JSON/Markdown 双轨导出
- compliance.py: 合规扫描 + 声明注入
- confidence.py: 置信度融合 + 降级
"""

from app.reasoning.output.compliance import (
    ComplianceResult,
    inject_compliance_declaration,
    log_report_audit,
    scan_content,
)
from app.reasoning.output.confidence import (
    SOURCE_TO_TIER,
    TIER_DESCRIPTIONS,
    downgrade_for_conflict,
    format_confidence_block,
    label_for_score,
    merge_confidence,
    source_type_to_tier,
)
from app.reasoning.output.report import (
    AnalysisReport,
    Catalyst,
    Conclusion,
    ConfidenceLevel,
    EvidenceRef,
    RiskItem,
    ScenarioProjection,
    TrackingIndicator,
    build_report_from_analysis,
)

__all__ = [
    # Report
    "AnalysisReport",
    "Conclusion",
    "EvidenceRef",
    "Catalyst",
    "RiskItem",
    "TrackingIndicator",
    "ScenarioProjection",
    "ConfidenceLevel",
    "build_report_from_analysis",
    # Compliance
    "scan_content",
    "inject_compliance_declaration",
    "log_report_audit",
    "ComplianceResult",
    # Confidence
    "source_type_to_tier",
    "merge_confidence",
    "downgrade_for_conflict",
    "format_confidence_block",
    "label_for_score",
    "TIER_DESCRIPTIONS",
    "SOURCE_TO_TIER",
]
