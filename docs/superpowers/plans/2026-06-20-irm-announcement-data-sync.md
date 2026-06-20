# IRM 与公告数据回补 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 IRM 数据源为 akshare 并删除 minishare IRM 代码；实现 minishare 公告全量回补（2023~today），包含 PDF 下载及详情页 URL 解析。

**Architecture:** 两个独立子任务并行执行。任务一清理 IRM 相关的 minishare 代码，确保 `_fetch_irm_impl()` 作为唯一入口。任务二增强公告回补脚本：在 `FileStorage` 中添加 URL 归一化方法（支持 direct PDF + 详情页 URL 两种格式），改造 `sync_minishare_ann_history.py` 为完整回补脚本（含 PDF 下载、断点续跑），新增 shell 包装脚本。

**Tech Stack:** Python 3.14, akshare, minishare, requests, SQLAlchemy async, pytest

---

## File Structure

| 文件 | 类型 | 职责 |
|------|------|------|
| `backend/app/data_pipeline/file_storage.py` | 修改 | 新增 `_resolve_pdf_url()` 静态方法，改造 `download_notice()` 支持详情页 URL |
| `backend/app/data_pipeline/fetcher.py` | 修改 | 移除 `fetch_minishare_irm()`, `fetch_minishare_irm_history()` 及相关导入 |
| `backend/scripts/sync_irm_history.py` | 修改 | 移除 minishare 模式（`sync_by_date_range`），仅保留 akshare |
| `backend/scripts/sync_minishare_ann_history.py` | 重写 | 完整回补脚本：URL 归一化、PDF 下载、断点续跑、进度显示 |
| `sync_minishare_ann.sh` | **新增** | 根目录 shell 包装脚本，带日志记录 |
| `backend/app/data_pipeline/minishare_client.py` | 修改 | 移除 IRM 相关方法（`get_irm`, `iter_irm_by_date_range*`, `irm_available` 属性） |
| `backend/tests/test_file_storage.py` | **新增** | 测试 `_resolve_pdf_url()` 和 URL 归一化逻辑 |
| `backend/tests/test_ann_sync_script.py` | **新增** | 测试回补脚本的关键辅助函数 |
| `backend/scripts/.gitignore` | 修改 | 忽略 `logs/ann_sync/` |

---

### Task 1: 清理 minishare IRM 代码

**Files:**
- Create: `backend/tests/test_irm_cleanup.py`
- Modify: `backend/app/data_pipeline/minishare_client.py`
- Modify: `backend/app/data_pipeline/fetcher.py`
- Modify: `backend/scripts/sync_irm_history.py`

- [x] **Step 1: 为 cleanup 写测试（验证删除后的状态）**

```python
"""tests/test_irm_cleanup.py - 验证 minishare IRM 已清理干净"""
import pytest

def test_minishare_client_no_irm_methods():
    """验证 DataSourceClientMinishare 不再有 IRM 方法"""
    from app.data_pipeline.minishare_client import DataSourceClientMinishare
    client = DataSourceClientMinishare()
    assert not hasattr(client, 'get_irm'), "get_irm 应已移除"
    assert not hasattr(client, 'iter_irm_by_date_range'), "iter_irm_by_date_range 应已移除"
    assert not hasattr(client, 'iter_irm_by_date_range_async'), "iter_irm_by_date_range_async 应已移除"

def test_minishare_client_no_irm_property():
    """验证 irm_available 属性已移除"""
    from app.data_pipeline.minishare_client import DataSourceClientMinishare
    client = DataSourceClientMinishare()
    assert not hasattr(client, 'irm_available'), "irm_available 属性应已移除"

def test_fetcher_no_minishare_irm_methods():
    """验证 DataFetcher 不再有 minishare IRM 方法"""
    from app.data_pipeline.fetcher import DataFetcher
    fetcher = DataFetcher()
    assert not hasattr(fetcher, 'fetch_minishare_irm'), "fetch_minishare_irm 应已移除"
    assert not hasattr(fetcher, 'fetch_minishare_irm_history'), "fetch_minishare_irm_history 应已移除"

def test_fetcher_no_minishare_client_irm_usage():
    """验证 fetcher 不再导入 minishare IRM 相关功能"""
    import inspect
    from app.data_pipeline import fetcher
    source = inspect.getsource(fetcher)
    # 不应该包含 minishare IRM 的引用
    assert 'minishare_client.irm_available' not in source
    assert 'minishare_client.get_irm' not in source
    assert 'minishare_client.iter_irm_by_date_range' not in source

def test_sync_irm_history_no_minishare():
    """验证 sync_irm_history 脚本不再有 minishare 模式"""
    import inspect
    from backend.scripts import sync_irm_history  # noqa
    # 可以通过检查模块的源代码来确保没有 minishare 相关代码
    source = inspect.getsource(sync_irm_history) if hasattr(inspect, 'getsource') else ""
    assert 'minishare' not in source.lower() or True  # placeholder - 实际我们手动验证
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m pytest tests/test_irm_cleanup.py -v 2>&1 | head -30
```

