import assert from 'node:assert/strict'
import test from 'node:test'
import { apply } from './index.ts'
import type { QingshuiConfig } from './index.ts'

function fakeCtx() {
  return {
    logger: { warn() {}, info() {} },
    inject() {},
    plugin() {
      return Promise.resolve()
    },
  }
}

const config: QingshuiConfig = {
  knowledgeBaseUrl: 'http://127.0.0.1:8001',
  knowledgeApiKeyRef: 'KNOWLEDGE_API_KEY',
  mcpBaseUrl: 'http://127.0.0.1:8100/mcp',
  requestTimeoutMs: 120000,
  toolCallTimeoutMs: 120000,
}

test('apply awaits Data MCP mount before returning so the first turn sees MCP tools', async () => {
  process.env.KNOWLEDGE_API_KEY = 'test-key'
  let mountFinished = false
  const mountDataMcp = async () => {
    await new Promise((r) => setTimeout(r, 40))
    mountFinished = true
  }
  const result = apply(fakeCtx() as never, config, {
    mountDataMcp,
    skillPlugin: { name: 'noop-skill' } as never,
  })
  assert.equal(
    typeof (result as Promise<void> | undefined)?.then,
    'function',
    'apply must return a Promise Cordis can await; void-fire-and-forget leaves first turn with 0 MCP tools',
  )
  assert.equal(mountFinished, false, 'mount must still be in flight when apply yields the promise')
  await result
  assert.equal(mountFinished, true)
})
