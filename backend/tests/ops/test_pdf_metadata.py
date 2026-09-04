from pathlib import Path

from app.ops.pdf_metadata import build_pdf_metadata, sha256_file


def test_pdf_metadata_contains_stable_sha256(tmp_path: Path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"pdf-content")
    first = build_pdf_metadata(path, pdf_url="https://example.invalid/a.pdf")
    second = build_pdf_metadata(path, pdf_url="https://example.invalid/a.pdf")
    assert first == second
    assert first["pdf_storage"] == "desktop"
    assert first["available"] is True
    assert first["pdf_sha256"] == sha256_file(path)


def test_missing_pdf_is_explicitly_unavailable(tmp_path: Path):
    metadata = build_pdf_metadata(tmp_path / "missing.pdf")
    assert metadata["available"] is False
    assert metadata["pdf_sha256"] is None
