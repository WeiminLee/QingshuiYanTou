# Harness + Data MCP Runbook（唯一 Agent 运行时）

> 2026-10-10 决策：**删除旧 LangChain Agent**（含 `/api/v1/agent/*`）。  
> 投研对话只走 **DeepSeek harness（dsh）+ `plugins/qingshui` + 只读 Data MCP**。

## 步骤

1. **起 Data MCP（云）** — 见 `deploy/mcp/README.md` + `qingshui-data-mcp.service.example`
2. **本机 harness（dev-eval）**：`mcpBaseUrl` 指向云端 MCP（HTTPS + API Key）；**禁止**默认 Mac 隧道
3. **云端 harness**：`mcpBaseUrl=http://127.0.0.1:8100/mcp`（与 Knowledge 同机）
4. **烟雾**：`KNOWLEDGE_API_KEY=… ./scripts/smoke_mcp_p0.sh`
5. **评测**（一键 runner，v2 11 案默认；回退 v1：`CASES=backend/eval/expected_gap_cases_v1.json`）：
   ```bash
   bash scripts/run-golden-eval.sh glm_$(date +%F)          # 可选第二参数 = 单案重跑 case_id
   # 产物：backend/eval/out/{harness_answers_*,expected_gap_*,expected_gap_*.json}
   #       raw 过程产物在 eval/out/raw/<tag>/（已 gitignore）
   ```
   手动判分（不做整轮）：
   ```bash
   cd backend
   .venv/bin/python scripts/eval_dual_track.py \
     --cases eval/expected_gap_cases_v2.json \
     --mode harness-files \
     --answer-file eval/out/harness_answers_<tag>.json \
     --out eval/out/expected_gap_<tag>.json \
     --gate 0.8 --history eval/out/gate_history.jsonl
   ```
   `harness_answers.json` 形状：`{ "<case_id>": { "answer": "...", "tools": ["compare_metric", ...] } }`   
   注意：v2 七新案（台账/源材料/概念/补涨）要求 chemagent 已部署 2026-10-13 后代码（含
   `/ledger/*`、`/sources/*`、`/market/concept_*` 端点），否则这些案按 missing 工具判失败。

## 门禁

见 `eval_dual_track.py` 模块 docstring（通过率、轨迹可定位、embedding 无 Mac 隧道、连续评测无回退）。

**门禁判定**（`--gate`/`--history`）：
- 每轮 append `eval/out/gate_history.jsonl`；`GATE: PASS` = 本轮通过率 ≥ 阈值（默认 0.8）**且**无上一轮已过→本轮未过的回归；
- 连续 3 轮达标时输出 `GATE-STABLE-3`（对齐设计 §9.2 切流前观察期）；
- runner 以非零退出码上报门禁失败（launchd/cron 可据此告警）。

**定时评测**：`deploy/eval/qingshui-golden-eval.plist.example`（launchd，每日一跑；建议每个交易日
一次）。每轮成本 ≈ 案数 × glm 长查询（v2 11 案约 2-3 小时 + pjlab token），用户手动 load。
