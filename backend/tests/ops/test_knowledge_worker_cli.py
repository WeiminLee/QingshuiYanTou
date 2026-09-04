import json

from scripts.knowledge_worker import main


def test_dry_run_prints_valid_startup_contract(capsys):
    assert main(["--dry-run", "--role", "evidence-extraction"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["role"] == "evidence-extraction"
    assert payload["concurrency"] == 1
