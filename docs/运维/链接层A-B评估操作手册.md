# 链接层 A/B 评估操作手册（2026-09-18 部署执行版）

> ⚠️ **部署/集群相关章节已作废（2026-09-23）**：文中 sensecore pod + Mac 持隧道的部署与运维章节已被
> **H 集群 chemagent** 形态取代（见 `AGENTS.md` 与
> `docs/superpowers/specs/2026-09-23-chemagent-worker-deployment-design.md`）。
> A/B 评估口径与业务记录部分仍有效。

> 状态：代码与数据库迁移已落地，全量回填后台进行中（~2 天）。本手册为运维一步-by-一步操作与当日现实记录。

## 1. 数据库迁移（已执行 ✅）

```bash
ssh root@124.221.188.38
cd /home/lwm/code/QingShuiTouYan/backend
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m alembic upgrade head   # 生产库 stamp 026 后已执行 027/028，current=028
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m alembic current
```

注意：生产库原本无 alembic 版本记录（历史表结构在迁移体系外演化），因此先 `stamp 026` 再 `upgrade head`。

## 2. gold set 回填（已执行 ✅，持续扩充中）

`backend/eval/gold_set_v1.json` 中的 `expected_evidence_ids` 必须是 Mongo `kg_evidence` 里的真实 `evidence_id`。

协议：从 `minishare_announcements` 池选真实公司 → `db.kg_evidence.find({subject_hint.ts_code: <ts_code>})` 挑选真实 evidence_id → 人工确认相关性后填入。
当前已填 2 条（timeline / cross_section 各一）；theme 类条目待向量通道修复后重填。

## 3. 链接层回填（进行中）

```bash
cd /home/lwm/code/QingShuiTouYan/backend
# 干跑
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.backfill_keyword_links --dry-run --sample 10
# 精准回填（gold set / 单条修复）
#   --refresh 强制重跑 LLM 提取（忽略缓存）——若未来加该参数；当前单条重置缓存可用 mongosh $unset
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.backfill_keyword_links            # 全量（含 LLM）
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.backfill_keyword_links --skip-llm # 只建词典层（网关不可用/省额度）
```

- 断点续跑键：`kg_evidence.keyword_extraction` 缓存（LLM 成功才写入，缓存 miss 即续跑）
- 幂等：link PK 冲突 do-nothing；重复执行安全
- 词典层（subject/stage/dimension + subject_hint 权威锚点）零 LLM，分钟级可全量重算

## 4. A/B 双跑与验收口径

```bash
cd /home/lwm/code/QingShuiTouYan/backend
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.eval_retrieval --backend semantic --k 20   # 基线（需 embedding 服务）
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.eval_retrieval --backend link     --k 20
```

验收：timeline / cross_section 条目上 **link ≥ semantic**；theme 条目为向量通道职责，不计入链接层验收。

**2026-09-18 实测（真实证据条目）**：timeline **1.00**，cross_section **1.00**（semantic 基线因 d-cluster 隧道断而不可测，见遗留 1）。

## 5. LLM 网关现实（2026-09-18 切换）

- 生产 `.env` 已从付费中转 tianxuncloud（额度耗尽 403）**切回 pjlab 免费网关** `token.pjlab.org.cn`（备份：`.env.bak-20260918-pre-pjlab-swap`）
- 抽取模型：`Qwen3.6-35B-A3B-FP8`（owner 指定）；对话主力暂代 `glm-5.3`（pjlab 无 deepseek-v4-pro-0813）

## 6. 生产切换（等待验收后执行）

```text
1. 云端 backend/.env 加 ENABLE_KG_EXTRACTION=false
2. docker compose --env-file backend/.env build backend && up -d backend
3. 重建 evidence worker 容器（server_start.sh，EVIDENCE_JOB_TYPES 含 link）
4. systemctl restart qingshui-scheduler.service
5. d 集群 tar 同步（GitHub 云端不可达，改走 bundle over SSH）
```

## 7. 遗留事项

