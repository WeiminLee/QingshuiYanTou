# IRM 与公告数据回补设计

- **日期：** 2026-06-20
- **状态：** 设计稿
- **涉及范围：** IRM 数据源统一、公告历史回补、PDF 下载适配

---

## 背景与问题

当前系统存在三条数据管道混用的混乱：

| 数据 | 问题 |
|------|------|
| **IRM（互动易）** | 同时使用 akshare（按股票全量拉）和 minishare（按天拉），两者都往 `announcements` 表写，但通过不同 checkpoint 各自维护。系统复杂度高，无统一调度。 |
| **公告 cninfo** | `fetch_announcements_history()` 用 cninfo 范围查询，被服务端截断，仅拉到 1,288 条，远不覆盖 2023 年至今。 |
| **PDF 下载** | 仅有 28 个 PDF 被下载（0.017%）。minishare 返回的公告 URL 有直接 PDF 链接和详情页链接两种格式，后者未适配。 |

---

## 任务一：IRM 数据源统一为 akshare

### 决策

- **放弃 minishare 作为 IRM 数据源**，统一使用 akshare
- minishare 的 IRM 数据仅有 2026-03 以后，而 akshare 按股票可拉全量历史（SZ 接口稳定、有 `问题编号` 唯一 ID；SH 接口无 ID，但可正常工作）
- 降低系统维护成本，保持单一数据源一致性

### 去重策略

沿用当前的 `cninfo_id` 生成方案：

```
cninfo_id = irm_{exchange}_{ts_code}_{question_time}_{q_hash}
q_hash    = MD5(question)[:10]
```

- `ON CONFLICT (cninfo_id) DO NOTHING` 兜底去重
- 重复执行幂等，不会产生重复记录

### Checkpoint 机制

维持现有 MongoDB `irm_checkpoint` collection：

```json
{
  "ts_code": "000001.SZ",
  "status": "done",
  "last_success_at": "2026-06-20T10:00:00Z",
  "last_attempt_at": "2026-06-20T10:00:00Z"
}
```

- 按 `ts_code` 唯一索引
- 20 小时窗口内已成功的股票跳过
- 此机制已存在，无需新增基础设施

### 改造内容

1. **清理 `fetcher.py` 中 minishare IRM 相关代码**（`fetch_minishare_irm`、`fetch_minishare_irm_history`）
2. **确保 `_fetch_irm_impl()` 作为唯一 IRM 入口**
3. **清理 `sync_irm_history.py` 中 minishare 模式**（仅保留 akshare 模式）
4. **可选：移除 `DataSourceClientMinishare` 中的 IRM 相关方法**（`get_irm`、`iter_irm_by_date_range*`）

---

## 任务二：公告历史回补（minishare → cninfo）

### 数据验证结论

通过实测确认：

| 特性 | 结果 |
|------|------|
| minishare `anns_d` 日期覆盖 | ✅ **2023-01 起正常返回**（测试 20230105 有数据） |
| PDF 直接链接可下载 | ✅ `static.cninfo.com.cn/finalpage/xxx.PDF` 格式，2023 年老文件也能正常下载 |
| 详情页链接需解析 | ⚠️ 返回的详情页 URL 需通过 cninfo `bulletin_detail` API 解析出真实 PDF 地址 |
| 每日公告量 | ~600~1,600 条/天 |
| 接口限速 | 80 req/min（已配置 `get_minishare_async_limiter("anns_d")`） |

### 回补方案

按天逐日遍历，日期范围 2023-01-01 ~ today。

#### 数据流

```
minishare anns_d(trade_date)
  │
  ├── 返回列表，每条含 {ann_date, ts_code, name, title, url}
  │
  ├── 关键词过滤 (announcement_filter.classify_title)
  │     ├── DOC_TYPE_SAVE → 继续
  │     └── DOC_TYPE_SKIP → 跳过
  │
  ├── URL 归一化
  │     ├── 直接 PDF → 直接下载
  │     └── 详情页 URL → 调 bulletin_detail API → 获得 PDF URL → 下载
  │
  ├── 保存到 announcements 表
  │     └── ON CONFLICT (cninfo_id) DO NOTHING
  │
  └── 保存到 minishare_announcements 表（原始记录存档）
        └── ON CONFLICT (ann_date, ts_code, title) DO NOTHING
```

### URL 归一化逻辑

新增 `resolve_pdf_url(url: str) -> str | None` 方法：

