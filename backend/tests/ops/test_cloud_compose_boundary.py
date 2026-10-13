"""Cloud compose boundary: PDF workers stay outside the frozen cloud stack."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _compose_services(*files: Path, env: dict[str, str] | None = None) -> dict[str, dict]:
    command = ["docker", "compose"]
    for file in files:
        command.extend(["-f", str(file)])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(result.stdout)["services"]


def test_cloud_compose_keeps_pdf_workers_outside_the_cloud_boundary():
    services = _compose_services(
        ROOT / "docker-compose.yml",
        ROOT / "docker-compose.cloud.yml",
        env={**os.environ, "COMPOSE_PROFILES": "cloud-ingestion"},
    )

    assert "pdf-download-worker" not in services
    assert "evidence-worker" not in services
