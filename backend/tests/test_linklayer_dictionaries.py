# backend/tests/test_linklayer_dictionaries.py
from app.knowledge.linklayer.dictionaries import load_vocabulary


def test_load_vocabulary_covers_seed_dimensions():
    vocab = load_vocabulary()
    for name in ("产线进展", "客户认证", "订单", "产能", "毛利率"):
        assert name in vocab.dimensions, f"缺少种子维度 {name}"


def test_staged_dimension_has_ladder():
    vocab = load_vocabulary()
    dim = vocab.dimensions["产线进展"]
    assert dim.kind == "staged"
    levels = [s["level"] for s in dim.stages]
    assert levels == sorted(levels) and len(levels) >= 3
    assert any("调试" in s["words"] for s in dim.stages)


def test_numeric_dimension():
    vocab = load_vocabulary()
    assert vocab.dimensions["毛利率"].kind == "numeric"
    assert "毛利率" in vocab.metric_words
