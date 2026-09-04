"""Environment-backed configuration shared by remote workers."""

from __future__ import annotations

import os
from dataclasses import dataclass

VALID_ROLES = {"ingestion", "evidence-extraction"}


def validate_worker_role(role: str) -> str:
    value = role.strip().lower()
    if value not in VALID_ROLES:
        raise ValueError(f"unsupported WORKER_ROLE={role!r}; expected one of {sorted(VALID_ROLES)}")
    return value


@dataclass(frozen=True)
class WorkerSettings:
    role: str = "evidence-extraction"
    concurrency: int = 1
    poll_interval: int = 30
    job_timeout: int = 1800
    pdf_storage_root: str = "/data/qingshui-pdfs"

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "WorkerSettings":
        env = os.environ if environ is None else environ
        role = validate_worker_role(env.get("WORKER_ROLE", cls.role))
        values = {
            "role": role,
            "concurrency": int(env.get("WORKER_CONCURRENCY", cls.concurrency)),
            "poll_interval": int(env.get("WORKER_POLL_INTERVAL", cls.poll_interval)),
            "job_timeout": int(env.get("WORKER_JOB_TIMEOUT", cls.job_timeout)),
            "pdf_storage_root": env.get("PDF_STORAGE_ROOT", cls.pdf_storage_root),
        }
        if values["concurrency"] < 1 or values["poll_interval"] < 1 or values["job_timeout"] < 1:
            raise ValueError("worker numeric settings must be positive")
        return cls(**values)
