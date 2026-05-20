<template>
  <div class="capital-sankey">
    <DataPanel :loading="loading" :error="error" :data="chartData">
      <div ref="chartRef" class="sankey-container" />
    </DataPanel>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '../store/ui.js'
import { useEChart } from '../composables/useEChart.js'
import DataPanel from './DataPanel.vue'
import { getCapitalFlow } from '../api/stocks.js'

const uiStore = useUiStore()
const { selectedCapital } = storeToRefs(uiStore)

const chartRef = ref(null)
const { initChart, disposeChart } = useEChart(chartRef)

const loading = ref(false)
const error = ref(null)
const chartData = ref([])

const props = defineProps({
  period: {
    type: String,
    default: 'D',
  },
})
const activePeriod = ref(props.period)
const sankeyData = ref({ nodes: [], links: [] })

async function fetchCapitalFlow() {
  loading.value = true
  error.value = null
  try {
    const data = await getCapitalFlow(activePeriod.value, 20)
    sankeyData.value = { nodes: data.nodes || [], links: data.links || [] }
    await nextTick()
    renderChart()
    attachClickHandler()
  } catch (e) {
    error.value = e.message || '加载资金流数据失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await fetchCapitalFlow()
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})

watch(() => props.period, () => {
  activePeriod.value = props.period
  fetchCapitalFlow()
})

function buildMockData() {
  // Mock capital flow data for 10 sectors
  const sectors = [
    '半导体', '新能源车', 'AI算力', '医药生物', '光伏设备',
    '白酒', '银行', '房地产', '军工', '煤炭',
  ]
  const nodes = sectors.map(name => {
    const net = (Math.random() - 0.4) * 10  // slightly biased to positive for demo
    return { name, net_inflow: +net.toFixed(2) }
  })

  // Build links: connect first 5 to last 5 as toy flow
  const links = []
  for (let i = 0; i < 5; i++) {
    for (let j = 5; j < 10; j++) {
      const val = Math.random() * 5
      links.push({ source: sectors[i], target: sectors[j], value: +val.toFixed(2) })
    }
  }
  return { nodes, links }
}

function renderChart() {
  if (!chartRef.value) return
  const { nodes, links } = sankeyData.value

  const sankeyNodes = nodes.map(n => ({
    name: n.name,
    value: Math.abs(n.net_inflow),
    itemStyle: { color: n.net_inflow >= 0 ? '#ef4444' : '#22c55e' },
  }))

  const sankeyLinks = links.map(l => ({
    source: l.source,
    target: l.target,
    value: l.value,
  }))

  const inst = initChart()
  inst.setOption({
    title: {
      text: '资金流向（桑基图）',
      left: 16,
      top: 8,
      textStyle: { fontSize: 14, fontWeight: 600, color: '#303133' },
    },
    tooltip: {
      trigger: 'item',
      formatter(params) {
        const d = params.data
        const sign = d.value >= 0 ? '+' : ''
        return `${d.source} → ${d.target}<br/>资金: ${sign}${d.value}亿`
      },
    },
    series: [{
      type: 'sankey',
      layout: 'none',
      emphasis: { focus: 'adjacency' },
      nodeAlign: 'left',
      data: sankeyNodes,
      links: sankeyLinks,
      lineStyle: { color: 'gradient', curveness: 0.5 },
      itemStyle: { borderWidth: 0 },
      label: { show: true, fontSize: 11, color: '#303133' },
    }],
  })
}

function attachClickHandler() {
  nextTick(() => {
    const inst = window.echarts?.getInstanceByDom(chartRef.value)
    inst?.on('click', (params) => {
      if (params.dataType === 'node') {
        const name = params.data.name
        const node = sankeyData.value.nodes.find(n => n.name === name)
        uiStore.setSelectedCapital({ name, ...node })
      }
    })
  })
}

onBeforeUnmount(disposeChart)
</script>

<style scoped>
.capital-sankey { width: 100%; height: 100%; display: flex; flex-direction: column; }
.sankey-container { width: 100%; min-height: 420px; flex: 1; }
</style>
