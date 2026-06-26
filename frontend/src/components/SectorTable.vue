<template>
  <div class="sector-table">
    <DataPanel :loading="loading" :error="error" :data="concepts">
      <el-table
        :data="concepts"
        stripe
        style="width: 100%"
        row-class-name="clickable-row"
        @row-click="onRowClick"
      >
        <el-table-column prop="name" label="板块名称" min-width="140" />
        <el-table-column prop="pct_change" label="涨跌幅" width="100" sortable>
          <template #default="{ row }">
            <span :class="pctClass(row.pct_change)">
              {{ row.pct_change >= 0 ? "+" : "" }}{{ row.pct_change?.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="amount" label="成交额" width="120" sortable>
          <template #default="{ row }">
            {{ formatAmount(row.amount) }}
          </template>
        </el-table-column>
      </el-table>
    </DataPanel>
  </div>
</template>

<script setup>
import { storeToRefs } from "pinia";
import { useMarketStore } from "../store/market.js";
import { useUiStore } from "../store/ui.js";
import { usePolling } from "../composables/usePolling.js";
import DataPanel from "./DataPanel.vue";

const marketStore = useMarketStore();
const uiStore = useUiStore();
const { concepts, loading, error } = storeToRefs(marketStore);

const { start } = usePolling(60_000, 300_000, () => marketStore.fetchConcepts());
onMounted(() => start());

function formatAmount(val) {
  if (!val) return "-";
  if (val >= 1e8) return (val / 1e8).toFixed(2) + "亿";
  if (val >= 1e4) return (val / 1e4).toFixed(2) + "万";
  return String(val);
}

function pctClass(val) {
  if (val > 0) return "gain-text";
  if (val < 0) return "loss-text";
  return "neutral-text";
}

function onRowClick(row) {
  uiStore.setSelectedSector(row);
}
</script>

<style scoped>
.sector-table {
  width: 100%;
  height: 100%;
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