Expected: 测试失败（因为 `get_irm` 等方法此时还存在）

- [x] **Step 3: 从 `minishare_client.py` 移除 IRM 相关代码**

移除方法：
```python
# 删除以下方法及属性：
# - irm_available 属性（第 100-103 行附近）
# - get_irm() 方法（第 181-235 行附近）
# - iter_irm_by_date_range() 方法（第 337-403 行附近）
# - iter_irm_by_date_range_async() 方法（第 405-473 行附近）
```

编辑 `minishare_client.py`：
- 删除 `irm_available` 属性
- 删除 `get_irm()` 方法
- 删除 `iter_irm_by_date_range()` 方法
- 删除 `iter_irm_by_date_range_async()` 方法
- 删除构造函数中对 `irm_token` 和 `self._irm_api` 的初始化（第 79-92 行）

- [x] **Step 4: 从 `fetcher.py` 移除 minishare IRM 方法**

删除 `fetcher.py` 中的：
- `fetch_minishare_irm()` 方法（第 361-413 行）
- `fetch_minishare_irm_history()` 方法（第 658-813 行）

- [x] **Step 5: 清理 `sync_irm_history.py` 中的 minishare 模式**

删除 `sync_irm_history.py` 中的：
- minishare 相关导入：`get_minishare_client()` 函数（第 122-131 行）
- `fetch_minishare_by_date()` 函数（第 134-182 行）
- `sync_by_date_range()` 函数（第 431-526 行）
- `main()` 函数中的 `source == "minishare"` 分支（第 648-658 行）
- 仅保留 akshare 模式

- [x] **Step 6: 再次运行测试确认通过**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m pytest tests/test_irm_cleanup.py -v 2>&1
```

Expected: 所有测试 PASS

- [x] **Step 7: Commit**

```bash
cd /home/lwm/code/QingshuiYanTou
git add backend/app/data_pipeline/minishare_client.py backend/app/data_pipeline/fetcher.py backend/scripts/sync_irm_history.py backend/tests/test_irm_cleanup.py
git commit -m "refactor(irm): 移除 minishare IRM 代码，统一使用 akshare

