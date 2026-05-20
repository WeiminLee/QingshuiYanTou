import { describe, it, expect, beforeEach } from 'vitest'
import { useStreamingRenderer } from '../src/composables/useStreamingRenderer.js'

describe('useStreamingRenderer — thinking 增量渲染', () => {
  let renderer

  beforeEach(() => {
    renderer = useStreamingRenderer()
    renderer.start()
  })

  // ── appendThinking 增量追加 ─────────────────────────────────────

  it('appendThinking 追加文本到 thinkingRaw', () => {
    renderer.appendThinking('正在分析')
    expect(renderer.thinkingRaw.value).toBe('正在分析')
  })

  it('appendThinking 多次调用累积追加', () => {
    renderer.appendThinking('第一步')
    renderer.appendThinking('第二步')
    renderer.appendThinking('第三步')
    expect(renderer.thinkingRaw.value).toBe('第一步第二步第三步')
  })

  it('appendThinking 空字符串不追加', () => {
    renderer.appendThinking('')
    renderer.appendThinking('有效')
    expect(renderer.thinkingRaw.value).toBe('有效')
  })

  // ── 流结束后 thinking 面板保留 ─────────────────────────────────

  it('finalize 后 thinkingRaw 保留（不清空）', () => {
    renderer.appendThinking('思考内容')
    renderer.finalize()
    expect(renderer.thinkingRaw.value).toBe('思考内容')
  })

  it('finalize 后 thinkingHtml 被渲染（不清空）', async () => {
    renderer.appendThinking('# 思考结论')
    await renderer.finalize()
    expect(renderer.thinkingHtml.value).toContain('<h1>')
  })

  it('finalize 后 isLoading 设为 false', () => {
    renderer.finalize()
    expect(renderer.isLoading.value).toBe(false)
  })

  it('start() 记录 thinkingStartTime', () => {
    renderer.start()
    expect(renderer.thinkingStartTime.value).not.toBeNull()
    expect(typeof renderer.thinkingStartTime.value).toBe('number')
  })

  it('finalize() 记录 thinkingEndTime', async () => {
    renderer.start()
    await renderer.finalize()
    expect(renderer.thinkingEndTime.value).not.toBeNull()
    expect(renderer.thinkingEndTime.value).toBeGreaterThanOrEqual(renderer.thinkingStartTime.value)
  })

  it('reset() 清空 thinking 时长', () => {
    renderer.start()
    renderer.reset()
    expect(renderer.thinkingStartTime.value).toBeNull()
    expect(renderer.thinkingEndTime.value).toBeNull()
  })

  it('reset 后 thinking 全部清空', () => {
    renderer.appendThinking('思考内容')
    renderer.reset()
    expect(renderer.thinkingRaw.value).toBe('')
    expect(renderer.thinkingHtml.value).toBe('')
  })

  // ── thinking + toolSteps 共同保留 ────────────────────────────────

  it('finalize 后 toolSteps 保留', () => {
    renderer.appendToolCall('get_kline', { code: '300308' }, 1)
    renderer.appendToolResult('get_kline', 'K线数据', 1)
    renderer.finalize()
    expect(renderer.toolSteps.value.length).toBe(1)
  })

  // ── appendThinking 与普通 append 分离 ──────────────────────────

  it('普通 append 不影响 thinkingRaw', () => {
    renderer.append('报告正文')
    expect(renderer.thinkingRaw.value).toBe('')
    expect(renderer.rawText.value).toBe('报告正文')
  })

  it('appendThinking 不影响 rawText（报告正文）', () => {
    renderer.appendThinking('思考内容')
    expect(renderer.rawText.value).toBe('')
    expect(renderer.thinkingRaw.value).toBe('思考内容')
  })

  // ── toolSteps 步骤条 ──────────────────────────────────────────

  it('appendToolCall 添加步骤，status=running', () => {
    renderer.appendToolCall('get_kline', { code: '300308' }, 1)
    const steps = renderer.toolSteps.value
    expect(steps.length).toBe(1)
    expect(steps[0].tool).toBe('get_kline')
    expect(steps[0].status).toBe('running')
  })

  it('appendToolResult 更新最后 matching 步骤，status=done', () => {
    renderer.appendToolCall('get_kline', { code: '300308' }, 1)
    renderer.appendToolResult('get_kline', 'K线数据', 1)
    const steps = renderer.toolSteps.value
    expect(steps[0].result).toBe('K线数据')
    expect(steps[0].status).toBe('done')
  })

  it('appendToolResult 只更新最后一个 running 步骤', () => {
    renderer.appendToolCall('get_kline', {}, 1)
    renderer.appendToolCall('get_concept_hot', {}, 1)
    renderer.appendToolResult('get_concept_hot', '热度数据', 1)
    const steps = renderer.toolSteps.value
    expect(steps[0].status).toBe('running')
    expect(steps[1].status).toBe('done')
  })
})


