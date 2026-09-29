/**
 * Market-hours-aware polling composable (INT-01, D-04)
 *
 * Usage:
 *   const { start, stop } = usePolling(60000, 300000, async () => marketStore.fetchConcepts())
 *   onBeforeUnmount(stop)  // auto-cleanup
 */
import { ref, onBeforeUnmount } from "vue";

const HIGH_FREQ = 60_000;
const LOW_FREQ = 300_000;

function isTradingHours() {
  const now = new Date();
  const day = now.getDay();
  if (day === 0 || day === 6) return false;
  const h = now.getHours();
  const m = now.getMinutes();
  const mins = h * 60 + m;
  return (mins >= 555 && mins < 690) || (mins >= 780 && mins < 900);
}

export function usePolling(highFreq = HIGH_FREQ, lowFreq = LOW_FREQ, fn) {
  const active = ref(false);
  let timer = null;

  function schedule() {
    if (!active.value) return;
    const interval = isTradingHours() ? highFreq : lowFreq;
    timer = setTimeout(async () => {
      try {
        await fn();
      } catch (e) {
        console.error("[usePolling] tick error", e);
      }
      schedule();
    }, interval);
  }

  function start() {
    if (active.value) return;
    active.value = true;
    fn().catch((e) => console.error("[usePolling] initial call error", e));
    schedule();
  }

  function stop() {
    active.value = false;
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  onBeforeUnmount(stop);

  return { active, start, stop };
}

/** Alias per D-04 */
export const useMarketAwarePolling = usePolling;
