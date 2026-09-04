"""Durable PDF download job payload contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class PdfDownloadJobPayload:
    """Stable payload for a durable PDF download job."""

    source_url: str
    source_type: str
    source_id: str
    stock_code: str
    publish_date: date
    filename: str

    @property
    def job_key(self) -> str:
        return self.source_id

    def to_payload(self) -> dict[str, str]:
        return {
            "source_url": self.source_url,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "stock_code": self.stock_code,
            "publish_date": self.publish_date.isoformat(),
            "filename": self.filename,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PdfDownloadJobPayload":
        publish_date = payload["publish_date"]
        if not isinstance(publish_date, date):
            publish_date = date.fromisoformat(str(publish_date))
        return cls(
            source_url=str(payload["source_url"]),
            source_type=str(payload["source_type"]),
            source_id=str(payload["source_id"]),
            stock_code=str(payload["stock_code"]),
            publish_date=publish_date,
            filename=str(payload["filename"]),
        )
