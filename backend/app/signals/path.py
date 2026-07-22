from __future__ import annotations

from typing import Any


def build_signal_path(metadata: dict[str, Any] | None, *, confidence: float) -> dict[str, Any] | None:
    metadata = metadata or {}
    nodes = [str(node) for node in metadata.get("path_nodes", []) if node]
    if not nodes:
        return None

    edges = []
    for edge in metadata.get("path_edges", []) or []:
        if not isinstance(edge, dict):
            continue
        edges.append(
            {
                "src": str(edge.get("src") or ""),
                "rel_type": str(edge.get("rel_type") or edge.get("type") or "RELATES"),
                "tgt": str(edge.get("tgt") or ""),
                "weight": float(edge.get("weight") if edge.get("weight") is not None else 1.0),
                "text": str(edge.get("text") or ""),
            }
        )

    hops = int(metadata.get("path_hops") or len(edges) or max(len(nodes) - 1, 0))
    return {
        "nodes": nodes,
        "edges": edges,
        "hops": hops,
        "confidence": round(float(confidence), 3),
    }
