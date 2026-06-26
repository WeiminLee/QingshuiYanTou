import { ref, computed } from "vue";
import { listTasks } from "@/api/agent.js";

export interface HistoryItem {
  task_id: string;
  question?: string;
  updated_at?: string;
  finished_at?: string;
  created_at?: string;
  start_time?: string;
}

function toTimestamp(item: HistoryItem): number {
  const raw = item?.updated_at || item?.finished_at || item?.created_at || item?.start_time || "";
  const ts = raw ? new Date(raw).getTime() : 0;
  return Number.isNaN(ts) ? 0 : ts;
}

export function useHistoryData() {
  const items = ref<HistoryItem[]>([]);
  const loading = ref(false);

  const sorted = computed(() => [...items.value].sort((a, b) => toTimestamp(b) - toTimestamp(a)));

  const recent = computed(() => sorted.value.slice(0, 4));

  const pastWeek = computed(() => {
    const now = Date.now();
    const weekAgo = now - 7 * 24 * 60 * 60 * 1000;
    return sorted.value.filter((item) => toTimestamp(item) >= weekAgo).slice(4, 10);
  });

  async function load(limit = 50): Promise<void> {
    loading.value = true;
    try {
      const res = await listTasks(limit);
      items.value = res.items || res || [];
    } catch {
      items.value = [];
    } finally {
      loading.value = false;
    }
  }

  function truncate(text: string, maxLen: number): string {
    if (!text) return "";
    return text.length > maxLen ? text.slice(0, maxLen) + "..." : text;
  }

  function reset(): void {
    items.value = [];
    loading.value = false;
  }

  return { items, loading, sorted, recent, pastWeek, load, truncate, reset };
}
