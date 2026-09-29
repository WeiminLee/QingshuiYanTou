import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formatEvidenceText, installQingshuiTools } from './tools.ts'
import type { KnowledgeClient } from './knowledge-client.ts'

test('formatEvidenceText truncates long excerpt', () => {
  const text = formatEvidenceText({
    evidence_id: 'EV:1',
    source_type: 'announcement',
    source_name: 'x',
    publish_date: '2024-01-01',
    confidence: 0.9,
    text_excerpt: 'a'.repeat(9000),
  })
  assert.match(text, /EV:1/)
  assert.match(text, /原文过长已截断/)
  assert.ok(text.length < 9500)
})

test('installQingshuiTools registers divergence tool set', () => {
  const registered: string[] = []
  const fakeCtx = {
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string }) => void } }) => void) {
      fn({
        tools: {
          register(tool) {
            registered.push(tool.name)
          },
        },
      })
    },
  }
  const client: KnowledgeClient = {
    async semanticSearch() { return {} },
    async fetchEvidence() { return {} },
    async compareMetric() { return {} },
    async metricTrend() { return {} },
    async rollupMetric() { return {} },
    async relatedNodes() { return {} },
    async propagateAlong() { return {} },
  }
  installQingshuiTools(fakeCtx as never, { client: () => client })
  for (const name of ['compare_metric', 'metric_trend', 'rollup_metric', 'fetch_evidence', 'semantic_search', 'related_nodes', 'propagate_along']) {
    assert.ok(registered.includes(name), `missing ${name}`)
  }
})
