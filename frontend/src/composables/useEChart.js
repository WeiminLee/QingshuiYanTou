/**
 * ECharts instance lifecycle manager (INT-03, D-11)
 *
 * Usage:
 *   const domRef = ref(null)
 *   const { initChart, setOption, disposeChart } = useEChart(domRef)
 *   onBeforeUnmount(disposeChart)
 */
import { ref, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

export function useEChart(domRef) {
  const instance = ref(null)

  function initChart(opts) {
    if (!domRef.value) return null
    if (instance.value) instance.value.dispose()
    instance.value = echarts.init(domRef.value)
    if (opts) instance.value.setOption(opts)
    return instance.value
  }

  function setOption(opts, notMerge = false) {
    instance.value?.setOption(opts, notMerge)
  }

  function disposeChart() {
    if (instance.value) {
      instance.value.dispose()
      instance.value = null
    }
  }

  onBeforeUnmount(disposeChart)

  return { instance, initChart, setOption, disposeChart }
}