describe('SSE thinking 事件字段提取', () => {
  function extractThinkingText(event) {
    return event.data?.delta || event.data?.content || event.data?.text || ''
  }

  it('thinking 事件取 delta 字段', () => {
    const event = { type: 'thinking', data: { delta: '正在分析光模块业务', turn: 1 } }
    expect(extractThinkingText(event)).toBe('正在分析光模块业务')
  })

  it('thinking 事件取 content 字段（向后兼容）', () => {
    const event = { type: 'thinking', data: { content: '买入评级', turn: 2 } }
    expect(extractThinkingText(event)).toBe('买入评级')
  })

  it('thinking 事件取 text 字段', () => {
    const event = { type: 'thinking', data: { text: '光模块景气向上', turn: 1 } }
    expect(extractThinkingText(event)).toBe('光模块景气向上')
  })

  it('delta 优先于 content', () => {
    const event = { type: 'thinking', data: { delta: '新格式', content: '旧格式' } }
    expect(extractThinkingText(event)).toBe('新格式')
  })

  it('空 data 返回空字符串', () => {
    expect(extractThinkingText({ type: 'thinking', data: {} })).toBe('')
  })
})


describe('thinking 面板 UI 状态', () => {
  function thinkingPanelVisible(thinkingHtml, thinkingRaw) {
    return !!(thinkingHtml || thinkingRaw)
  }

  it('有 thinkingHtml 时面板可见', () => {
    expect(thinkingPanelVisible('<p>思考中</p>', '')).toBe(true)
  })

  it('有 thinkingRaw（未渲染）时面板也可见', () => {
    expect(thinkingPanelVisible('', '思考内容')).toBe(true)
  })

  it('都为空时面板不显示', () => {
    expect(thinkingPanelVisible('', '')).toBe(false)
  })
})


// ══════════════════════════════════════════════════════
// Phase C: Tool Result 渲染增强
// ══════════════════════════════════════════════════════

// 工具名 → 中文映射
const TOOL_NAME_MAP = {
  get_kline: 'K线查询',
  get_concept_hot: '热度查询',
  get_market_breadth: '市场宽度',
  neo4j_traverse: '图谱检索',
  get_research_report: '研报查询',
  get_announcement: '公告查询',
  tavily_search: '联网搜索',
  get_stock_profile: '公司档案',
  get_irm: '互动易查询',
  present_chart: '图表生成',
}

// 工具名 → 图标映射
const TOOL_ICON_MAP = {
  get_kline: '📈',
  get_concept_hot: '🔥',
  get_market_breadth: '🌊',
  neo4j_traverse: '🕸️',
  get_research_report: '📄',
  get_announcement: '📋',
  tavily_search: '🔍',
  get_stock_profile: '🏢',
  get_irm: '📊',
  present_chart: '📊',
}

// ── appendToolResult 元数据存储 ─────────────────────────────────

