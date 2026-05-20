"""
端到端测试：POST /api/v1/kg/feedback

依赖：后端服务运行在 http://localhost:8000
Mark: @pytest.mark.integration — skipped in regular test runs.
"""
import logging
import pytest
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"


@pytest.mark.integration
def test_feedback_confirm():
    """confirm 类型：轻微提升 weight (+0.05)"""
    payload = {
        "relation_id": "R:C:600519.SH|P:chip_A|2026-04-21",
        "type": "confirm",
    }
    resp = requests.post(f"{BASE_URL}/api/v1/kg/feedback", json=payload, timeout=10)
    logger.info("test_feedback_confirm status=%d body=%s", resp.status_code, resp.text)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "previous_weight" in data, f"Missing previous_weight: {data}"
    assert "corrected_weight" in data, f"Missing corrected_weight: {data}"
    assert "feedback_id" in data, f"Missing feedback_id: {data}"
    print("PASS: test_feedback_confirm")


@pytest.mark.integration
def test_feedback_reject():
    """reject 类型：降低 weight (-0.15)"""
    payload = {
        "relation_id": "R:C:600519.SH|P:chip_A|2026-04-21",
        "type": "reject",
    }
    resp = requests.post(f"{BASE_URL}/api/v1/kg/feedback", json=payload, timeout=10)
    logger.info("test_feedback_reject status=%d body=%s", resp.status_code, resp.text)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    # reject 应该让 corrected_weight < previous_weight
    assert data["corrected_weight"] < data["previous_weight"], (
        f"Expected corrected_weight < previous_weight, got "
        f"prev={data['previous_weight']}, new={data['corrected_weight']}"
    )
    print("PASS: test_feedback_reject")


@pytest.mark.integration
def test_feedback_correct():
    """correct 类型：高置信关系（>=0.85）设置 corrected_weight=0.30 时，DECAY_FLOOR 保护触发"""
    payload = {
        "relation_id": "R:C:600519.SH|P:chip_A|2026-04-21",
        "type": "correct",
        "corrected_weight": 0.30,
    }
    resp = requests.post(f"{BASE_URL}/api/v1/kg/feedback", json=payload, timeout=10)
    logger.info("test_feedback_correct status=%d body=%s", resp.status_code, resp.text)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    # 当前 weight >= 0.85 时，corrected_weight 不得低于 0.50
    assert data["corrected_weight"] >= 0.50, (
        f"DECAY_FLOOR protection failed: corrected_weight={data['corrected_weight']} < 0.50"
    )
    print("PASS: test_feedback_correct")


@pytest.mark.integration
def test_feedback_invalid_type():
    """无效 type 返回 400"""
    payload = {
        "relation_id": "R:C:600519.SH|P:chip_A|2026-04-21",
        "type": "invalid_type",
    }
    resp = requests.post(f"{BASE_URL}/api/v1/kg/feedback", json=payload, timeout=10)
    logger.info("test_feedback_invalid_type status=%d body=%s", resp.status_code, resp.text)
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    print("PASS: test_feedback_invalid_type")


@pytest.mark.integration
def test_feedback_not_found():
    """不存在的 relation_id 返回 404"""
    payload = {
        "relation_id": "R:C:NOTEXIST.SH|P:fake|2026-04-21",
        "type": "confirm",
    }
    resp = requests.post(f"{BASE_URL}/api/v1/kg/feedback", json=payload, timeout=10)
    logger.info("test_feedback_not_found status=%d body=%s", resp.status_code, resp.text)
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    print("PASS: test_feedback_not_found")


if __name__ == "__main__":
    test_feedback_confirm()
    test_feedback_reject()
    test_feedback_correct()
    test_feedback_invalid_type()
    test_feedback_not_found()
    print("\nAll tests passed.")
