import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { buildAnysearchArgv, installAnysearchTool } from './anysearch.ts'

const skillPath = join(dirname(fileURLToPath(import.meta.url)), '../skills/anysearch/SKILL.md')
const patchPath = join(dirname(fileURLToPath(import.meta.url)), '../cordis.patch.yml')

test('search argv is the query plus explicit flags', () => {
  const built = buildAnysearchArgv({
    command: 'search',
    query: '芯片概念',
    max_results: 3,
    language: 'zh-CN',
  })
  assert.deepEqual(built, {
    argv: ['search', '芯片概念', '--language', 'zh-CN', '--max_results', '3'],
  })
})

test('domain general is ordinary search and omits domain flags', () => {
  const built = buildAnysearchArgv({
    command: 'search',
    domain: 'general',
    language: 'zh-CN',
    max_results: '10',
    query: '大普微 股票代码 涨停',
    zone: 'cn',
  })
  assert.deepEqual(built, {
    argv: ['search', '大普微 股票代码 涨停', '--zone', 'cn', '--language', 'zh-CN', '--max_results', '10'],
  })
  const batched = buildAnysearchArgv({
    command: 'batch_search',
    domain: 'general',
    queries: JSON.stringify([{ query: '大普微 涨停' }]),
  })
  assert.deepEqual(batched, {
    argv: ['batch_search', '--queries', JSON.stringify([{ query: '大普微 涨停' }])],
  })
})

test('vertical search requires a sub_domain and keeps required params', () => {
  const missing = buildAnysearchArgv({ command: 'search', query: 'AAPL', domain: 'finance' })
  assert.deepEqual(missing, { error: '垂直检索要带 sub_domain 或 tag。先调用 get_sub_domains。' })
  const built = buildAnysearchArgv({
    command: 'search',
    query: 'AAPL',
    domain: 'finance',
    sub_domain: 'finance.quote',
    params: 'type=stock,symbol=AAPL,cn_code=',
  })
  assert.deepEqual(built, {
    argv: [
      'search', 'AAPL',
      '--domain', 'finance',
      '--sub_domain', 'finance.quote',
      '--params', 'type=stock,symbol=AAPL,cn_code=',
    ],
  })
})

test('rejects api keys, file reads, and non-http extract urls', () => {
  assert.equal('error' in buildAnysearchArgv({ command: 'search', query: 'x', api_key: 'sekret' }), true)
  const fileQuery = buildAnysearchArgv({ command: 'batch_search', queries: '@/etc/passwd' })
  assert.deepEqual(fileQuery, { error: 'queries 不要用 @文件' })
  const fileUrl = buildAnysearchArgv({ command: 'extract', url: 'file:///etc/passwd' })
  assert.deepEqual(fileUrl, { error: 'url 只能是 http 或 https' })
})

test('get_sub_domains and batch_search stay on the allowlist', () => {
  assert.deepEqual(buildAnysearchArgv({ command: 'get_sub_domains', domain: 'finance' }), {
    argv: ['get_sub_domains', '--domain', 'finance'],
  })
  assert.deepEqual(buildAnysearchArgv({ command: 'doc' }), {
    error: 'command 只能是 search、batch_search、extract、get_sub_domains',
  })
  const batched = buildAnysearchArgv({
    command: 'batch_search',
    queries: JSON.stringify([
      { query: 'AAPL', api_key: 'nope', domain: 'finance' },
      { query: 'MSFT' },
    ]),
    max_results: 2,
  })
  assert.deepEqual(batched, {
    argv: [
      'batch_search',
      '--queries',
      JSON.stringify([
        { query: 'AAPL', domain: 'finance' },
        { query: 'MSFT' },
      ]),
      '--max_results',
      '2',
    ],
  })
})

test('installAnysearchTool runs only the built argv', async () => {
  const tools = new Map<string, { execute: (args: Record<string, unknown>) => Promise<unknown> }>()
  const calls: string[][] = []
  installAnysearchTool({
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string }) => void } }) => void) {
      fn({ tools: { register(tool) { tools.set(tool.name, tool as never) } } })
    },
  } as never, {
    resolveCli: () => '/tmp/anysearch_cli.js',
    run: async (cli, argv) => {
      calls.push([cli, ...argv])
      return { code: 0, stdout: 'finance.quote\n', stderr: '' }
    },
  })
  const tool = tools.get('anysearch')
  assert.ok(tool)
  const value = await tool.execute({ command: 'get_sub_domains', domain: 'finance' })
  assert.deepEqual(value, { text: 'finance.quote\n' })
  assert.deepEqual(calls, [['/tmp/anysearch_cli.js', 'get_sub_domains', '--domain', 'finance']])
})

test('missing CLI and failed CLI do not look like a successful search', async () => {
  const tools = new Map<string, { execute: (args: Record<string, unknown>) => Promise<{ error?: string; text?: string }> }>()
  installAnysearchTool({
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string }) => void } }) => void) {
      fn({ tools: { register(tool) { tools.set(tool.name, tool as never) } } })
    },
  } as never, {
    resolveCli: () => undefined,
    run: async () => {
      throw new Error('should not run')
    },
  })
  const missing = await tools.get('anysearch')!.execute({ command: 'search', query: 'x' })
  assert.match(missing.error ?? '', /anysearch CLI/)

  const failing = new Map<string, { execute: (args: Record<string, unknown>) => Promise<{ error?: string }> }>()
  installAnysearchTool({
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string }) => void } }) => void) {
      fn({ tools: { register(tool) { failing.set(tool.name, tool as never) } } })
    },
  } as never, {
    resolveCli: () => '/tmp/anysearch_cli.js',
    run: async () => ({ code: 1, stdout: '', stderr: 'Error: boom' }),
  })
  const failed = await failing.get('anysearch')!.execute({ command: 'search', query: 'x' })
  assert.match(failed.error ?? '', /boom/)
})

test('anysearch skill tells the model to call the tool', () => {
  const text = readFileSync(skillPath, 'utf8')
  for (const phrase of [
    'name: anysearch',
    'get_sub_domains',
    '空字符串',
    '不是 EV',
    'auto_registered',
    'api.anysearch.com',
    '不要用 bash',
    'web_search',
    '不传 `domain`',
    'domain` 为 `general`',
  ]) {
    assert.ok(text.includes(phrase), `missing ${phrase}`)
  }
  assert.equal(text.includes('anysearch_cli'), false)
  const patch = readFileSync(patchPath, 'utf8')
  assert.match(patch, /先读 anysearch skill/)
  assert.match(patch, /web_search/)
  assert.match(patch, /不传 domain/)
  assert.match(patch, /先读 limit-up skill/)
  assert.match(patch, /search_stock/)
  assert.equal(patch.includes('id: tool-web'), false)
})