| # | 事项 | 依赖 |
|---|---|---|
| 1 | **d-cluster 隧道修复**（9-17 起断）：daemon 机上重启 `qingshui-embed-tunnel.sh`，云端验证 `curl http://172.18.0.1:11434/health` | 内网 ssh 权限 |
| 2 | 全量回填完成核对（`keyword_extraction` 缓存口径 × 316k evidence） | 时间 |
| 3 | 词表治理例会：scope 候选 ~2 条/证据增长，周期性 `merge_keyword` 归并 | 运营例程 |
| 4 | collation version mismatch `ALTER DATABASE qingshui REFRESH COLLATION VERSION`（需评估索引重建） | 择期 |
| 5 | flag 未翻前新证据仍会入队 combined（量小）；可重跑 `/tmp/mark_combined_skipped.js` 批量清理 | flip 前 |

## 8. 事故记录（2026-09-19）

**09-18 事故**：云机 8G 内存被回填并发（concurrency=4 + 新增 2 进程）打穿（available 从 426MB 起步），sshd 卡 banner，owner 云端重启恢复。

**修正**：
- 回填并发胃口以 `free -m` available > 2G 为水位线开闸；当前采用 `--concurrency 2`（重启后 available 5,492MB 起步）
- 全量回填按 evidence 剩余 ~312k、实测 ~30/min（LLM 延迟主导）估算，完成需 ~7 天；如需提速：a) 升配云机至 16G；b) 等台式机恢复后续把 backfill 移到台式机跑（资源体量大两个数量级）
- 设备优先序的重申：embedding 通道修复（d-cluster）优先于一切回填调参
- vector worker（`qingshui-vector-worker.service`，owner 原有 systemd 单元）在 embedding 修复前会持续把 pending vector 任务置 failed：**隧道修复后需批量 `failed → pending` 回收**（mongosh updateMany）

## 9. 遗留事项 1 收口（2026-09-19 三通道 A/B 终版）

**embedding 通道**：d-cluster（sensecore pod，root@10.140.158.130:49190）bge-m3 GPU 服务 `sembed_server.py` 绑 127.0.0.1:11434 + 反向隧道 `-R 172.18.0.1:11434→127.0.0.1:11434`，云端 `curl http://172.18.0.1:11434/health` → 200。生产 `.env` 已指向 172.18.0.1:11434/v1，vector worker / eval 全链路复通。模型缓存在 pod `/root/hf-cache`，venv `/root/wq/venv`（必带 `MACA_PATH=/opt/maca`）。

**gold set 扩到 3 条**（backend/eval/gold_set_v1.json，commit 972214d）：
- 新增 `theme-ai-copper-foil-001`（博威合金 601137.SH 压延铜箔 IRM，expected EV:b147cb8d…）；theme 按设计走 **semantic** 通道（queries.py scan_dimension 对 dimension=None 返回空）。

**eval 语义基线口径修正**（`scripts/eval_retrieval.py`）：retrieve_semantic 改为 **doc_chunks 单通道** top-k 直查。原先误用 hybrid_vector_search（RRF 四集合合并），entities/relations 的结果 payload 无 evidence_id、永不命中，却挤占 global top-k，系统性低估基线。

**终版数字（k=20）**：

| 通道 | timeline | cross_section | theme | mean | hit rate |
|---|---|---|---|---|---|
| link | 1.00 | 1.00 | —（设计内走向量） | **1.000** | **1.000** |
| semantic（chunks lane） | 0.67 | 0.00 | 1.00 | 0.556 | 0.667 |

结论不变且更扎实：横截面（跨公司毛利率对比）semantic 基线全灭（长年报 chunk 稀释 + 稠密跨文本对齐弱），正是链接层价值主张的实证。

