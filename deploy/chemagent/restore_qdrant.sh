#!/bin/bash
set -e
cd /data/migration
echo "=== 停 qdrant → 解包 → 起 qdrant ==="
docker stop qingshui_qdrant
rm -rf /data/qingshui/qdrant/collections/doc_chunks
tar -xzf doc_chunks.tgz -C /data/qingshui/qdrant/collections/
# 退役集合不迁：只留 doc_chunks（及 qdrant 需要的元数据目录）
ls /data/qingshui/qdrant/collections/
docker start qingshui_qdrant
sleep 8
echo "=== 验证 ==="
curl -s -m 10 "http://127.0.0.1:6333/collections/doc_chunks" | python3 -c "import json,sys; d=json.load(sys.stdin)[\"result\"]; print(\"doc_chunks points:\", d[\"points_count\"], \"status:\", d[\"status\"])"
