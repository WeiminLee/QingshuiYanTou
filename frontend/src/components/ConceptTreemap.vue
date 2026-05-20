<template>
  <div class="concept-treemap">
    <!-- Breadcrumb navigation -->
    <div class="breadcrumb-bar" v-if="breadcrumb.length > 1">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item
          v-for="(crumb, idx) in breadcrumb"
          :key="idx"
          :to="idx === 0 ? {} : undefined"
          @click="idx === 0 && marketStore.resetBreadcrumb()"
        >
          {{ crumb.name }}
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <!-- Treemap chart wrapped in DataPanel -->
    <DataPanel :loading="loading" :error="error" :data="concepts">
      <div ref="chartRef" class="chart-container" />
    </DataPanel>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useMarketStore } from '../store/market.js'
import { useUiStore } from '../store/ui.js'
import { usePolling } from '../composables/usePolling.js'
import { useEChart } from '../composables/useEChart.js'
import DataPanel from './DataPanel.vue'
import * as echarts from 'echarts'

const marketStore = useMarketStore()
const uiStore = useUiStore()
const { concepts, breadcrumb, loading, error } = storeToRefs(marketStore)

const chartRef = ref(null)
const { initChart, setOption, disposeChart } = useEChart(chartRef)

const { start } = usePolling(60_000, 300_000, () => marketStore.fetchConcepts())

onMounted(async () => {
  await marketStore.fetchConcepts()
  await nextTick()
  renderChart()
  attachClickHandler()
  start()
})

watch(concepts, () => { nextTick(() => renderChart()) })

function buildTreeData(data) {
  return data.slice(0, 100).map(item => ({
    name: item.name,
    value: item.amount || 1,
    ts_code: item.ts_code,
    pct_change: item.pct_change ?? 0,
    amount: item.amount,
    itemStyle: { color: colorForPct(item.pct_change) },
  }))
}

function colorForPct(pct) {
  if (pct > 0) return '#ef4444'
  if (pct < 0) return '#22c55e'
  return '#d1d5db'
}

async function renderChart() {
  if (!chartRef.value || !concepts.value.length) return
  const inst = initChart()
  inst.setOption({
    title: {
      text: '概念板块热力图',
      left: 16,
      top: 8,
      textStyle: { fontSize: 14, fontWeight: 600, color: '#303133' },
    },
    tooltip: {
      formatter(params) {
        const d = params.data
        const sign = d.pct_change >= 0 ? '+' : ''
        return `<b>${d.name}</b><br/>涨跌幅: ${sign}${d.pct_change}%<br/>成交额: ${((d.amount || 0) / 1e8).toFixed(2)}亿`
      },
    },
    series: [{
      type: 'treemap',
      data: buildTreeData(concepts.value),
      leafDepth: 1,
      label: {
        show: true,
        formatter: '{b}',
        fontSize: 11,
        color: '#fff',
        overflow: 'truncate',
        truncate: { maxChars: 8 },
      },
      upperLabel: { show: false },
      itemStyle: { borderColor: '#fff', borderWidth: 1, gapWidth: 1 },
    }],
  }, true)
}

function attachClickHandler() {
  nextTick(() => {
    const inst = echarts.getInstanceByDom(chartRef.value)
    inst?.on('click', async (params) => {
      const d = params.data || {}
      if (!d.ts_code) return
      marketStore.setBreadcrumb([{ name: d.name }])
      const detail = await marketStore.fetchConceptDetail(d.ts_code)
      uiStore.setSelectedSector({
        ...d,
        constituents: detail?.constituents || detail?.stocks || [],
      })
    })
  })
}

onBeforeUnmount(disposeChart)
</script>

<style scoped>
.concept-treemap {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.breadcrumb-bar {
  padding: 8px 4px;
  flex-shrink: 0;
}

.chart-container {
  width: 100%;
  min-height: 400px;
  flex: 1;
}
</style>
