"""Tests for announcement chapter filter in evidence_builders_simple."""

from app.knowledge.evidence_builders_simple import _classify_announcement_chapter


def test_keep_ann_type_always_keep():
    """investment/ma_activity/research_survey 始终保留"""
    for ann_type in ("investment", "ma_activity", "research_survey"):
        assert _classify_announcement_chapter("风险因素", "一些风险内容", ann_type) == "keep"
        assert _classify_announcement_chapter("", "一些内容", ann_type) == "keep"


def test_skip_noise_heading():
    """噪音章节标题 → skip"""
    headings = ["会计师事务所", "其他相关说明", "独立董事意见", "信息披露", "募集资金"]
    for h in headings:
        assert _classify_announcement_chapter(h, "无实质内容") == "skip", f"expected skip: {h}"


def test_skip_default_no_match():
    """heading 无匹配 + body 无实质关键词 → skip"""
    assert _classify_announcement_chapter("托管情况", "本期无托管情况说明") == "skip"
    assert _classify_announcement_chapter("", "一般性描述内容") == "skip"
    assert _classify_announcement_chapter("流动风险", "公司面临的流动性风险...") == "skip"


def test_keep_by_heading():
    """实质性标题 → keep"""
    cases = [
        ("本期业绩预计情况", "2024年业绩预计..."),
        ("业绩变动原因说明", "业绩变动原因..."),
        ("营业收入和营业成本", "本期实现收入..."),
        ("研发投入", "研发投入情况..."),
        ("业务概要", "公司主营业务为..."),
        ("产品市场份额", "核心产品市场占有率..."),
        ("关于签订重大合同的公告", "合同金额..."),
        ("收购资产", "收购标的资产..."),
        ("股权转让", "股权转让..."),
    ]
    for heading, body in cases:
        assert _classify_announcement_chapter(heading, body) == "keep", f"expected keep: {heading}"


def test_keep_skip_heading_overridden_by_body():
    """heading 匹配 SKIP 但 body 含实质性关键词 → keep"""
    assert _classify_announcement_chapter("风险因素", "公司营业收入下降风险") == "keep"
    assert _classify_announcement_chapter("独立董事意见", "关于收购资产的独立意见") == "keep"
    assert _classify_announcement_chapter("其他相关说明", "公司业绩情况说明") == "keep"


def test_keep_default_by_body():
    """heading 无匹配但 body 含实质性关键词 → keep"""
    assert _classify_announcement_chapter("公司未来发展的展望", "公司将聚焦主营业务...") == "keep"
    assert _classify_announcement_chapter("管理层讨论与分析", "公司营业收入增长20%") == "keep"
    assert _classify_announcement_chapter("", "公司2024年净利润大幅增长") == "keep"


def test_empty_heading_empty_body():
    """无 heading 无 body → skip"""
    assert _classify_announcement_chapter("", "") == "skip"


def test_keep_quarter_report_with_performance():
    """quarter_report 含有业绩关键词 → keep"""
    assert _classify_announcement_chapter(
        "报告期内基金的业绩表现", "净值增长率为-11.19%", "quarter_report"
    ) == "keep"
