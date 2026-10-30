export interface KnowledgeClient {
  semanticSearch(input: {
    query: string
    scope?: 'entities' | 'chunks' | 'both'
    ts_code?: string | null
    top_k?: number
  }): Promise<Record<string, unknown>>
  fetchEvidence(evidenceId: string): Promise<Record<string, unknown>>
  compareMetric(input: {
    dimension: string
    scope?: string | null
    as_of?: string | null
    top_k?: number
  }): Promise<Record<string, unknown>>
  metricTrend(input: {
    subject: string
    dimension?: string | null
    limit?: number
  }): Promise<Record<string, unknown>>
  rollupMetric(input: {
    parent: string
    scope?: string | null
    top_k?: number
  }): Promise<Record<string, unknown>>
  relatedNodes(input: {
    keyword: string
    layer?: string | null
    top_k?: number
  }): Promise<Record<string, unknown>>
  propagateAlong(input: {
    start: string
    max_hops?: number
    min_cooccur?: number
    top_k?: number
  }): Promise<Record<string, unknown>>
  getKline(input: {
    ts_code: string
    start_date?: string | null
    end_date?: string | null
    freq?: string | null
  }): Promise<Record<string, unknown>>
  getStockProfile(tsCode: string): Promise<Record<string, unknown>>
  searchStocks(input: { q: string; limit?: number }): Promise<Record<string, unknown>>
  getMarketSnapshot(): Promise<Record<string, unknown>>
  getOverseasSnapshot(): Promise<Record<string, unknown>>
  /** Liveness probe against the Knowledge API /health (open, no auth). */
  health(): Promise<Record<string, unknown>>
  /** Latest active findings (ledger search, newest first; dismissed/superseded excluded). */
  searchFindings(input?: { limit?: number }): Promise<Record<string, unknown>>
  /** Aggregate one announcement document (chapters without bodies, pdf flags). */
  fetchDocument(annId: string): Promise<Record<string, unknown>>
  /**
   * Open the retained PDF for an announcement. The raw response is returned
   * without status checks so 404/416/304 bodies reach the browser untouched;
   * only transport failures reject.
   */
  openDocumentPdf(annId: string, range?: string): Promise<Response>
  listRecentEvents(limit?: number): Promise<Record<string, unknown>>
  listSignals(input: { sourceType: string; limit?: number }): Promise<Record<string, unknown>>
  writeObservation(input: {
    subject_ts_code: string
    dimension: string
    evidence_id: string
    span_start: number
    span_end: number
    stage_raw?: string | null
    stage_level?: number | null
    dimension_scope?: string | null
    subject_name?: string | null
    event_date?: string | null
    published_at?: string | null
    metric_value?: Record<string, unknown> | null
  }): Promise<Record<string, unknown>>
  writeFinding(input: {
    subject_ts_code: string
    dimension: string
    kind: string
    judgment: string
    supports: Array<{ evidence_id: string; span_start: number; span_end: number; obs_id?: string | null }>
    dimension_scope?: string | null
    from_state?: Record<string, unknown> | null
    to_state?: Record<string, unknown> | null
    delta?: Record<string, unknown> | null
    contradicts?: Array<{ evidence_id: string; span_start: number; span_end: number; obs_id?: string | null }> | null
    confidence?: number | null
    supersedes?: string | null
    created_by?: Record<string, unknown> | null
  }): Promise<Record<string, unknown>>
}