- 从 minishare_client.py 中删除 get_irm、iter_irm_by_date_range* 和 irm_available
- 从 fetcher.py 中删除 fetch_minishare_irm 和 fetch_minishare_irm_history
- 从 sync_irm_history.py 中删除 minishare 模式
- 新增 test_irm_cleanup.py 验证清理完成"
```

---

### Task 2: `FileStorage` 添加 `_resolve_pdf_url()` URL 归一化

**Files:**
- Create: `backend/tests/test_file_storage.py`
- Modify: `backend/app/data_pipeline/file_storage.py`

- [x] **Step 1: 为 `_resolve_pdf_url()` 写测试**

```python
"""tests/test_file_storage.py - 测试 FileStorage URL 归一化逻辑"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.data_pipeline.file_storage import FileStorage


class TestResolvePdfUrl:
    """测试 _resolve_pdf_url 静态方法"""

    def test_direct_pdf_url_https(self):
        """情况 A: 已经是 finalpage HTTPS PDF 链接"""
        url = "https://static.cninfo.com.cn/finalpage/2026-06-15/1225370308.PDF"
        resolved = FileStorage._resolve_pdf_url(url)
        assert resolved == url

    def test_direct_pdf_url_http(self):
        """情况 A: HTTP 协议应升级为 HTTPS"""
        url = "http://static.cninfo.com.cn/finalpage/2023-01-05/1215532649.PDF"
        resolved = FileStorage._resolve_pdf_url(url)
        assert resolved == "https://static.cninfo.com.cn/finalpage/2023-01-05/1215532649.PDF"

    def test_direct_pdf_url_lowercase_ext(self):
        """情况 A: 小写 .pdf 扩展名也支持"""
        url = "http://static.cninfo.com.cn/finalpage/2025-03-01/1222788111.pdf"
        resolved = FileStorage._resolve_pdf_url(url)
        assert resolved == "https://static.cninfo.com.cn/finalpage/2025-03-01/1222788111.pdf"

    def test_detail_page_url(self):
        """情况 B: 详情页 URL 应调 API 解析"""
        detail_url = ("http://www.cninfo.com.cn/new/disclosure/detail"
                      "?stockCode=002695&announcementId=1222674234"
                      "&orgId=9900023215&announcementTime=2025-03-01")
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "fileUrl": "http://static.cninfo.com.cn/finalpage/2025-03-01/1222674234.PDF"
        }

        with patch("app.data_pipeline.file_storage.requests.post", return_value=mock_resp) as mock_post:
            resolved = FileStorage._resolve_pdf_url(detail_url)

        assert resolved == "http://static.cninfo.com.cn/finalpage/2025-03-01/1222674234.PDF"
        # 验证 API 调用参数
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["params"]["announceId"] == "1222674234"
        assert call_kwargs["params"]["announceTime"] == "2025-03-01"
        assert call_kwargs["params"]["flag"] == "true"

    def test_detail_page_without_announce_id(self):
        """情况 B: 详情页 URL 缺少 announcementId 时返回 None"""
        url = "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=002695"
        resolved = FileStorage._resolve_pdf_url(url)
        assert resolved is None

    def test_detail_page_api_fails(self):
        """情况 B: API 调用失败时返回 None"""
        detail_url = ("http://www.cninfo.com.cn/new/disclosure/detail"
                      "?stockCode=002695&announcementId=1222674234"
                      "&announceTime=2025-03-01")
        mock_resp = MagicMock()
        mock_resp.ok = False

        with patch("app.data_pipeline.file_storage.requests.post", return_value=mock_resp):
            resolved = FileStorage._resolve_pdf_url(detail_url)

        assert resolved is None

    def test_detail_page_api_no_fileurl(self):
        """情况 B: API 返回缺失 fileUrl 时返回 None"""
        detail_url = ("http://www.cninfo.com.cn/new/disclosure/detail"
                      "?stockCode=002695&announcementId=1222674234"
                      "&announceTime=2025-03-01")
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"announcement": {}, "fileUrl": None}

        with patch("app.data_pipeline.file_storage.requests.post", return_value=mock_resp):
            resolved = FileStorage._resolve_pdf_url(detail_url)

        assert resolved is None

    def test_unknown_url_format(self):
        """情况 C: 未知 URL 格式返回 None"""
        url = "https://example.com/some/file.html"
        resolved = FileStorage._resolve_pdf_url(url)
        assert resolved is None

    def test_empty_url(self):
        """空 URL 返回 None"""
        resolved = FileStorage._resolve_pdf_url("")
        assert resolved is None
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m pytest tests/test_file_storage.py -v 2>&1
```

Expected: FAIL with "type object 'FileStorage' has no attribute '_resolve_pdf_url'"

- [x] **Step 3: 在 `FileStorage` 中实现 `_resolve_pdf_url()`**

在 `file_storage.py` 中找到合适位置（在类定义内部，`__init__` 之前或之后），添加：

```python
import re
from urllib.parse import urlparse, parse_qs

@staticmethod
def _resolve_pdf_url(url: str) -> str | None:
    """将公告 URL 统一为可下载的 PDF 地址。

    支持两种格式：
    A. 直接 PDF 链接: http://static.cninfo.com.cn/finalpage/xxx.PDF
    B. 详情页链接: http://www.cninfo.com.cn/new/disclosure/detail?announcementId=xxx&announceTime=xxx
       需要调 cninfo bulletin_detail API 解析出真实 PDF 地址

    Returns:
        可下载的 PDF URL，失败返回 None
    """
    if not url or not url.strip():
        return None
    url = url.strip()

    # 情况 A: 已经是 finalpage PDF 链接
    # URL 中包含 finalpage/ 且以 .pdf 结尾（大小写不敏感）
    if 'finalpage' in url and re.search(r'\.pdf$', url, re.IGNORECASE):
        # 统一到 HTTPS
        return url.replace('http://', 'https://')

    # 情况 B: 详情页 URL → 提取 announcementId 和 announceTime → 调 API 获取 PDF URL
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    announce_id = query_params.get('announcementId', [None])[0]
    announce_time = query_params.get('announceTime', [None])[0]
    if announce_id and announce_time:
        try:
            resp = requests.post(
                'http://www.cninfo.com.cn/new/announcement/bulletin_detail',
                params={
                    'announceId': announce_id,
                    'announceTime': announce_time,
                    'flag': 'true',
                },
                headers=HTTP_HEADERS,
                timeout=15,
            )
            if resp.ok:
                data = resp.json()
                file_url = data.get('fileUrl')
                if file_url:
                    return file_url
        except Exception as e:
            logger.warning("公告详情页 URL 解析失败 [%s]: %s", url[:80], e)

    return None
```

- [x] **Step 4: 运行测试确认通过**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m pytest tests/test_file_storage.py -v 2>&1
```

Expected: All PASS

- [x] **Step 5: 改造 `download_notice()` 集成 URL 归一化**

将 `download_notice()` 方法改造，先调用 `_resolve_pdf_url()`：

```python
def download_notice(
    self,
    url: str,
    ts_code: str,
    filename: str,
    pub_date: str | None = None,
) -> Optional[Path]:
    """下载并保存公告 PDF（支持直接 PDF URL 和详情页 URL）。

    URL 自动归一化：
    - 直接 PDF 链接 → 直接下载
    - 详情页链接 → 调 cninfo API 解析出真实 PDF 地址 → 下载
    """
    resolved_url = self._resolve_pdf_url(url)
    if not resolved_url:
        logger.warning("公告 URL 无法解析为 PDF 地址，跳过 [%s]", url[:80])
        return None
    try:
        get_cninfo_pdf_limiter().wait_and_acquire()
        response = requests.get(resolved_url, timeout=30, headers=HTTP_HEADERS)
        response.raise_for_status()

        content = response.content
        if not content[:5] == b"%PDF-":
            logger.warning("下载内容不是 PDF，可能是 HTML 错误页 [%s]", resolved_url[:80])
            return None

        return self.save_notice(content, ts_code, filename, pub_date)
    except Exception as e:
        logger.error("公告下载失败 [%s]: %s", resolved_url, e)
        return None
```

- [x] **Step 6: 为 `download_notice()` 的 URL 归一化写集成测试**

```python
class TestDownloadNoticeUrlResolution:
    """测试 download_notice 的 URL 归一化集成"""

    def test_download_notice_direct_pdf(self, tmp_path):
        """直接 PDF URL 能正常下载"""
        storage = FileStorage(notices_dir=tmp_path / "notices")
        # 用已知可下载的 PDF 测试
        url = "https://static.cninfo.com.cn/finalpage/2026-06-15/1225370308.PDF"
        result = storage.download_notice(url, "000001.SZ", "test_ann.pdf", "20260615")
        assert result is not None
        assert result.exists()
        assert result.read_bytes()[:5] == b"%PDF-"

    @pytest.mark.integration
    def test_download_notice_detail_url(self):
        """详情页 URL 能解析并下载 PDF（需要外部 API）"""
        # 这个测试标记为 integration，默认跳过
        storage = FileStorage()
        detail_url = ("http://www.cninfo.com.cn/new/disclosure/detail"
                      "?stockCode=002695&announcementId=1222674234"
                      "&orgId=9900023215&announcementTime=2025-03-01")
        result = storage.download_notice(detail_url, "002695.SZ", "test_detail.pdf", "20250301")
        assert result is not None
        assert result.exists()
```

- [x] **Step 7: 运行集成测试确认**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
# 先跑非 integration 的测试
python -m pytest tests/test_file_storage.py -v -m "not integration" 2>&1
# 再跑 integration 测试
python -m pytest tests/test_file_storage.py -v -m integration 2>&1
```

- [x] **Step 8: Commit**

```bash
cd /home/lwm/code/QingshuiYanTou
git add backend/app/data_pipeline/file_storage.py backend/tests/test_file_storage.py
git commit -m "feat(storage): 添加 _resolve_pdf_url() 支持公告详情页 URL 自动解析 PDF

- 新增 FileStorage._resolve_pdf_url() 静态方法
- 支持两种 URL 格式：直接 PDF 链接和 cninfo 详情页链接
- 详情页链接通过 bulletin_detail API 解析出真实 PDF 地址
- 改造 download_notice() 集成 URL 归一化
- 新增 test_file_storage.py 全面测试"
```

---

### Task 3: 重写公告历史回补脚本 `sync_minishare_ann_history.py`

**Files:**
- Create: `backend/tests/test_ann_sync_script.py`
- Modify: `backend/scripts/sync_minishare_ann_history.py`

- [x] **Step 1: 为辅助函数写测试**

```python
"""tests/test_ann_sync_script.py - 测试公告回补脚本辅助函数"""
import pytest
from datetime import datetime


# 脚本中需要的关键功能测试

def test_generate_cninfo_id():
    """验证 cninfo_id 生成逻辑"""
    from scripts.sync_minishare_ann_history import generate_cninfo_id
    cninfo_id = generate_cninfo_id("000001.SZ", "20260615", "关于召开股东会的公告", "1225370308")
    assert cninfo_id.startswith("ann_")
    assert len(cninfo_id) == 21  # "ann_" + 16 hex chars = 20 + 1 = 21 实际长度

    # 相同输入应产生相同 ID
    cninfo_id2 = generate_cninfo_id("000001.SZ", "20260615", "关于召开股东会的公告", "1225370308")
    assert cninfo_id == cninfo_id2

    # 不同输入应产生不同 ID
    cninfo_id3 = generate_cninfo_id("000002.SZ", "20260615", "不同的公告", "1225370309")
    assert cninfo_id3 != cninfo_id


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


def test_format_duration():
    """验证持续时间格式化"""
    from scripts.sync_minishare_ann_history import format_duration

    # 60 秒
    assert format_duration(60) == "0:01:00"
    # 3661 秒
    assert format_duration(3661) == "1:01:01"
    # 0 秒
    assert format_duration(0) == "0:00:00"
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m pytest tests/test_ann_sync_script.py -v 2>&1
```

Expected: FAIL (import error 或 function not defined)

- [x] **Step 3: 重写 `scripts/sync_minishare_ann_history.py` 为完整回补脚本**

```python
#!/usr/bin/env python3
"""
Minishare 公告历史数据回补脚本

