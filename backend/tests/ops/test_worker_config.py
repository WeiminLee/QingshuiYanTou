import pytest

from app.ops.worker_config import WorkerSettings, validate_worker_role


def test_defaults_are_safe_for_cloud_machine():
    settings = WorkerSettings.from_environment({})
    assert settings.role == "evidence-extraction"
    assert settings.concurrency == 1
    assert settings.pdf_storage_root == "/data/qingshui-pdfs"


def test_environment_overrides_are_typed():
    settings = WorkerSettings.from_environment({
        "WORKER_ROLE": " ingestion ",
        "WORKER_CONCURRENCY": "2",
        "WORKER_POLL_INTERVAL": "7",
        "WORKER_JOB_TIMEOUT": "90",
        "PDF_STORAGE_ROOT": "/srv/pdfs",
    })
    assert settings == WorkerSettings("ingestion", 2, 7, 90, "/srv/pdfs")


def test_invalid_role_and_non_positive_values_fail():
    with pytest.raises(ValueError, match="unsupported"):
        validate_worker_role("agent")
    with pytest.raises(ValueError, match="positive"):
        WorkerSettings.from_environment({"WORKER_CONCURRENCY": "0"})