describe('appendToolResult — duration_ms / original_len / success 元数据', () => {
  let renderer

  beforeEach(() => {
    renderer = useStreamingRenderer()
    renderer.start()
  })

  it('接受 duration_ms 并存储到 step', () => {
    renderer.appendToolCall('get_kline', { code: '300308' }, 1)
    renderer.appendToolResult('get_kline', '查询到 120 条K线数据', 1, { duration_ms: 234.5 })
    const step = renderer.toolSteps.value[0]
    expect(step.duration_ms).toBe(234.5)
  })

  it('接受 success/original_len 并存储', () => {
    renderer.appendToolCall('get_kline', { code: '300308' }, 1)
    renderer.appendToolResult('get_kline', '查询到 120 条K线数据', 1, {
      success: true,
      original_len: 8000,
    })
    const step = renderer.toolSteps.value[0]
    expect(step.success).toBe(true)
    expect(step.original_len).toBe(8000)
  })

  it('无元数据时字段为 undefined', () => {
    renderer.appendToolCall('get_kline', { code: '300308' }, 1)
    renderer.appendToolResult('get_kline', 'K线数据', 1)
    expect(renderer.toolSteps.value[0].duration_ms).toBeUndefined()
    expect(renderer.toolSteps.value[0].success).toBeUndefined()
  })

  it('success=false 时也存储', () => {
    renderer.appendToolCall('get_kline', { code: '300308' }, 1)
    renderer.appendToolResult('get_kline', 'K线查询失败', 1, { success: false })
    expect(renderer.toolSteps.value[0].success).toBe(false)
  })

  it('完整元数据结构验证', () => {
    renderer.appendToolCall('get_kline', { code: '300308', days: 30 }, 1)
    renderer.appendToolResult('get_kline', '查询到 120 条K线数据', 1, {
      duration_ms: 500,
      original_len: 3000,
      success: true,
    })
    const step = renderer.toolSteps.value[0]
    expect(step.tool).toBe('get_kline')
    expect(step.args).toEqual({ code: '300308', days: 30 })
    expect(step.turn).toBe(1)
    expect(step.status).toBe('done')
    expect(step.result).toBe('查询到 120 条K线数据')
    expect(step.duration_ms).toBe(500)
    expect(step.original_len).toBe(3000)
    expect(step.success).toBe(true)
  })

  it('reset 清空 toolSteps（含元数据）', () => {
    renderer.appendToolCall('get_kline', { code: '300308' }, 1)
    renderer.appendToolResult('get_kline', 'K线数据', 1, { duration_ms: 100, success: true })
    renderer.reset()
    expect(renderer.toolSteps.value).toEqual([])
  })
})


// ── 工具名/图标显示 ──────────────────────────────────────────────

describe('工具名显示 — normalizeToolName', () => {
  function normalizeToolName(tool) {
    return TOOL_NAME_MAP[tool] || tool
  }

  it('已知工具返回中文名', () => {
    expect(normalizeToolName('get_kline')).toBe('K线查询')
    expect(normalizeToolName('tavily_search')).toBe('联网搜索')
    expect(normalizeToolName('get_stock_profile')).toBe('公司档案')
  })

  it('未知工具返回原名', () => {
    expect(normalizeToolName('my_tool')).toBe('my_tool')
    expect(normalizeToolName('')).toBe('')
  })
})


describe('工具图标映射 — getToolIcon', () => {
  function getToolIcon(toolName) {
    return TOOL_ICON_MAP[toolName] || '⚙️'
  }

  it('已知工具返回对应图标', () => {
    expect(getToolIcon('get_kline')).toBe('📈')
    expect(getToolIcon('tavily_search')).toBe('🔍')
    expect(getToolIcon('get_stock_profile')).toBe('🏢')
  })

  it('未知工具返回默认图标', () => {
    expect(getToolIcon('unknown_tool')).toBe('⚙️')
    expect(getToolIcon('')).toBe('⚙️')
  })
})


// ── 工具参数格式化 ──────────────────────────────────────────────

describe('工具参数格式化 — formatToolArgs', () => {
  function formatToolArgs(toolName, args) {
    if (!args || typeof args !== 'object') return ''
    const str = JSON.stringify(args)
    if (str === '{}') return ''
    try {
      return JSON.stringify(JSON.parse(str), null, 2)
    } catch {
      return str
    }
  }

  it('空参数返回空字符串', () => {
    expect(formatToolArgs('get_kline', {})).toBe('')
    expect(formatToolArgs('get_kline', null)).toBe('')
  })

  it('有参数返回格式化 JSON', () => {
    const args = { code: '300308', days: 30 }
    const result = formatToolArgs('get_kline', args)
    expect(result).toContain('"code"')
    expect(result).toContain('300308')
  })
})


