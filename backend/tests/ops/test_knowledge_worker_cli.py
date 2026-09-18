import json

from scripts.knowledge_worker import main


def test_dry_run_prints_valid_startup_contract(capsys):
    assert main(["--dry-run", "--role", "evidence-extraction"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["role"] == "evidence-extraction"
    assert payload["concurrency"] == 1


def test_default_rotation_drains_link(monkeypatch):
    claimed = []

    class FakeWorker:
        def __init__(self, max_concurrency=1):
            pass

        async def run_once(self, limit=None, job_type="combined"):
            claimed.append(job_type)
            return {"claimed": 0, "success": 0, "failed": 0, "skipped": 0, "job_type": job_type}

    monkeypatch.setattr("app.knowledge.evidence_worker.EvidenceExtractionWorker", FakeWorker)

    assert main(["--role", "evidence-extraction", "--once"]) == 0
    assert set(claimed) == {"combined", "vector", "signal", "link"}