**vector 数据修复（当日完成）**：
1. `kg_extraction_jobs` 里 vector/failed 3,999 条 → 批量 reset pending（vector worker 已全部消费回 done）
2. 池内 evidence vs doc_chunks 索引精确 diff（uuid5 批检索）→ **48,471 条缺向量**（无任务可走，纯入池时 embedding 断供遗留）→ `/tmp/build_gap_v3.py`（求差集）+ `/tmp/repair_gap_v1.py`（并发 3 直写 upsert_evidence_chunk_vector，断点 `/tmp/vector_repair_done.txt`，日志 `/tmp/vector-repair.out`），实测 ~20/s，ETA ~40min
3. **company_aliases.json** 缺失：`backend/data/` 是 gitignore 的部署时产物，需在云端从 `stocks` 表生成（`/tmp/build_aliases.py`，7,972 条；dict_match 有 stocks 兜底但告警噪音大）——若换机部署必须重建

## 10. 架构铁律与回填迁移 d 集群（2026-09-19 owner 定调）

**铁律**（详见仓库根 `AGENTS.md`）：evidence 处理代码一律在 d 集群以 worker 拉取任务消费；云机只做存储（Mongo/PG/Qdrant/Neo4j）与调度面。云侧不再新增/扩容 evidence 处理 worker。

**回填迁移记录（当日）**：
- pod 实底：1,507GB RAM / 255 核 / 出网 pjlab 200；venv Python 3.12
- 停云端 `backfill_keyword_links`（PID 8287）防双跑
- pod 装最小依赖（aliyun 镜像：tuna 缺 sqlalchemy 2.0.36）：sqlalchemy/asyncpg/motor/pydantic-*/openai/tiktoken/httpx —— **numpy 1.26.4 与 torch 2.8.0+metax 完好**（装包前后均验证）
- 配置：pod 持有锁，直接 `ssh cloud 'cat backend/.env' > /root/wq/backend/.env`（云端 PG=5433 / Mongo=27018 非标端口）
- 正向隧道：`ssh -N -L 127.0.0.1:5433 -L 127.0.0.1:27018 root@124.221.188.38`（由本地 Mac 持有，disable_timeout）
- 连通验证：PG `select 1` ✅ / Mongo `kg_evidence` 计数 ✅
- 试跑：`--limit 200 --concurrency 4`，观察吞吐与 pjlab 429，再定全量并发（目标 8~12、1~2 天跑完 312k 池）

**Pod worker 运维三条**：
1. worker/隧道必须前台持有式挂起（Mac 后台 bash disable_timeout，86400s 上限需每日重挂，幂等断点无损失）
2. 断点 = Mongo `keyword_extraction` 缓存标记，重启即续
3. 音量协调：云端 knowledge_worker（新证据 link 消费）仍共享 pjlab 网关，试跑期并发 4 起步，防 429 连坐

## 11. 生产 flip 完成记录（2026-09-19 14:31 检查点自动执行）

**前置全绿**：
- 48k 向量直写修复收官：48,471/48,471，**零失败**（10:53→14:11，实测 ~190/min）
- gold 六点抽验（uuid5 直查）：**6/6 全 200**
- 终跑 eval：link **1.000**（2/2）；semantic **0.556**（timeline 0.67 / cross 0.00 / theme 1.00），与 12:10 结果逐位一致

**flip 动作链**：
1. `backend/.env`：`ENABLE_KG_EXTRACTION=false`（grep 守卫幂等）
2. compose 发现漏键：**docker-compose.yml 原本没有 CONsumed 这两个环境键的声明**——`up` 后容器 env 里查无此旗。已在 backend/scheduler/job-worker 三个 service 的 environment 段补 `ENABLE_KG_EXTRACTION=${VAR:-false}` 与 `LLM_DISABLE_THINKING=${VAR:-false}`（compose default 即 flip 态），重建 backend 容器后 `docker inspect` 确认两旗在场
3. `systemctl restart qingshui-scheduler`
4. d 集群代码同步：git archive(HEAD) → **Mac 中继** scp → pod /root/wq 解包（云→pod 无法直连，方向永远 pod→引干线/云，Mac 是唯一双向跳板）；pod 补生成 company_aliases.json（7,972 条）
5. 云仓库与 GitHub 对齐：**bundle 中继**（cloud 3ce6432 → 本地 4f62ad5）。教训：云端 git 树长期落后于 origin，任何以 cloud 为源的 archive/tar 都可能缺近几日 commit——**发布前必须比对 `git log -1`**

