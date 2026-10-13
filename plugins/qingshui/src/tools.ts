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

/** Model-facing text for the fetch_evidence canonical value (raw doc or {error}). */
function renderEvidenceValue(value: unknown): string {
  if (typeof value === 'object' && value !== null && 'error' in value) {
    return String((value as { error: unknown }).error)
  }
  return formatEvidenceText(value as Record<string, unknown> | null | undefined)
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
        schema: { type: 'json' },
        render: (_a, v) => [{ type: 'text', text: renderEvidenceValue(v) }],
        presentationMeta: (_a, v) => v,
      },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return { error: c.error } as unknown as JsonValue
        try {
          return await c.fetchEvidence(String(args.evidence_id ?? '')) as unknown as JsonValue
        } catch (e) {
          return { error: `证据查询失败: ${e instanceof Error ? e.message : String(e)}` } as unknown as JsonValue
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
      output: {
        schema: { type: 'json' },
        render: (_a, v) => renderJson(v),
        presentationMeta: (_a, v) => v,
      },
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

    tctx.tools.register(defineTool({
      name: 'get_kline',
      description:
        '行情 K 线：个股 OHLCV 时间序列（本地行情库）。返回 count 与 items' +
        '（trade_date/open/high/low/close/pre_close/volume/amount/pct_chg/turnover_rate）及摘要 text。' +
        '例：get_kline(ts_code="300308.SZ", start_date="20250901", end_date="20251013")。',
      parameters: {
        ts_code: { type: 'string', required: true, description: '股票代码，如 300308.SZ' },
        start_date: { type: 'string', description: '起始日 YYYYMMDD；缺省为 end_date 前 180 天' },
        end_date: { type: 'string', description: '截止日 YYYYMMDD；缺省为今天' },
        freq: { type: 'string', description: '周期 D|W|M，默认 D' },
      },
      output: {
        schema: { type: 'json' },
        render: (_a, v) => renderJson(v),
        presentationMeta: (_a, v) => v,
      },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        return await c.getKline({
          ts_code: String(args.ts_code ?? ''),
          start_date: args.start_date ? String(args.start_date) : null,
          end_date: args.end_date ? String(args.end_date) : null,
          freq: args.freq ? String(args.freq) : null,
        }) as unknown as JsonValue
      },
    }))

    tctx.tools.register(defineTool({
      name: 'get_stock_profile',
      description:
        '公司概况：主营业务与经营范围（本地股票库）。返回 main_business/business_scope 与摘要 text。' +
        '例：get_stock_profile(ts_code="300308.SZ")。',
      parameters: {
        ts_code: { type: 'string', required: true, description: '股票代码，如 300308.SZ' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        return await c.getStockProfile(String(args.ts_code ?? '')) as unknown as JsonValue
      },
    }))

    // ── 判断沉淀（findings 台账，写面；读面走 MCP：history_findings/search_findings/watermark） ──

    tctx.tools.register(defineTool({
      name: 'write_observation',
      description:
        '沉淀一条观察到判断台账（observation 层）：主体在某维度的原始表述/指标点，句级锚定 EV。' +
        '写入即推进水位线；返回 is_new_level 表示是否首次站上新台阶（新台阶=预期差信号）。' +
        '硬闸门：evidence 必须真实存在且 span 落在原文内，否则拒写。',
      parameters: {
        subject_ts_code: { type: 'string', required: true, description: '主体 ts_code，如 003026.SZ' },
        dimension: { type: 'string', required: true, description: '维度：产线进展/客户认证/毛利率/订单/产能…' },
        evidence_id: { type: 'string', required: true, description: '证据 ID（EV:…）' },
        span_start: { type: 'json', required: true, description: '句级锚点起始偏移（含）' },
        span_end: { type: 'json', required: true, description: '句级锚点结束偏移（不含）' },
        stage_raw: { type: 'string', description: '阶梯原始措辞（verbatim），如 增产上量' },
        stage_level: { type: 'json', description: '阶梯归一化 level（1 起）' },
        dimension_scope: { type: 'string', description: '细化范围，如 8英寸抛光硅片；可空' },
        event_date: { type: 'string', description: '事件日期 YYYY-MM-DD；可空' },
        published_at: { type: 'string', description: '披露时间 ISO；可空' },
        metric_value: { type: 'json', description: '数值型观察：{num, unit, period, metric}' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        const toJson = (v: unknown): unknown => {
          if (typeof v !== 'string') return v ?? null
          const sv = v.trim()
          if (!sv) return null
          try { return JSON.parse(sv) } catch { return v }
        }
        return await c.writeObservation({
          subject_ts_code: String(args.subject_ts_code ?? ''),
          dimension: String(args.dimension ?? ''),
          evidence_id: String(args.evidence_id ?? ''),
          span_start: Number(args.span_start ?? 0),
          span_end: Number(args.span_end ?? 0),
          stage_raw: args.stage_raw ? String(args.stage_raw) : null,
          stage_level: args.stage_level != null ? Number(args.stage_level) : null,
          dimension_scope: args.dimension_scope ? String(args.dimension_scope) : null,
          event_date: args.event_date ? String(args.event_date) : null,
          published_at: args.published_at ? String(args.published_at) : null,
          metric_value: toJson(args.metric_value) as Record<string, unknown> | null,
        }) as unknown as JsonValue
      },
    }))

    tctx.tools.register(defineTool({
      name: 'write_finding',
      description:
        '沉淀一条判断到判断台账（finding 层）：递进/恶化/新增事件/关联传导/矛盾五类之一，' +
        'supports 必须句级锚定至少一条真实证据（同前 fetch_evidence 的 EV）。' +
        '判断可持续累积（跨任务复用）：下次先查 history_findings，水位线内不重复断言。' +
        '幂等：同 (主体,维度,to_level,支撑集) 重写自动合并。',
      parameters: {
        subject_ts_code: { type: 'string', required: true, description: '主体 ts_code，如 003026.SZ' },
        dimension: { type: 'string', required: true, description: '维度名' },
        kind: {
          type: 'string',
          required: true,
          description: 'progression(递进)|regression(恶化)|new_event(新增事件)|association(关联传导)|divergence(矛盾)',
        },
        judgment: { type: 'string', required: true, description: '结论文字（自然语言）' },
        supports: {
          type: 'json',
          required: true,
          description: '支撑锚点列表：[{evidence_id, span_start, span_end, obs_id?}]，每一项都必须句级锚定',
        },
        dimension_scope: { type: 'string', description: '细化范围；可空' },
        from_state: { type: 'json', description: '状态 from：{level, stage, date?, obs_id?}' },
        to_state: { type: 'json', description: '状态 to：{level, stage, date?, obs_id?}' },
        delta: { type: 'json', description: '变化量：{stage_delta, value_delta, pct?}' },
        contradicts: { type: 'json', description: '反方证据锚点列表，同 supports 结构' },
        confidence: { type: 'json', description: '0-1' },
        supersedes: { type: 'string', description: '被本判断取代的 finding_id；可空' },
      },
      output: { schema: { type: 'json' }, render: (_a, v) => renderJson(v) },
      async execute(args) {
        const c = needClient(options)
        if ('error' in c) return c as unknown as JsonValue
        const toJson = (v: unknown): unknown => {
          if (typeof v !== 'string') return v ?? null
          const sv = v.trim()
          if (!sv) return null
          try { return JSON.parse(sv) } catch { return v }
        }
        const toCors = (list: unknown): Array<{ evidence_id: string; span_start: number; span_end: number; obs_id?: string | null }> => {
          const parsed = toJson(list)
          if (!Array.isArray(parsed)) return []
          return parsed.map((s) => {
            const sup = (s ?? {}) as Record<string, unknown>
            return {
              evidence_id: String(sup.evidence_id ?? ''),
              span_start: Number(sup.span_start ?? 0),
              span_end: Number(sup.span_end ?? 0),
              obs_id: sup.obs_id != null ? String(sup.obs_id) : null,
            }
          })
        }
        return await c.writeFinding({
          subject_ts_code: String(args.subject_ts_code ?? ''),
          dimension: String(args.dimension ?? ''),
          kind: String(args.kind ?? ''),
          judgment: String(args.judgment ?? ''),
          supports: toCors(args.supports),
          dimension_scope: args.dimension_scope ? String(args.dimension_scope) : null,
          from_state: toJson(args.from_state) as Record<string, unknown> | null,
          to_state: toJson(args.to_state) as Record<string, unknown> | null,
          delta: toJson(args.delta) as Record<string, unknown> | null,
          contradicts: toCors(args.contradicts),
          confidence: args.confidence != null ? Number(args.confidence) : null,
          supersedes: args.supersedes ? String(args.supersedes) : null,
        }) as unknown as JsonValue
      },
    }))
  })
}
