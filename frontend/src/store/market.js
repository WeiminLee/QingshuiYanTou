import { defineStore } from "pinia";
import { ref } from "vue";
import { getConceptList, getConceptDetail } from "../api/concept.js";
import { getStockScores } from "../api/stocks.js";

export const useMarketStore = defineStore("market", () => {
  const concepts = ref([]);
  const stocks = ref([]);
  const breadcrumb = ref([{ name: "全部板块" }]);
  const loading = ref(false);
  const error = ref(null);

  async function fetchConcepts() {
    loading.value = true;
    error.value = null;
    try {
      const data = await getConceptList();
      concepts.value = Array.isArray(data) ? data : data.items || data.data || [];
    } catch (e) {
      error.value = e.message || "加载板块数据失败";
    } finally {
      loading.value = false;
    }
  }

  async function fetchStocks() {
    try {
      const data = await getStockScores(100, 0);
      stocks.value = Array.isArray(data) ? data : data.items || data.data || [];
    } catch (e) {
      console.error("[marketStore] fetchStocks failed", e);
    }
  }

  async function fetchConceptDetail(conceptTsCode) {
    try {
      return await getConceptDetail(conceptTsCode);
    } catch (e) {
      console.error("[marketStore] fetchConceptDetail failed", e);
      return null;
    }
  }

  function setBreadcrumb(path) {
    breadcrumb.value = [{ name: "全部板块" }, ...path];
  }

  function resetBreadcrumb() {
    breadcrumb.value = [{ name: "全部板块" }];
  }

  return {
    concepts,
    stocks,
    breadcrumb,
    loading,
    error,
    fetchConcepts,
    fetchStocks,
    fetchConceptDetail,
    setBreadcrumb,
    resetBreadcrumb,
  };
});
