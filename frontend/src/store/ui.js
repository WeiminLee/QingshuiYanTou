import { defineStore } from "pinia";
import { ref } from "vue";

export const useUiStore = defineStore("ui", () => {
  const sidebarCollapsed = ref(false);
  const activePanel = ref("sector");
  const selectedTarget = ref(null);
  const selectedInfo = ref(null);

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value;
  }

  function setActivePanel(panel) {
    activePanel.value = panel;
    selectedTarget.value = null;
  }

  function setSelectedSector(data) {
    selectedTarget.value = { type: "sector", data };
  }

  function setSelectedStock(data) {
    selectedTarget.value = { type: "stock", data };
  }

  const selectedCapital = ref(null);

  function setSelectedCapital(data) {
    selectedTarget.value = { type: "capital", data };
    selectedCapital.value = data;
  }

  function clearSelection() {
    selectedTarget.value = null;
  }

  function setSelectedInfo(data) {
    selectedTarget.value = { type: "info", data };
    selectedInfo.value = data;
  }

  function clearInfoSelection() {
    selectedTarget.value = null;
    selectedInfo.value = null;
  }

  return {
    sidebarCollapsed,
    activePanel,
    selectedTarget,
    selectedInfo,
    toggleSidebar,
    setActivePanel,
    setSelectedSector,
    setSelectedStock,
    clearSelection,
    setSelectedInfo,
    clearInfoSelection,
    selectedCapital,
    setSelectedCapital,
  };
});