```python
def resolve_pdf_url(url: str) -> str | None:
    """将公告 URL 统一为可下载的 PDF 地址"""
    # 情况 A: 已经是 finalpage PDF 链接
    if 'finalpage' in url and url.lower().endswith('.pdf'):
        return url.replace('http://', 'https://')

    # 情况 B: 详情页 URL → 提取参数 → 调 API
    # http://www.cninfo.com.cn/new/disclosure/detail?announcementId=xxx&announceTime=xxx
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    announce_id = params.get('announcementId', [None])[0]
    announce_time = params.get('announcementTime', [None])[0]
    if announce_id and announce_time:
        resp = requests.post(
            'http://www.cninfo.com.cn/new/announcement/bulletin_detail',
            params={'announceId': announce_id, 'announceTime': announce_time, 'flag': 'true'}
        )
        if resp.ok:
            return resp.json().get('fileUrl')
    return None
```

### PDF 下载集成

将 URL 归一化逻辑接入 `FileStorage.download_notice()`，使其能处理两种 URL 格式：

```python
class FileStorage:
    def download_notice(self, url, ts_code, filename, pub_date) -> Path | None:
        resolved_url = self._resolve_pdf_url(url)
        if not resolved_url:
            return None
        # 现有下载逻辑不变...
```

### 断点续跑（Checkpoint）

复用现有的 `ingestion_checkpoints` 表（`IngestionProgressTracker`）：

- Key: `last_success_watermark`（日期字符串 YYYYMMDD）
- 每天处理完成后写入
- 下次运行从断点+1天继续

### 限速与并发

| 限制 | 值 | 说明 |
|------|-----|------|
| minishare API 限速 | 80 req/min | 已配置 `anns_d` endpoint 限速器 |
| PDF 下载限速 | 1 req/s | 复用 `get_cninfo_pdf_limiter()` |
| 日处理量 | ~1,600 条 | 逐条处理 |
| 预计总耗时 | 2023-01 ~ today ≈ 1,200 交易日 | 每条约 1s，总约 1,200s（含下载） |

### Shell 包装脚本

`sync_minishare_ann.sh`：

```bash
#!/bin/bash
# 根目录下的 sh 脚本，包装 Python 入口

set -euo pipefail

START_DATE="${1:-20230101}"
END_DATE="${2:-$(date +%Y%m%d)}"
LOG_DIR="logs/ann_sync"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/sync_${START_DATE}_${END_DATE}_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

echo "========================================"
echo "公告历史回补: ${START_DATE} ~ ${END_DATE}"
echo "日志: ${LOG_FILE}"
echo "========================================"

cd "$(dirname "$0")/backend"

python -m scripts.sync_minishare_ann_history \
    --start-date "$START_DATE" \
    --end-date "$END_DATE" \
    2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
echo ""
echo "完成，退出码: ${EXIT_CODE}"
echo "日志已保存: ${LOG_FILE}"
exit $EXIT_CODE
```

---

## 涉及修改的文件清单

| 文件 | 改动类型 | 内容 |
|------|----------|------|
| `backend/app/data_pipeline/fetcher.py` | 清理 | 移除 `fetch_minishare_irm()`, `fetch_minishare_irm_history()` |
| `backend/app/data_pipeline/fetcher.py` | 修改 | 增强 `_download_announcement_pdf()` 支持详情页 URL |
| `backend/app/data_pipeline/file_storage.py` | 新增 | 添加 `_resolve_pdf_url()` 方法 |
| `backend/app/data_pipeline/announcement_filter.py` | 保留 | 关键词过滤规则保持现状 |
| `backend/scripts/sync_minishare_ann_history.py` | 修改 | 增强为完整回补脚本（含 URL 归一化、PDF 下载） |
| `backend/scripts/sync_irm_history.py` | 清理 | 移除 minishare 模式，仅保留 akshare |
| `backend/app/data_pipeline/minishare_client.py` | 可选清理 | 移除 IRM 相关方法（`get_irm`, `iter_irm_by_date_range*`） |
| `sync_minishare_ann.sh` | **新增** | 根目录 shell 包装脚本 |
| `backend/scripts/.gitignore` | 修改 | 忽略 `logs/ann_sync/` |

---

## 不涉及变更的部分

- **`announcements` 表结构** — 现有 schema 够用，不新增字段
- **`irm_filter.py`** — 保持现状，仅在 `sync_irm_history.py` 中使用
- **`cninfo_client.py`** — 保持不变，公告回补不走 cninfo API
- **`rate_limiter.py`** — 保持不变，现有配置够用
- **`scheduler.py`** — 暂不改动，完成后再考虑更新调度任务