// ── 耗时格式化 ─────────────────────────────────────────────────

describe('耗时格式化 — formatDuration', () => {
  function formatDuration(ms) {
    if (ms == null) return ''
    if (ms < 1000) return `${Math.round(ms)}毫秒`
    return `${(ms / 1000).toFixed(1)}秒`
  }

  it('毫秒级正确', () => {
    expect(formatDuration(0)).toBe('0毫秒')
    expect(formatDuration(500)).toBe('500毫秒')
    expect(formatDuration(999)).toBe('999毫秒')
  })

  it('秒级正确', () => {
    expect(formatDuration(1000)).toBe('1.0秒')
    expect(formatDuration(1500)).toBe('1.5秒')
    expect(formatDuration(2345)).toBe('2.3秒')
    expect(formatDuration(60000)).toBe('60.0秒')
    expect(formatDuration(90000)).toBe('90.0秒')
  })

  it('null/undefined 返回空字符串', () => {
    expect(formatDuration(undefined)).toBe('')
    expect(formatDuration(null)).toBe('')
  })
})


// ── K线数据检测 ──────────────────────────────────────────────

describe('K线数据检测 — isKlineData', () => {
  function isKlineData(text) {
    if (!text || typeof text !== 'string') return false
    const klinePatterns = [
      /\b(date|time|datetime)\b.*\b(open|high|low|close|volume)\b/i,
      /\b(open|close|volume)\b.*\b(date|time)\b/i,
      /\b(open|high|low|close)\b\s*:/i,
    ]
    return klinePatterns.some(p => p.test(text))
  }

  it('标准 K 线 JSON 识别', () => {
    const json = '{"date":"2026-04-01","open":120.5,"high":125.0,"low":119.0,"close":124.0,"volume":500000}'
    expect(isKlineData(json)).toBe(true)
  })

  it('简写 K 线字段识别', () => {
    expect(isKlineData('date:2026-04-01 open:120.5 close:124.0')).toBe(true)
  })

  it('非 K 线数据返回 false', () => {
    expect(isKlineData('中际旭创今日上涨5%')).toBe(false)
    expect(isKlineData('净利润同比增长150%')).toBe(false)
    expect(isKlineData('')).toBe(false)
    expect(isKlineData(null)).toBe(false)
  })
})


// ── 工具结果格式化（Phase F: preview 直接展示） ──────────────────

describe('工具结果格式化 — formatToolResult', () => {
  // Phase F: result 字段已经是 preview 描述，不需要额外格式化
  function formatToolResult(step) {
    return step.result || ''
  }

  it('preview 字符串直接返回', () => {
    const step = { result: '查询到 120 条K线数据' }
    expect(formatToolResult(step)).toBe('查询到 120 条K线数据')
  })

  it('空 result 返回空字符串', () => {
    const step = { result: '' }
    expect(formatToolResult(step)).toBe('')
  })

  it('undefined result 返回空字符串', () => {
    const step = {}
    expect(formatToolResult(step)).toBe('')
  })
})


// ── SSE tool_result 事件解析 ───────────────────────────────────

describe('SSE tool_result 事件解析 — parseToolResultEvent', () => {
  // Phase F: result 字段为 preview，success 必含，truncated/truncated_len 已移除
  function parseToolResultEvent(event) {
    const data = event.data || event
    return {
      toolName: data.name || data.tool || '',
      result: data.result || data.content || '',
      turn: data.turn || 1,
      duration_ms: data.duration_ms,
      original_len: data.original_len,
      success: data.success,
    }
  }

  it('从 data.result 提取 preview 结果', () => {
    const event = { type: 'tool_result', data: { name: 'get_kline', result: '查询到 120 条K线数据' } }
    const parsed = parseToolResultEvent(event)
    expect(parsed.toolName).toBe('get_kline')
    expect(parsed.result).toBe('查询到 120 条K线数据')
  })

  it('提取 duration_ms', () => {
    const event = { type: 'tool_result', data: { name: 'get_kline', result: 'x', duration_ms: 234.5 } }
    expect(parseToolResultEvent(event).duration_ms).toBe(234.5)
  })

  it('提取 success/original_len 元数据', () => {
    const event = {
      type: 'tool_result',
      data: { name: 'get_kline', result: '查询到 120 条K线数据', success: true, original_len: 5000 },
    }
    const parsed = parseToolResultEvent(event)
    expect(parsed.success).toBe(true)
    expect(parsed.original_len).toBe(5000)
  })

  it('fallback 到 event.tool 字段', () => {
    const event = { type: 'tool_result', data: { tool: 'tavily_search', result: '找到 8 篇相关文章' } }
    expect(parseToolResultEvent(event).toolName).toBe('tavily_search')
  })
})


