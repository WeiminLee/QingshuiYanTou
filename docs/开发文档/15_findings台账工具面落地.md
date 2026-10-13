# Findings 判断台账工具面落地记录

日期：2026-10-13 · 状态：已实现（离线验证通过；E2E 金标待 chemagent 部署同步后跑 v2）
依据：`docs/findings判断台账设计草案-2026-09-17.md`（三层结构与硬闸门）、
`docs/预期差的理解与设想-2026-09-17.md`（挖掘→维护）、双轨 plan Task 13（P0.5）。
相关提交：`709f1c2`（Phase L 台账面）、`57093ae`（Phase P P0.5）、Phase E（金标 v2 + 门禁）。

## 一、落地范围（草案 → 实现）

| 草案接口（§6） | 实现 | 通道 | 端点/工具名 |
|---|---|---|---|
| `write_observation` | `app.knowledge.agent_ledger_ops.save_observation` | **仅 Knowledge HTTP + 插件 tools.ts** | `POST /api/v1/knowledge/ledger/observation` |
| `write_finding` | `save_finding`（kind 白名单 + supports 句锚） | 同上 | `POST /api/v1/knowledge/ledger/finding` |
| `history_findings(subject, dimension…)` | `history_findings`（(主体,维度) 观察时间线+判断+水位线，补齐全库读空白） | HTTP + **MCP** | `POST /ledger/history`、MCP `history_findings` |
| `search_findings(dimension, kind…)` | `search_findings`（默认排除 dismissed） | HTTP + MCP | `POST /ledger/search`、MCP `search_findings` |
| `watermark(subject, dimension, scope)` | `read_watermark` | HTTP + MCP | `POST /ledger/watermark`、MCP `watermark` |

P0.5 一并落地（全只读）：`get_announcement`/`get_irm`/`find_events`/`get_event_detail`/
`scan_dimension`/`backlinks`/`get_top_concepts`/`get_concept_stocks`/`get_stock_concepts`
——HTTP 面分别在 `api/agent_sources.py`、`agent_links.py`、`agent_market.py`；MCP `tools_readonly`
注册后只读工具由 9 个扩到 21 个。

## 二、关键决策（对应草案 §8 开放问题）

1. **存储**：PostgreSQL 三表 `observations`/`findings`/`watermarks`——**alembic 028 早已建好**
   （observations+watermarks 由 link 流水线在线写入，findings 此前无写入方），零新迁移。
   agent 写入只是 findings 的**首个**写入方，值域与幂等键沿用草案定义
   （`obs_id`/`finding_id` 内容哈希，重跑合并）。
2. **写面通道**：**不进 MCP**（MCP 第一期只读铁律 + `WRITE_TOOL_NAMES` 护栏新增两写名）。
   写能力只经 Knowledge HTTP（X-API-key 鉴权 + Pydantic 强校验），dsh 插件以自有 HTTP 工具面
   直连——与 worker_writes 同级风险面，长度/枚举/span 范围双重收紧。
3. **校验失败契约**：`{"ok": False, "errors": [...]}` + HTTP 200（沿用旧 `932576f` 工具面惯例，
   不抛 4xx）——agent 可读错误自我修正。
4. **硬证据闸门**：`evidence_id` 必须存在于 Mongo，且 `[span_start, span_end)` 落在
   `text_excerpt` 内；伪造/越界拒写（草案 §1.4 一切锚 evidence_id）。
5. **水位线推进**：写入 observation 顺带 `advance_watermark`（只升不降的 PG ON CONFLICT
   GREATEST 单语句实现），返回 `is_new_level` = 本轮写入是否首上新台阶——把「新颖度判定」
   翻译成 agent 可直接消费的布尔信号。
6. **阶梯是软约束**（草案 §1.3）：prompt/skill 只给维度示例（产线进展/客户认证/毛利率/订单/
   产能…），不强制枚举；台账存原始措辞 + 可选 level。

## 三、技能侧（divergence-mining v4）

- 流程末新增**沉淀段**：先 `history_findings` 查水位 → 等价判断引用不重建 → 新观察
  `write_observation` → 新台阶 `write_finding`；引用格式 `FD:…`（判断）/ `EV:…`（证据）。
- persona 未动（避免再触发全轮金标回归）；沉淀纪律全部收在 skill 层。

## 四、金标与门禁（v2）

- `backend/eval/expected_gap_cases_v2.json`：v1 三案 + 七新案（台账写/台账复用/公告/互动易/
  事件/概念补涨/维度扫描），新案标注 `requires_deploy`。
- 门禁：`eval_dual_track.py --gate 0.8 --history eval/out/gate_history.jsonl`——通过率阈值 +
  上轮已过案零回归 + 连续 3 轮达标（`GATE-STABLE-3`）才具备切流判定条件（§9.2）。
- 定时：`deploy/eval/qingshui-golden-eval.plist.example`（launchd 每日一跑，用户手动 load；
  每轮成本 = 案数 × glm 长查询，约 2-3 小时）。

## 五、与 v1.3 全局场景的差距（后续迭代候选）

- 观察的 `metric_value` 数值维度尚无自动环比/区间外判定（草案 §3 数值型新颖度）；
- finding 的 `supersedes` 语义已落数据结构但无专用 supersede 工作流；
- `search_findings` 的跨主体预警订阅、台账→雷达信号的 agent 侧回流（pipeline 侧已由
  `emit_radar_signals` 覆盖机械候选）可在第二期接上。
