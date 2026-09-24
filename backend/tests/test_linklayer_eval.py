"""Gold set schema 与评估器纯逻辑测试。"""

import json
import re
from pathlib import Path

GOLD_PATH = Path(__file__).parent.parent / "eval" / "gold_set_v1.json"

# 真实 evidence_id 格式：stable_evidence_id() 生成的 "EV:" + sha256（见 app/knowledge/evidence.py）
EVIDENCE_ID_RE = re.compile(r"^EV:[0-9a-f]{64}$")
# 待人工回填的占位符，如 "<真实evidence_id_1>"（无 live Mongo 环境下的骨架数据）
PLACEHOLDER_RE = re.compile(r"^<.+>$")


def _is_valid_evidence_id(evidence_id: str) -> bool:
    """格式校验（不查存在性）：真实 EV:<sha256> 或显式占位符。"""
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        return False
    return bool(EVIDENCE_ID_RE.match(evidence_id) or PLACEHOLDER_RE.match(evidence_id))


def test_gold_set_schema():
    data = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    assert len(data) >= 5, "gold set 至少 5 条起步"
    types_seen = set()
    for entry in data:
        # subject 是「主体」字段：cross_section/theme 类是跨主体查询，天然无单一主体
        for field in ("query_id", "type", "question", "expected_evidence_ids"):
            assert field in entry, f"缺少字段 {field}"
        if entry["type"] == "timeline":
            assert entry.get("subject"), "timeline 条目必须有 subject"
        assert entry["type"] in ("timeline", "cross_section", "theme")
        assert len(entry["expected_evidence_ids"]) > 0
        for evidence_id in entry["expected_evidence_ids"]:
            assert _is_valid_evidence_id(evidence_id), f"evidence_id 格式非法: {evidence_id}"
        for evidence_id in entry.get("hard_negative_evidence_ids", []):
            assert _is_valid_evidence_id(evidence_id), f"hard_negative 格式非法: {evidence_id}"
        types_seen.add(entry["type"])
    assert types_seen == {"timeline", "cross_section", "theme"}, "三类查询均须覆盖"