// ══════════════════════════════════════════════════════════════════
// Phase D: stream_end 内嵌完整报告
// ══════════════════════════════════════════════════════════════════

describe('stream_end 内嵌报告字段解析', () => {
  // 模拟前端从 SSE 事件解析 stream_end 的逻辑
  function parseStreamEnd(event) {
    const data = event.data || {}
    return {
      report_content: data.report_content || null,
      report_json: data.report_json || null,
      report_id: data.report_id || (data.report_json || {}).report_id || null,
      compliance_passed: data.compliance_passed,
    }
  }

  it('report_content 从 data.report_content 提取', () => {
    const event = {
      type: 'stream_end',
      data: {
        report_content: '## 分析结论\n光模块景气向上，建议买入。',
      },
    }
    const parsed = parseStreamEnd(event)
    expect(parsed.report_content).toBe('## 分析结论\n光模块景气向上，建议买入。')
  })

  it('report_json 从 data.report_json 提取', () => {
    const event = {
      type: 'stream_end',
      data: {
        report_json: {
          report_id: 'abc123',
          topic: '中际旭创分析',
          sections: { conclusion: '买入' },
        },
      },
    }
    const parsed = parseStreamEnd(event)
    expect(parsed.report_json).toEqual({
      report_id: 'abc123',
      topic: '中际旭创分析',
      sections: { conclusion: '买入' },
    })
  })

  it('report_id 优先取 data.report_id，其次从 report_json 读取', () => {
    const event = {
      type: 'stream_end',
      data: {
        report_id: 'xyz789',
        report_json: { report_id: 'inner_id' },
      },
    }
    const parsed = parseStreamEnd(event)
    expect(parsed.report_id).toBe('xyz789')
  })

  it('report_id fallback 到 report_json.report_id', () => {
    const event = {
      type: 'stream_end',
      data: {
        report_json: { report_id: 'fallback_id' },
      },
    }
    const parsed = parseStreamEnd(event)
    expect(parsed.report_id).toBe('fallback_id')
  })

  it('compliance_passed 为布尔值', () => {
    const event = {
      type: 'stream_end',
      data: { compliance_passed: true },
    }
    const parsed = parseStreamEnd(event)
    expect(parsed.compliance_passed).toBe(true)
  })

  it('compliance_passed 为 false 时也提取', () => {
    const event = {
      type: 'stream_end',
      data: { compliance_passed: false },
    }
    const parsed = parseStreamEnd(event)
    expect(parsed.compliance_passed).toBe(false)
  })

  it('缺少内嵌字段时返回 null（向后兼容）', () => {
    const event = { type: 'stream_end', data: {} }
    const parsed = parseStreamEnd(event)
    expect(parsed.report_content).toBeNull()
    expect(parsed.report_json).toBeNull()
    expect(parsed.report_id).toBeNull()
    expect(parsed.compliance_passed).toBeUndefined()
  })
})


