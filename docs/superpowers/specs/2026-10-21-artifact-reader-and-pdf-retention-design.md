# 产物阅读器 + 原文 PDF 保留与回补（设计稿）

- 日期：2026-10-21
- 状态：待 owner 批准
- 仓库：`QingshuiYanTou`
- owner 决定（2026-10-21 对话）：
  1. 产物（当前 = 原文 PDF + evidence 文本块，未来 = 知识图谱等）要**在一个地方**呈现，且用户友好。
  2. 「工作区」= 一次研究会话及其产物，不恢复 dsh 的 workspace 概念。
  3. **PDF 保留策略要改**：永久保留 + 全量回补，不再「抽完即删」。

## 1. 目标

1. 会话里出现的材料能在一个全屏阅读器里看完：文档章节、证据正文（引用区间高亮）、原文 PDF。
2. 原文 PDF 从 chemagent 本地盘直出，**不联网**去巨潮取。
3. 历史公告可回看：40,873 份公告的 PDF 全部保留并可回补（约 25GB）。
4. 容器可扩展：以后知识图谱等产物按 `kind` 加渲染器，不重做外壳。

## 2. 非目标 / 反目标

- 不做买卖建议、仓位、择时；阅读器只呈现材料，不给结论槽位（清水铁律）。
- 不新增 MCP 工具，不改 22 工具面。
- 不恢复 dsh workspace 概念，不改主页对话数据。
- 不做 PDF 页码定位（`kg_evidence` 无页码字段）。
- 不做多用户/权限体系；仍是本机 loopback。
- 不在云端做任何写入。
- 反目标：把 PDF 再删一次、或把「文件不存在」显示成空白——宁可明说「原文未归档」。

## 3. 实测事实（2026-10-21，chemagent + 本地）

| 事实 | 证据 |
|---|---|
| PDF 存储根 = `/data/qingshui/pdf`（容器 `.env` 的 `PDF_STORAGE_ROOT`），**目录是空的** | `backend/.env`；`ls /data/qingshui/pdf` |
| 残留 301 份 / 180MB 在 `/mnt/shared-storage-user/liweimin/qingshui/qingshui-pdfs`，结构 `notices/{ts}/{YYYY-MM}/*.pdf` | 实测 find/du |
| `source_ref.pdf_path` 指向 `/data/qingshui-pdfs/...`（已不存在）；`available: true` 是入库快照，不可信 | 实测 `GET /qingshui/evidence/EV:068b01e5...` |
| 抽取后无条件删 PDF，无年龄阈值、无配置开关，每 15 分钟一轮；构建失败/超时的记录也会被标记并删文件 | `backend/app/data_pipeline/scheduler.py:833-849`、`:1170-1177` |
| 两年轮转：每周日 02:00，只清 `kg_file_index`，`days_threshold=730` 硬编码 | `pdf_rotator.py:49-89`、`scheduler.py:108-109,863,867-878,1178` |
| 一份公告 = N 条 evidence（`source_ref.ann_id` + `chapter_index`），`total_chapters` 是**解析章节总数**，`chapter_index` 是**保留章节序号** —— 两者不可比 | `evidence_builders_simple.py:343-373` |
| 无 PDF 流端点、无文档聚合端点、无 evidence 列表端点；无 `FileResponse`；Starlette 0.38.6 的 `FileResponse` **不支持 Range** | `backend/app/**`；容器内 introspection |
| backend / data-mcp 容器**没有任何 volume**；只有 scheduler 挂了 `/data/qingshui/pdf` | `docker inspect`、`deploy/chemagent/docker-compose.yml:63-113` |
| 部署是**镜像构建**不是 bind mount；真实编排文件是 `/data/qingshui/docker-compose.yml`，与仓库副本是两份 | `docs/运维/2026-10-12-chemagent-full-migration.md:145-174` |
| `kg_evidence` 共 377,401 条，其中 **122,845 条带 `source_ref.pdf_path`**、122,520 条标 `available` —— 磁盘上只剩 301 份 | 实测 Mongo |
| 样本：600962.SH 2026-08-12 公告（ann_id 2200763），103 章，`metadata.title` = `1225468566.PDF`（标题退化为文件名） | 实测 Mongo 记录 |
| `source_ref.ann_id` 存的是 **PG 的 int**（`record.get("id")` 原样写入），Mongo 类型敏感 | `evidence_builders_simple.py:254,305,360` |
| `minishare_announcements` 40,873 行（2024-08-28 ~ 2026-10-20）；`/data` 剩 449G | PG + `df -h` |

