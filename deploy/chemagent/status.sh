#!/bin/bash
# 清水 chemagent 全栈状态一览
M=/mnt/shared-storage-user/liweimin/qingshui
source /etc/profile.d/ssh-init.sh 2>/dev/null
echo "===== GPU 推理服务（rjob, 单卡）====="
rjob list 2>&1 | grep -A2 "1gpu" | head -3 || echo "  未运行"
NODE=$(python3 -c "import json;print(json.load(open('$M/endpoints.json'))['node_ip'])" 2>/dev/null)
echo "  node_ip: $NODE"
for p in 23456 23457; do printf "  port %s: " $p; curl -s -m 5 --noproxy "*" -o /dev/null -w "%{http_code}\n" http://$NODE:$p/v1/models 2>/dev/null || echo "n/a"; done
echo "===== worker（systemd supervisor）====="
echo "  active=$(systemctl is-active qingshui-worker.service) enabled=$(systemctl is-enabled qingshui-worker.service 2>/dev/null)"
pgrep -af knowledge_worker | sed "s|.*job-type |  job-type |" | head -4
echo "===== 本机数据面 ====="
for p in 8001 8100; do printf "  port %s: " $p; curl -s -m 5 --noproxy "*" -o /dev/null -w "%{http_code}\n" http://127.0.0.1:$p/health 2>/dev/null || echo "n/a"; done
echo "===== 存储 ====="
df -h /data | tail -1
df -h $M | tail -1
echo "===== 最近 supervisor 日志 ====="
tail -3 $M/logs/supervisor.log
