from pathlib import Path


def test_file_storage_prefers_pdf_storage_root(monkeypatch, tmp_path):
    from app.data_pipeline import file_storage

    class Settings:
        pdf_storage_root = tmp_path / "desktop-pdfs"
        minishare_data_root = tmp_path / "legacy"

    monkeypatch.setattr("app.config.settings", Settings())
    storage = file_storage.FileStorage()
    assert storage.notices_dir == Path(tmp_path / "desktop-pdfs" / "notices")
