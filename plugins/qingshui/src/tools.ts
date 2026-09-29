import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { JsonValue } from '@deepseek-ai/dsh-tools'
import type { KnowledgeClient } from './knowledge-client.ts'
import { renderJson } from './tool-output.ts'

const MAX_EVIDENCE_TEXT = 8000

export function formatEvidenceText(doc: Record<string, unknown> | null | undefined): string {
  if (!doc) return '未找到该证据记录（可能 evidence_id 无效或数据已过期）。'
  let text = String(doc.text_excerpt ?? '(无文本内容)') || '(无文本内容)'
  if (text.length > MAX_EVIDENCE_TEXT) {
    text =
      text.slice(0, MAX_EVIDENCE_TEXT) +
      `\n...[原文过长已截断：共 ${text.length} 字符，仅显示前 ${MAX_EVIDENCE_TEXT} 字符]`
  }
  const lines = [
    `证据 ID: ${doc.evidence_id ?? 'N/A'}`,
    `来源类型: ${doc.source_type ?? 'N/A'}`,
    `来源名称: ${doc.source_name ?? 'N/A'}`,
    `发布时间: ${doc.publish_date ?? 'N/A'}`,
    `置信度: ${doc.confidence ?? 'N/A'}`,
    '--- 原始文本 ---',
    text,
  ]
  const subject = (doc.subject_hint as Record<string, unknown> | undefined) ?? {}
  if (subject.ts_code) lines.splice(2, 0, `关联股票: ${subject.ts_code}`)
  return lines.join('\n')
}

export interface ToolInstallOptions {
  client: () => KnowledgeClient | undefined
}

function needClient(options: ToolInstallOptions): KnowledgeClient | { error: string } {
  const client = options.client()
  if (!client) return { error: 'Knowledge client not configured (set knowledgeBaseUrl + KNOWLEDGE_API_KEY/API_KEY)' }
  return client
}

export function installQingshuiTools(ctx: Context, options: ToolInstallOptions): void {
  ctx.inject(['tools'], (tctx) => {
    tctx.tools.register(defineTool({
      name: 'compare_metric',
      description:
        '横向预期差：同一标尺(dimension)下跨主体数值排名。返回主体/数值/单位/期间/evidence_id。' +
        '例：compare_metric(dimension="营业收入", scope="硅片")。period 不同不可直接比。',
      parameters: {
        dimension: { type: 'string', required: true, description: '标尺名，如 营业收入/毛利率' },
        scope: { type: 'string', description: '产品/主题范围，如 硅片' },
        as_of: { type: 'string', description: '可选 ISO 时点，只看该日之前' },
        top_k: { type: 'json', description: '返回主体数上限，默认 30' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        return await c.compareMetric({
          dimension: String(args.dimension ?? ''),
          scope: args.scope ? String(args.scope) : null,
          as_of: args.as_of ? String(args.as_of) : null,
          top_k: typeof args.top_k === 'number' ? args.top_k : 30,
        }) as unknown as JsonValue
      },
    }))

    tctx.tools.register(defineTool({
      name: 'metric_trend',
      description:
        '纵向预期差：同一主体在时间轴上的数值/表述变化（状态演进）。' +
        '返回 timeline（value/unit/period/evidence_id）。例：metric_trend(subject="600962.SH", dimension="营业收入")。',
      parameters: {
        subject: { type: 'string', required: true, description: '主体 ts_code 或名称' },
        dimension: { type: 'string', description: '标尺名；不填则取该主体全部指标' },
        limit: { type: 'json', description: '条数上限，默认 50' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        return await c.metricTrend({
          subject: String(args.subject ?? ''),
          dimension: args.dimension ? String(args.dimension) : null,
          limit: typeof args.limit === 'number' ? args.limit : 50,
        }) as unknown as JsonValue
      },
    }))

    tctx.tools.register(defineTool({
      name: 'rollup_metric',
      description:
        '层次预期差：粗粒度标尺下的细分子指标及 evidence 命中量。' +
        '例：rollup_metric(parent="营收")。',
      parameters: {
        parent: { type: 'string', required: true, description: '粗粒度标尺，如 营收' },
        scope: { type: 'string', description: '可选产品/主题范围' },
        top_k: { type: 'json', description: '子指标数上限，默认 30' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        return await c.rollupMetric({
          parent: String(args.parent ?? ''),
          scope: args.scope ? String(args.scope) : null,
          top_k: typeof args.top_k === 'number' ? args.top_k : 30,
        }) as unknown as JsonValue
      },
    }))

    tctx.tools.register(defineTool({
      name: 'fetch_evidence',
      description: '按 evidence_id（EV:…）拉取 Mongo 证据原文与来源元数据。判断必须引用 EV。',
      parameters: {
        evidence_id: { type: 'string', required: true, description: '证据 ID，格式 EV:…' },
      },
      output: {
        schema: { type: 'string' },
        render: (_a, v) => [{ type: 'text', text: String(v) }],
      },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c.error
        try {
          const doc = await c.fetchEvidence(String(args.evidence_id ?? ''))
          return formatEvidenceText(doc)
        } catch (e) {
          return `证据查询失败: ${e instanceof Error ? e.message : String(e)}`
        }
      },
    }))

    tctx.tools.register(defineTool({
      name: 'semantic_search',
      description:
        '语义冷启动（可选）：模糊搜实体/证据片段。判断递进/变化禁止只靠此工具。' +
        '拿到 evidence_id 后用 fetch_evidence。',
      parameters: {
        query: { type: 'string', required: true, description: '自然语言检索词' },
        scope: { type: 'string', description: 'entities(默认)|chunks|both' },
        ts_code: { type: 'string', description: '可选股票代码' },
        top_k: { type: 'json', description: '每类条数，默认 5' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        return await c.semanticSearch({
          query: String(args.query ?? ''),
          scope: (args.scope as 'entities' | 'chunks' | 'both' | undefined) ?? 'entities',
          ts_code: args.ts_code ? String(args.ts_code) : null,
          top_k: typeof args.top_k === 'number' ? args.top_k : 5,
        }) as unknown as JsonValue
      },
    }))

    tctx.tools.register(defineTool({
      name: 'related_nodes',
      description: '传导一跳：某关键字关联的主体/指标/阶段节点（共现）。用于板块玩家面。',
      parameters: {
        keyword: { type: 'string', required: true, description: '锚点关键字，如 硅片' },
        layer: { type: 'string', description: '可选层：subject|dimension|stage 等' },
        top_k: { type: 'json', description: '默认 20' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        return await c.relatedNodes({
          keyword: String(args.keyword ?? ''),
          layer: args.layer ? String(args.layer) : null,
          top_k: typeof args.top_k === 'number' ? args.top_k : 20,
        }) as unknown as JsonValue
      },
    }))

    tctx.tools.register(defineTool({
      name: 'propagate_along',
      description: '传导多跳：从 start 按共现扩展可达节点（指标/阶段/公司）。用于传导面。',
      parameters: {
        start: { type: 'string', required: true, description: '起点，如 硅片' },
        max_hops: { type: 'json', description: '跳数 1-3，默认 1' },
        min_cooccur: { type: 'json', description: '最小共现，默认 5' },
        top_k: { type: 'json', description: '默认 20' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        return await c.propagateAlong({
          start: String(args.start ?? ''),
          max_hops: typeof args.max_hops === 'number' ? args.max_hops : 1,
          min_cooccur: typeof args.min_cooccur === 'number' ? args.min_cooccur : 5,
          top_k: typeof args.top_k === 'number' ? args.top_k : 20,
        }) as unknown as JsonValue
      },
    }))
  })
}
