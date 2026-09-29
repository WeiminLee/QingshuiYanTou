<template>
  <div class="dashboard-shell">
    <el-container class="dashboard-layout">
      <!-- Private header: 56px -->
      <el-header class="dashboard-header-area">
        <DashboardHeader
          :collapsed="uiStore.sidebarCollapsed"
          @toggle-sidebar="uiStore.toggleSidebar()"
        />
      </el-header>

      <!-- Body: sidebar + main content -->
      <el-container class="dashboard-body">
        <!-- Sidebar: 220px / 64px -->
        <el-aside class="dashboard-aside" :class="{ 'aside-collapsed': uiStore.sidebarCollapsed }">
          <Sidebar :collapsed="uiStore.sidebarCollapsed" />
        </el-aside>

        <!-- Main content: left panel + right detail panel -->
        <el-main class="dashboard-main">
          <div class="content-area">
            <!-- Left: panel content: swaps by activePanel -->
            <div class="left-panel">
              <template v-if="uiStore.activePanel === 'sector'">
                <div class="panel-sector">
                  <div class="panel-sector-treemap">
                    <ConceptTreemap />
                  </div>
                  <div class="panel-sector-table">
                    <SectorTable />
                  </div>
                </div>
              </template>

              <template v-else-if="uiStore.activePanel === 'stock'">
                <StockLeaderboard />
              </template>

              <template v-else-if="uiStore.activePanel === 'sectorRelation'">
                <CapitalSankey />
              </template>

              <template
                v-else-if="uiStore.activePanel === 'news' || uiStore.activePanel === 'intel'"
              >
                <div class="info-panel">
                  <FilterBar class="info-filter-bar" @change="onFilterChange" />
                  <InfoTimeline class="info-timeline" :filters="activeFilters" />
                </div>
              </template>

              <template v-else>
                <div class="panel-placeholder">功能开发中</div>
              </template>
            </div>

            <!-- Right: detail panel (always visible) -->
            <div class="right-panel">
              <div v-if="!uiStore.selectedTarget" class="detail-default">
                <el-empty description="大盘概览" />
              </div>
              <SectorDetailPanel v-else-if="uiStore.selectedTarget?.type === 'sector'" />
              <StockDetailPanel v-else-if="uiStore.selectedTarget?.type === 'stock'" />
              <InfoDetailPanel v-else-if="uiStore.selectedTarget?.type === 'info'" />
              <CapitalDetailPanel v-else-if="uiStore.selectedTarget?.type === 'capital'" />
            </div>
          </div>
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { storeToRefs } from "pinia";
import { useUiStore } from "../store/ui.js";
import DashboardHeader from "../components/DashboardHeader.vue";
import Sidebar from "../components/Sidebar.vue";
import ConceptTreemap from "../components/ConceptTreemap.vue";
import SectorTable from "../components/SectorTable.vue";
import StockLeaderboard from "../components/StockLeaderboard.vue";
import SectorDetailPanel from "../components/SectorDetailPanel.vue";
import StockDetailPanel from "../components/StockDetailPanel.vue";
import InfoTimeline from "../components/InfoTimeline.vue";
import FilterBar from "../components/FilterBar.vue";
import InfoDetailPanel from "../components/InfoDetailPanel.vue";
import CapitalSankey from "../components/CapitalSankey.vue";
import CapitalDetailPanel from "../components/CapitalDetailPanel.vue";

const uiStore = useUiStore();
const { sidebarCollapsed } = storeToRefs(uiStore);
const activeFilters = ref({ sources: [], tiers: [] });

function onFilterChange(filters) {
  activeFilters.value = filters;
}
</script>

<style scoped>
.dashboard-shell {
  width: 100%;
  height: 100%;
}

.dashboard-layout {
  height: calc(100vh - 60px);
  overflow: hidden;
}

.dashboard-header-area {
  height: 56px;
  padding: 0;
  overflow: hidden;
}

.dashboard-body {
  height: calc(100vh - 60px - 56px);
}

.dashboard-aside {
  width: 220px !important;
  transition: width 0.3s ease;
  background: #1a1a2e;
  overflow: hidden;
  flex-shrink: 0;
}

.dashboard-aside.aside-collapsed {
  width: 64px !important;
}

.dashboard-main {
  flex: 1;
  padding: 16px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.content-area {
  display: flex;
  gap: 16px;
  height: 100%;
  overflow: hidden;
}

.left-panel {
  flex: 1;
  overflow: auto;
  min-width: 0;
}

.right-panel {
  width: 360px;
  flex-shrink: 0;
  background: #ffffff;
  border-radius: 8px;
  padding: 16px;
  overflow-y: auto;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.detail-default {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.panel-sector {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  overflow: auto;
}

.panel-sector-treemap {
  flex-shrink: 0;
  min-height: 420px;
  background: #ffffff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.panel-sector-table {
  flex: 1;
  background: #ffffff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.info-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow: auto;
}

.info-filter-bar {
  flex-shrink: 0;
}

.info-timeline {
  flex: 1;
  overflow-y: auto;
}

.panel-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
  font-size: 14px;
}
</style>