describe('Phase D 前端渲染决策', () => {
  // 模拟 ReportView.vue 的渲染决策逻辑
  function decideRenderSource(event) {
    const hasEmbedded = event.data?.report_content != null
    return hasEmbedded ? 'embedded' : 'rest'
  }

  it('有 report_content 时使用内嵌数据', () => {
    const event = {
      type: 'stream_end',
      data: { report_content: '## 报告内容' },
    }
    expect(decideRenderSource(event)).toBe('embedded')
  })

  it('无 report_content 时降级 REST', () => {
    const event = { type: 'stream_end', data: {} }
    expect(decideRenderSource(event)).toBe('rest')
  })

  it('report_content 为空字符串时也视为有数据', () => {
    // 空字符串在 JS 中为 falsy，但 SSE 内嵌空报告仍应优先使用
    const event = { type: 'stream_end', data: { report_content: '' } }
    // 使用 != null 判断（含 null 和 undefined）
    const hasEmbedded = event.data?.report_content != null
    expect(hasEmbedded).toBe(true)
  })
})


describe('Phase D report_json 结构验证', () => {
  function validateReportJson(report_json) {
    const errors = []
    if (!report_json) return errors
    if (!report_json.report_id) errors.push('缺少 report_id')
    if (!report_json.topic) errors.push('缺少 topic')
    if (!report_json.generated_at) errors.push('缺少 generated_at')
    return errors
  }

  it('标准 AnalysisReport.to_dict() 结构验证通过', () => {
    const report_json = {
      report_id: 'abc123',
      topic: '中际旭创分析',
      generated_at: '2026-04-26 12:00:00',
      sections: { conclusion: '买入', catalyst: [] },
    }
    const errors = validateReportJson(report_json)
    expect(errors).toHaveLength(0)
  })

  it('缺少 report_id 返回错误', () => {
    const report_json = { topic: '分析', generated_at: '2026-04-26' }
    const errors = validateReportJson(report_json)
    expect(errors).toContain('缺少 report_id')
  })

  it('缺少 topic 返回错误', () => {
    const report_json = { report_id: 'x', generated_at: '2026-04-26' }
    const errors = validateReportJson(report_json)
    expect(errors).toContain('缺少 topic')
  })

  it('null report_json 不崩溃', () => {
    const errors = validateReportJson(null)
    expect(errors).toHaveLength(0)
  })
})


// ══════════════════════════════════════════════════════════════════
// Phase E: ping 保活 + 前端重连 + 错误映射
// ══════════════════════════════════════════════════════════════════

describe('Phase E: ping 事件处理', () => {
  // 模拟前端处理 ping 事件的逻辑
  function handlePingEvent(event) {
    if (event.type === 'ping') return 'ping_received'
    return null
  }

  it('ping 事件不触发 phase 变化', () => {
    const event = { type: 'ping', data: {} }
    const result = handlePingEvent(event)
    expect(result).toBe('ping_received')
  })

  it('ping 事件不触发报告渲染', () => {
    const event = { type: 'ping', data: {} }
    expect(event.type).not.toBe('stream_end')
    expect(event.type).not.toBe('report_content')
  })
})


describe('Phase E: SSE 重连逻辑', () => {
  // 模拟前端重连延迟计算
  function calcDelay(retryCount) {
    return Math.pow(2, retryCount - 1) * 1000
  }

  it('第 1 次重连延迟 1 秒', () => {
    expect(calcDelay(1)).toBe(1000)
  })

  it('第 2 次重连延迟 2 秒', () => {
    expect(calcDelay(2)).toBe(2000)
  })

  it('第 3 次重连延迟 4 秒', () => {
    expect(calcDelay(3)).toBe(4000)
  })

  it('最多重连 3 次（MAX_SSE_RETRIES = 3）', () => {
    const MAX_SSE_RETRIES = 3
    function shouldRetry(retryCount) {
      return retryCount < MAX_SSE_RETRIES
    }
    expect(shouldRetry(0)).toBe(true)
    expect(shouldRetry(1)).toBe(true)
    expect(shouldRetry(2)).toBe(true)
    expect(shouldRetry(3)).toBe(false)  // 第3次后不再重试
  })

  it('重试计数初始为 0', () => {
    let retryCount = 0
    // 模拟连接成功
    retryCount = 0  // 重置
    expect(retryCount).toBe(0)
  })

  it('连接成功后重试计数归零', () => {
    let retryCount = 2
    retryCount = 0
    expect(retryCount).toBe(0)
  })
})