## 4. 保留策略（chemagent 数据面）

### 4.1 统一根目录

- 所有进程的 `PDF_STORAGE_ROOT` 统一为 `/data/qingshui/pdf`：
  - `deploy/chemagent/worker_supervisor.py:24,72`（现在是 shared storage）
  - `backend/app/ops/worker_config.py:24` 默认值（现在是 `/data/qingshui-pdfs`）
- compose（仓库副本 + `/data/qingshui/docker-compose.yml` 两份都要改）给 `backend` 增加
  `/data/qingshui/pdf:/data/qingshui/pdf`；`data-mcp` 不需要（不读文件）。
- 迁移现存 301 份：shared storage → `/data/qingshui/pdf`，保持 `notices/` 子结构。
- **不改历史 `source_ref.pdf_path`**：解析器按下面的顺序找文件。PG 的 `file_path` 由回补/迁移脚本刷新。
- **解析顺序（唯一口径，接口与回补共用）**：
  1. 取 `source_ref.pdf_path` **从 `notices/`、`reports/`、`irm/` 起的那一段**（丢弃前面的任意前缀），
     拼到 canonical root 下 —— 这样不用枚举历史前缀（已知至少两种：
     `/data/qingshui-pdfs/...` 与 `/mnt/shared-storage-user/liweimin/qingshui/qingshui-pdfs/...`）。
     仓库现有的 `PATH_PREFIX_MAP`（`evidence_builders_simple.py:189-192`）只覆盖 Mac 开发路径，不复用。
  2. 找不到再试 **canonical 文件名** `notices/{ts_code}/{YYYY-MM}/{ann_id}.pdf` —— 回补统一按这个名字落盘，
     所以标题退化、`pdf_path` 缺失的 evidence 也能命中。
  3. 都没有 → `pdf.exists=false`。

### 4.2 关掉删除

- `_run_announcement_ingestion_job`：删掉 `Path(fp).unlink(...)`；`download_status='stored'`，保留 `file_path`。
- 轮转：加开关 `PDF_ROTATION_ENABLED`（默认 `false`），保留函数与 `dry_run` 供运维手工用。
- 磁盘核算：40,873 × ~0.6MB ≈ 25GB，`/data` 剩 449G。
- 已知遗留（不在本期修）：构建失败/超时的公告仍会被标记 `evidence_at`，造成知识缺章。因为文件不再删除，
  重跑只需清 `evidence_at`。记为后续项。

### 4.3 全量回补

一次性脚本 `backend/scripts/backfill_announcement_pdfs.py`：

- 选取：`minishare_announcements` 中 `evidence_at IS NOT NULL` 且目标路径无文件的记录，`ann_date DESC`。
- 下载：复用 `file_storage` 的详情页→PDF 解析（worker 那条路径不解析详情页，不能用）。
- 落盘：canonical root，**统一文件名 `{ann_id}.pdf`**（历史文件名有两套规则：
  `{ann_date}_{ts_code}_{safe_title}.pdf` 与 cninfo 的 `{id}.PDF`，无法可靠反推；统一命名后
  解析规则 2 恒定命中）。
- 回写：`file_path`（新路径）+ `download_status='stored'`；不动 evidence 文本。
- 纪律：`--dry-run` / `--limit` / `--since` / `--sleep`（默认 1s + 抖动）；文件存在即跳过（断点续跑）；
  失败重试 3 次并记账；分批日志。
- 运行方式：`docker exec qingshui_scheduler python scripts/backfill_announcement_pdfs.py ...`
  （scheduler 容器有挂载）。不新增常驻进程。

## 5. 后端只读接口（chemagent）

新增 `backend/app/knowledge/api/agent_documents.py`，前缀 `/api/v1/knowledge/documents`，
鉴权沿用 `require_api_key(x_api_key)`。

### 5.1 `GET /documents/{ann_id}`

```json
{
  "ann_id": "2200763",
  "ts_code": "600962.SH",
  "source_name": "公告:600962.SH",
  "publish_date": "2026-08-12",
  "title": null,
  "title_is_filename": true,
  "chapters_parsed": 103,
  "chapters_kept": 92,
  "pdf": { "exists": false, "sha256": "aa29...", "size": null },
  "chapters": [
    { "evidence_id": "EV:068b...", "chapter_index": 91, "heading": null, "chars": 10234 }
  ]
}
```