**效果**：旧三元组 combined 抽取管道停止入队（存量 150,973 skipped 保持不动，690 failed 已 Frozen）；新证据只走 vector + link 两条任务;链接层成为唯一知识层。

## 12. LLM thinking 事故与修复（2026-09-19，迁移排障记录）

**现象**：迁移到 d 集群后回填实测仅 14.5/min（压测同池可达 68~100）。
**根因**：`LLM_DISABLE_THINKING` 从未在任何 .env 设置（默认 False），chat_async 只对 deepseek/minimax 显式关 thinking。Qwen3.6-35B-A3B-FP8 为推理模型，长年报证据"想"到 180s 流总超时（A/B 实测：ON 133.6s 均值，一半撞墙；OFF 2~4s）。
**修复**：pod + cloud .env 双加 `LLM_DISABLE_THINKING=true`；compose 三 service 补键（同 §11）；实测回填 24 槽 **101/min**（14.5 → 101，约 7 倍）。
**教训（换模型必查清单）**：① thinking 流费与该模型推理属性；② chat_async 是否 stream + 总超时兜底值；③ 网关无 429 时以"长尾卡死"形态限流，压测表不呈线性——按 p95 观察而非并发峰值。

## 12.1 模型选型横评存档（2026-09-19 晚，boyue 网关）

**口径**：同 40/24 条真实证据（kw_v2 基线 = 生产 Qwen3.6-35B-A3B-FP8 的抽取缓存），字段集 F1（company/product/metric）。

| 模型 | 总体 F1 | 备注 |
|---|---|---|
| 生产 pjlab Qwen3.6-35B-A3B-FP8 | 基线 | 101/min（24 槽，thinking off） |
| **Qwen2.5-14B-Instruct** | **0.739** | 公司 0.910 全家最强；13.0/min；贴质量闸 |
| Qwen3-14B | 0.643 | 22.9/min；零解析失败 |
| Qwen3.5-4B | 0.632 | 10.5/min；零解析失败 |
| Qwen3.5-9B | 0.620 | 4 条格式失败 + 慢车道 |
| qwen3-30b-a3b-instruct-2507 | 0.587 | **公司 0.448 崩**——同生产架构假说被证伪 |
| Qwen3-8B | 0.455 | 出局 |

**本地部署实验**：pod GPU1 上 transformers bs1 裸跑 Qwen3-4B-Instruct → **40 条 >85 分钟未完（<0.6/min）：部署形态否决**（MetaX 生态无 vllm 情况下 transformers 不可用于批量抽取）。F1 未取得即出局（吞吐先杀）。

**四条教训**：
1. 架构新 ≠ 任务强：同生产血统的 30b-a3b（2507 旧块）公司识别崩盘，而上代 2.5-14B 是小模型冠军——**模型必须实测，别赌血统**
2. 浅抽取吃 instruct 纪律（稳定 JSON、稳实体粒度），不吃推理深度
3. MetaX 上批量抽取的本地化前提 = vllm-metax（或 llama.cpp）可用性——候选模型定为 **Qwen2.5-14B-Instruct**（28GB bf16 单卡可装）
4. 长文本（年报 18-24k 字符）是所有小模型的共同软肋：截断窗口 + 实体丢失，company 精度首当其冲

**事故两连（当日运维）**：① 本地持有会话被远端重置时，pod 端 nohup 进程与隧道全部存活（与平台清后台的旧教训相比，说明清理具有选择性）；但本地 ssh 的 TCP 半开会让包装任务悬挂——监控要与远端 log 文件挂钩而非本地管道。② `pkill -f` 模式若与同一命令行的其他段（heredoc/路径）匹配时会自杀——多动作命令必须拆分或用极短独特 pattern。

## 12.2 本地化实测记录(2026-09-21,vllm-metax 已跑通,fp8/3.5 系双双卡死)

