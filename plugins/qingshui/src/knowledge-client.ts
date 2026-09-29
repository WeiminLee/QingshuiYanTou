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
