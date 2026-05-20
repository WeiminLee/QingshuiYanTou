# =============================================
# 清水投研系统 - 定时任务模板
#
# 当前状态：云端已统一数据来源，本地定时同步任务已全部清理。
# 如需恢复，请按需取消注释对应的任务行。
# =============================================

# （预留）每 30 分钟 KG 知识图谱增量抽取（flock 防止重叠运行）
# */30 * * * * flock -n /tmp/kg_extraction.lock -c "cd /home/10241671/code/LocalProjects/QingShuiTouYan/backend && /home/10241671/code/LocalProjects/QingShuiTouYan/.venv/bin/python scripts/kg_extraction_pipeline.py >> logs/kg_extraction.log 2>&1"
