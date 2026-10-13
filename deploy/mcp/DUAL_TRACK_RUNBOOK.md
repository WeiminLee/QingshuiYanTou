# Harness + Data MCP Runbook（唯一 Agent 运行时）

> 2026-10-10 决策：**删除旧 LangChain Agent**（含 `/api/v1/agent/*`）。  
> 投研对话只走 **DeepSeek harness（dsh）+ `plugins/qingshui` + 只读 Data MCP**。

## 步骤

1. **起 Data MCP（云）** — 见 `deploy/mcp/README.md` + `qingshui-data-mcp.service.example`
2. **本机 harness（dev-eval）**：`mcpBaseUrl` 指向云端 MCP（HTTPS + API Key）；**禁止**默认 Mac 隧道
3. **云端 harness**：`mcpBaseUrl=http://127.0.0.1:8100/mcp`（与 Knowledge 同机）
4. **烟雾**：`KNOWLEDGE_API_KEY=… ./scripts/smoke_mcp_p0.sh`
5. **评测**（harness 产出 JSON 后打分）：
   ```bash
   cd backend
   .venv/bin/python scripts/eval_dual_track.py \
     --cases eval/expected_gap_cases_v1.json \
     --mode harness-files \
     --answer-file /tmp/harness_answers.json \
     --out eval/out/expected_gap_report.json
   ```
   `harness_answers.json` 形状：`{ "<case_id>": { "answer": "...", "tools": ["compare_metric", ...] } }`

## 门禁

见 `eval_dual_track.py` 模块 docstring（通过率、轨迹可定位、embedding 无 Mac 隧道、连续评测无回退）。
