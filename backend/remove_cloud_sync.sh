#!/bin/bash
# 移除云端同步相关代码

echo "=== 移除云端同步代码 ==="

# 1. crontab.txt - 删除云端同步任务
sed -i '/# 每日 18:10（收盘后）—— 从云端同步公告和研报元数据/,/sync_from_cloud.log/d' crontab.txt
echo "[1/6] crontab.txt 已更新"

# 2. metadata.py - 删除 SOURCE_CLOUD_API 常量和映射
sed -i '/SOURCE_CLOUD_API = "cloud_api"/d' app/core/metadata.py
sed -i '/source_name="云端 API"/,/},$/d' app/core/metadata.py
echo "[2/6] metadata.py 已更新"

# 3. models.py - 删除 SyncLog 模型类
sed -i '/class SyncLog(Base):/,/^$/d' app/models/models.py
sed -i '/云端同步日志（每日同步记录）/d' app/models/models.py
echo "[3/6] models.py 已更新"

# 4. kg_indexer.py - 移除注释中的"云端"描述
sed -i '/云端 = 数据仓库/d' app/knowledge/kg_indexer.py
sed -i '/不访问云端/d' app/knowledge/kg_indexer.py
sed -i '/云端元数据/d' app/knowledge/kg_indexer.py
sed -i '/云端下载 URL/d' app/knowledge/kg_indexer.py
echo "[4/6] kg_indexer.py 已更新"

# 5. api/data.py - 移除注释
sed -i 's/已移除云端 API 依赖。//' app/data_pipeline/api/data.py
echo "[5/6] api/data.py 已更新"

# 6. api/concept.py - 移除废弃端点说明
sed -i '/Tushare 已停用/d' app/knowledge/api/concept.py
sed -i '/已废弃/d' app/knowledge/api/concept.py
echo "[6/6] api/concept.py 已更新"

echo ""
echo "=== 完成 ==="
echo "请检查修改结果并运行测试验证"
