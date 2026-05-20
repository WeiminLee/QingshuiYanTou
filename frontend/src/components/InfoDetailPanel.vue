<template>
  <div class="info-detail-panel" v-if="info">
    <!-- Back button -->
    <div class="detail-back">
      <el-button size="small" @click="uiStore.clearInfoSelection()">
        ← 返回列表
      </el-button>
    </div>

    <!-- Source + time header -->
    <div class="detail-header">
      <span class="source-badge" :style="sourceStyle(info.source)">
        {{ sourceLabel(info.source) }}
      </span>
      <span class="detail-time">{{ formatTime(info.publish_time || info.time) }}</span>
    </div>

    <!-- Title -->
    <h3 class="detail-title">{{ info.title }}</h3>

    <!-- Content -->
    <div class="detail-content">
      {{ info.content || info.summary || '暂无正文内容' }}
    </div>

    <!-- Related concepts -->
    <div v-if="info.related_concepts?.length" class="related-section">
      <div class="related-label">关联板块</div>
      <div class="related-tags">
        <el-tag
          v-for="c in info.related_concepts"
          :key="c.ts_code || c.name"
          class="related-tag"
          @click="navigateToSector(c)"
        >
          {{ c.name || c.ts_code }}
        </el-tag>
      </div>
    </div>

    <!-- Related stocks -->
    <div v-if="info.related_stocks?.length" class="related-section">
      <div class="related-label">关联个股</div>
      <div class="related-tags">
        <el-tag
          v-for="s in info.related_stocks"
          :key="s.ts_code"
          class="related-tag stock-tag"
          @click="navigateToStock(s)"
        >
          {{ s.name || s.ts_code }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '../store/ui.js'

const uiStore = useUiStore()
const { selectedInfo } = storeToRefs(uiStore)

const info = computed(() =>
  selectedInfo.value?.type === 'info' ? selectedInfo.value.data : null
)

function navigateToSector(c) {
  uiStore.setSelectedSector(c)
}

function navigateToStock(s) {
  uiStore.setSelectedStock(s)
}

function sourceLabel(source) {
  const map = { cls: '财联社', announcement: '公告', research: '研报', qa: '互动易' }
  return map[source] || source || ''
}

function sourceStyle(source) {
  const styles = {
    cls: { background: '#fff4ef', color: '#ff6b35' },
    announcement: { background: '#f5f3ff', color: '#7c3aed' },
    research: { background: '#ecfeff', color: '#0891b2' },
    qa: { background: '#ecfdf5', color: '#059669' },
  }
  return styles[source] || { background: '#f5f7fa', color: '#909399' }
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d)) return String(ts)
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}
</script>

<style scoped>
.info-detail-panel { display: flex; flex-direction: column; gap: 12px; }

.detail-back { margin-bottom: 4px; }

.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.source-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.detail-time { font-size: 12px; color: #909399; margin-left: auto; }

.detail-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  line-height: 1.4;
  margin: 0;
}

.detail-content {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  white-space: pre-wrap;
  max-height: 360px;
  overflow-y: auto;
  padding: 12px;
  background: #fafafa;
  border-radius: 6px;
}

.related-section { display: flex; flex-direction: column; gap: 8px; }
.related-label { font-size: 12px; font-weight: 600; color: #606266; }
.related-tags { display: flex; flex-wrap: wrap; gap: 6px; }

.related-tag { cursor: pointer; }
.related-tag:hover { opacity: 0.8; }
.stock-tag { color: #303133; }
</style>
