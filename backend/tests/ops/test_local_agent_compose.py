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


def _env_map(service: dict) -> dict[str, str]:
    env = service.get("environment", {})
    if isinstance(env, dict):
        return {str(key): str(value) for key, value in env.items()}
    result: dict[str, str] = {}
    for item in env:
        key, _, value = item.partition("=")
        result[key] = value
    return result


def _volume_strings(service: dict) -> list[str]:
    volumes = service.get("volumes", [])
    result: list[str] = []
    for volume in volumes:
        if isinstance(volume, str):
            result.append(volume)
            continue
        source = volume.get("source", "")
        target = volume.get("target", "")
        suffix = ":ro" if volume.get("read_only") else ""
        result.append(f"{source}:{target}{suffix}")
    return result


def test_settings_expose_desktop_pdf_storage_boundary(monkeypatch):
    monkeypatch.delenv("PDF_STORAGE_ROOT", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test")
    monkeypatch.setenv("MONGODB_URL", "mongodb://test")
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("NEO4J_PASSWORD", "test")

    from app.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test",
        mongodb_url="mongodb://test",
        llm_api_key="test",
        neo4j_password="test",
        knowledge_api_url="http://10.20.0.1:8080",
        knowledge_api_key="local-agent-key",
        agent_database_fallback=False,
        pdf_storage_root="/Users/lwm/data/qingshui_pdfs",
    )

    assert str(settings.pdf_storage_root) == "/Users/lwm/data/qingshui_pdfs"
    assert settings.knowledge_api_url == "http://10.20.0.1:8080"
    assert settings.knowledge_api_key == "local-agent-key"
    assert settings.agent_database_fallback is False


def test_local_agent_compose_owns_pdf_workers_and_agent_runtime():
    path = ROOT / "docker-compose.local-agent.yml"
    services = _compose_services(
        ROOT / "docker-compose.yml",
        path,
        env={
            **os.environ,
            "COMPOSE_PROFILES": "local-agent",
            "PDF_STORAGE_ROOT": "/Users/lwm/data/qingshui_pdfs",
            "KNOWLEDGE_API_URL": "http://10.20.0.1:8080",
            "KNOWLEDGE_API_KEY": "local-agent-key",
            "AGENT_DATABASE_FALLBACK": "false",
        },
    )
    assert {"pdf-download-worker", "evidence-worker"} <= services.keys()

    agent_services = [
        name
        for name, service in services.items()
        if {"KNOWLEDGE_API_URL", "KNOWLEDGE_API_KEY", "AGENT_DATABASE_FALLBACK"} <= _env_map(service).keys()
    ]
    assert len(agent_services) == 1, f"expected one agent runtime service, found {agent_services}"

    pdf_mounts = _volume_strings(services["pdf-download-worker"])
    evidence_mounts = _volume_strings(services["evidence-worker"])
    assert any(mount.endswith("/data/qingshui-pdfs") for mount in pdf_mounts)
    assert not any(mount.endswith("/data/qingshui-pdfs:ro") for mount in pdf_mounts)
    assert any(mount.endswith("/data/qingshui-pdfs:ro") for mount in evidence_mounts)

    mounted_services = {
        name
        for name, service in services.items()
        if any("/data/qingshui-pdfs" in mount for mount in _volume_strings(service))
    }
    assert mounted_services == {"pdf-download-worker", "evidence-worker"}
    assert "scheduler" not in services
    assert "job-worker" not in services


def test_cloud_compose_keeps_pdf_workers_outside_the_cloud_boundary():
    services = _compose_services(
        ROOT / "docker-compose.yml",
        ROOT / "docker-compose.cloud.yml",
        env={**os.environ, "COMPOSE_PROFILES": "cloud-ingestion"},
    )

    assert "pdf-download-worker" not in services
    assert "evidence-worker" not in services


def test_local_agent_env_example_declares_pdf_storage_root():
    env_path = ROOT / "backend/.env.local-agent.example"
    content = env_path.read_text(encoding="utf-8")

    assert "PDF_STORAGE_ROOT=" in content
    assert "KNOWLEDGE_API_URL=" in content
    assert "KNOWLEDGE_API_KEY=" in content
    assert "AGENT_DATABASE_FALLBACK=" in content
