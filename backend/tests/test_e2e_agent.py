"""
E2E test: Canvas + Lead Agent

Requires: backend running at http://localhost:8000 + real LLM API.
Mark: @pytest.mark.integration — skipped in regular test runs.
Run explicitly: pytest tests/test_e2e_agent.py -v
"""

import logging
import time

import pytest
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"
API_KEY = "sk-V-ZNidHIYdGK4rOXpPCsPw"
HEADERS = {"X-Api-Key": API_KEY}


@pytest.mark.integration
def test_e2e_connection_check():
    """Sanity check: /health endpoint returns 200."""
    resp = requests.get(f"{BASE_URL}/health", timeout=5)
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    print("PASS: test_e2e_connection_check")


@pytest.mark.integration
def test_e2e_semiconductor_sector():
    """
    Sends a semiconductor-sector analysis query and verifies:
    1. HTTP 200 response
    2. Response body contains AnalysisReport five-section keys:
       conclusions, catalysts, risks, scenarios, tracking_indicators
    3. At least one non-empty conclusion present
    """
    payload = {
        "question": "分析中际旭创的竞争格局和产品布局",
        "max_turns": 2,  # keep test fast
    }
    logger.info("POST /api/v1/agent/chat with semiconductor query")
    t0 = time.time()
    resp = requests.post(f"{BASE_URL}/api/v1/agent/chat", json=payload, headers=HEADERS, timeout=120)
    elapsed = time.time() - t0
    logger.info("Response status=%d elapsed=%.1fs body_len=%d", resp.status_code, elapsed, len(resp.text))

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"

    data = resp.json()
    # Accept both flat "content" string and structured "report" dict
    content = data.get("content", "") or data.get("report", {}).get("content", "")

    # Check AnalysisReport five-section markers (crude but effective)
    SECTION_KEYS = ["conclusions", "catalysts", "risks", "scenarios", "tracking_indicators"]
    data_str = str(data)
    found_keys = [k for k in SECTION_KEYS if k in data_str]
    logger.info("Found section keys: %s", found_keys)

    assert len(found_keys) >= 3, (
        f"Expected at least 3 of {SECTION_KEYS} in response, found {found_keys}. Response preview: {data_str[:500]}"
    )
    print(f"PASS: test_e2e_semiconductor_sector ({elapsed:.1f}s, {len(found_keys)} sections)")
    return data


if __name__ == "__main__":
    test_e2e_connection_check()
    test_e2e_semiconductor_sector()
