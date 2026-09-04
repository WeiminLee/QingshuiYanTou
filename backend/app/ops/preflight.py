"""Dependency preflight checks for the remote Evidence worker."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class CheckResult:
    name: str
    target: str
    ok: bool
    error: str | None = None


def parse_target(name: str, url: str) -> tuple[str, int]:
    parsed = urlparse(url if "://" in url else f"//{url}")
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"{name} must include host and port: {url!r}")
    return parsed.hostname, parsed.port


def check_tcp(name: str, url: str, timeout: float = 2.0) -> CheckResult:
    try:
        host, port = parse_target(name, url)
        with socket.create_connection((host, port), timeout=timeout):
            return CheckResult(name, f"{host}:{port}", True)
    except (OSError, ValueError) as exc:
        return CheckResult(name, url, False, str(exc))
