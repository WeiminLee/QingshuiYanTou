import assert from 'node:assert/strict'
import test from 'node:test'
import {
  bareToolName,
  buildMcpClientConfig,
  validateMcpMountConfig,
} from './mcp-mount.ts'

test('mcp mount config requires non-empty mcpBaseUrl for remote profile', () => {
  const bad = validateMcpMountConfig({ mcpBaseUrl: '' }, { mode: 'remote' })
  assert.equal(bad.ok, false)
  if (!bad.ok) assert.match(bad.reason, /mcpBaseUrl/)

  const good = validateMcpMountConfig(
    { mcpBaseUrl: 'http://127.0.0.1:8100/mcp' },
    { mode: 'remote' },
  )
  assert.equal(good.ok, true)
})

test('mcp mount off mode allows empty url', () => {
  const r = validateMcpMountConfig({ mcpBaseUrl: '' }, { mode: 'off' })
  assert.equal(r.ok, true)
})

test('buildMcpClientConfig uses streamable-http and qingshui_data', () => {
  process.env.KNOWLEDGE_API_KEY = 'secret-key'
  const cfg = buildMcpClientConfig({
    knowledgeBaseUrl: 'http://127.0.0.1:8080',
    knowledgeApiKeyRef: 'KNOWLEDGE_API_KEY',
    mcpBaseUrl: 'http://127.0.0.1:8100/mcp',
    requestTimeoutMs: 120000,
    toolCallTimeoutMs: 90000,
  })
  assert.equal(cfg.transport, 'streamable-http')
  assert.equal(cfg.serverName, 'qingshui_data')
  assert.equal(cfg.url, 'http://127.0.0.1:8100/mcp')
  assert.equal(cfg.headers['X-API-Key'], 'secret-key')
  assert.equal(cfg.toolCallTimeoutMs, 90000)
  assert.equal(cfg.failOnStartupError, false)
})

test('bareToolName strips mcp server prefix', () => {
  assert.equal(bareToolName('mcp__qingshui_data__compare_metric'), 'compare_metric')
  assert.equal(bareToolName('compare_metric'), 'compare_metric')
})
