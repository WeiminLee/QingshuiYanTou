# Cloud handoff — dsh vertical slice + 硅片预期差

Host: `root@124.221.188.38` path `/home/lwm/code/QingShuiTouYan` (see ops docs).

## One-shot headless 预期差（今晚验收）

```bash
ssh root@124.221.188.38
cd /home/lwm/code/QingShuiTouYan
git fetch && git checkout feat/dsh-vertical-slice && git pull
# Node 24 via nvm
export NVM_DIR=/home/lwm/.nvm; . "$NVM_DIR/nvm.sh"; nvm use 24
# env (gitignored): OPENAI_API_KEY, LLM_*, KNOWLEDGE_API_KEY or API_KEY from backend/.env
set -a; source .env.dsh; set +a
pnpm install
cd dsh && CI=true pnpm_config_verify_deps_before_run=false pnpm install && pnpm run build:lib:host && cd ..
pnpm run build:plugin
pnpm dsh plugin --profile headless add ./plugins/qingshui
# May stop data-acquisition processes for test
pnpm run check:skills
pnpm dsh --profile headless --patch patches/qingshui.yml "对硅片板块做预期差分析" | tee /tmp/silicon-wafer-divergence-dsh.md
```

Rollback: leave submodule/plugin in git; stop any dsh unit; Vue/LangChain untouched.