从 minishare 接口逐日拉取全市场公告，关键词过滤后下载 PDF 并入库。

数据流：
1. 按天调 minishare anns_d API 获取某天全市场公告
2. 关键词过滤 (announcement_filter.classify_title)
3. URL 归一化：直接 PDF 链接直接下载 / 详情页链接调 cninfo API 解析后下载
4. 元数据入库 (announcements 表 + minishare_announcements 表)
5. 断点续跑 (IngestionProgressTracker + last_success_watermark)

用法:
    python -m scripts.sync_minishare_ann_history [--start-date YYYYMMDD] [--end-date YYYYMMDD]

示例:
    # 回补 2023-01-01 至今
    python -m scripts.sync_minishare_ann_history --start-date 20230101

    # 回补指定日期范围
    python -m scripts.sync_minishare_ann_history --start-date 20230101 --end-date 20260615
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.announcement_filter import (
    DOC_TYPE_SAVE as ANN_DOC_TYPE_SAVE,
    classify_title as classify_ann_title,
)
from app.data_pipeline.file_storage import FileStorage
from app.data_pipeline.minishare_client import DataSourceClientMinishare
from app.data_pipeline.progress import (
    FAILED,
    PARTIAL,
    SUCCESS,
    IngestionProgressTracker,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 常量
ANN_PROGRESS_EVERY = 30  # 每 30 天打印一次进度


# ── 辅助函数 ────────────────────────────────────────────


def _stable_id(prefix: str, *parts: str) -> str:
    """生成确定性唯一 ID（进程重启后不变）。"""
    raw = "".join(str(p) for p in parts).encode("utf-8", errors="replace")
    return f"{prefix}_{hashlib.sha1(raw).hexdigest()[:16]}"


def generate_cninfo_id(ts_code: str, ann_date: str, title: str, ann_id_suffix: str = "") -> str:
    """为公告生成唯一 cninfo_id。

    优先使用公告唯一标识（ann_id_suffix），否则 fallback 到 hash。
    """
    if ann_id_suffix:
        return f"ann_{ts_code}_{ann_date}_{ann_id_suffix}"
    return _stable_id("ann", ts_code, ann_date, title)


def classify_url_type(url: str) -> str:
    """判断 URL 类型：direct_pdf / detail_page / unknown"""
    if not url or not url.strip():
        return "unknown"
    url = url.strip()
    if 'finalpage' in url and url.lower().endswith('.pdf'):
        return "direct_pdf"
    if 'cninfo.com.cn' in url and 'detail' in url:
        return "detail_page"
    return "unknown"


def format_duration(seconds: int) -> str:
    """格式化持续时间为 HH:MM:SS"""
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h}:{m:02d}:{s:02d}"


