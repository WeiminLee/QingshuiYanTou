# d-cluster Embedding 修复包（2026-09-19）

> 背景证据：云端探针任务（vector job）被 d-cluster worker 秒级领走但 3 连失败（`vector upsert failed`），
> 证明 **d-cluster worker 进程存活、embedding 通道断裂**；云端侧 `GatewayPorts clientspecified` 正常，
> sshd 仅 2 条孤立 `ssh-rsa` 拒绝记录（非持续重试），隧道脚本 9-17 晚起死亡且未自愈。
> 我方所有远程通道无授权（desktop 网络不可达 / root+liweimin publickey 拒绝），需在 d-cluster 会话执行本包。

## 一、诊断（先跑，输出贴回来即可定位）

```bash
# 1. embedding 服务体检（9-04 拓扑：GPU0，127.0.0.1:11434）
ps aux | grep -i embed | grep -v grep
curl -s -m 5 http://127.0.0.1:11434/health || echo "本地 11434 无响应"

# 2. worker 配置指纹（指向哪个 embedding）
grep -E "EMBEDDING" ~/qingshui-worker/backend/.env 2>/dev/null || find / -maxdepth 4 -name ".env" -path "*worker*" 2>/dev/null | xargs grep -l EMBEDDING 2>/dev/null

# 3. 关键脚本定位
find /root/workspace /home /opt -maxdepth 4 \( -name "embedding_server*.py" -o -name "qingshui-embed-tunnel.sh" \) 2>/dev/null

# 4. 隧道进程
ps aux | grep "embed-tunnel" | grep -v grep
```

## 二、修复（按诊断结果二选一）

**A. 若本地 11434 无响应（embedding 服务挂了）——重启服务：**
```bash
cd $(dirname <step3 找到的 embedding_server.py 路径>)
nohup /opt/conda/bin/python embedding_server.py --host 127.0.0.1 --port 11434 \
  </dev/null >/tmp/embedding_server.log 2>&1 &
sleep 20 && curl -s http://127.0.0.1:11434/health
```

**B. 本地服务健康但隧道断——重启隧道：**
```bash
pkill -f qingshui-embed-tunnel 2>/dev/null; sleep 1
cd $(dirname <step3 找到的 qingshui-embed-tunnel.sh 路径>)
nohup bash qingshui-embed-tunnel.sh </dev/null >/tmp/embed-tunnel.log 2>&1 &
sleep 10
```

## 三、云端验证（任一路径修完必须回验）

```bash
ssh root@124.221.188.38 "ss -tlnp | grep 11434; curl -s -m 5 http://172.18.0.1:11434/health"
```

云侧 `ss -tlnp` 应出现 11434 监听（`-R` 反向绑定），且 health 200。

## 四、恢复语义评估（云端，隧道通了以后）

```bash
ssh root@124.221.188.38 'su lwm -s /bin/bash -c "cd /home/lwm/code/QingShuiTouYan/backend && \
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.eval_retrieval --backend semantic --k 20"'
```

按 gold set 更新 theme 条目（AI 算力候选证据已备好：`EV:b147cb8d…`，601137.SH 2026-06-18 IRM，
内容为 AI 服务器压延合金铜箔/算力厂商/2027 扩产），即可完成三通道全量 A/B。

## 五、常见坑

1. 隧道绑定：云侧 `GatewayPorts clientspecified` 已允许 `ssh -R 172.18.0.1:11434:127.0.0.1:11434` 绑定 docker bridge；
   若脚本绑的是 127.0.0.1，backend 容器（经 172.18.0.1）将不可达——绑定地址必须与 `EMBEDDING_BASE_URL` 一致。
2. 云端 sshd 8.8+ 默认拒绝 `ssh-rsa`（SHA-1）签名：若 d-cluster 用老旧 RSA key，`-R` 会每 5s 失败一次。
   建议换成 ed25519 key；紧急时可在云侧 `Match User root` 段加 `PubkeyAcceptedAlgorithms +ssh-rsa`（弱签名，短期用）。
3. 重启后务必跑一次云端 vector 任务回验（插探针 job 或走真实公告摄入）。
