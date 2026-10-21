"""Filled numeric slots stay on compare and history. Vector search is the unbound residual."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

hypothetical_document_calls = 0


def reset_hypothetical_document_calls() -> None:
    global hypothetical_document_calls
    hypothetical_document_calls = 0


def build_hypothetical_document(query: str) -> str:
    """HyDE invents a number and then retrieves that fiction. Numeric state must not call this."""
    global hypothetical_document_calls
    hypothetical_document_calls += 1
    raise RuntimeError("hypothetical document expansion is not used for numeric state")


def numeric_slots_filled(subject: str | None, dimension: str | None, period: str | None, value: str | None) -> bool:
    has_value = value is not None and str(value) != ""
    return bool(subject and dimension and (period or has_value))


async def retrieve_bound_or_residual(
    *,
    query: str,
    subject: str | None,
    dimension: str | None,
    period: str | None,
    value: str | None,
    compare_metric: Callable[..., Awaitable],
    pull_history: Callable[..., Awaitable],
    search_residual: Callable[[str], list],
) -> dict:
    if numeric_slots_filled(subject, dimension, period, value):
        compared = await compare_metric(dimension=dimension)
        history = await pull_history(subject, dimension=dimension)
        return {
            "route": "structured",
            "compare": compared,
            "history": history,
            "hypothetical_document": None,
        }
    return {
        "route": "residual",
        "facts": search_residual(query),
        "hypothetical_document": None,
    }