**§12.1 前置条件已翻绿且翻车面明确**——`vllm_metax-0.13.0+g181dc3.d20260129` 可批量服务(live 实测载入/吞吐正常),但本 build 两条硬限制:
1. **fp8 全线不支持**:Qwen3-32B-FP8 与 Qwen3.6-35B-A3B-FP8 均 `Value error: fp8 quantization is currently not supported in maca`(留档 `/root/wq/vllm_32b.log`);
2. **qwen3_5_moe 架构(3.5/3.6 系)无实现**:transformers 旧版不识别 model_type + vllm/metax models/ 全仓无注册(`/root/wq/vllm_35b.log`)。→ 3.5/3.6 本地化 = 等 MetaX 新 wheel;权重(3.6-FP8 36GB)已落盘 `/root/models/` 备用。

**当前最优本地形态 = Qwen3-32B-AWQ**(int4,插件专用 MacaAWQConfig 上车):GPU1 单卡权重 18.14GiB、KV 池 30.97GiB(126,832 tokens)、16k 窗口最大并发 7.74x、thinking 0 泄漏。

**同口径对比(终版,pinned)**(`backend/scripts/eval_local_extract.py`,样本钉死 `pinned_sample_ids_seed42_40.json`(40 条 = 30 IRM + 10 公告,ids 入库存 `backend/eval/local_extract_2026-09-21/`),参照 = 云上生产 kw_v2 缓存,Qwen3 系 `enable_thinking=false`;三份 JSON `*_pinned.json` 同库可查):

| 模型 | company | product | metric | 总体 F1 | 解析失败 | 吞吐@6并发 |
|---|---|---|---|---|---|---|
| **Qwen3-32B-AWQ**(GPU int4) | **0.801** | 0.619 | **0.773** | **0.731** | 0 | 8.9/min |
| Qwen2.5-14B-Instruct(GPU bf16) | 0.738 | 0.616 | 0.708 | 0.687 | 0 | 14.8/min |
| Qwen3.5-35B-A3B-Q8_0(CPU llama.cpp) | 0.761 | 0.649 | 0.603 | 0.671 | 2 | 0.1/min |

- 生产 3.6-35B(网关)仍为参照本身(101/min);本地最优 = 32B-AWQ(质量),14B(吞吐),两者各有定位;
- **Qwen3.5-35B-A3B(用户问询象)实测质量差于 32B-AWQ/14B**:metric 崩(0.603)、总体垫底 0.671——与 §12.1"3.5 系小弟中游"家族趋势一致;且 llm.cpp CPU 通路(0.1/min,28 核配额 + 宿机 load 38)注定其只作质量验证,不作生产;
- **方法学三连教训(当日)**:① Mongo `$sample` 无 seed → §12.1 无法复现(要 pin);② 池增长 + 回填 `$set` 引发自然序漂移,同 seed 不同取(曾两轮假"同题"),解法 = ids 钉文件;③ GPU 链与 CPU 齐跑会互相污染(客户端 180s 超时被 contention 触发 21/40 假失败),解法 = 请求层 3600s + `.partial` 逐条落盘;故跨模型结论只认 pinned 表,下列历史数字全部作废:0.760/0.742(漂移样本)、0.7778/0.7312(canonical-A/B 互异)、0.7949(N=8 初步)、0.488(超时污染)。

**吞吐对照 = 不能独立承担回填**:生产网关 101/min(24槽) vs 本地 GPU 9-15/min;31 万池本地独跑约 11-24 天。定位 = 网关故障时的冗余通道,或"本地夜间 + 网关峰值"混合。

**运维注**:评测 serve 均经本地 Mac 后台会话持有(合乎 §10 纪律);ModelScope 下载实测 ~3.5GB/min(hf-mirror 同达,huggingface 被墙);llama.cpp 源码经 gh-proxy 获取(github 直连 git 协议不通,https curl 反而 200);pod cgroup CPU 配额 28 核(nproc 255 具迷惑性),宿机 load 常态 ~38-44 含他租户。**遗留**:llama-server/14B/32B 实验 serve 已全部清理,卡与端口归还回填与生产。

**运维注**:今日评测 serve 均经本地 Mac 后台会话持有(合乎 §10 纪律);ModelScope 下载实测 ~3.5GB/min(hf-mirror 同达,huggingface 被墙)。
