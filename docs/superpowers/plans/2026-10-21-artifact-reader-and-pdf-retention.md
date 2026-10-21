# 产物阅读器 + 原文 PDF 保留与回补 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能在一个阅读器里看会话材料的文档章节、证据正文（引用区间高亮）和原文 PDF，并把 PDF「抽完即删」改成永久保留 + 全量回补。

**Architecture:** chemagent 数据面新增两个只读接口（文档聚合、PDF 流），PDF 从 canonical 根 `/data/qingshui/pdf` 直出；Mac 侧 plugin 做 loopback 代理，浏览器经 `shell.overlay` 打开一个三栏阅读器。保留策略先在采集链关掉删除，再由一次性脚本回补历史文件。

**Tech Stack:** FastAPI 0.115 / Starlette 0.38.6（无 Range，需手写）、Motor、APScheduler；TypeScript + React、tsdown、node:test；dsh slot `shell.overlay`。

**Spec:** `docs/superpowers/specs/2026-10-21-artifact-reader-and-pdf-retention-design.md`

## Global Constraints

- 清水只出研究结论，阅读器里**不得**出现买入/卖出/仓位/择时槽位。
- 生产数据面只在 chemagent；云端 `124.221.188.38` 只读冻结，禁止任何写入。
- 不可重建数据落 `/data`；PDF 根统一 `/data/qingshui/pdf`。
- 浏览器取数只经 loopback 代理路由，API key 不得进浏览器；所有新路由必须过 `isLoopbackHostRequest`。
- 接口**不返回服务器路径**。
- 不新增 MCP 工具（工具面保持 22）。
- 页码定位不做；`chapter_index`（保留序号）与 `total_chapters`（解析总数）不得换算成「第 N/M 段」。
- 后端测试：`cd backend && .venv/bin/python -m pytest tests/<file> -q`。
- 插件测试：`npm run test:plugin`；构建：`npm run build:plugin`。
- 提交信息用仓库现有 `feat|fix|docs|test(scope): ...` 风格。

## Review Focus

- 证据正文里出现 `<` `&` 或极长行时，高亮渲染不能破坏 markdown / 不能注入 HTML —— 高亮只切纯文本片段，不拼 HTML 字符串。
- `pdf_path` 里带 `..`、绝对路径逃逸或空 basename 时，PDF 接口必须 400/404，绝不读到根外文件。
- `Range` 头畸形（`bytes=abc`、`bytes=999999999-`、多段 range）时不能崩，按 416 处理。
- 历史 evidence 的 `ann_id` 可能是字符串、`pdf_path` 可能是两种前缀；接口对两种都要命中。
- 回补脚本重跑时不得重复下载、不得覆盖不同公告的文件、不得删除任何已有文件。

---

## Part A · chemagent 数据面

### Task A1: PDF 路径解析器

**Files:**
- Create: `backend/app/knowledge/pdf_store.py`
- Test: `backend/tests/test_pdf_store.py`

**Interfaces:**
- Produces:
  - `STORAGE_SEGMENTS: tuple[str, ...] = ("notices", "reports", "irm")`
  - `strip_to_storage_tail(stored_path: str | None) -> str | None` —— 返回从 `notices|reports|irm` 起的那段 POSIX 相对路径；没有该段返回 `None`。
  - `canonical_pdf_relpath(ts_code: str, ann_date: str | None, ann_id: str | int) -> str` —— `notices/{ts}/{YYYY-MM}/{ann_id}.pdf`；`ann_date` 接受 `YYYYMMDD` 或 `YYYY-MM-DD`，无法解析则 `YYYY-MM` 用 `unknown`；`ts_code` 只保留 `[A-Za-z0-9._-]`。
  - `resolve_pdf_path(stored_path, *, ts_code, ann_date, ann_id, root) -> Path | None` —— 先试 `strip_to_storage_tail`，再试 canonical；每个候选都要 `resolve()` 后位于 `root.resolve()` 之下且是文件，否则跳过。

