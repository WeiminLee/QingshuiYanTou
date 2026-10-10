# 双轨观察 Runbook（Approach C）

旧入口保持默认（若部署仍暴露 LangChain `stream/report`）；新轨 = Data MCP + dsh + `plugins/qingshui`。**未达标前不要切默认流量。**

> 注意：当前 `origin/main` 上 `/api/v1/agent/*` 返回 **410 Gone**（09-29 cutover 已合入）。若云上仍跑旧 Agent 镜像，用该环境做 old-track；否则用 `eval_dual_track.py --mode judge-files` 对比粘贴结果，并另开决策是否恢复旧轨 HTTP。

## 步骤

1. **起 Data MCP（云）** — 见 `deploy/mcp/README.md` + `qingshui-data-mcp.service.example`  
2. **本机 harness（dev-eval）**：`mcpBaseUrl` 指向云端 MCP（HTTPS + API Key）；**禁止**默认 Mac 隧道  
3. **云端 harness**：`mcpBaseUrl=http://127.0.0.1:8100/mcp`（与 Knowledge 同机）  
4. **烟雾**：`KNOWLEDGE_API_KEY=… ./scripts/smoke_mcp_p0.sh`  
5. **评测**：
   ```bash
   cd backend
   .venv/bin/python scripts/eval_dual_track.py \
     --cases eval/expected_gap_cases_v1.json \
     --mode judge-files \
     --old-answer-file /tmp/old_answers.json \
     --new-answer-file /tmp/new_answers.json \
     --out eval/out/dual_track_report.json
   ```
6. **切流门禁**（见 `eval_dual_track.py` docstring）：新≥旧、无回归、轨迹可定位、embedding 无 Mac 隧道、连续 ≥3 次无回退  

## 未达标前

默认对话入口仍走旧轨（若可用）；dsh / MCP 仅旁路与评测。
