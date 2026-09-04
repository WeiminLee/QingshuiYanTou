# lwm-server-d 知识抽取节点迁移实施方案

## 1. 背景

项目原先计划将 PDF 下载、解析和 Evidence 抽取运行在台式机上，通过 WireGuard 直连云端 PostgreSQL、MongoDB 和 Qdrant。实际部署时发现，`lwm-server-d` 更适合承担批处理任务：它拥有 2 张 MetaX C550 GPU、28 vCPU、360 GiB 内存和大容量存储；同时，d 集群实例不允许普通用户创建 WireGuard 网卡，无法授予 `NET_ADMIN` 时不能采用数据库直连方案。

因此本阶段改为 API 解耦：`lwm-server-d` 只通过 HTTPS 调用腾讯云 Knowledge API，不直接访问云端数据库，也不依赖 WireGuard。

## 2. 目标

- 云端继续负责 API、调度、数据采集、任务状态和持久化存储。
- `lwm-server-d` 负责 PDF 下载、PDF 解析、段落/表格结构化、Evidence 抽取和 Embedding 计算。
- Worker 与云端之间只使用 HTTPS + API Key。
- PDF 原文件存储在 `lwm-server-d` 的本地大容量磁盘。
- 解析和抽取任务可在 C550 GPU 上并发运行，并受实例配额约束。
- 台式机保留为 Agent 交互和备用节点，不再是生产主 Worker。

## 3. 最终架构

```text
腾讯云
├── Backend / Knowledge API :8080
├── Scheduler
├── Ingestion Worker
├── PostgreSQL
├── MongoDB
└── Qdrant
        ▲
        │ HTTPS + X-API-Key
        ▼
lwm-server-d
├── PDF Download Worker
├── PDF Storage（本地大容量磁盘）
├── PyMuPDF 正文解析
├── pdfplumber 表格兜底
├── pymupdf4llm Markdown 格式化
├── Evidence Worker
├── LLM 抽取
└── C550 Embedding 服务
```

## 4. 已验证的基础条件

### 4.1 网络

从 `lwm-server-d` 访问腾讯云 API 已验证成功：

```text
GET http://124.221.188.38:8080/health
HTTP 200 {"status":"ok"}
```

OpenAPI 文档也可访问，响应时间约 20～50 ms。

### 4.2 GPU 与推理环境

实例配额：

```text
GPU：2 × MetaX C550，单卡 64 GiB
vCPU：28
内存：360 GiB
```

已验证环境：

```text
MACA：3.3.0.15
PyTorch：2.8.0+metax3.3.0.3
torch.cuda.is_available()：True
GPU 数量：2
```

### 4.3 PDF 解析依赖

```text
PyMuPDF：1.28.2
pdfplumber：0.11.10
pypdf：6.16.2
pymupdf4llm：1.28.2
```

## 5. 服务职责

### 5.1 云端

- 从 minishare/tinyshare 获取公告及元数据；
- 生成 PDF 下载任务；
- 提供任务领取、确认和失败重试 API；
- 保存公告元数据、Evidence、实体和关系；
- 负责 Qdrant 持久化和 Knowledge API 查询；
- 提供任务统计、健康检查和审计日志。

云端 ingestion 不下载 PDF，不依赖 `PDF_STORAGE_ROOT`。

### 5.2 lwm-server-d

- 领取待处理 PDF 任务；
- 从公告来源 URL 下载 PDF；
- 保存到本地 `PDF_STORAGE_ROOT`；
- 使用 PyMuPDF 提取普通正文；
- 仅对疑似表格页面调用 pdfplumber；
- 需要 Markdown/复杂版面时调用 pymupdf4llm；
- 执行 Evidence 和 LLM 抽取；
- 通过 API 将结果写回云端；
- 失败任务通过 API 标记并支持重试。

## 6. API 契约

现有 API 已支持健康检查、知识查询、实体/关系写入和 KG 抽取。Worker 迁移还需要补充以下接口：