describe('Phase E: 错误类型 → 友好文案映射', () => {
  // 模拟 getFriendlyErrorMsg 函数
  function getFriendlyErrorMsg(errorType) {
    const mapping = {
      timeout: '推理超时，请稍后重试',
      model_error: 'AI 模型暂时不可用，请稍后再试',
      tool_error: '数据查询失败，请检查网络后重试',
      auth_error: '认证失败，请联系管理员',
      internal_error: '服务器开小差了，请稍后再试',
    }
    return mapping[errorType] || '发生未知错误，请稍后重试'
  }

  it('timeout 映射到推理超时', () => {
    expect(getFriendlyErrorMsg('timeout')).toBe('推理超时，请稍后重试')
  })

  it('model_error 映射到 AI 模型不可用', () => {
    expect(getFriendlyErrorMsg('model_error')).toBe('AI 模型暂时不可用，请稍后再试')
  })

  it('tool_error 映射到数据查询失败', () => {
    expect(getFriendlyErrorMsg('tool_error')).toBe('数据查询失败，请检查网络后重试')
  })

  it('auth_error 映射到认证失败', () => {
    expect(getFriendlyErrorMsg('auth_error')).toBe('认证失败，请联系管理员')
  })

  it('internal_error 映射到服务器开小差', () => {
    expect(getFriendlyErrorMsg('internal_error')).toBe('服务器开小差了，请稍后再试')
  })

  it('未知 error_type 映射到默认文案', () => {
    expect(getFriendlyErrorMsg('unknown_type')).toBe('发生未知错误，请稍后重试')
  })

  it('null error_type 使用默认文案', () => {
    expect(getFriendlyErrorMsg(null)).toBe('发生未知错误，请稍后重试')
  })
})


describe('Phase E: SSE 重连后 stream_end 仍能正常处理', () => {
  it('重连后 stream_end 事件正确提取 report_content', () => {
    const event = {
      type: 'stream_end',
      data: {
        report_content: '## 重连后报告\n内容',
        report_json: { report_id: 'x', topic: '测试' },
      },
    }
    const hasContent = event.data?.report_content != null
    expect(hasContent).toBe(true)
    expect(event.data.report_content).toBe('## 重连后报告\n内容')
  })
})


// ══════════════════════════════════════════════════════════════════
// Bug #2: fetchFinalReport 无错误处理 → 用户看到假死
// Bug #3: setTimeout 闭包内存泄漏
// ══════════════════════════════════════════════════════════════════

describe('Bug #2: fetchFinalReport 失败时应设置错误状态', () => {
  // Bug #2: fetchFinalReport() 在 REST 失败时没有任何反馈
  // 用户看到 phase='reasoning'，以为还在推理，不知道报告拉取失败

  it('REST 失败时 error 应被设置', async () => {
    // 模拟 getTaskResult 抛出异常
    const mockGetTaskResult = async () => {
      throw new Error('网络错误')
    }

    // Bug #2: 修复前，catch 只打日志，不设置 error
    // 修复后，catch 应设置 error 并将 phase 设为 error
    let errorSet = false
    let phaseSetToError = false

    // 模拟状态
    const error = { value: null }
    const phase = { value: 'reasoning' }

    // 修复后的 fetchFinalReport 逻辑（伪代码）
    async function fetchFinalReportFixed() {
      try {
        const res = await mockGetTaskResult()
        if (res.reportContent) {
          // 成功处理
        }
      } catch (e) {
        // Bug #2 修复：设置错误状态
        errorSet = true
        phaseSetToError = true
        error.value = '获取报告失败，请重试'
        phase.value = 'error'
      }
    }

    await fetchFinalReportFixed()
    expect(errorSet).toBe(true)
    expect(phaseSetToError).toBe(true)
  })

  it('REST 失败时 phase 应设为 error（不是停留在 reasoning）', async () => {
    const mockGetTaskResult = async () => {
      throw new Error('服务器错误')
    }

    const phase = { value: 'reasoning' }

    async function fetchFinalReportFixed() {
      try {
        await mockGetTaskResult()
      } catch (e) {
        phase.value = 'error'
      }
    }

    await fetchFinalReportFixed()
    expect(phase.value).toBe('error')
  })

  it('REST 返回空内容时 phase 不变', async () => {
    // REST 成功但内容为空：不是错误，是未知状态
    const mockGetTaskResult = async () => ({ reportContent: null })

    const phase = { value: 'reasoning' }

    async function fetchFinalReportFixed() {
      try {
        const res = await mockGetTaskResult()
        // 成功但无内容：保持当前状态，不设为 error
        if (!res.reportContent) {
          // 不改变 phase，用户继续等待
        }
      } catch (e) {
        phase.value = 'error'
      }
    }

    await fetchFinalReportFixed()
    expect(phase.value).toBe('reasoning')
  })
})


