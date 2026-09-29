<template>
  <el-menu
    :default-active="activePanel"
    :collapse="collapsed"
    class="dashboard-sidebar"
    :background-color="ledgerSpineBg"
    :text-color="ledgerTextColor"
    :active-text-color="ledgerActiveTextColor"
    :collapse-transition="true"
    @select="onSelect"
  >
    <el-menu-item index="sector">
      <el-icon><TrendCharts /></el-icon>
      <template #title>概念涨跌</template>
    </el-menu-item>

    <el-menu-item index="stock">
      <el-icon><DataLine /></el-icon>
      <template #title>龙头股</template>
    </el-menu-item>

    <el-menu-item index="sectorRelation">
      <el-icon><Connection /></el-icon>
      <template #title>板块关系</template>
    </el-menu-item>

    <el-menu-item index="news">
      <el-icon><Document /></el-icon>
      <template #title>资讯信息</template>
    </el-menu-item>

    <el-menu-item index="intel">
      <el-icon><Search /></el-icon>
      <template #title>情报信息</template>
    </el-menu-item>
  </el-menu>
</template>

<script setup>
import { TrendCharts, DataLine, Connection, Document, Search } from "@element-plus/icons-vue";
import { storeToRefs } from "pinia";
import { useUiStore } from "../store/ui.js";

const uiStore = useUiStore();
const { activePanel } = storeToRefs(uiStore);

// Ledger Spine color values
const ledgerSpineBg = "#1E1C18";
const ledgerTextColor = "rgba(255,255,255,0.7)";
const ledgerActiveTextColor = "#D8D0C0";

const props = defineProps({
  collapsed: {
    type: Boolean,
    default: false,
  },
});

function onSelect(index) {
  uiStore.setActivePanel(index);
}
</script>

<style scoped>
.dashboard-sidebar {
  height: 100%;
  border-right: none;
  background: #1e1c18 !important;
}

.dashboard-sidebar:not(.el-menu--collapse) {
  width: 220px;
}

.dashboard-sidebar .el-menu-item {
  border-left: 3px solid transparent;
  color: rgba(255, 255, 255, 0.7);
}

.dashboard-sidebar .el-menu-item.is-active {
  background-color: #2c2419 !important;
  border-left-color: #b8860b;
  color: #d8d0c0;
}

.dashboard-sidebar .el-menu-item:hover {
  background-color: #353028 !important;
  color: #d8d0c0;
}

.dashboard-sidebar .el-menu-item.is-disabled {
  opacity: 0.5;
}
</style>