- [ ] **Step 1: 写失败测试**

```python
def test_resolves_both_legacy_prefixes(tmp_path):
    # stored 前缀分别是 /data/qingshui-pdfs 和 /mnt/shared-storage-user/.../qingshui-pdfs
    # 两种 stored_path 都指向同一个 root/notices/600962.SH/2026-08/1225468566.PDF
    assert resolve_pdf_path(stored, ts_code="600962.SH", ann_date="20260812", ann_id=2200763, root=tmp_path) == expected

def test_falls_back_to_canonical_ann_id_filename(tmp_path):
    # stored_path=None，磁盘上只有 notices/600962.SH/2026-08/2200763.pdf
    assert resolve_pdf_path(None, ..., root=tmp_path) == expected

def test_rejects_traversal_and_missing(tmp_path):
    assert resolve_pdf_path("/x/notices/../../etc/passwd", ...) is None
    assert resolve_pdf_path("/x/notices/a/b/none.pdf", ...) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_store.py -q`
Expected: `ModuleNotFoundError: app.knowledge.pdf_store`

- [ ] **Step 3: 实现 `pdf_store.py`**

用 `PurePosixPath` 切段、`Path.resolve()` + `is_relative_to()` 做边界检查；不做任何文件遍历或 glob。

- [ ] **Step 4: 跑测试确认通过**

Run: 同 Step 2。Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add backend/app/knowledge/pdf_store.py backend/tests/test_pdf_store.py
git commit -m "feat(knowledge): resolve retained PDFs across legacy roots"
```

### Task A2: 保留策略（不再删 + 轮转开关）

**Files:**
- Modify: `backend/app/data_pipeline/scheduler.py:833-849`（删除 unlink、改状态）
- Modify: `backend/app/data_pipeline/scheduler.py:863-878`（轮转开关）
- Modify: `backend/app/config.py:105` 附近（新增 `pdf_rotation_enabled`）
- Test: `backend/tests/test_pdf_retention.py`

**Interfaces:**
- Produces:
  - `async def finalize_announcement_batch(records: list[dict[str, Any]], execute: Callable[[str, dict[str, Any]], Awaitable[Any]]) -> int` —— 执行 `UPDATE minishare_announcements SET evidence_at = now(), download_status = 'stored' WHERE id = ANY(:ids)`，返回处理条数；**不触碰文件系统**。
  - `settings.pdf_rotation_enabled: bool = False`（env `PDF_ROTATION_ENABLED`）。
  - `add_pdf_rotation_job(scheduler)` 在开关关闭时直接返回。

- [ ] **Step 1: 写失败测试**

```python
async def test_finalize_keeps_pdf_and_marks_stored(tmp_path):
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF-1.4")
    seen: list[tuple[str, dict]] = []
    async def execute(sql, params): seen.append((sql, params))
    n = await finalize_announcement_batch([{"id": 7, "file_path": str(pdf)}], execute)
    assert n == 1
    assert pdf.exists()
    assert "download_status = 'stored'" in seen[0][0]
    assert "file_path = NULL" not in seen[0][0]