export function createKnowledgeClient(options: {
  baseUrl: string
  apiKey: string
  timeoutMs: number
  fetchImpl?: typeof fetch
}): KnowledgeClient {
  const base = options.baseUrl.replace(/\/$/, '')
  const fetchImpl = options.fetchImpl ?? fetch

  async function request(path: string, init: RequestInit): Promise<unknown> {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), options.timeoutMs)
    try {
      const res = await fetchImpl(`${base}${path}`, {
        ...init,
        signal: ctrl.signal,
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': options.apiKey,
          ...(init.headers ?? {}),
        },
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`Knowledge API ${res.status}: ${text.slice(0, 200)}`)
      }
      return await res.json()
    } finally {
      clearTimeout(timer)
    }
  }

  const post = (path: string, body: unknown) =>
    request(path, { method: 'POST', body: JSON.stringify(body) }) as Promise<Record<string, unknown>>

  const get = (path: string, params?: Record<string, string>) => {
    const query = params === undefined ? '' : `?${new URLSearchParams(params).toString()}`
    return request(`${path}${query}`, { method: 'GET' }) as Promise<Record<string, unknown>>
  }

  return {
    semanticSearch(input) {
      return post('/api/v1/knowledge/search/semantic', {
        query: input.query,
        scope: input.scope ?? 'entities',
        ts_code: input.ts_code ?? null,
        top_k: input.top_k ?? 5,
      })
    },
    fetchEvidence(evidenceId) {
      return request(`/api/v1/knowledge/evidence/${encodeURIComponent(evidenceId)}`, {
        method: 'GET',
      }) as Promise<Record<string, unknown>>
    },
    compareMetric(input) {
      return post('/api/v1/knowledge/agent/compare_metric', {
        dimension: input.dimension,
        scope: input.scope ?? null,
        as_of: input.as_of ?? null,
        top_k: input.top_k ?? 30,
      })
    },
    metricTrend(input) {
      return post('/api/v1/knowledge/agent/metric_trend', {
        subject: input.subject,
        dimension: input.dimension ?? null,
        limit: input.limit ?? 50,
      })
    },
    rollupMetric(input) {
      return post('/api/v1/knowledge/agent/rollup_metric', {
        parent: input.parent,
        scope: input.scope ?? null,
        top_k: input.top_k ?? 30,
      })
    },
    relatedNodes(input) {
      return post('/api/v1/knowledge/agent/related_nodes', {
        keyword: input.keyword,
        layer: input.layer ?? null,
        top_k: input.top_k ?? 20,
      })
    },
    propagateAlong(input) {
      return post('/api/v1/knowledge/agent/propagate_along', {
        start: input.start,
        max_hops: input.max_hops ?? 1,
        min_cooccur: input.min_cooccur ?? 5,
        top_k: input.top_k ?? 20,
      })
    },
    getKline(input) {
      return get('/api/v1/knowledge/market/kline', {
        ts_code: input.ts_code,
        start_date: input.start_date ?? '',
        end_date: input.end_date ?? '',
        freq: input.freq ?? 'D',
      })
    },
    getStockProfile(tsCode) {
      return get('/api/v1/knowledge/market/stock_profile', { ts_code: tsCode })
    },
    searchStocks(input) {
      const limit = input.limit ?? 10
      return get('/api/v1/stocks/search', {
        q: input.q,
        limit: String(limit),
      })
    },
    getMarketSnapshot() {
      return get('/api/v1/knowledge/market/snapshot')
    },
    getOverseasSnapshot() {
      return get('/api/v1/knowledge/market/overseas')
    },
    health() {
      return get('/health')
    },
    searchFindings(input) {
      return post('/api/v1/knowledge/ledger/search', { limit: input?.limit ?? 20 })
    },
    fetchDocument(annId) {
      return request(`/api/v1/knowledge/documents/${encodeURIComponent(annId)}`, {
        method: 'GET',
      }) as Promise<Record<string, unknown>>
    },
    async openDocumentPdf(annId, range) {
      const ctrl = new AbortController()
      // The timeout guards the response head, not the streamed body: the timer
      // clears once fetch resolves, so a slow PDF is not cut off mid-transfer.
      const timer = setTimeout(() => ctrl.abort(), options.timeoutMs)
      try {
        return await fetchImpl(`${base}/api/v1/knowledge/documents/${encodeURIComponent(annId)}/pdf`, {
          method: 'GET',
          signal: ctrl.signal,
          headers: {
            'X-API-Key': options.apiKey,
            ...(range === undefined ? {} : { Range: range }),
          },
        })
      } finally {
        clearTimeout(timer)
      }
    },
    listSignals(input) {
      return get('/api/v1/signals', {
        source_type: input.sourceType,
        limit: String(input.limit ?? 4),
      })
    },
    async listRecentEvents(limit = 20) {
      try {
        return await post('/api/v1/knowledge/sources/events/recent', { limit })
      } catch (error) {
        const message = error instanceof Error ? error.message : ''
        // Older knowledge hosts have find_events only. A single % matches every title.
        if (!message.includes('Knowledge API 404') && !message.includes('Knowledge API 405')) throw error
        return post('/api/v1/knowledge/sources/events', { query: '%', top_n: limit })
      }
    },
    writeObservation(input) {
      return post('/api/v1/knowledge/ledger/observation', {
        subject_ts_code: input.subject_ts_code,
        dimension: input.dimension,
        evidence_id: input.evidence_id,
        span_start: input.span_start,
        span_end: input.span_end,
        stage_raw: input.stage_raw ?? null,
        stage_level: input.stage_level ?? null,
        dimension_scope: input.dimension_scope ?? null,
        subject_name: input.subject_name ?? null,
        event_date: input.event_date ?? null,
        published_at: input.published_at ?? null,
        metric_value: input.metric_value ?? null,
      })
    },
    writeFinding(input) {
      return post('/api/v1/knowledge/ledger/finding', {
        subject_ts_code: input.subject_ts_code,
        dimension: input.dimension,
        kind: input.kind,
        judgment: input.judgment,
        supports: input.supports,
        dimension_scope: input.dimension_scope ?? null,
        from_state: input.from_state ?? null,
        to_state: input.to_state ?? null,
        delta: input.delta ?? null,
        contradicts: input.contradicts ?? [],
        confidence: input.confidence ?? null,
        supersedes: input.supersedes ?? null,
        created_by: input.created_by ?? null,
      })
    },
  }
}

export function resolveApiKey(ref: string): string {
  const name = ref.trim() || 'KNOWLEDGE_API_KEY'
  const direct = (process.env[name] ?? '').trim()
  if (direct) return direct
  // Cloud backend historically uses API_KEY for Knowledge auth.
  if (name === 'KNOWLEDGE_API_KEY') return (process.env.API_KEY ?? '').trim()
  return ''
}