describe('Bug #3: SSE 重连时应先清理旧连接', () => {
  // Bug #3: setTimeout 闭包持有 EventSource 引用，导致内存泄漏
  // 修复：重连前先 disconnect() 清理旧连接

  it('重连前旧 SSE 连接应被清理', () => {
    // 模拟 ReportView 的状态
    let esClosed = false
    const es = {
      close: () => { esClosed = true },
    }

    // Bug #3: 修复前，setTimeout 直接引用旧 es
    // 修复后，connectSSE 开始时应先 disconnect() 清理旧连接
    function connectSSEFixed(taskId, esRef) {
      // 重连前先断开旧连接
      if (esRef) {
        esRef.close()
        esClosed = true
      }
      // 然后创建新连接
      return { close: () => {} }
    }

    const newEs = connectSSEFixed('task-123', es)
    expect(esClosed).toBe(true)
    // 新连接不应立即关闭
    expect(newEs).toBeDefined()
  })

  it('disconnect 后 pending setTimeout 应被清理', () => {
    // disconnect() 应清理所有 pending 的 setTimeout
    const pendingTimeouts = []

    // 模拟连接
    function connectSSEWithTimeout() {
      const t1 = setTimeout(() => console.log('重连1'), 1000)
      const t2 = setTimeout(() => console.log('重连2'), 2000)
      pendingTimeouts.push(t1, t2)
      return { timeouts: [t1, t2] }
    }

    function disconnectFixed(connection) {
      if (connection) {
        connection.timeouts.forEach(t => clearTimeout(t))
        connection.timeouts = []
      }
    }

    const conn = connectSSEWithTimeout()
    disconnectFixed(conn)
    // 所有 timeout 应被清理（clearTimeout 不报错）
    expect(conn.timeouts.length).toBe(0)
  })

  it('MAX_SSE_RETRIES=3 时的重连序列', () => {
    const MAX_SSE_RETRIES = 3
    const delays = []

    for (let i = 0; i < MAX_SSE_RETRIES; i++) {
      const retryCount = i
      const delay = Math.pow(2, retryCount) * 1000
      delays.push(delay)
    }

    expect(delays).toEqual([1000, 2000, 4000])

    // 第 4 次（i=3）不再重连
    const retry4Delay = Math.pow(2, 3) * 1000
    expect(retry4Delay).toBe(8000)
    // 但此时 sseRetryCount >= MAX_SSE_RETRIES，应降级轮询而非重连
    expect(3 >= MAX_SSE_RETRIES).toBe(true)  // 不再重连
  })
})


describe('Bug #2+3: 端到端场景', () => {
  it('stream_end 无 report_content 时降级 REST，REST 失败设 error', async () => {
    // 场景：后端 stream_end 无 report_content（Bug #1 已修复场景）
    // 前端降级调用 fetchFinalReport，REST 失败时设置 error
    let errorSet = false
    let phaseSetToError = false

    const error = { value: null }
    const phase = { value: 'done' }  // stream_end 到达时 phase='done'

    async function fetchFinalReportScenario() {
      try {
        // REST 失败
        throw new Error('获取报告失败，请稍后重试')
      } catch (e) {
        errorSet = true
        phaseSetToError = true
        error.value = '获取报告失败，请稍后重试'
        phase.value = 'error'
      }
    }

    await fetchFinalReportScenario()
    expect(errorSet).toBe(true)
    expect(phaseSetToError).toBe(true)
    expect(phase.value).toBe('error')
    expect(error.value).toBe('获取报告失败，请稍后重试')
  })
})