def test_rotation_job_is_off_by_default(monkeypatch):
    # 用一个只记录 add_job 的假 scheduler
    monkeypatch.setattr(settings, "pdf_rotation_enabled", False, raising=False)
    add_pdf_rotation_job(fake); assert fake.jobs == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_retention.py -q`

- [ ] **Step 3: 实现**

把调度任务里的内联 UPDATE 与 unlink 抽成 `finalize_announcement_batch`，docstring 写明「保留 PDF 是有意为之，见设计稿 §4.2」；`config.py` 加字段；`add_pdf_rotation_job` 首行 `if not settings.pdf_rotation_enabled: return`。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_retention.py tests/data_pipeline -q`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add backend/app/data_pipeline/scheduler.py backend/app/config.py backend/tests/test_pdf_retention.py
git commit -m "feat(pipeline): retain announcement PDFs after evidence build"
```

### Task A3: 统一 PDF 根目录

**Files:**
- Modify: `backend/app/ops/worker_config.py:24`
- Modify: `deploy/chemagent/worker_supervisor.py:24,72`
- Modify: `deploy/chemagent/docker-compose.yml`（backend 加 volume）
- Test: `backend/tests/test_pdf_storage_root.py`

**Interfaces:**
- Produces: 所有进程的默认根 = `/data/qingshui/pdf`；`backend` 容器挂载 `/data/qingshui/pdf:/data/qingshui/pdf`。

- [ ] **Step 1: 写失败测试**

```python
def test_worker_config_default_root():
    assert WorkerConfig.pdf_storage_root == "/data/qingshui/pdf"

