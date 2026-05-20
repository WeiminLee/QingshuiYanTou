<template>
  <div class="capital-detail-panel" v-if="capital">
    <!-- Period selector -->
    <div class="period-selector">
      <span class="selector-label">周期：</span>
      <el-radio-group v-model="activePeriod" size="small" @change="onPeriodChange">
        <el-radio-button value="D">日</el-radio-button>
        <el-radio-button value="W">周</el-radio-button>
        <el-radio-button value="M">月</el-radio-button>
      </el-radio-group>
    </div>

    <!-- Sector name + net flow hero -->
    <div class="detail-hero">
      <div class="hero-name">{{ capital.name }}</div>
      <div :class="['hero-net', netFlowClass]">
        {{ netFlow >= 0 ? '+' : '' }}{{ netFlow.toFixed(2) }}亿
      </div>
      <div class="hero-sub">主力净流入</div>
    </div>

    <!-- Metrics row -->
    <div class="metrics-row">
      <div class="metric-item">
        <div class="metric-label">净流入</div>
        <div :class="['metric-value', netFlow >= 0 ? 'gain-text' : 'loss-text']">
          {{ netFlow >= 0 ? '+' : '' }}{{ netFlow.toFixed(2) }}亿
        </div>
      </div>
      <div class="metric-item">
        <div class="metric-label">净流出</div>
        <div class="metric-value loss-text">-{{ outflow.toFixed(2) }}亿</div>
      </div>
      <div class="metric-item">
        <div class="metric-label">总成交额</div>
        <div class="metric-value">{{ totalAmount.toFixed(2) }}亿</div>
      </div>
    </div>

    <!-- Constituent bar chart -->
    <div v-if="barLoading" class="chart-loading">
      <el-skeleton :rows="3" animated />
    </div>
    <div v-else ref="chartRef" class="bar-chart" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '../store/ui.js'
import { useEChart } from '../composables/useEChart.js'

const uiStore = useUiStore()
const { selectedCapital } = storeToRefs(uiStore)

const chartRef = ref(null)
const { initChart, disposeChart } = useEChart(chartRef)

const activePeriod = ref('D')
const barLoading = ref(false)

const capital = computed(() =>
  selectedCapital.value?.type === 'capital' ? selectedCapital.value.data : null
)

const netFlow = computed(() => capital.value?.net_inflow ?? 0)
const netFlowClass = computed(() => netFlow.value >= 0 ? 'gain-text' : 'loss-text')

// Mock derived metrics (in production would come from API)
const outflow = computed(() => Math.abs(netFlow.value) * 0.4)
const totalAmount = computed(() => Math.abs(netFlow.value) * 1.4)

function onPeriodChange(val) {
  activePeriod.value = val
  fetchDetail()
}

async function fetchDetail() {
  if (!capital.value) return
  barLoading.value = true
  try {
    await nextTick()
    renderBarChart()
  } finally {
    barLoading.value = false
  }
}

function renderBarChart() {
  if (!chartRef.value) return
  // Mock: show top-5 "contributor" bars as random data
  // Real: would call /api/v1/stocks/capital-flow?period=X with ts_code filter
  const labels = ['成分股A', '成分股B', '成分股C', '成分股D', '成分股E']
  const values = labels.map(() => +(Math.random() * 5).toFixed(2))
  const colors = values.map(v => v >= 0 ? '#ef4444' : '#22c55e')

  const inst = initChart()
  inst.setOption({
    title: {
      text: '资金流入 Top5 成分股',
      left: 0,
      textStyle: { fontSize: 12, fontWeight: 600, color: '#303133' },
    },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: labels, axisLabel: { fontSize: 10, color: '#909399' } },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}亿', fontSize: 10 } },
    series: [{
      type: 'bar',
      data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
      barWidth: '50%',
    }],
  })
}

watch(capital, async () => {
  await nextTick()
  fetchDetail()
}, { immediate: true })

onBeforeUnmount(disposeChart)
</script>

<style scoped>
.capital-detail-panel { display: flex; flex-direction: column; gap: 16px; }

.period-selector { display: flex; align-items: center; gap: 8px; }
.selector-label { font-size: 12px; color: #909399; }

.detail-hero { text-align: center; }
.hero-name { font-size: 18px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.hero-net { font-size: 28px; font-weight: 600; margin-bottom: 2px; }
.hero-sub { font-size: 12px; color: #909399; }

.gain-text { color: #ef4444; }
.loss-text { color: #22c55e; }

.metrics-row { display: flex; gap: 16px; }
.metric-item { display: flex; flex-direction: column; gap: 2px; }
.metric-label { font-size: 12px; color: #909399; }
.metric-value { font-size: 16px; font-weight: 600; color: #303133; }

.bar-chart { width: 100%; height: 160px; }
.chart-loading { width: 100%; height: 160px; display: flex; align-items: center; justify-content: center; }
</style>
