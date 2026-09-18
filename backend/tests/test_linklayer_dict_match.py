# backend/tests/test_linklayer_dict_match.py
from app.knowledge.linklayer.dict_match import SubjectIndex, match_all
from app.knowledge.linklayer.dictionaries import load_vocabulary

VOCAB = load_vocabulary()
SUBJ = SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ", "中晶": "003026.SZ"})


def test_stage_match_with_span():
    matches = match_all("公司8英寸抛光硅片产线处于调试阶段", VOCAB, SUBJ)
    stages = [m for m in matches if m.layer == "stage"]
    assert any(m.norm_text == "调试" and m.dimension == "产线进展" for m in stages)
    m = next(m for m in stages if m.norm_text == "调试")
    assert 0 < m.span_start < m.span_end


def test_subject_match():
    matches = match_all("中晶科技回复：产线正常", VOCAB, SUBJ)
    assert any(m.layer == "subject" and m.norm_text == "003026.SZ" for m in matches)


def test_metric_word_matches_dimension_layer():
    matches = match_all("公司毛利率稳步提升", VOCAB, SUBJ)
    assert any(m.layer == "dimension" and m.norm_text == "毛利率" for m in matches)


def test_no_false_generic_match():
    matches = match_all("本公司产品毛利率", VOCAB, SubjectIndex(alias_to_norm={}))
    assert all(m.norm_text != "产品" for m in matches)
