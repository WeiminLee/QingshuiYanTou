<template>
  <div class="info-timeline">
    <DataPanel :loading="loading" :error="error" :data="filteredItems">
      <el-timeline v-if="filteredItems.length">
        <el-timeline-item
          v-for="item in filteredItems"
          :key="item.id"
          :timestamp="formatTime(item.publish_time || item.time)"
          placement="top"
          class="timeline-item"
          @click="selectItem(item)"
        >
          <div class="timeline-card" :class="{ 'is-selected': selectedId === item.id }">
            <div class="card-header">
              <span class="source-badge" :style="sourceStyle(item.source)">
                {{ sourceLabel(item.source) }}
              </span>
              <span
                class="tier-dot"
                :style="{ background: tierColor(item.tier ?? item.confidence_tier) }"
                :title="`TIER ${item.tier ?? item.confidence_tier ?? '?'}`"
              />
              <span class="card-time">{{ formatTime(item.publish_time || item.time) }}</span>
            </div>
            <div class="card-title">{{ item.title }}</div>
          </div>
        </el-timeline-item>
      </el-timeline>
      <div v-else-if="!loading && !error" class="no-items">
        <el-empty :description="hasActiveFilter ? '暂无符合筛选条件的资讯' : '暂无资讯数据'" />
      </div>
    </DataPanel>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '../store/ui.js'
import { getNewsList } from '../api/information.js'
import DataPanel from './DataPanel.vue'

const props = defineProps({
  filters: {
    type: Object,
    default: () => ({ sources: [], tiers: [] }),
  },
})

const uiStore = useUiStore()
const { selectedInfo } = storeToRefs(uiStore)

const allItems = ref([])
const loading = ref(false)
const error = ref(null)

const selectedId = computed(() => selectedInfo.value?.id)

const hasActiveFilter = computed(() =>
  (props.filters.sources?.length ?? 0) > 0 || (props.filters.tiers?.length ?? 0) > 0
)

const filteredItems = computed(() => {
  let items = allItems.value
  if (props.filters.sources?.length) {
    items = items.filter(i => props.filters.sources.includes(i.source))
  }
  if (props.filters.tiers?.length) {
    items = items.filter(i => {
      const t = i.tier ?? i.confidence_tier ?? -1
      return props.filters.tiers.includes(t)
    })
  }
  return items
})

onMounted(() => fetchNews())

async function fetchNews() {
  loading.value = true
  error.value = null
  try {
    const data = await getNewsList()
    allItems.value = Array.isArray(data) ? data : []
  } catch (e) {
    error.value = e.message || '加载资讯失败'
  } finally {
    loading.value = false
  }
}

function selectItem(item) {
  uiStore.setSelectedInfo(item)
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

function tierColor(tier) {
  const colors = { 0: '#059669', 1: '#16a34a', 2: '#ca8a04', 3: '#ea580c', 4: '#dc2626' }
  return colors[tier ?? -1] || '#d1d5db'
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d)) return String(ts)
  return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}
</script>

<style scoped>
.info-timeline { width: 100%; height: 100%; }

.timeline-item { cursor: pointer; }

.timeline-card {
  padding: 8px 12px;
  border-radius: 6px;
  background: #fafafa;
  border: 1px solid transparent;
  transition: all 0.15s;
}
.timeline-card:hover { background: #f0f4ff; border-color: #409eff; }
.timeline-card.is-selected { background: #ecf5ff; border-color: #409eff; }

.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.source-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
}

.tier-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.card-time { font-size: 11px; color: #909399; margin-left: auto; }
.card-title { font-size: 13px; color: #303133; line-height: 1.4; }

.no-items { padding: 24px; text-align: center; }
</style>