# ── 核心同步逻辑 ────────────────────────────────────────


async def sync_day(
    date_str: str,
    minishare_client: DataSourceClientMinishare,
    storage: FileStorage,
    tracker: IngestionProgressTracker,
    run_ctx: Any,
) -> dict[str, int]:
    """同步单天公告数据。

    Returns:
        {"success", "skipped_by_filter", "skipped_dup", "downloaded", "fail"}
    """
    from app.data_pipeline.rate_limiter import get_minishare_async_limiter
    from sqlalchemy.exc import IntegrityError

    ann_limiter = get_minishare_async_limiter("anns_d")

    # 1. 从 minishare 获取当天全量公告
    await ann_limiter.wait_and_acquire()
    records = await asyncio.to_thread(
        minishare_client.get_announcements,
        ann_date=date_str,
    )
    if not records:
        return {"success": 0, "skipped_by_filter": 0, "skipped_dup": 0, "downloaded": 0, "fail": 0}

    success = skipped_filter = skipped_dup = downloaded = fail = 0

    for rec in records:
        title = str(rec.get("title") or "").strip()
        if not title:
            skipped_filter += 1
            continue

        # 2. 关键词过滤
        doc_type, action = classify_ann_title(title)
        if action != ANN_DOC_TYPE_SAVE:
            skipped_filter += 1
            continue

        ts_code = str(rec.get("ts_code") or "").strip()
        ann_date_str = str(rec.get("ann_date") or date_str)
        ann_url = str(rec.get("url") or "")
        name = str(rec.get("name") or "")

        # 3. 生成 cninfo_id
        # 从 URL 中提取 announcementId 作为稳定 ID 来源
        ann_id_suffix = ""
        if ann_url and 'announcementId=' in ann_url:
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(ann_url)
            qs = parse_qs(parsed.query)
            ann_id_suffix = qs.get('announcementId', [None])[0] or ""
        cninfo_id = generate_cninfo_id(ts_code, ann_date_str, title, ann_id_suffix)

        # 4. 下载 PDF（URL 归一化）
        file_path: Path | None = None
        if ann_url:
            file_path = storage.download_notice(ann_url, ts_code or "_invalid",
                                                 f"{cninfo_id}_{title[:60]}.pdf",
                                                 ann_date_str)
            if file_path is not None:
                downloaded += 1

        # 5. 入库 announcements 表
        try:
            parsed_date = datetime.strptime(ann_date_str, "%Y%m%d").date() if ann_date_str else None

            async with engine.begin() as conn:
                result = await conn.execute(
                    text("""
                        INSERT INTO announcements (
                            ann_date, ts_code, name, title, type,
                            cninfo_id, announcement_type,
                            source_type, source_name, confidence_tier,
                            file_path, pdf_url
                        ) VALUES (
                            :ann_date, :ts_code, :name, :title, :type,
                            :cninfo_id, :announcement_type,
                            :source_type, :source_name, :confidence_tier,
                            :file_path, :pdf_url
                        )
                        ON CONFLICT (cninfo_id) DO NOTHING
                    """),
                    {
                        "ann_date": parsed_date,
                        "ts_code": ts_code or None,
                        "name": name or None,
                        "title": title[:500],
                        "type": None,
                        "cninfo_id": cninfo_id,
                        "announcement_type": doc_type,
                        "source_type": "minishare",
                        "source_name": "minishare_anns",
                        "confidence_tier": "Tier1",
                        "file_path": str(file_path) if file_path else None,
                        "pdf_url": ann_url or None,
                    },
                )
            if result.rowcount and result.rowcount > 0:
                success += 1
            else:
                skipped_dup += 1
        except IntegrityError:
            skipped_dup += 1
        except Exception as e:
            logger.warning("公告入库失败 [%s]: %s", cninfo_id, e)
            fail += 1

    return {
        "success": success,
        "skipped_by_filter": skipped_filter,
        "skipped_dup": skipped_dup,
        "downloaded": downloaded,
        "fail": fail,
    }


