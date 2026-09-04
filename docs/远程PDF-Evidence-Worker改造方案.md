# QingShui 远程 PDF / Evidence Worker 改造方案

> 更新时间：2026-09-01
>
> 目标：腾讯云继续承载公网生产服务，台式机承担高性能 PDF 解析、Evidence 切分和抽取任务，系统对外仍表现为一个完整的 QingShui 服务。

## 1. 总体结论

推荐采用“腾讯云控制面 + 台式机计算 Worker”的部署方式：

```text
腾讯云（生产控制面）
  API / PostgreSQL / MongoDB / Qdrant / Redis / 调度器
                         ▲
                         │ WireGuard VPN
                         ▼
台式机（计算面）
  PDF 存储 / PyMuPDF4LLM / pdfplumber / Evidence Worker / LLM 抽取
```

数据库、队列、Evidence 和抽取结果只有腾讯云一份；台式机不维护独立数据库，不形成第二套系统。

## 2. 机器与资源

### 腾讯云 `124.221.188.38`

- 4 核 CPU
- 约 7.5 GiB 内存
- 无 GPU
- 磁盘剩余约 32 GiB
- 运行 Docker Compose 生产服务

### 台式机 `lwm-desktop-server`

- 主机：`PJNL231040031`
- 16 核 CPU
- 62 GiB 内存
- NVIDIA GeForce GTX 1660 Ti，6 GiB 显存
- 磁盘可用约 394 GiB
- Ubuntu 24.04，内核 6.17
- SSH 别名配置在 `~/.ssh/config`

## 3. PDF 解析与 Evidence 方案

### 3.1 生产解析链路

```text
公告 PDF
  → PyMuPDF4LLM 输出 Markdown 标题/段落
  → SmartChunker 按标题和段落切分
  → 保留公告章节过滤规则
  → 超长段落按句子/token 窗口切分
  → 严格 max_tokens <= 6000
  → 解析失败自动回退 PyMuPDF
```

### 3.2 公告章节过滤

原有过滤规则必须保留，不能因为更换解析器而删除，包括：

- 跳过程序性、格式性章节：审计情况、董事会决议、监事会决议、股东大会决议、附件、释义、备查文件、投票说明、风险提示等；
- 如果被跳过标题的正文包含营业收入、净利润、业务、产品、市场、收购、重组、股权、研发等实质性关键词，则保留；
- 规则入口：`_classify_announcement_chapter()`。

### 3.3 Evidence 粒度

旧方案会把同一公告的所有有效章节合并成一条 Evidence，导致单条 Evidence 可能达到数万 tokens，引发 LLM 超时。

新方案改为：

- 每个通过过滤的 chunk 独立生成一条 Evidence；
- 每条 Evidence 目标 2,000–4,000 tokens；
- 硬上限 6,000 tokens；
- 使用 `chapter_index` 参与稳定 Evidence ID，避免同一公告多个 chunk ID 冲突。

## 4. 已完成事项

### 代码

- 已新增 `extract_structured_text_from_pdf()`；
- Evidence builder 已切换到结构化解析入口；
- PyMuPDF4LLM 不可用时自动回退 PyMuPDF；
- SmartChunker 已增加最终 token 安全阀；
- 已修复超长句子突破 token 上限的问题；
- 公告 Evidence 已改为每个有效 chunk 独立输出；
- `ingest_announcements_to_kg.py` 已使用 `chapter_index` 生成稳定 ID；
- 原公告章节过滤逻辑保留。

### 评测

- 已在 100 份真实 PDF、2,615 页上完成批量基线测试；
- 原方案最大 chunk 达到约 6,087 tokens；
- 新方案超出 6,000 tokens 的样本数为 0；
- 原方案平均约 5.92 个 chunks/PDF；
- PyMuPDF4LLM 已在真实研报上验证能输出 Markdown 标题和段落；
- PyMuPDF4LLM 单份样本前 3 页耗时约 1.95–2.85 秒。

### 网络与机器

