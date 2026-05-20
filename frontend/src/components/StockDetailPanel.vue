<template>
  <div class="stock-detail-panel" v-if="stock">
    <div class="detail-header">
      <div class="stock-info">
        <div class="stock-name">{{ stock.name || '—' }}</div>
        <div class="stock-code">{{ stock.ts_code }}</div>
      </div>
      <div class="stock-price-block">
        <div class="stock-price">{{ priceStr(stock.price) }}</div>
        <div :class="['stock-pct', pctClass(stock.pct_change)]">
          {{ pctSign(stock.pct_change) }}{{ stock.pct_change?.toFixed(2) }}%
        </div>
      </div>
    </div>

    <div class="metrics-row">
      <div class="metric-item">
        <div class="metric-label">换手率</div>
        <div class="metric-value">{{ stock.turnover_rate?.toFixed(2) }}%</div>
      </div>
      <div class="metric-item">
        <div class="metric-label">成交量</div>
        <div class="metric-value">{{ ((stock.volume || 0) / 10000).toFixed(2) }}万手</div>
      </div>
    </div>

    <div class="kline-chart">
      <div v-if="klineLoading" class="chart-loading">
        <el-skeleton :rows="4" animated />
      </div>
      <div v-else-if="klineError" class="chart-error">
        <span class="error-hint">{{ klineError }}</span>
      </div>
      <div v-else ref="chartRef" class="kline-container" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '../store/ui.js'
import { useEChart } from '../composables/useEChart.js'
import { getKlineData } from '../api/stocks.js'

const uiStore = useUiStore()
const { selectedTarget } = storeToRefs(uiStore)

const chartRef = ref(null)
const { initChart, disposeChart } = useEChart(chartRef)

const klineLoading = ref(false)
const klineError = ref(null)

const stock = computed(() =>
  selectedTarget.value?.type === 'stock' ? selectedTarget.value.data : null
)

function pctClass(val) {
  if (!val) return 'neutral-text'
  if (val > 0) return 'gain-text'
  if (val < 0) return 'loss-text'
  return 'neutral-text'
}

function pctSign(val) {
  if (!val) return ''
  return val >= 0 ? '+' : ''
}

function priceStr(val) {
  if (val === null || val === undefined) return '-'
  return val.toFixed(2)
}

async function fetchKline() {
  if (!stock.value?.ts_code) return
  klineLoading.value = true
  klineError.value = null
  try {
    const periods = await getKlineData(stock.value.ts_code, 60)
    if (!periods || periods.length === 0) throw new Error('无K线数据')
    await nextTick()
    renderChartFromPeriods(periods)
  } catch (e) {
    klineError.value = e.message || 'K线加载失败'
    await nextTick()
    renderFallbackChart()
  } finally {
    klineLoading.value = false
  }
}

function renderChartFromPeriods(periods) {
  if (!chartRef.value) return
  const dates = periods.map(p => {
    const s = String(p.date)
    return `${s.slice(4, 6)}/${s.slice(6, 8)}`
  })
  const ohlc = periods.map(p => [p.open, p.close, p.low, p.high])
  const pct = stock.value?.pct_change ?? 0
  const bullColor = '#ef4444'
  const bearColor = '#22c55e'
  const candleColor = pct >= 0 ? bullColor : bearColor

  const inst = initChart()
  inst.setOption({
    title: {
      text: 'K线走势（近60日）',
      left: 0,
      textStyle: { fontSize: 12, fontWeight: 600, color: '#303133' },
    },
    tooltip: { trigger: 'axis', axisSelector: true },
    grid: { left: 8, right: 8, top: 36, bottom: 24, containLabel: false },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 9, color: '#909399', interval: 9 },
      boundaryGap: false,
    },
    yAxis: { scale: true, axisLabel: { fontSize: 10, color: '#909399' } },
    series: [{
      type: 'candlestick',
      data: ohlc,
      itemStyle: {
        color: candleColor,
        color0: bearColor,
        borderColor: candleColor,
        borderColor0: bearColor,
      },
    }],
  })
}

function renderFallbackChart() {
  if (!chartRef.value) return
  const base = stock.value?.price || 100
  const prices = []
  const dates = []
  let close = base
  for (let i = 59; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000)
    dates.push(`${d.getMonth() + 1}/${d.getDate()}`)
    close = close * (1 + (Math.random() - 0.5) * 0.01)
    prices.push(+close.toFixed(2))
  }

  const inst = initChart()
  inst.setOption({
    title: {
      text: 'K线走势（暂无数据，仅供参考）',
      left: 0,
      textStyle: { fontSize: 12, color: '#909399' },
    },
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 8, top: 36, bottom: 24, containLabel: false },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 9, color: '#909399', interval: 9 },
      boundaryGap: false,
    },
    yAxis: { scale: true, axisLabel: { fontSize: 10, color: '#909399' } },
    series: [{
      type: 'line',
      data: prices,
      smooth: true,
      showSymbol: false,
      lineStyle: { color: '#409eff', width: 1 },
    }],
  })
}

watch(stock, async () => { await nextTick(); fetchKline() })
onMounted(async () => { await nextTick(); fetchKline() })
onBeforeUnmount(disposeChart)
</script>

<style scoped>
.stock-detail-panel { display: flex; flex-direction: column; gap: 16px; }

.detail-header { display: flex; align-items: flex-start; justify-content: space-between; }

.stock-name { font-size: 18px; font-weight: 600; color: #303133; }
.stock-code { font-size: 12px; color: #909399; margin-top: 2px; }

.stock-price-block { text-align: right; }
.stock-price { font-size: 24px; font-weight: 600; color: #303133; }
.stock-pct { font-size: 16px; font-weight: 600; }

.gain-text { color: #ef4444; }
.loss-text { color: #22c55e; }
.neutral-text { color: #909399; }

.metrics-row { display: flex; gap: 24px; }
.metric-item { display: flex; flex-direction: column; gap: 2px; }
.metric-label { font-size: 12px; color: #909399; }
.metric-value { font-size: 14px; font-weight: 600; color: #303133; }

.kline-chart { width: 100%; }
.kline-container { width: 100%; height: 200px; }
.chart-loading, .chart-error {
  width: 100%;
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.error-hint { font-size: 12px; color: #909399; }
</style>