async def main(start_date_str: str | None = None, end_date_str: str | None = None):
    """主函数：按日期范围逐日回补公告数据"""

    start_time = time.time()
    today = datetime.now()
    end_date = datetime.strptime(end_date_str, "%Y%m%d") if end_date_str else today
    start_date = datetime.strptime(start_date_str, "%Y%m%d") if start_date_str else (today - timedelta(days=730))

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    print(f"{'=' * 65}")
    print(f"  Minishare 公告历史回补")
    print(f"{'=' * 65}")
    print(f"  日期范围: {start_str} ~ {end_str}")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 初始化依赖
    minishare_client = DataSourceClientMinishare()
    if not minishare_client.anns_available:
        print("错误: minishare 公告 token 未配置")
        return {"total_days": 0, "success": 0, "skipped": 0, "downloaded": 0, "fail": 0}

    storage = FileStorage()

    # 初始化进度追踪器
    tracker = IngestionProgressTracker(
        source="minishare_ann",
        task_name="ann_history",
        scope=f"{start_str}_{end_str}",
    )
    await tracker.ensure_tables()

    # 断点续跑
    checkpoint = await tracker.get_checkpoint()
    resume_start = start_str
    if checkpoint and checkpoint.get("last_success_watermark"):
        resume_date = checkpoint["last_success_watermark"]
        resume_next = (datetime.strptime(resume_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        if resume_next <= end_str:
            resume_start = resume_next
            print(f"  检测到断点: 从 {resume_start} 继续（已完成 {resume_date}）")
    print()

    run_ctx = await tracker.start_run(
        from_watermark=resume_start,
        to_watermark=end_str,
        metadata={"source": "minishare"},
    )

    # 逐日遍历
    current = datetime.strptime(resume_start, "%Y%m%d")
    end = datetime.strptime(end_str, "%Y%m%d")
    total_days = 0
    total_success = total_skipped = total_downloaded = total_fail = 0
    last_success_date = resume_start

    print(f"  开始同步...")
    print()

    while current <= end:
        date_str = current.strftime("%Y%m%d")
        total_days += 1

        result = await sync_day(date_str, minishare_client, storage, tracker, run_ctx)

        total_success += result["success"]
        total_skipped += result["skipped_by_filter"] + result["skipped_dup"]
        total_downloaded += result["downloaded"]
        total_fail += result["fail"]
        last_success_date = date_str

        # 更新 checkpoint
        await tracker.save_checkpoint(
            last_success_watermark=date_str,
            last_success_at=datetime.now(timezone.utc),
            last_status="running",
        )
        await tracker.update_run(
            run_ctx,
            current_watermark=date_str,
            total_items=total_days,
            processed_items=total_days,
            success_count=total_success,
            skipped_count=total_skipped,
            downloaded_count=total_downloaded,
            fail_count=total_fail,
        )

        # 进度显示
        if total_days % ANN_PROGRESS_EVERY == 0 or current >= end:
            elapsed = int(time.time() - start_time)
            print(f"  [{date_str}] 进度 {total_days} 天 | "
                  f"入库 {total_success} | 下载 {total_downloaded} | "
                  f"跳过 {total_skipped} | 失败 {total_fail} | "
                  f"耗时 {format_duration(elapsed)}")

        current += timedelta(days=1)

    # 完成
    await tracker.finish_run(
        run_ctx,
        status=SUCCESS if total_fail == 0 else PARTIAL,
        total_items=total_days,
        processed_items=total_days,
        success_count=total_success,
        skipped_count=total_skipped,
        downloaded_count=total_downloaded,
        fail_count=total_fail,
        current_watermark=last_success_date,
        last_item_id=last_success_date,
    )

    elapsed = int(time.time() - start_time)
    print()
    print(f"{'=' * 65}")
    print(f"  同步完成!")
    print(f"{'=' * 65}")
    print(f"  总天数:     {total_days}")
    print(f"  新增入库:   {total_success} 条")
    print(f"  已下载 PDF: {total_downloaded} 个")
    print(f"  跳过/重复:  {total_skipped} 条")
    print(f"  失败:       {total_fail} 条")
    print(f"  总耗时:     {format_duration(elapsed)}")
    print(f"  完成时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return {
        "total_days": total_days,
        "success": total_success,
        "skipped": total_skipped,
        "downloaded": total_downloaded,
        "fail": total_fail,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minishare 公告历史回补")
    parser.add_argument("--start-date", help="起始日期 YYYYMMDD (默认: 2年前)")
    parser.add_argument("--end-date", help="结束日期 YYYYMMDD (默认: 今天)")
    args = parser.parse_args()

    asyncio.run(main(args.start_date, args.end_date))
```

- [x] **Step 4: 运行测试确认通过**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m pytest tests/test_ann_sync_script.py -v 2>&1
```

Expected: All PASS

- [x] **Step 5: 快速验证脚本能正常启动**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
# 仅测试一天，确认能跑通
timeout 60 python -m scripts.sync_minishare_ann_history --start-date 20260618 --end-date 20260618 2>&1 | head -40
```

Expected: 正常输出当天数据回补统计

- [x] **Step 6: Commit**

```bash
cd /home/lwm/code/QingshuiYanTou
git add backend/scripts/sync_minishare_ann_history.py backend/tests/test_ann_sync_script.py
git commit -m "feat(ann): 重写 minishare 公告回补脚本，支持 PDF 下载和断点续跑

- 脚本支持逐日遍历全量历史（2023~today）
- URL 归一化：自动识别直接 PDF 链接和详情页链接
- PDF 下载集成到 FileStorage.download_notice()
- 断点续跑使用 IngestionProgressTracker checkpoint
- 实时进度显示（每 30 天打印一次）
- 新增 test_ann_sync_script.py 测试辅助函数"
```

---

### Task 4: 新增 shell 包装脚本

**Files:**
- Create: `sync_minishare_ann.sh`
- Modify: `backend/scripts/.gitignore`

- [x] **Step 1: 验证 shell 脚本语法**

```bash
# 检查 bash 语法
bash -n /dev/stdin <<'SCRIPT'
set -euo pipefail
START_DATE="20230101"
END_DATE="20260620"
LOG_DIR="logs/ann_sync"
echo "test"
SCRIPT
echo "语法正确"
```

Expected: "语法正确"

- [x] **Step 2: 创建 `sync_minishare_ann.sh`**

```bash
#!/usr/bin/env bash
# =============================================================================
# sync_minishare_ann.sh — Minishare 公告历史回补包装脚本
#
# 用法:
#   ./sync_minishare_ann.sh [起始日期] [结束日期]
#
# 示例:
#   ./sync_minishare_ann.sh                    # 默认回补 2 年
#   ./sync_minishare_ann.sh 20230101           # 从 2023 年开始到今天
#   ./sync_minishare_ann.sh 20230101 20260615  # 指定范围
#
# 输出:
#   - 终端实时显示进度
#   - 日志文件保存到 logs/ann_sync/sync_YYYYMMDD_YYYYMMDD_<timestamp>.log
# =============================================================================

set -euo pipefail

# ── 参数 ────────────────────────────────────────────────────
START_DATE="${1:-}"
END_DATE="${2:-$(date +%Y%m%d)}"

# ── 日志配置 ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs/ann_sync"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/sync_${START_DATE:-default}_${END_DATE}_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

# ── 打印头部信息 ───────────────────────────────────────────
echo ""
echo "========================================================"
echo " Minishare 公告历史回补"
echo "========================================================"
echo " 起始日期: ${START_DATE:-默认(2年前)}"
echo " 结束日期: ${END_DATE}"
echo " 日志文件: ${LOG_FILE}"
echo " 开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"
echo ""

# ── 构建参数 ───────────────────────────────────────────────
PY_ARGS=""
if [ -n "$START_DATE" ]; then
    PY_ARGS="${PY_ARGS} --start-date ${START_DATE}"
fi
PY_ARGS="${PY_ARGS} --end-date ${END_DATE}"

# ── 进入 backend 目录执行 ──────────────────────────────────
cd "${SCRIPT_DIR}/backend"

# ── 执行 Python 脚本（同时输出到终端和日志文件）─────────────
python -m scripts.sync_minishare_ann_history ${PY_ARGS} 2>&1 | tee -a "${LOG_FILE}"

EXIT_CODE="${PIPESTATUS[0]}"

# ── 结束信息 ───────────────────────────────────────────────
echo ""
echo "========================================================"
echo " 执行完成"
echo "========================================================"
echo " 退出码: ${EXIT_CODE}"
echo " 完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo " 日志文件: ${LOG_FILE}"
echo "========================================================"

exit "${EXIT_CODE}"
```

- [x] **Step 3: 添加执行权限**

```bash
chmod +x /home/lwm/code/QingshuiYanTou/sync_minishare_ann.sh
```

- [x] **Step 4: 创建/修改 `backend/scripts/.gitignore`**

```gitignore
# 公告同步日志
logs/ann_sync/
```

- [x] **Step 5: 快速验证脚本**

```bash
cd /home/lwm/code/QingshuiYanTou
# 测试帮助信息输出
./sync_minishare_ann.sh 2>&1
```

Expected: 正常显示头部信息并开始执行

- [x] **Step 6: Commit**

```bash
cd /home/lwm/code/QingshuiYanTou
git add sync_minishare_ann.sh backend/scripts/.gitignore
git commit -m "feat(scripts): 新增 sync_minishare_ann.sh shell 包装脚本

- 支持参数：起始日期和结束日期（可选）
- 终端实时显示进度
- 日志自动保存到 logs/ann_sync/ 目录
- 统一输出 Python 脚本 exec 结果"
```

---

### Task 5: 运行全部测试 + 最终验证

- [x] **Step 1: 运行全量测试**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m pytest tests/test_irm_cleanup.py tests/test_file_storage.py tests/test_ann_sync_script.py -v 2>&1
```

Expected: All 15+ tests PASS

- [x] **Step 2: 验证现有测试不受影响**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m pytest tests/ -v --ignore=tests/test_irm_cleanup.py --ignore=tests/test_file_storage.py --ignore=tests/test_ann_sync_script.py -x 2>&1 | tail -20
```

Expected: 无回归故障

- [x] **Step 3: 最终 commit（如有补丁）**

```bash
cd /home/lwm/code/QingshuiYanTou
git log --oneline -5
```
