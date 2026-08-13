from app.signals.path import build_signal_path


def test_build_signal_path_from_propagation_metadata():
    metadata = {
        "path_nodes": ["中际旭创", "800G光模块", "光芯片"],
        "path_edges": [
            {
                "src": "中际旭创",
                "rel_type": "RELATES",
                "tgt": "800G光模块",
                "weight": 0.9,
                "text": "生产 800G 光模块",
            },
            {
                "src": "800G光模块",
                "rel_type": "RELATES",
                "tgt": "光芯片",
                "weight": 0.8,
                "text": "上游依赖光芯片",
            },
        ],
        "path_hops": 2,
    }

    signal_path = build_signal_path(metadata, confidence=0.82)

    assert signal_path == {
        "nodes": ["中际旭创", "800G光模块", "光芯片"],
        "edges": [
            {
                "src": "中际旭创",
                "rel_type": "RELATES",
                "tgt": "800G光模块",
                "weight": 0.9,
                "text": "生产 800G 光模块",
            },
            {
                "src": "800G光模块",
                "rel_type": "RELATES",
                "tgt": "光芯片",
                "weight": 0.8,
                "text": "上游依赖光芯片",
            },
        ],
        "hops": 2,
        "confidence": 0.82,
    }


def test_build_signal_path_returns_none_without_nodes():
    assert build_signal_path({}, confidence=0.8) is None