- 查询：`ann_id` 从路径参数接收字符串，**同时按 int 与原样字符串查**（`$in: [int(ann_id), ann_id]`），
  因为 Mongo 里存的是 PG int，历史数据可能是字符串。新增索引 `source_ref.ann_id`。
- **章节列表不返回正文**（一份 103 章文档全文 ~1MB）；正文按需走现有
  `GET /qingshui/evidence/<EV:id>`（已有客户端缓存）。
- 标题：`subject_hint.title` → `metadata.title`；若形如纯文件名（匹配 `^[\w.-]+\.(PDF|pdf)$`，
  例如 `1225468566.PDF`），置 `title_is_filename=true`、`title=null`，客户端显示
  「公告（标题缺失）」+ 文件名次要展示。
- `pdf.exists` **实时探测**（解析路径 + `os.path.exists`），不用 `available` 字段。
- 不返回任何服务器路径。无记录 → 404 `{"detail":{"code":"document_not_found"}}`。

### 5.2 `GET /documents/{ann_id}/pdf`

- 解析：按 §4.1 的两步解析顺序找文件；`Path.resolve()` 后必须仍在 root 之下
  （复用 `_sanitize_*` 思路），否则 400。
- 返回：`Content-Type: application/pdf`、`Content-Disposition: inline`、`ETag: <sha256>`、
  `Cache-Control: private, max-age=86400`。
- **手动 Range**：解析 `Range: bytes=a-b`，返回 206 + `Content-Range` + `Accept-Ranges: bytes`；
  非法 range → 416；文件缺失 → 404 `{"detail":{"code":"pdf_missing"}}`。
  （Starlette 0.38.6 `FileResponse` 不支持 Range，必须自己切块。）
- 超过 200MB 的文件拒绝（现状 0.6MB 量级，仅防御）。

### 5.3 端口/网络

沿用现有：chemagent `127.0.0.1:8001` → Mac SSH 隧道。不新增对外端口。

## 6. 插件代理（Mac dsh）

- `GET /qingshui/document/<ann_id>` → 上述文档接口。
- `GET /qingshui/pdf/<ann_id>` → 透传字节流；转发 `Range` 并回传 `206/416`、`Content-Range`、
  `Content-Type`、`Content-Length`、`ETag`。
- 两者都走 `isLoopbackHostRequest` 围栏；错误映射 403/404/502/503 与现有路由一致。
- 命名复用 `ev-route.ts` 的结构，新增 `document-route.ts`。

## 7. 前端：产物阅读器

### 7.1 落点

- 新增 `shell.overlay` 注册（dsh 的帧级浮层，`ui-layout/src/client/index.ts:75-83`），
  组件 `ArtifactReader.tsx`：全屏遮罩 + `min(1180px, 94vw) × 88vh` 面板，Esc / 背景关闭。
- 打开入口（均在已有组件上加入口，不做会话级产物清单）：
  - 回话里的 EV 引用 / 证据卡 / 判断卡（`FindingCard` 的证据锚点）上的「查看原文」；
  - 右侧 `ResearchPanel` 的「证据原文」头部加「展开」；
  - 打开时带上来源上下文：从判断卡进入则带 `supports` 的区间（用于高亮），从 EV 引用进入则只有 `evidenceId`。
- 只有 `evidenceId` 时，阅读器先用 `/qingshui/evidence/<id>` 取 `source_ref.ann_id`，再拉章节；
  没有 `ann_id`（IRM / 研报 / upload）则直接进单证据视图。

### 7.2 布局

```
┌──────────────────────────────────────────────────────────┐
│ 600962.SH · 2026-08-12 · 公告            [原文] [关闭]   │
├──────────────┬──────────────────────────┬────────────────┤
│ 章节 (92)    │ 证据正文                  │ 原文 PDF       │
│ 1  ...       │ (引用区间高亮)            │ <iframe>       │
│ ...          │                          │                │
│ 91 ●         │ 置信度 0.95 · EV:068b…    │ (可切换隐藏)   │
└──────────────┴──────────────────────────┴────────────────┘
```

- 左侧：`chapters` 列表，标签 = `chapter_index+1` + `heading`（空则显示正文首行）；点击切换中间正文。
- 中间：正文按需从 `/qingshui/evidence/<EV:id>` 取（切换章节就是换一个 id，走已有缓存）；
  显示 `置信度 / 来源类型 / evidence_id`；长文可折叠到前 40 行。
