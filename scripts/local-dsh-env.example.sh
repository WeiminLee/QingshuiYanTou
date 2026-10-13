#!/usr/bin/env bash
# 本地 dsh 运行环境模板（复制为 scripts/local-dsh-env.sh 并填真实密钥；该文件已 gitignore 吗？没有——请勿提交真实密钥版）
# 用法：source scripts/local-dsh-env.sh
#
# Knowledge API / Data MCP 鉴权（chemagent 服务，经 SSH 隧道 8001/8100 访问）
# 取值同 deploy/chemagent/worker_supervisor.py 里的 KNOWLEDGE_API_KEY
export KNOWLEDGE_API_KEY="<同 worker_supervisor.py 的 KNOWLEDGE_API_KEY>"
# LLM：pjlab 网关（dsh provider "qingshui" 的 apiKeyEnv=OPENAI_API_KEY）
# 取值见 chemagent /root/code/QingShuiYanTou/backend/.env 的 LLM_API_KEY
export OPENAI_API_KEY="<chemagent backend/.env 的 LLM_API_KEY>"
