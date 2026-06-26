"""
Tests for build_alias_table.py script.

Tests cover:
1. fetch_and_transform — correct API response → aliases format transformation
2. merge_aliases — preserves existing manual entries, adds new entries correctly
3. Full flow — fetch → transform → merge → write
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add backend to path for imports
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from scripts.build_alias_table import (  # noqa: E402
    _is_manual_entry,
    fetch_and_transform,
    merge_aliases,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_cloud_stocks():
    """Sample stock data returned by CloudDataClient.get_stocks()"""
    return [
        {"ts_code": "600030.SH", "name": "中信证券", "industry": "证券"},
        {"ts_code": "300308.SZ", "name": "中际旭创", "industry": "光通信"},
        {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行"},
        {"ts_code": "601318.SH", "name": "中国平安", "industry": "保险"},
        # Entry with empty name should be skipped
        {"ts_code": "688999.SH", "name": "", "industry": "科技"},
        # Entry with whitespace name should be skipped
        {"ts_code": "688998.SH", "name": "   ", "industry": "科技"},
    ]


@pytest.fixture
def existing_manual_aliases():
    """Existing aliases with manual curation (sector_tags/notes)"""
    return {
        "中信证券": {
            "names": ["中信证券", "中信"],
            "listing": True,
            "ts_code": "600030.SH",
            "industry_tags": ["证券"],
            "sector_tags": ["金融", "券商"],
            "notes": "头部券商",
        },
        "中际旭创": {
            "names": ["中际旭创", "旭创"],
            "listing": True,
            "ts_code": "300308.SZ",
            "industry_tags": ["光通信"],
            "sector_tags": ["光模块"],
            "notes": "光模块龙头",
        },
    }


@pytest.fixture
def existing_cloud_aliases():
    """Existing aliases without manual curation (pure cloud-sourced)"""
    return {
        "平安银行": {
            "names": ["平安银行"],
            "listing": True,
            "ts_code": "000001.SZ",
            "industry_tags": ["银行"],
            "notes": "",
        },
        "中国平安": {
            "names": ["中国平安"],
            "listing": True,
            "ts_code": "601318.SH",
            "industry_tags": ["保险"],
            "notes": "",
        },
    }


# ── Test fetch_and_transform ─────────────────────────────────────────────────


@patch("scripts.build_alias_table.CloudDataClient")
def test_fetch_and_transform_basic(mock_client_class, mock_cloud_stocks):
    """Test basic transformation from API response to alias format."""
    # Setup mock
    mock_instance = MagicMock()
    mock_instance.get_stocks.return_value = mock_cloud_stocks
    mock_client_class.return_value = mock_instance

    # Execute
    result = fetch_and_transform()

    # Verify
    assert "中信证券" in result
    assert result["中信证券"]["ts_code"] == "600030.SH"
    assert result["中信证券"]["names"] == ["中信证券"]
    assert result["中信证券"]["listing"] is True
    assert result["中信证券"]["industry_tags"] == ["证券"]
    assert result["中信证券"]["notes"] == ""

    assert "中际旭创" in result
    assert result["中际旭创"]["ts_code"] == "300308.SZ"
    assert result["中际旭创"]["industry_tags"] == ["光通信"]

    # Empty/whitespace names should be skipped
    assert len(result) == 4  # Only 4 valid entries


@patch("scripts.build_alias_table.CloudDataClient")
def test_fetch_and_transform_empty_industry(mock_client_class):
    """Test handling of stocks without industry field."""
    mock_instance = MagicMock()
    mock_instance.get_stocks.return_value = [
        {"ts_code": "688001.SH", "name": "测试公司", "industry": ""},
        {"ts_code": "688002.SH", "name": "测试公司2", "industry": None},
    ]
    mock_client_class.return_value = mock_instance

    result = fetch_and_transform()

    assert result["测试公司"]["industry_tags"] == []
    assert result["测试公司2"]["industry_tags"] == []


@patch("scripts.build_alias_table.CloudDataClient")
def test_fetch_and_transform_empty_response(mock_client_class):
    """Test handling of empty API response."""
    mock_instance = MagicMock()
    mock_instance.get_stocks.return_value = []
    mock_client_class.return_value = mock_instance

    result = fetch_and_transform()

    assert result == {}


# ── Test _is_manual_entry ───────────────────────────────────────────────────


def test_is_manual_entry_with_sector_tags():
    """Entry with non-empty sector_tags is manual."""
    entry = {"sector_tags": ["光模块", "AI"]}
    assert _is_manual_entry(entry) is True


def test_is_manual_entry_with_notes():
    """Entry with non-empty notes is manual."""
    entry = {"notes": "头部券商"}
    assert _is_manual_entry(entry) is True


def test_is_manual_entry_with_empty_sector_tags():
    """Entry with empty sector_tags list is not manual."""
    entry = {"sector_tags": []}
    assert _is_manual_entry(entry) is False


def test_is_manual_entry_with_whitespace_notes():
    """Entry with whitespace-only notes is not manual."""
    entry = {"notes": "   "}
    assert _is_manual_entry(entry) is False


def test_is_manual_entry_cloud_sourced():
    """Pure cloud-sourced entry (no manual indicators) is not manual."""
    entry = {
        "names": ["测试公司"],
        "listing": True,
        "ts_code": "688001.SH",
        "industry_tags": ["科技"],
        "notes": "",
    }
    assert _is_manual_entry(entry) is False


# ── Test merge_aliases (Incremental Mode) ────────────────────────────────────


def test_merge_aliases_incremental_preserves_existing(existing_manual_aliases, existing_cloud_aliases):
    """Incremental mode never overwrites existing entries."""
    existing = {**existing_manual_aliases, **existing_cloud_aliases}

    cloud_entries = {
        "中信证券": {
            "names": ["中信证券"],
            "listing": True,
            "ts_code": "600030.SH_NEW",  # Different ts_code
            "industry_tags": ["新行业"],
            "notes": "",
        },
        "新公司": {
            "names": ["新公司"],
            "listing": True,
            "ts_code": "688999.SH",
            "industry_tags": ["科技"],
            "notes": "",
        },
    }

    merged = merge_aliases(existing, cloud_entries, full_rebuild=False)

    # Existing manual entry preserved (not overwritten)
    assert merged["中信证券"]["ts_code"] == "600030.SH"
    assert merged["中信证券"]["sector_tags"] == ["金融", "券商"]
    assert merged["中信证券"]["notes"] == "头部券商"

    # Existing cloud entry also preserved
    assert merged["平安银行"]["ts_code"] == "000001.SZ"

    # New entry added
    assert "新公司" in merged
    assert merged["新公司"]["ts_code"] == "688999.SH"


def test_merge_aliases_incremental_adds_new_only(
    existing_cloud_aliases,
):
    """Incremental mode only adds entries not in existing."""
    cloud_entries = {
        "新公司A": {
            "names": ["新公司A"],
            "listing": True,
            "ts_code": "688001.SH",
            "industry_tags": ["科技"],
            "notes": "",
        },
        "新公司B": {
            "names": ["新公司B"],
            "listing": True,
            "ts_code": "688002.SH",
            "industry_tags": ["医药"],
            "notes": "",
        },
    }

    merged = merge_aliases(existing_cloud_aliases, cloud_entries, full_rebuild=False)

    assert len(merged) == 4  # 2 existing + 2 new
    assert "新公司A" in merged
    assert "新公司B" in merged


# ── Test merge_aliases (Full Rebuild Mode) ───────────────────────────────────


def test_merge_aliases_full_rebuild_preserves_manual(existing_manual_aliases, existing_cloud_aliases):
    """Full rebuild preserves manual entries, replaces cloud-sourced."""
    existing = {**existing_manual_aliases, **existing_cloud_aliases}

    cloud_entries = {
        "中信证券": {
            "names": ["中信证券"],
            "listing": True,
            "ts_code": "600030.SH_UPDATED",
            "industry_tags": ["证券新"],
            "notes": "",
        },
        "平安银行": {
            "names": ["平安银行"],
            "listing": True,
            "ts_code": "000001.SZ_UPDATED",
            "industry_tags": ["银行新"],
            "notes": "",
        },
        "新公司": {
            "names": ["新公司"],
            "listing": True,
            "ts_code": "688999.SH",
            "industry_tags": ["科技"],
            "notes": "",
        },
    }

    merged = merge_aliases(existing, cloud_entries, full_rebuild=True)

    # Manual entry preserved (not overwritten)
    assert merged["中信证券"]["ts_code"] == "600030.SH"
    assert merged["中信证券"]["sector_tags"] == ["金融", "券商"]
    assert merged["中信证券"]["notes"] == "头部券商"

    # Cloud-sourced entry replaced with fresh data
    assert merged["平安银行"]["ts_code"] == "000001.SZ_UPDATED"
    assert merged["平安银行"]["industry_tags"] == ["银行新"]

    # New entry added
    assert "新公司" in merged

    # Check counts
    assert len(merged) == 4  # 2 manual + 1 replaced + 1 new


def test_merge_aliases_full_rebuild_no_manual_entries(
    existing_cloud_aliases,
):
    """Full rebuild with no manual entries replaces all."""
    cloud_entries = {
        "平安银行": {
            "names": ["平安银行"],
            "listing": True,
            "ts_code": "000001.SZ_NEW",
            "industry_tags": ["银行新"],
            "notes": "",
        },
    }

    merged = merge_aliases(existing_cloud_aliases, cloud_entries, full_rebuild=True)

    # Replaced with fresh data
    assert merged["平安银行"]["ts_code"] == "000001.SZ_NEW"
    assert merged["平安银行"]["industry_tags"] == ["银行新"]


# ── Test Full Flow (Integration) ─────────────────────────────────────────────


@patch("scripts.build_alias_table.CloudDataClient")
def test_full_flow_incremental(mock_client_class, mock_cloud_stocks, existing_manual_aliases, tmp_path):
    """Test complete flow: fetch → transform → merge → write."""
    # Setup mock
    mock_instance = MagicMock()
    mock_instance.get_stocks.return_value = mock_cloud_stocks
    mock_client_class.return_value = mock_instance

    # Create temp alias file with existing entries
    alias_file = tmp_path / "company_aliases.json"
    alias_file.write_text(
        json.dumps(existing_manual_aliases, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Patch ALIAS_FILE to use temp
    with patch("scripts.build_alias_table.ALIAS_FILE", alias_file):
        from scripts.build_alias_table import load_aliases, save_aliases

        # Step 1: Fetch and transform
        cloud_entries = fetch_and_transform()
        assert len(cloud_entries) == 4

        # Step 2: Load existing
        existing = load_aliases(alias_file)
        assert len(existing) == 2

        # Step 3: Merge (incremental)
        merged = merge_aliases(existing, cloud_entries, full_rebuild=False)

        # Verify merge
        assert len(merged) == 4  # 2 existing + 2 new
        # Manual entries preserved
        assert merged["中信证券"]["sector_tags"] == ["金融", "券商"]
        # New entries added
        assert "平安银行" in merged
        assert "中国平安" in merged

        # Step 4: Save
        save_aliases(alias_file, merged)

        # Verify file written
        loaded = json.loads(alias_file.read_text(encoding="utf-8"))
        assert len(loaded) == 4
        assert loaded["中信证券"]["sector_tags"] == ["金融", "券商"]


@patch("scripts.build_alias_table.CloudDataClient")
def test_full_flow_full_rebuild(
    mock_client_class, mock_cloud_stocks, existing_manual_aliases, existing_cloud_aliases, tmp_path
):
    """Test full rebuild flow preserves manual entries, replaces cloud-sourced."""
    # Setup mock
    mock_instance = MagicMock()
    mock_instance.get_stocks.return_value = mock_cloud_stocks
    mock_client_class.return_value = mock_instance

    # Create temp alias file with both manual and cloud entries
    existing = {**existing_manual_aliases, **existing_cloud_aliases}
    alias_file = tmp_path / "company_aliases.json"
    alias_file.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with patch("scripts.build_alias_table.ALIAS_FILE", alias_file):
        from scripts.build_alias_table import load_aliases, save_aliases

        # Fetch fresh data
        cloud_entries = fetch_and_transform()

        # Load existing
        existing_loaded = load_aliases(alias_file)

        # Merge (full rebuild)
        merged = merge_aliases(existing_loaded, cloud_entries, full_rebuild=True)

        # Manual entries preserved
        assert merged["中信证券"]["sector_tags"] == ["金融", "券商"]
        assert merged["中际旭创"]["sector_tags"] == ["光模块"]

        # Cloud-sourced entries replaced (平安银行/中国平安 in fresh data)
        assert merged["平安银行"]["ts_code"] == "000001.SZ"
        assert merged["中国平安"]["ts_code"] == "601318.SH"

        # Save
        save_aliases(alias_file, merged)

        # Verify
        loaded = json.loads(alias_file.read_text(encoding="utf-8"))
        assert loaded["中信证券"]["notes"] == "头部券商"


# ── Edge Cases ───────────────────────────────────────────────────────────────


def test_merge_aliases_empty_existing():
    """Merging into empty existing dict works correctly."""
    cloud_entries = {
        "新公司": {
            "names": ["新公司"],
            "listing": True,
            "ts_code": "688999.SH",
            "industry_tags": ["科技"],
            "notes": "",
        },
    }

    merged = merge_aliases({}, cloud_entries, full_rebuild=False)

    assert len(merged) == 1
    assert merged["新公司"]["ts_code"] == "688999.SH"


def test_merge_aliases_empty_cloud_entries(existing_manual_aliases):
    """Merging empty cloud data preserves existing."""
    merged = merge_aliases(existing_manual_aliases, {}, full_rebuild=False)

    assert merged == existing_manual_aliases


def test_merge_aliases_immutability(existing_cloud_aliases):
    """Verify merge_aliases does not mutate existing dict."""
    original = existing_cloud_aliases.copy()
    cloud_entries = {
        "新公司": {
            "names": ["新公司"],
            "listing": True,
            "ts_code": "688999.SH",
            "industry_tags": ["科技"],
            "notes": "",
        },
    }

    merge_aliases(existing_cloud_aliases, cloud_entries, full_rebuild=False)

    # existing should not be modified
    assert existing_cloud_aliases == original


# ── Test load_aliases/save_aliases ────────────────────────────────────────────


def test_load_aliases_missing_file(tmp_path):
    """Test loading aliases when file doesn't exist returns empty dict."""
    from scripts.build_alias_table import load_aliases

    missing_file = tmp_path / "nonexistent.json"
    result = load_aliases(missing_file)

    assert result == {}


def test_load_aliases_existing_file(tmp_path, existing_manual_aliases):
    """Test loading aliases from existing file."""
    from scripts.build_alias_table import load_aliases

    alias_file = tmp_path / "company_aliases.json"
    alias_file.write_text(
        json.dumps(existing_manual_aliases, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = load_aliases(alias_file)

    assert len(result) == 2
    assert result["中信证券"]["ts_code"] == "600030.SH"


def test_save_aliases_creates_file(tmp_path):
    """Test save_aliases creates parent directories and file."""
    from scripts.build_alias_table import save_aliases

    # Create a nested path that doesn't exist
    alias_file = tmp_path / "subdir" / "another" / "company_aliases.json"
    aliases = {
        "测试公司": {
            "names": ["测试公司"],
            "listing": True,
            "ts_code": "688001.SH",
            "industry_tags": ["科技"],
            "notes": "",
        }
    }

    save_aliases(alias_file, aliases)

    # Verify file created
    assert alias_file.exists()
    # Verify content
    loaded = json.loads(alias_file.read_text(encoding="utf-8"))
    assert "测试公司" in loaded