- 台式机和腾讯云已安装 WireGuard tools；
- WireGuard 地址：腾讯云 `10.20.0.1`，台式机 `10.20.0.2`；
- 已验证握手和 ping，延迟约 8.7ms；
- 台式机已安装 Docker 29.1.3；
- 台式机已安装 Docker Compose 2.40.3；
- 台式机 Docker 服务已设置开机启动；
- 后端代码已同步到台式机 `~/qingshui-worker/backend`。

## 5. 进行中/待完成事项

### 5.1 WireGuard 持久化确认

- 两端 `wg-quick@wg0` 已启用并运行；
- 需要重启验证自动恢复；
- 腾讯云安全组需保留 UDP 51820 入站规则，建议最终限制为台式机公网 IP。

### 5.2 腾讯云服务 VPN 访问

WireGuard 已打通，但需要确认并记录以下服务的 VPN 访问地址：

```text
MongoDB：10.20.0.1:27018
PostgreSQL：10.20.0.1:5433
Qdrant：10.20.0.1:6333
API：10.20.0.1:8080
```

当前 MongoDB 和 PostgreSQL 已从台式机测试可达；API/Qdrant 需在 Worker 启动前做最终连通测试。

### 5.3 台式机 Worker

待创建 Worker 专用环境配置，不复制生产机完整密钥文件。至少需要：

```text
MONGODB_URL=mongodb://10.20.0.1:27018/qingshui
DATABASE_URL=postgresql+asyncpg://...@10.20.0.1:5433/qingshui
QDRANT_URL=http://10.20.0.1:6333
LLM_BASE_URL=...
LLM_API_KEY=...
EMBEDDING_BASE_URL=...
EMBEDDING_API_KEY=...
```

启动方式建议使用独立 Docker Compose 服务或 systemd：

```text
evidence_extraction_worker
  → claim 腾讯云 kg_extraction_jobs
  → 读取台式机 PDF
  → 解析/切分/LLM 抽取
  → 回写腾讯云 MongoDB、PostgreSQL、Qdrant
```

### 5.4 PDF 统一存储

PDF 可以统一存储在台式机，但数据库只能保存元数据：

```json
{
  "pdf_storage": "desktop",
  "pdf_path": "/data/qingshui-pdfs/...",
  "pdf_sha256": "...",
  "pdf_url": "...",
  "available": true
}
```

需要补充：

- 台式机 PDF 根目录；
- PDF 下载/缺失时的重试机制；
- PDF 备份策略；
- 台式机关机时禁止永久锁死任务。

## 6. Evidence 全量重建流程

在 Worker 依赖和端到端连接验证通过前，不删除旧数据。

正式流程：

1. 统计公告 Evidence、jobs、pending/running/done/failed 数量；
2. 备份旧 Evidence 的数量和导出索引；
3. 只删除 `source_type=announcement` 的旧 Evidence；
4. 删除对应 `kg_extraction_jobs`；
5. 从 PostgreSQL 重新读取公告记录；
6. 从台式机 PDF 重新解析；
7. 应用公告章节过滤规则；
8. 每个有效 chunk 写入独立 Evidence；
9. 为每条 Evidence 创建 `combined` 和 `vector` job；
10. 台式机 Worker 先处理 1 条任务做冒烟测试；
11. 逐步扩大到 10、100、1000 条；
12. 观察 token、耗时、失败率和重复 ID；
13. 最后再进行全量抽取。

## 7. 安全与可靠性要求

- 不把 MongoDB、PostgreSQL、Qdrant 直接暴露给公网；
- 通过 WireGuard 网段访问内部服务；
- API Key 只写入 Worker 专用 `.env`，不提交 Git；
- Evidence 写入必须幂等；
- Worker 必须有心跳、锁超时和失败重试；
- 台式机离线时任务保持 pending 或可恢复，不得永久 running；
- PDF 文件用 SHA256 校验，避免重复下载和错误覆盖；
- 保留旧 Evidence 导出或快照，确认新流程稳定后再清理备份。

## 8. 回滚方案

如果新 Worker 出现解析或抽取问题：

1. 停止台式机 Worker；
2. 保留已经生成的新 Evidence 和失败日志；
3. 恢复腾讯云原有 Worker/调度器；
4. 使用 Evidence 备份恢复旧公告数据；
5. 删除新建的 pending jobs；
6. 修复后用 20 份样本重新验证，再继续扩大范围。

