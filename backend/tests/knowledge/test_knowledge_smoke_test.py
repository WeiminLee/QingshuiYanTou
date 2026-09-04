import pytest

from scripts import knowledge_smoke_test


def test_main_rejects_non_positive_limits():
    with pytest.raises(SystemExit):
        knowledge_smoke_test.main(["--limits", "10,0"])

