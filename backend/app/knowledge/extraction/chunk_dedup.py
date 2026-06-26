"""
chunk_dedup.py — Chunk-level content fingerprint deduplication

Used to detect changed chunks before KG re-extraction to avoid redundant LLM calls.

Functions:
- compute_chunk_hash: MD5 hash of stripped text
- compute_document_hashes: Batch hash computation
- find_new_chunk_indices: Compare hashes to detect changes
"""

import hashlib


def compute_chunk_hash(text: str) -> str:
    """
    Compute MD5 hash of stripped text.

    Args:
        text: Chunk text content

    Returns:
        32-char hex string, or "" if text is empty/whitespace-only

    Examples:
        >>> compute_chunk_hash("华为")
        '32-char hex string'
        >>> compute_chunk_hash("")
        ''
        >>> compute_chunk_hash("华为") == compute_chunk_hash("华为 ")
        True
    """
    stripped = text.strip()
    if not stripped:
        return ""

    return hashlib.md5(stripped.encode("utf-8")).hexdigest()


def compute_document_hashes(chunks: list[str]) -> list[str]:
    """
    Batch compute hashes for a list of chunks.

    Args:
        chunks: List of chunk text strings

    Returns:
        List of hashes (same length as input), empty strings for empty chunks

    Examples:
        >>> compute_document_hashes(["华为", "腾讯", ""])
        ['hash1', 'hash2', '']
    """
    return [compute_chunk_hash(chunk) for chunk in chunks]


def find_new_chunk_indices(
    new_hashes: list[str],
    existing_hashes: list[str],
) -> list[int]:
    """
    Find indices of chunks that have changed (added or modified).

    Args:
        new_hashes: Hashes of new document chunks
        existing_hashes: Hashes of existing document chunks (from registry)

    Returns:
        List of indices where new_chunks[index] differs from or extends existing_chunks

    Examples:
        >>> find_new_chunk_indices(["a", "b"], ["a"])
        [1]
        >>> find_new_chunk_indices(["a", "b"], ["a", "b"])
        []
        >>> find_new_chunk_indices(["a", "b", "c"], ["a"])
        [1, 2]
    """
    if not existing_hashes:
        return list(range(len(new_hashes)))

    changed_indices: list[int] = []

    # Check existing chunks for modifications
    for i, (new_hash, existing_hash) in enumerate(zip(new_hashes, existing_hashes)):
        if new_hash != existing_hash:
            changed_indices.append(i)

    # Mark added chunks (beyond existing length)
    if len(new_hashes) > len(existing_hashes):
        changed_indices.extend(range(len(existing_hashes), len(new_hashes)))

    return changed_indices
