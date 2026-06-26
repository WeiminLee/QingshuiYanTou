"""Tests for chunk_dedup.py — Chunk-level content fingerprint deduplication."""

import hashlib

from app.knowledge.extraction.chunk_dedup import (
    compute_chunk_hash,
    compute_document_hashes,
    find_new_chunk_indices,
)

# ---------------------------------------------------------------------------
# compute_chunk_hash
# ---------------------------------------------------------------------------


class TestComputeChunkHash:
    """Tests for compute_chunk_hash function."""

    def test_normal_text_returns_32_char_hex(self) -> None:
        """Normal ASCII text should return a 32-char MD5 hex digest."""
        text = "hello world"
        expected = hashlib.md5(text.encode("utf-8")).hexdigest()
        result = compute_chunk_hash(text)

        assert result == expected
        assert len(result) == 32

    def test_empty_text_returns_empty_string(self) -> None:
        """Empty string should return an empty string."""
        assert compute_chunk_hash("") == ""

    def test_chinese_text_returns_correct_hash(self) -> None:
        """Chinese text should be hashed correctly via UTF-8 encoding."""
        text = "华为"
        expected = hashlib.md5(text.encode("utf-8")).hexdigest()
        assert compute_chunk_hash(text) == expected

    def test_whitespace_only_returns_empty_string(self) -> None:
        """Whitespace-only text should return an empty string after stripping."""
        assert compute_chunk_hash("   ") == ""

    def test_trailing_whitespace_stripped_before_hash(self) -> None:
        """Trailing/leading whitespace should be stripped before hashing."""
        assert compute_chunk_hash("华为") == compute_chunk_hash("  华为  ")

    def test_tabs_and_newlines_stripped(self) -> None:
        """Tabs and newlines should be stripped before hashing."""
        assert compute_chunk_hash("\t\nhello\n\t") == compute_chunk_hash("hello")

    def test_deterministic(self) -> None:
        """Same input always produces the same hash."""
        text = "deterministic test"
        assert compute_chunk_hash(text) == compute_chunk_hash(text)


# ---------------------------------------------------------------------------
# compute_document_hashes
# ---------------------------------------------------------------------------


class TestComputeDocumentHashes:
    """Tests for compute_document_hashes function."""

    def test_empty_list_returns_empty_list(self) -> None:
        """Empty input list should return an empty list."""
        assert compute_document_hashes([]) == []

    def test_multi_element_list(self) -> None:
        """Multiple chunks should produce a list of equal length with correct hashes."""
        chunks = ["华为", "腾讯", "阿里巴巴"]
        result = compute_document_hashes(chunks)

        assert len(result) == 3
        assert result[0] == compute_chunk_hash("华为")
        assert result[1] == compute_chunk_hash("腾讯")
        assert result[2] == compute_chunk_hash("阿里巴巴")

    def test_list_with_empty_chunk(self) -> None:
        """Empty chunk in the list should produce an empty string hash."""
        chunks = ["华为", ""]
        result = compute_document_hashes(chunks)

        assert result[0] == compute_chunk_hash("华为")
        assert result[1] == ""

    def test_preserves_order(self) -> None:
        """Output order must match input order."""
        chunks = ["aaa", "bbb", "ccc"]
        result = compute_document_hashes(chunks)

        assert result == [
            compute_chunk_hash("aaa"),
            compute_chunk_hash("bbb"),
            compute_chunk_hash("ccc"),
        ]


# ---------------------------------------------------------------------------
# find_new_chunk_indices
# ---------------------------------------------------------------------------


class TestFindNewChunkIndices:
    """Tests for find_new_chunk_indices function."""

    def test_all_new_when_no_existing(self) -> None:
        """When existing_hashes is empty, all indices should be returned."""
        new_hashes = ["a", "b", "c"]
        assert find_new_chunk_indices(new_hashes, []) == [0, 1, 2]

    def test_all_new_both_empty(self) -> None:
        """When both lists are empty, result should be empty."""
        assert find_new_chunk_indices([], []) == []

    def test_partial_duplicate(self) -> None:
        """Only changed and added indices should be returned."""
        new_hashes = ["a", "b", "c"]
        existing_hashes = ["a", "x"]
        result = find_new_chunk_indices(new_hashes, existing_hashes)

        # index 0: "a" == "a" → unchanged
        # index 1: "b" != "x" → changed
        # index 2: added (beyond existing length)
        assert result == [1, 2]

    def test_full_duplicate(self) -> None:
        """When all hashes match, no indices should be returned."""
        new_hashes = ["a", "b"]
        existing_hashes = ["a", "b"]
        assert find_new_chunk_indices(new_hashes, existing_hashes) == []

    def test_existing_longer_than_new(self) -> None:
        """When existing is longer, only compare up to new length."""
        new_hashes = ["a"]
        existing_hashes = ["a", "b", "c"]
        assert find_new_chunk_indices(new_hashes, existing_hashes) == []

    def test_existing_longer_with_change(self) -> None:
        """When existing is longer but first chunk changed, report it."""
        new_hashes = ["x"]
        existing_hashes = ["a", "b", "c"]
        assert find_new_chunk_indices(new_hashes, existing_hashes) == [0]

    def test_single_new_single_existing_same(self) -> None:
        """Single matching hash produces empty result."""
        assert find_new_chunk_indices(["a"], ["a"]) == []

    def test_single_new_single_existing_different(self) -> None:
        """Single differing hash produces [0]."""
        assert find_new_chunk_indices(["b"], ["a"]) == [0]

    def test_empty_new_with_existing(self) -> None:
        """Empty new hashes with non-empty existing produces empty result."""
        assert find_new_chunk_indices([], ["a", "b"]) == []