- 高亮：只在「从判断卡进入」时用该判断的 `supports[]` 区间做 `<mark>`（区间夹在文本长度内，
  越界则丢弃）；从 EV 引用进入不猜区间、不高亮。
- 右侧：`iframe src="/qingshui/pdf/<ann_id>"`，浏览器原生 PDF 阅读器；可收起让正文占满。
- 状态：
  - `pdf.exists=false` → 右侧显示「原文未归档：该公告入库时 PDF 已被清理。新公告自本次变更起会保留。」
  - 章节接口失败 → 左侧隐藏，中间退化为单条证据；正文仍可读。
  - 非公告类型 evidence（IRM / 研报 / upload）→ 无 ann_id，退化为单条证据视图（无章节、无 PDF）。

### 7.3 扩展点

- 阅读器输入统一为 `Artifact`：
  `{ kind: 'document', annId } | { kind: 'evidence', evidenceId } | { kind: 'graph', ... }`（未来）。
- 外壳（遮罩、头部、关闭、错误态）共用，`kind` 决定中间渲染器。

## 8. 验收

1. 600962.SH / ann_id 2200763：`/documents/2200763`（字符串路径参数，命中 Mongo 的 int）
   返回 `chapters_kept` 与实际条目一致；`pdf.exists=false` 时前端显示「原文未归档」，
   不显示空白 PDF 框。
2. 回补 dry-run 20 条 + 实跑 20 条后，同一接口 `pdf.exists=true`，`/pdf` 首字节 `%PDF-`。
3. `Range: bytes=0-1023` 返回 206、`Content-Range: bytes 0-1023/<size>`、长度 1024。
4. 路径逃逸（构造 `../../etc/passwd`）返回 400，且不触达文件系统。
5. 插件单测：document/pdf 路由的 403/404/502/503；`title_is_filename` 判定；高亮区间越界保护。
6. 手工：从对话点「查看原文」→ 阅读器打开 → 切换章节 → 正文与 PDF 同时可见 → Esc 关闭。

## 9. 落地顺序

1. **保留先落地**（数据面）：关 purge + 关轮转 + 统一根 + compose 挂载 + 迁移 301 份。
   这一步先做，否则后面回补的文件仍会被下一次抽取删除。
2. **后端接口**：文档聚合 + PDF 流（手动 Range）+ 索引 + 单测。镜像重建。
3. **插件代理 + 前端阅读器**：可先在无 PDF 的历史公告上验收降级态。
4. **回补**：小批量验证 → 全量（夜间、限速、断点续跑）。回补与前端并行，不阻塞 UI。

## 10. 风险与回滚

| 风险 | 处置 |
|---|---|
| 回补触发巨潮限流 | 默认 1 req/s + 抖动；失败记账可重跑；先小批量验证。 |
| 4 万份下载中断/磁盘 | 断点续跑（文件存在即跳过）；25GB 对 449G 无压力。 |
| `available` 语义失真 | UI 只信实时 `exists`；接口层不改历史字段。 |
| compose 两份不同步 | 仓库副本与 `/data/qingshui/docker-compose.yml` 同时改，改完 `docker compose config` 比对。 |
| 后端镜像重建停机 1-2 min | 低峰执行；先 `build` 再 `up -d`。 |
| 误删 | 保留策略只删「开关打开时的轮转」，默认关；回补脚本只写文件不删。 |

回滚：`PDF_ROTATION_ENABLED=true` + 恢复 purge 代码即回到旧行为（但不复原已删文件）。

## 11. 我的判断（builder calls，owner 可推翻）

1. **doc_key 用 `ann_id`**，不用 `source_id`/哈希：公告都有 ann_id，且能与 PG 对账。
2. **章节序号不换算**：`chapter_index` 是保留序号、`total_chapters` 是解析总数，UI 写
   「已保留 92 段（原文解析 103 章）」，不显示「第 92/103 段」这种会误导的比值。
3. **不引 pdf.js**：本机单用户、Chrome 原生阅读器够用，省一个依赖和一套渲染维护。
4. **不做会话级产物清单**：v1 的「一个地方」就是阅读器本身，从证据卡/判断卡/面板进入；
   不新增「列某会话产物」接口，也避免客户端反推 transcript。
5. **阅读器不做页码联动**：数据无页码，硬做只会造出错误跳转。
6. **回补脚本放 `backend/scripts/`，用 `docker exec` 跑**，不注册调度任务；回补是一次性运维。