def test_compose_mounts_pdf_volume_into_backend():
    compose = yaml.safe_load(Path("deploy/chemagent/docker-compose.yml").read_text())
    assert "/data/qingshui/pdf:/data/qingshui/pdf" in compose["services"]["backend"]["volumes"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_storage_root.py -q`

- [ ] **Step 3: 改配置与编排**

`worker_config.py` 默认改 `/data/qingshui/pdf`；`worker_supervisor.py` 两处 `PDF_STORAGE_ROOT` 改同一路径；compose 的 `backend.volumes` 加挂载（`data-mcp` 不加）。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git commit -am "feat(deploy): pin PDF storage root to /data/qingshui/pdf"
```

> 上线时仓库副本与 `/data/qingshui/docker-compose.yml` **两份都要改**（见 Task C1）。

### Task A4: 文档聚合服务

**Files:**
- Create: `backend/app/knowledge/document_service.py`
- Test: `backend/tests/test_document_service.py`

**Interfaces:**
- Produces:
  - `FILENAME_TITLE_RE = re.compile(r"^[\w.-]+\.(?:pdf|PDF)$")`
  - `classify_title(title: str | None) -> tuple[str | None, bool]`
  - `ann_id_variants(ann_id: str) -> list[object]` —— 纯数字时 `[int, str]`，否则 `[str]`。
  - `build_document_response(rows: list[dict[str, Any]], *, root: Path | str) -> dict[str, Any] | None`
    返回键：`ann_id` `ts_code` `source_name` `publish_date` `title` `title_is_filename` `chapters_parsed` `chapters_kept` `pdf{exists,sha256,size}` `chapters[{evidence_id,chapter_index,heading,chars}]`；`chapters` 按 `chapter_index` 升序；`chapters_parsed` 取 `total_chapters` 最大值，`chapters_kept = len(rows)`。
  - `async def load_document(db, ann_id: str, *, root: Path | str) -> dict | None` —— `db.kg_evidence.find({"source_ref.ann_id": {"$in": ann_id_variants(ann_id)}})`。
  - `async def load_pdf_path(db, ann_id: str, *, root: Path | str) -> Path | None`
  - `async def ensure_document_indexes(db) -> None` —— 建 `source_ref.ann_id`。
  - `parse_range(header: str | None, size: int) -> tuple[int, int] | None` —— `None` 表示整文件；不合法抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

```python
def test_builds_document_from_evidence_rows(tmp_path):
    rows = [ ...两条 chapter_index 91/92，total_chapters 103... ]
    doc = build_document_response(rows, root=tmp_path)
    assert doc["chapters_kept"] == 2 and doc["chapters_parsed"] == 103
    assert doc["chapters"][0]["chapter_index"] == 91
    assert doc["pdf"]["exists"] is False

def test_filename_title_is_not_a_title():
    assert classify_title("1225468566.PDF") == (None, True)
    assert classify_title("关于重大资产重组的公告") == ("关于重大资产重组的公告", False)

def test_ann_id_variants_covers_int_and_str():
    assert ann_id_variants("2200763") == [2200763, "2200763"]
    assert ann_id_variants("EV:abc") == ["EV:abc"]

@pytest.mark.parametrize("header,size,expected", [
    (None, 100, None), ("bytes=0-9", 100, (0, 9)),
    ("bytes=90-", 100, (90, 99)), ("bytes=-10", 100, (90, 99)),
])
def test_parse_range(header, size, expected): assert parse_range(header, size) == expected

def test_parse_range_rejects_bad_input():
    for bad in ("bytes=abc", "bytes=200-300", "bytes=5-1", "items=0-1"):
        with pytest.raises(ValueError): parse_range(bad, 100)
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现（`rows` 全是普通 dict，不依赖 Motor；`load_*` 只做查询）**
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat(knowledge): aggregate announcement chapters into a document view`

### Task A5: 文档接口

**Files:**
- Create: `backend/app/knowledge/api/agent_documents.py`
- Modify: `backend/app/main.py:177-186`（include router）
- Test: `backend/tests/test_agent_documents_api.py`

**Interfaces:**
- Produces: `router = APIRouter(prefix="/api/v1/knowledge/documents", tags=["知识 文档"])`；
  `GET /{ann_id}` → 200 文档 JSON / 401 / 404 `{"detail":{"code":"document_not_found"}}`。
- Consumes: `load_document`、`settings.pdf_storage_root`、`require_api_key`。

- [ ] **Step 1: 写失败测试**（TestClient + `monkeypatch.setattr(agent_documents, "load_document", fake)`；断言 200 形状、401 无 key、404 不存在）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**——鉴权用 `Header(default=None)` + `require_api_key`，与 `worker_jobs.py:31-33` 一致；`root=settings.pdf_storage_root`。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat(knowledge): expose read-only document endpoint`

### Task A6: PDF 流接口（手动 Range）

**Files:**
- Modify: `backend/app/knowledge/api/agent_documents.py`（加 `/pdf`）
- Test: `backend/tests/test_agent_documents_pdf_api.py`

**Interfaces:**
- Produces: `GET /{ann_id}/pdf` →
  - 200 整文件 / 206 分段（`Content-Range: bytes a-b/size`、`Accept-Ranges: bytes`）
  - 416（`Content-Range: bytes */size`）/ 404 `{"detail":{"code":"pdf_missing"}}` / 400 `{"detail":{"code":"pdf_path_invalid"}}` / 401
  - 头固定 `Content-Type: application/pdf`、`Content-Disposition: inline`、`ETag: "<sha256>"`、`Cache-Control: private, max-age=86400`；>200MB 返回 413。

- [ ] **Step 1: 写失败测试**（临时文件写 `%PDF-1.4` + 若干字节，monkeypatch `load_pdf_path`；断言 200 字节、`Range: bytes=0-1023` → 206 且长度 1024、`Range: bytes=999999-` → 416、缺文件 404）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**——用 `parse_range` + `StreamingResponse`，按 `seek(start)` 分块 `read(64*1024)`；不整文件读入内存。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat(knowledge): stream retained PDFs with range support`

### Task A7: 回补脚本

**Files:**
- Create: `backend/scripts/backfill_announcement_pdfs.py`
- Test: `backend/tests/test_backfill_pdfs.py`

**Interfaces:**
- Produces:
  - `backfill_target_path(ts_code, ann_date, ann_id, root) -> Path` —— canonical 命名。
  - `plan_download(candidate: dict[str, Any], root: Path | str) -> str` —— 目标文件已存在返回 `"skip"`，否则 `"download"`（幂等闸门）。
  - `build_candidates_sql() -> str` —— `SELECT id, ts_code, ann_date, title, source_url, file_path FROM minishare_announcements WHERE evidence_at IS NOT NULL AND (file_path IS NULL OR file_path = '') [AND ann_date >= :since] ORDER BY ann_date DESC LIMIT :limit`。
  - `async def run(*, dry_run: bool, limit: int | None, since: str | None, sleep_s: float) -> dict[str, int]` —— 计数 `{"candidates","downloaded","skipped","failed"}`。
  - CLI flags：`--dry-run --limit --since --sleep --ann-ids`。

- [ ] **Step 1: 写失败测试**

```python
def test_target_path_is_canonical(tmp_path):
    assert backfill_target_path("600962.SH", "20260812", 2200763, tmp_path) == \
        tmp_path / "notices" / "600962.SH" / "2026-08" / "2200763.pdf"

def test_candidates_sql_only_targets_purged_rows():
    sql = build_candidates_sql()
    assert "evidence_at IS NOT NULL" in sql and "ORDER BY ann_date DESC" in sql

def test_plan_download_is_idempotent(tmp_path):
    cand = {"id": 2200763, "ts_code": "600962.SH", "ann_date": "20260812"}
    assert plan_download(cand, tmp_path) == "download"
    target = backfill_target_path("600962.SH", "20260812", 2200763, tmp_path)
    target.parent.mkdir(parents=True); target.write_bytes(b"%PDF-1.4")
    assert plan_download(cand, tmp_path) == "skip"
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**——下载复用 `FileStorage().download_notice(url, ts_code, filename, pub_date)`，但**落盘前**把文件名改成 `{ann_id}.pdf`（`download_notice` 的 `filename` 参数即可控制）；成功后 `UPDATE ... SET file_path=:p, download_status='stored'`；失败重试 3 次；文件已存在直接 `skipped`；`--dry-run` 只打印候选。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat(scripts): backfill purged announcement PDFs`

---

## Part B · 本地交互层

### Task B1: 插件代理路由（文档 + PDF）

**Files:**
- Create: `plugins/qingshui/src/document-route.ts`
- Modify: `plugins/qingshui/src/knowledge-client.ts`（加 `fetchDocument`、`openDocumentPdf`）
- Modify: `plugins/qingshui/src/index.ts`（注册 + dispose）
- Test: `plugins/qingshui/src/document-route.test.ts`

**Interfaces:**
- Produces:
  - `DOCUMENT_ROUTE_PATH = '/qingshui/document'`、`PDF_ROUTE_PATH = '/qingshui/pdf'`
  - `installDocumentRoute(webCtx, deps)`、`installPdfRoute(webCtx, deps)`，`deps: { client: () => KnowledgeClient | undefined }`
  - `KnowledgeClient.fetchDocument(annId: string): Promise<Record<string, unknown>>`
  - `KnowledgeClient.openDocumentPdf(annId: string, range?: string): Promise<Response>`
- Consumes: `isLoopbackHostRequest`（`ev-route.ts`）。

- [ ] **Step 1: 写失败测试**（照 `ledger-route.test.ts` 的 `capture()`/`call()` 写法：403 非 loopback、503 无 client、404 透传、502 包装错误；PDF 路由断言 `Range` 被转发、`206`/`Content-Range` 原样回写、客户端缺失 503）
- [ ] **Step 2: 跑测试确认失败**

Run: `npm run test:plugin`
Expected: 找不到 `./document-route.ts`

- [ ] **Step 3: 实现**——两条路由用 `kind: 'prefix'`，`path.slice(PATH.length)` 取 id 并 `decodeURIComponent`；PDF 路由用 `Readable.fromWeb(response.body)` 管道到 `res`。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat(plugin): proxy document and PDF routes`

### Task B2: 产物状态与纯函数

**Files:**
- Create: `plugins/qingshui/src/client/artifact-store.ts`
- Test: `plugins/qingshui/src/client/artifact-store.test.ts`

**Interfaces:**
- Produces:
  - `type ArtifactSpan = { start: number; end: number }`
  - `type Artifact = { kind: 'document'; annId: string; evidenceId?: string; spans?: ArtifactSpan[] } | { kind: 'evidence'; evidenceId: string; spans?: ArtifactSpan[] }`
  - `openArtifact(a: Artifact): void`、`closeArtifact(): void`、`getArtifactState(): { artifact?: Artifact }`、`subscribeArtifact(fn: () => void): () => void`
  - `clampSpans(spans: ArtifactSpan[] | undefined, length: number): ArtifactSpan[]` —— 丢弃越界/倒序/非整数区间，按 start 升序合并重叠。
  - `splitBySpans(text: string, spans: ArtifactSpan[]): { text: string; marked: boolean }[]` —— 纯文本切片，**不生成 HTML**。
  - `chapterLabel(chapter: { chapter_index: number; heading: string | null }): string`

- [ ] **Step 1: 写失败测试**（open/close 通知、`clampSpans` 越界与重叠、`chapterLabel` 空 heading 回退；
  `splitBySpans("a<script>x</script>b", [{start:1,end:8}])` 里 `<script>` 只作为**文本**留在片段中，
  且拼回原文与输入全等）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（模块级 store，结构对齐 `ev-cite-store.ts`）
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat(client): add artifact reader state`

### Task B3: 阅读器组件

**Files:**
- Create: `plugins/qingshui/src/client/ArtifactReader.tsx`
- Modify: `plugins/qingshui/src/client/theme.ts`（`.qs-art*` 样式）
- Test: 无独立测试文件（组件行为在 Task B4 之后手工验收；纯逻辑已在 B2 覆盖）

**Interfaces:**
- Consumes: `artifact-store`、`GET /qingshui/document/<annId>`、`GET /qingshui/evidence/<EV:id>`、`GET /qingshui/pdf/<annId>`、`clampSpans`、`chapterLabel`。
- Produces: `export function ArtifactReader(): React.ReactElement | null`（无 artifact 时返回 `null`）。

- [ ] **Step 1: 实现骨架**——遮罩 + `min(1180px, 94vw) × 88vh`；Esc 与背景点击关闭；`role="dialog" aria-modal="true"`；打开时焦点移入、关闭时还原。
- [ ] **Step 2: 左栏章节**——`/qingshui/document` 拉到 `chapters`；当前项高亮；点击切换 `evidenceId`。
- [ ] **Step 3: 中栏正文**——`/qingshui/evidence/<id>` 取 `text_excerpt`；`clampSpans` 后按纯文本切片渲染 `<mark>`（**不拼 HTML 字符串**）；显示置信度/来源类型/evidence_id；默认折叠 40 行。
- [ ] **Step 4: 右栏 PDF**——`iframe src="/qingshui/pdf/<annId>"`，可收起；`pdf.exists === false` 时显示「原文未归档：该公告入库时 PDF 已被清理，新公告自本次变更起会保留」。
- [ ] **Step 5: 降级与错误**——无 `annId` → 单证据视图；document 接口失败 → 隐藏左栏；evidence 加载失败 → 重试按钮。
- [ ] **Step 6: 样式**——三栏栅格、`@media (max-width: 1100px)` 收起 PDF 栏、`prefers-reduced-motion` 不加动画；窄屏 720px 下单栏切换。
- [ ] **Step 7: 构建 + 提交** `feat(client): add full-screen artifact reader`

### Task B4: 入口接线

**Files:**
- Modify: `plugins/qingshui/src/client/index.ts`（注册 `shell.overlay`）
- Modify: `plugins/qingshui/src/client/ev-cite-layer.tsx`（EvBody 加「查看原文」）
- Modify: `plugins/qingshui/src/client/ResearchPanel.tsx`（「证据原文」头部加「展开」）
- Modify: `plugins/qingshui/src/client/toolviews/model.ts`（`FindingDoc` 增 `supports: FindingSupport[]`）
- Modify: `plugins/qingshui/src/client/toolviews/finding-card.tsx`（证据锚点行）
- Test: `plugins/qingshui/src/client/toolviews/model.test.ts`（补 supports 解析）

**Interfaces:**
- Produces:
  - `export type FindingSupport = { evidence_id: string; span_start: number; span_end: number }`
  - `FindingDoc.supports: FindingSupport[]`（只保留 evidence_id 非空、区间为整数的项）。
- Consumes: `openArtifact`。

- [ ] **Step 1: 写失败测试**——`asFindingDoc` 对带 `supports` 的样本返回 2 条并丢弃脏项。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现模型解析**
- [ ] **Step 4: 接线三处入口**（EV 证据卡 Footer、面板头部、判断卡证据锚点；锚点点击 `openArtifact({ kind:'document', annId?, evidenceId, spans })`——先取 evidence 的 `source_ref.ann_id`，取不到就用 `kind:'evidence'`）
- [ ] **Step 5: 注册 overlay**

```ts
ctx.effect(
  () => ctx.slots.inject('shell.overlay', () => ctx.slots.register({
    name: 'shell.overlay', id: 'qingshui-artifact-reader', order: 10, locale: NS,
  }, ArtifactReader)),
  'qingshui: artifact reader',
)
```

- [ ] **Step 6: 构建 + 测试 + 提交**

Run: `npm run build:plugin && npm run test:plugin`
Expected: 构建通过、全绿；重启 `launchctl kickstart -k gui/$(id -u)/com.qingshui.dsh-web` 后手工验收。

---

## Part C · 上线

### Task C1: 部署、迁移 301 份、回补

**Files:**
- Modify: `/data/qingshui/docker-compose.yml`（chemagent 上的真实编排，非仓库副本）
- Create: `/data/qingshui/ops/migrate_pdfs.sh`（一次性迁移脚本，chemagent 上）

**Interfaces:** 无代码接口；这是运维步骤。

- [ ] **Step 1: 部署代码**——按 `docs/运维/2026-10-12-chemagent-full-migration.md:145-174`：`git archive` → scp → 解包到 `/root/code/QingShuiYanTou`（保留 `.env`）→ 同步 `/data/qingshui/docker-compose.yml` → `docker compose build backend` → `up -d backend data-mcp scheduler`。
- [ ] **Step 2: 迁移现存 301 份**——`rsync -a /mnt/shared-storage-user/liweimin/qingshui/qingshui-pdfs/ /data/qingshui/pdf/`，然后 `find /data/qingshui/pdf -name '*.pdf' | wc -l` 期望 301。
- [ ] **Step 3: 冒烟**——隧道在线时 `curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8001/api/v1/knowledge/documents/2200763 | head -c 300`；再取一个 10 月有 PDF 的 ann_id，`curl -r 0-1023 .../pdf | head -c 5` 期望 `%PDF-`。
- [ ] **Step 4: 回补 dry-run**——`docker exec qingshui_scheduler python scripts/backfill_announcement_pdfs.py --dry-run --limit 20`，核对候选与目标路径。
- [ ] **Step 5: 小批量实跑**——`--limit 20 --sleep 1`，复查 `pdf.exists` 变 true、`%PDF-` 命中。
- [ ] **Step 6: 全量回补**——`--sleep 1`（约 11 小时），记录 `downloaded/failed`；失败项重跑一次。
- [ ] **Step 7: 更新文档**——`docs/待办.md` 记 G 组进展；AGENTS.md「现状对照」补一行 PDF 保留策略。

---

## 自检记录

- **Spec 覆盖**：§4.1→A1/A3/C1；§4.2→A2；§4.3→A7/C1；§5.1→A4/A5；§5.2→A6；§6→B1；§7.1→B4；§7.2→B3；§8 验收→各任务测试 + C1；§9 顺序→A→B→C。
- **未覆盖并有意排除**：会话级产物清单（§11 判断 4）、页码联动（判断 5）、`evaluate` 以外的知识图谱渲染（扩展点留在 `Artifact.kind`）。
