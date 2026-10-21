#!/usr/bin/env bash
# 本地 dsh 运行环境模板。
#
# 用法：
#   cp scripts/local-dsh-env.example.sh scripts/local-dsh-env.sh
#   chmod 600 scripts/local-dsh-env.sh          # 只读本人
#   填入真实密钥后 `source scripts/local-dsh-env.sh`
#
# scripts/local-dsh-env.sh 已被 .gitignore 忽略，**不要**把它提交回仓库。

# Knowledge API / Data MCP 鉴权（chemagent 服务，经 SSH 隧道 8001/8100 访问）。
# 取值 = chemagent 上 backend/.env 的 API_KEY（后端用它校验 X-API-Key）。
export KNOWLEDGE_API_KEY="<chemagent backend/.env 的 API_KEY>"

# LLM：pjlab 网关（dsh provider "qingshui" 的 apiKeyEnv=OPENAI_API_KEY）
# 取值 = chemagent 上 backend/.env 的 LLM_API_KEY
export OPENAI_API_KEY="<chemagent backend/.env 的 LLM_API_KEY>"
