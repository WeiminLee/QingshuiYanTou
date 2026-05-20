<template>
  <el-menu
    :default-active="activePanel"
    :collapse="collapsed"
    class="dashboard-sidebar"
    background-color="#1a1a2e"
    text-color="rgba(255,255,255,0.7)"
    active-text-color="#ffffff"
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
import { TrendCharts, DataLine, Connection, Document, Search } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '../store/ui.js'

const uiStore = useUiStore()
const { activePanel } = storeToRefs(uiStore)

const props = defineProps({
  collapsed: {
    type: Boolean,
    default: false,
  },
})

function onSelect(index) {
  uiStore.setActivePanel(index)
}
</script>

<style scoped>
.dashboard-sidebar {
  height: 100%;
  border-right: none;
}

.dashboard-sidebar:not(.el-menu--collapse) {
  width: 220px;
}

.dashboard-sidebar .el-menu-item {
  border-left: 3px solid transparent;
}

.dashboard-sidebar .el-menu-item.is-active {
  background-color: rgba(64, 158, 255, 0.1) !important;
  border-left-color: #409eff;
  color: #ffffff;
}

.dashboard-sidebar .el-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.05) !important;
  color: #ffffff;
}

.dashboard-sidebar .el-menu-item.is-disabled {
  opacity: 0.5;
}
</style>