```text
POST /api/v1/knowledge/jobs/claim
POST /api/v1/knowledge/jobs/{job_id}/success
POST /api/v1/knowledge/jobs/{job_id}/failure
POST /api/v1/knowledge/evidence/upsert
```

所有请求必须携带：

```http
X-API-Key: <受控密钥>
```

`claim` 必须保证任务租约和幂等；`success`/`failure` 必须校验任务持有者；`evidence/upsert` 使用稳定 Evidence ID，重复提交不得产生重复记录。

## 7. PDF 混合解析策略

```text
默认路径：PyMuPDF
    ↓
页面疑似表格？
    ├─ 否：正文清洗、段落合并、分块
    └─ 是：pdfplumber 提取表格并转 Markdown
    ↓
复杂版面或 LLM Markdown 需求？
    └─ 是：pymupdf4llm 生成结构化 Markdown
```

规则：

- 不让三个库串行处理整份 PDF；
- 普通正文优先保证吞吐；
- 表格保留 `is_table=True` 和 `table_str`；
- 表格不得与普通正文混合切分；
- 跨页段落依据句末标点和版面连续性合并；
- 文本量异常少或抽取失败时才进入兜底路径。

## 8. 并发与资源策略

按实例配额而不是宿主机暴露资源配置：

```text
PDF 解析：4～8 并发
LLM：先从 2 并发开始
Embedding：每张 GPU 1 个进程
总 CPU 使用：控制在 20～24 vCPU 内
内存：控制在 280～300 GiB 内，预留系统空间
```

超过配额时，CPU 通常被限流，GPU 显存或内存超限会导致任务失败，因此 Worker 必须支持超时、重试和失败回写。

## 9. 部署步骤

1. 使用 `/opt/conda/bin/python` 作为 Worker Python。
2. 同步 Qingshui 代码到 `/root/workspace/qingshui-worker`。
3. 配置 `KNOWLEDGE_API_URL` 和 `KNOWLEDGE_API_KEY`。
4. 设置本地 `PDF_STORAGE_ROOT`。
5. 部署 PDF Download Worker 和 Evidence Worker。
6. 调用 `worker_preflight` 检查 API、外网和存储目录。
7. 用 1 个真实公告任务完成下载、解析、抽取和写回。
8. 逐步提高并发到 2、4、8，记录耗时、失败率和显存。
9. 再启动过去两年的分阶段数据重建。

## 10. 验收标准

- API 健康检查连续成功；
- Worker 可领取任务且不会重复领取；
- 真实公告 PDF 下载成功并落盘；
- 段落无明显截断或跨页丢失；
- 表格能转换为结构化 Markdown；
- Evidence 重复提交保持幂等；
- LLM/Embedding 成功写回云端；
- Worker 重启后可继续处理 pending/failed 任务；
- 任务失败不会阻塞后续任务；
- 运行日志包含任务 ID、PDF ID、耗时、GPU、失败原因。

## 11. 安全与回滚

- API Key 只写入服务器受限权限文件，不提交 Git；
- 云端数据库不开放公网端口；
- PDF 本地目录与代码目录分离；
- 迁移初期保留台式机 Worker，但只运行备用实例；
- 重建前导出任务统计和 Evidence 统计；
- 回滚时停止 `lwm-server-d` Worker，恢复原台式机 Worker；
- 失败任务只标记状态，不删除原始 PDF 或已有 Evidence。

## 12. 当前阻塞与后续工作

当前已验证 API 网络、C550/MACA/PyTorch、PDF 依赖和 tinyshare 调用。剩余实现工作是：

1. 在云端补齐 PDF 任务领取和 Evidence 写回 API；
2. 将 `pdf_download_worker` 改为 API 客户端模式；
3. 在 `lwm-server-d` 部署 Embedding HTTP 服务；
4. 完成单任务端到端验证；
5. 启动过去两年数据重建。