## 9. 验收标准

远程 Worker 方案满足以下条件后，才视为完成：

- 台式机重启后 WireGuard 自动恢复；
- 台式机可以访问腾讯云 MongoDB、PostgreSQL、Qdrant；
- Worker 可以成功 claim、处理并完成一条真实 Evidence job；
- 新 Evidence 单条不超过 6,000 tokens；
- 公告过滤规则仍能正确 skip/keep；
- 任务重复执行不会生成重复 Evidence；
- 台式机关机后任务可恢复；
- 20、100、1000 条批量测试无持续性超时和锁死；
- 腾讯云 API 仍然可以正常返回抽取结果。

## 10. 配置、链接与端口信息

### 10.1 SSH 连接

本机 `~/.ssh/config` 中的台式机别名：

```ssh
Host lwm-desktop-server
    HostName 10.6.24.116
    User liweimin
    IdentityFile ~/.ssh/id_ed25519
```

腾讯云生产机：

```text
公网地址：124.221.188.38
SSH 用户：lwm
root 操作使用 root 账号
```

SSH 私钥只允许保存在操作者本机：

```text
~/.ssh/id_ed25519
```

私钥不得复制到仓库、Worker 镜像、聊天记录或 PDF 存储目录。

### 10.2 WireGuard

```text
VPN 网段：10.20.0.0/24
腾讯云 wg0：10.20.0.1/24
台式机 wg0：10.20.0.2/24
监听端口：UDP 51820（腾讯云）
```

配置文件位置：

```text
腾讯云：/etc/wireguard/wg0.conf
台式机：/etc/wireguard/wg0.conf
```

服务管理：

```bash
sudo systemctl enable --now wg-quick@wg0
sudo wg show wg0
```

当前已登记的公开密钥仅用于识别 Peer；私钥不写入本文档：

```text
台式机 Peer public key：记录在两端 wg0.conf 的 [Peer] 段
腾讯云 Peer public key：记录在两端 wg0.conf 的 [Peer] 段
```

### 10.3 腾讯云服务端口

腾讯云 Docker 服务当前发布端口：

| 服务 | 容器端口 | 腾讯云主机端口 | Worker 访问地址 |
|---|---:|---:|---|
| QingShui API | 8000 | 8080 | `10.20.0.1:8080` |
| MongoDB | 27017 | 27018 | `10.20.0.1:27018` |
| PostgreSQL | 5432 | 5433 | `10.20.0.1:5433` |
| Qdrant HTTP | 6333 | 6333 | `10.20.0.1:6333` |
| Qdrant gRPC | 6334 | 6334 | `10.20.0.1:6334` |
| Redis | 6379 | 6379 | `10.20.0.1:6379` |
| WireGuard | — | 51820/UDP | 台式机 VPN 握手 |

推荐 Worker 使用 VPN 地址，不使用公网地址。腾讯云安全组只需对台式机公网 IP 放行 UDP 51820；数据库和 Qdrant 不应新增公网白名单。

### 10.4 Worker 环境变量

台式机 Worker 使用独立 `.env`，示例：

```dotenv
MONGODB_URL=mongodb://10.20.0.1:27018/qingshui
DATABASE_URL=postgresql+asyncpg://<user>:<password>@10.20.0.1:5433/qingshui
QDRANT_URL=http://10.20.0.1:6333
LLM_BASE_URL=<internal-llm-endpoint>
LLM_API_KEY=<secret>
EMBEDDING_BASE_URL=<embedding-endpoint>
EMBEDDING_API_KEY=<secret>
```

`.env` 只保存在台式机 Worker 目录，权限设为 `600`，不得提交 Git。

### 10.5 Minishare 与 PDF 存储

```text
PDF 根目录（建议）：/data/qingshui-pdfs
Minishare 凭据：仅通过 Worker 环境变量注入
PDF 元数据：保存 pdf_path、pdf_url、pdf_sha256、available
```

密码、API Key、数据库密码、WireGuard 私钥和 Minishare token 均属于敏感信息，不写入本文档；部署时通过受控终端或密钥管理工具注入。
