"""tests/test_ann_sync_script.py - 测试公告回补脚本辅助函数"""
import sys
from pathlib import Path

# 确保能正确导入 scripts 模块
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_generate_cninfo_id():
    """验证 cninfo_id 生成逻辑"""
    from scripts.sync_minishare_ann_history import generate_cninfo_id

    # 带 ann_id_suffix 时
    cninfo_id = generate_cninfo_id("000001.SZ", "20260615", "关于召开股东会的公告", "1225370308")
    assert cninfo_id == "ann_000001.SZ_20260615_1225370308"

    # 相同输入应产生相同 ID
    cninfo_id2 = generate_cninfo_id("000001.SZ", "20260615", "关于召开股东会的公告", "1225370308")
    assert cninfo_id == cninfo_id2

    # 不带 ann_id_suffix 时，使用 hash
    cninfo_id3 = generate_cninfo_id("000001.SZ", "20260615", "关于召开股东会的公告")
    assert cninfo_id3.startswith("ann_")
    # 用 hash 产生的 ID 长度: "ann_" + sha1_hex[:16] = 4 + 16 = 20
    assert len(cninfo_id3) == 20

    # 不同输入应产生不同 ID
    cninfo_id4 = generate_cninfo_id("000002.SZ", "20260615", "不同的公告", "1225370309")
    assert cninfo_id4 != cninfo_id


def test_classify_url_type():
    """验证 URL 类型分类"""
    from scripts.sync_minishare_ann_history import classify_url_type

    direct_url = "https://static.cninfo.com.cn/finalpage/2026-06-15/1225370308.PDF"
    detail_url = ("http://www.cninfo.com.cn/new/disclosure/detail"
                  "?stockCode=002695&announcementId=1222674234"
                  "&orgId=9900023215&announcementTime=2025-03-01")
    empty_url = ""
    unknown_url = "https://example.com/file.html"

    assert classify_url_type(direct_url) == "direct_pdf"
    assert classify_url_type(detail_url) == "detail_page"
    assert classify_url_type(empty_url) == "unknown"
    assert classify_url_type(unknown_url) == "unknown"


def test_classify_url_type_edge_cases():
    """验证 URL 类型分类的边界情况"""
    from scripts.sync_minishare_ann_history import classify_url_type

    # 带空格的 URL
    assert classify_url_type("  ") == "unknown"
    # 仅空格
    assert classify_url_type(" \t\n ") == "unknown"
    # None 不会调用（因为类型注解 str），但空字符串要处理
    assert classify_url_type("") == "unknown"


def test_format_duration():
    """验证持续时间格式化"""
    from scripts.sync_minishare_ann_history import format_duration

    # 60 秒
    assert format_duration(60) == "0:01:00"
    # 3661 秒
    assert format_duration(3661) == "1:01:01"
    # 0 秒
    assert format_duration(0) == "0:00:00"
    # 大数值
    assert format_duration(86400) == "24:00:00"
    # 整分钟
    assert format_duration(120) == "0:02:00"


def test_stable_id():
    """验证 _stable_id 辅助函数（相同输入相同输出）"""
    from scripts.sync_minishare_ann_history import _stable_id

    id1 = _stable_id("test", "000001.SZ", "20260615", "标题")
    id2 = _stable_id("test", "000001.SZ", "20260615", "标题")
    assert id1 == id2
    assert id1.startswith("test_")
    # "test_" + 16 hex chars = 21
    assert len(id1) == 21
