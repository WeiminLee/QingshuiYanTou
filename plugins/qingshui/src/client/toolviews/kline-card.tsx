/**
 * KlineCard: candlestick + volume toolview for get_kline (native + MCP twin).
 * Structured data prefers settled block.meta (native presentationMeta), then
 * JSON.parse of the result text (MCP twin returns a JSON string), else a raw
 * text fallback.
 */
import { useEffect, useRef } from 'react'
import { IconDataOutline16 } from '@deepseek-ai/dsh-client-ui-primitives'
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { BarSeriesOption, CandlestickSeriesOption } from 'echarts/charts'
import type {
  DataZoomComponentOption,
  GridComponentOption,
  TooltipComponentOption,
} from 'echarts/components'
import { ErrorBody, RawFallback, TvCard, type QsToolviewProps } from './common.tsx'
import {
  asKlinePayload,
  blockArgs,
  blockState,
  extractResultJson,
  formatKlineTooltip,
  formatTradeDate,
  formatVolume,
  freqLabel,
  isSettled,
  type KlinePayload,
  type KlineTooltipParam,
} from './model.ts'

echarts.use([CandlestickChart, BarChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

type KlineOption = echarts.ComposeOption<
  CandlestickSeriesOption | BarSeriesOption | GridComponentOption | TooltipComponentOption | DataZoomComponentOption
>

/** 红涨绿跌 (Chinese market convention), aligned with frontend StockDetailPanel. */
const UP_COLOR = '#ef4444'
const DOWN_COLOR = '#22c55e'

function themeColors(el: HTMLElement): {
  label: string
  border: string
  tooltipBg: string
  tooltipText: string
} {
  const cs = getComputedStyle(el)
  const read = (name: string, fallback: string): string => cs.getPropertyValue(name).trim() || fallback
  return {
    label: read('--dsw-alias-label-tertiary', '#909399'),
    border: read('--dsw-alias-border-l2', '#e5e5e5'),
    tooltipBg: read('--dsw-alias-tooltip-bg', '#ffffff'),
    tooltipText: read('--dsw-alias-label-primary', '#303133'),
  }
}

function buildOption(payload: KlinePayload, el: HTMLElement): KlineOption {
  const colors = themeColors(el)
  const items = payload.items
  const dates = items.map(item => formatTradeDate(item.trade_date))
  const kdata = items.map(item => [item.open, item.close, item.low, item.high])
  const vdata = items.map(item => ({
    value: item.volume,
    itemStyle: { color: item.close >= item.open ? UP_COLOR : DOWN_COLOR },
  }))
  const zoomStart = items.length > 120 ? Math.round((1 - 120 / items.length) * 100) : 0
  return {
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: colors.tooltipBg,
      borderColor: colors.border,
      textStyle: { color: colors.tooltipText, fontSize: 11 },
      formatter: (params: unknown) => {
        const list = (Array.isArray(params) ? params : [params]) as KlineTooltipParam[]
        return formatKlineTooltip(items, list)
      },
    },
    grid: [
      { left: 8, right: 12, top: 10, height: '54%', containLabel: true },
      { left: 8, right: 12, top: '70%', height: '14%', containLabel: true },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        boundaryGap: true,
        axisLine: { lineStyle: { color: colors.border } },
        axisTick: { show: false },
        axisLabel: {
          color: colors.label,
          fontSize: 9,
          formatter: (value: string) => value.slice(5),
        },
        splitLine: { show: false },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        boundaryGap: true,
        axisLine: { lineStyle: { color: colors.border } },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        axisLabel: { color: colors.label, fontSize: 10 },
        splitLine: { lineStyle: { color: colors.border } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: {
          color: colors.label,
          fontSize: 9,
          formatter: (value: number) => formatVolume(value),
        },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: zoomStart, end: 100 },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        top: '90%',
        height: 16,
        start: zoomStart,
        end: 100,
        borderColor: colors.border,
        textStyle: { color: colors.label, fontSize: 9 },
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: kdata,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: UP_COLOR,
          color0: DOWN_COLOR,
          borderColor: UP_COLOR,
          borderColor0: DOWN_COLOR,
        },
      },
      {
        name: '成交量',
        type: 'bar',
        data: vdata,
        xAxisIndex: 1,
        yAxisIndex: 1,
      },
    ],
  }
}

function KlineChart({ payload }: { payload: KlinePayload }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    const el = ref.current
    if (el === null) return
    const chart = echarts.init(el)
    chartRef.current = chart
    chart.setOption(buildOption(payload, el))
    const observer = new ResizeObserver(() => { chart.resize() })
    observer.observe(el)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [payload])

  return <div ref={ref} className="qs-tv-kline-chart" />
}

export function KlineCard({ block, t }: QsToolviewProps) {
  const state = blockState(block)
  const args = blockArgs(block)
  const argCode = typeof args.ts_code === 'string' ? args.ts_code : ''
  const title = (
    <span className="qs-tv-kline-head">
      <span className="qs-tv-kline-title">{t('tv.kline.title')}</span>
      {argCode === '' ? null : <span>{argCode}</span>}
    </span>
  )

  if (state === 'running') {
    return (
      <TvCard icon={<IconDataOutline16 size={14} />} title={title} state={state}>
        <div className="qs-tv-loading">{t('tv.kline.loading', { ts_code: argCode })}</div>
      </TvCard>
    )
  }
  if (state === 'error') {
    return (
      <TvCard icon={<IconDataOutline16 size={14} />} title={title} state={state}>
        <ErrorBody block={block} />
      </TvCard>
    )
  }

  const payload = isSettled(block) ? asKlinePayload(extractResultJson(block)) : undefined
  if (payload === undefined) {
    return (
      <TvCard icon={<IconDataOutline16 size={14} />} title={title} state={state}>
        <RawFallback block={block} />
      </TvCard>
    )
  }
  const range = `${formatTradeDate(payload.start_date)} ~ ${formatTradeDate(payload.end_date)}`
  const summary = t('tv.kline.summary', { freq: freqLabel(payload.freq), range, count: payload.count })
  if (payload.count === 0 || payload.items.length === 0) {
    return (
      <TvCard icon={<IconDataOutline16 size={14} />} title={title} summary={summary} state={state}>
        <div className="qs-tv-empty">{payload.text ?? t('tv.kline.empty')}</div>
      </TvCard>
    )
  }
  return (
    <TvCard icon={<IconDataOutline16 size={14} />} title={title} summary={summary} state={state}>
      <KlineChart payload={payload} />
    </TvCard>
  )
}
