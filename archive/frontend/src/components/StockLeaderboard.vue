<template>
  <div class="stock-leaderboard">
    <!-- ECharts horizontal bar chart -->
    <div class="leaderboard-chart">
      <div ref="chartRef" class="chart-container" />
    </div>

    <!-- Data table -->
    <DataPanel :loading="loading" :error="error" :data="stocks">
      <el-table
        :data="stocks"
        stripe
        style="width: 100%"
        row-class-name="clickable-row"
        @row-click="onRowClick"
      >
        <el-table-column prop="name" label="股票名称" min-width="100" />
        <el-table-column prop="ts_code" label="代码" width="110">
          <template #default="{ row }">
            <span style="font-family: monospace; font-size: 12px">{{ row.ts_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="现价" width="80">
          <template #default="{ row }">
            {{ row.price?.toFixed(2) || "-" }}
          </template>
        </el-table-column>
        <el-table-column prop="pct_change" label="涨跌幅" width="90" sortable>
          <template #default="{ row }">
            <span :class="pctClass(row.pct_change)">
              {{ pctSign(row.pct_change) }}{{ row.pct_change?.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="turnover_rate" label="换手率" width="80" sortable>
          <template #default="{ row }"> {{ row.turnover_rate?.toFixed(2) }}% </template>
        </el-table-column>
        <el-table-column prop="volume" label="成交量" width="100" sortable>
          <template #default="{ row }">
            {{ formatVolume(row.volume) }}
          </template>
        </el-table-column>
      </el-table>
    </DataPanel>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick, watch } from "vue";
import { storeToRefs } from "pinia";
import { useMarketStore } from "../store/market.js";
import { useUiStore } from "../store/ui.js";
import { usePolling } from "../composables/usePolling.js";
import { useEChart } from "../composables/useEChart.js";
import DataPanel from "./DataPanel.vue";

const marketStore = useMarketStore();
const uiStore = useUiStore();
const { stocks, loading, error } = storeToRefs(marketStore);

const chartRef = ref(null);
const { initChart, setOption, disposeChart } = useEChart(chartRef);

const { start } = usePolling(60_000, 300_000, () => marketStore.fetchStocks());

onMounted(async () => {
  await marketStore.fetchStocks();
  await nextTick();
  renderChart();
  start();
});

watch(stocks, async () => {
  await nextTick();
  renderChart();
});

function renderChart() {
  if (!chartRef.value || !stocks.value.length) return;
  const top10 = stocks.value.slice(0, 10);
  const names = top10.map((s) => (s.name || s.ts_code || "").slice(0, 6));
  const pcts = top10.map((s) => s.pct_change ?? 0);
  const colors = pcts.map((p) => (p >= 0 ? "#ef4444" : "#22c55e"));

  const inst = initChart();
  inst.setOption({
    title: {
      text: "龙头股涨跌幅 Top10",
      left: 0,
      textStyle: { fontSize: 12, fontWeight: 600, color: "#303133" },
    },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 8, right: 48, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: "value", axisLabel: { formatter: "{value}%", fontSize: 10, color: "#909399" } },
    yAxis: { type: "category", data: names, axisLabel: { fontSize: 10, color: "#909399" } },
    series: [
      {
        type: "bar",
        data: pcts.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
        barWidth: "60%",
        label: { show: true, position: "right", formatter: "{c}%", fontSize: 10 },
      },
    ],
  });
}

function pctClass(val) {
  if (val > 0) return "gain-text";
  if (val < 0) return "loss-text";
  return "neutral-text";
}

function pctSign(val) {
  return val >= 0 ? "+" : "";
}

function formatVolume(v) {
  if (!v) return "-";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(2) + "万";
  return String(v);
}

function onRowClick(row) {
  uiStore.setSelectedStock(row);
}

onBeforeUnmount(disposeChart);
</script>

<style scoped>
.stock-leaderboard {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.leaderboard-chart {
  flex-shrink: 0;
}
.chart-container {
  width: 100%;
  height: 200px;
}

.gain-text {
  color: #ef4444;
  font-weight: 600;
}
.loss-text {
  color: #22c55e;
  font-weight: 600;
}
.neutral-text {
  color: #909399;
}

.clickable-row {
  cursor: pointer;
}
.clickable-row:hover > td {
  background-color: #f5f7fa !important;
}
</style>
