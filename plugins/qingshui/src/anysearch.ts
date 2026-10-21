import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { JsonValue } from '@deepseek-ai/dsh-tools'

/** Domains accepted by AnySearch CLI 3.1.1. */
export const ANYSEARCH_DOMAINS = [
  'general', 'resource', 'social_media', 'finance', 'academic', 'legal',
  'health', 'business', 'security', 'ip', 'code', 'energy',
  'environment', 'agriculture', 'travel', 'film', 'gaming',
] as const

const COMMANDS = ['search', 'batch_search', 'extract', 'get_sub_domains'] as const
const MAX_TEXT = 60_000
const QUERY_ITEM_KEYS = new Set(['query', 'domain', 'sub_domain', 'sub_domain_params', 'tag', 'max_results', 'params'])

export interface AnysearchArgs {
  command?: unknown
  query?: unknown
  queries?: unknown
  domain?: unknown
  domains?: unknown
  sub_domain?: unknown
  params?: unknown
  tag?: unknown
  max_results?: unknown
  url?: unknown
  zone?: unknown
  language?: unknown
  api_key?: unknown
}

export interface AnysearchRunResult {
  code: number
  stdout: string
  stderr: string
}

export interface AnysearchToolOptions {
  resolveCli?: () => string | undefined
  run?: (cliPath: string, argv: string[]) => Promise<AnysearchRunResult>
}

function clip(text: string): string {
  if (text.length <= MAX_TEXT) return text
  return `${text.slice(0, MAX_TEXT)}\n...[anysearch 输出已截断，共 ${text.length} 字符]`
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function domainOk(value: string): boolean {
  return (ANYSEARCH_DOMAINS as readonly string[]).includes(value)
}

function maxResultsFlag(value: unknown): { error: string } | { flag: string[] } | { flag: [] } {
  if (value === undefined || value === null || value === '') return { flag: [] }
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isInteger(n) || n < 1 || n > 10) return { error: 'max_results 必须是 1 到 10 的整数' }
  return { flag: ['--max_results', String(n)] }
}

function pushOptional(argv: string[], flag: string, value: unknown, check?: (text: string) => string | undefined): string | undefined {
  const text = asText(value)
  if (!text) return undefined
  const problem = check?.(text)
  if (problem) return problem
  argv.push(flag, text)
  return undefined
}

export function buildAnysearchArgv(args: AnysearchArgs): { argv: string[] } | { error: string } {
  if (asText(args.api_key)) return { error: '不要在工具参数里传 api_key' }
  const command = asText(args.command)
  if (!(COMMANDS as readonly string[]).includes(command)) {
    return { error: 'command 只能是 search、batch_search、extract、get_sub_domains' }
  }
  const argv = [command]
  if (command === 'search') {
    const query = asText(args.query)
    if (!query) return { error: 'search 需要 query' }
    if (query.length > 2000) return { error: 'query 过长' }
    argv.push(query)
    const domain = asText(args.domain)
    const vertical = domain !== '' && domain !== 'general'
    const subDomain = asText(args.sub_domain)
    const tag = asText(args.tag)
    if (vertical && !domainOk(domain)) return { error: `未知 domain：${domain}` }
    if (vertical && !subDomain && !tag) return { error: '垂直检索要带 sub_domain 或 tag。先调用 get_sub_domains。' }
    if (vertical) argv.push('--domain', domain)
    if (vertical && subDomain) argv.push('--sub_domain', subDomain)
    if (vertical && tag) argv.push('--tag', tag)
    const paramsError = pushOptional(argv, '--params', args.params, (text) => (
      text.length > 4000 ? 'params 过长' : undefined
    ))
    if (paramsError) return { error: paramsError }
    const zone = asText(args.zone)
    if (zone && zone !== 'cn' && zone !== 'intl') return { error: 'zone 只能是 cn 或 intl' }
    if (zone) argv.push('--zone', zone)
    const languageError = pushOptional(argv, '--language', args.language, (text) => (
      /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$/.test(text) ? undefined : 'language 格式不对'
    ))
    if (languageError) return { error: languageError }
    const max = maxResultsFlag(args.max_results)
    if ('error' in max) return max
    argv.push(...max.flag)
    return { argv }
  }
  if (command === 'get_sub_domains') {
    const domains = asText(args.domains)
    const domain = asText(args.domain)
    const list = domains
      ? domains.split(',').map(item => item.trim()).filter(Boolean)
      : (domain ? [domain] : [])
    if (list.length === 0) return { error: 'get_sub_domains 需要 domain 或 domains' }
    if (list.length > 5) return { error: 'get_sub_domains 最多 5 个 domain' }
    const unknown = list.find(item => !domainOk(item))
    if (unknown) return { error: `未知 domain：${unknown}` }
    if (domains) argv.push('--domains', list.join(','))
    else argv.push('--domain', list[0] ?? domain)
    return { argv }
  }
  if (command === 'extract') {
    const url = asText(args.url)
    if (!url) return { error: 'extract 需要 url' }
    let parsed: URL
    try {
      parsed = new URL(url)
    } catch {
      return { error: 'url 只能是 http 或 https' }
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return { error: 'url 只能是 http 或 https' }
    argv.push('--url', url)
    return { argv }
  }
  const rawQueries = args.queries
  if (typeof rawQueries === 'string' && rawQueries.trim().startsWith('@')) return { error: 'queries 不要用 @文件' }
  let parsedQueries: unknown = rawQueries
  if (typeof rawQueries === 'string') {
    try {
      parsedQueries = JSON.parse(rawQueries)
    } catch {
      return { error: 'queries 必须是 JSON 数组' }
    }
  }
  if (!Array.isArray(parsedQueries) || parsedQueries.length < 1 || parsedQueries.length > 5) {
    return { error: 'queries 必须是 1 到 5 条' }
  }
  const cleaned: Array<Record<string, unknown>> = []
  for (const item of parsedQueries) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return { error: 'queries 的每一项都要有 query' }
    const record = item as Record<string, unknown>
    const query = asText(record.query)
    if (!query) return { error: 'queries 的每一项都要有 query' }
    const next: Record<string, unknown> = { query }
    for (const key of QUERY_ITEM_KEYS) {
      if (key === 'query' || record[key] === undefined) continue
      next[key] = record[key]
    }
    cleaned.push(next)
  }
  argv.push('--queries', JSON.stringify(cleaned))
  const domain = asText(args.domain)
  const vertical = domain !== '' && domain !== 'general'
  if (vertical && !domainOk(domain)) return { error: `未知 domain：${domain}` }
  if (vertical) argv.push('--domain', domain)
  const sharedError = pushOptional(argv, '--sub_domain', args.sub_domain)
    ?? pushOptional(argv, '--tag', args.tag)
    ?? pushOptional(argv, '--params', args.params)
  if (sharedError) return { error: sharedError }
  const max = maxResultsFlag(args.max_results)
  if ('error' in max) return max
  argv.push(...max.flag)
  return { argv }
}

export function defaultAnysearchCliPath(
  env: NodeJS.ProcessEnv = process.env,
  home = homedir(),
): string | undefined {
  const agentsHome = env.DSH_AGENTS_HOME || join(home, '.agents')
  const candidates = [
    env.QINGSHUI_ANYSEARCH_CLI,
    join(agentsHome, 'skills', 'anysearch', 'scripts', 'anysearch_cli.js'),
  ].filter((item): item is string => typeof item === 'string' && item.length > 0)
  return candidates.find(item => existsSync(item))
}

export async function runAnysearchCli(cliPath: string, argv: string[]): Promise<AnysearchRunResult> {
  return await new Promise((resolve) => {
    execFile(process.execPath, [cliPath, ...argv], {
      timeout: 45_000,
      maxBuffer: 2_000_000,
    }, (error, stdout, stderr) => {
      const err = error as (NodeJS.ErrnoException & { code?: number | string }) | null
      const code = typeof err?.code === 'number' ? err.code : (err ? 1 : 0)
      resolve({
        code,
        stdout: stdout ?? '',
        stderr: stderr || (err && code !== 0 ? err.message : ''),
      })
    })
  })
}

export function installAnysearchTool(ctx: Context, options: AnysearchToolOptions = {}): void {
  const resolveCli = options.resolveCli ?? (() => defaultAnysearchCliPath())
  const run = options.run ?? runAnysearchCli
  ctx.inject(['tools'], (tctx) => {
    tctx.tools.register(defineTool({
      name: 'anysearch',
      description:
        '垂直检索、批量检索和页面摘录（AnySearch）。新闻、资讯和复盘报道用 web_search；web_search 失败时用本工具做普通检索。' +
        '普通检索只传 query，不传 domain。domain 为 general 也按普通检索。' +
        'command 为 search、batch_search、extract、get_sub_domains。' +
        `垂直领域先 get_sub_domains。domain 取值：${ANYSEARCH_DOMAINS.join(', ')}。` +
        '标了 required 的参数全部放进 params，没有值就传空字符串。' +
        '本地行情、公告、事件、概念不要用本工具。结果不是 EV 证据。不要传 api_key。',
      parameters: {
        command: {
          type: 'string',
          required: true,
          enum: COMMANDS,
          description: 'search、batch_search、extract、get_sub_domains',
        },
        query: { type: 'string', description: 'search 的检索词' },
        queries: { type: 'json', description: 'batch_search 的 JSON 数组，1 到 5 条，每条含 query' },
        domain: { type: 'string', description: '垂直领域，如 finance' },
        domains: { type: 'string', description: 'get_sub_domains 的多个 domain，逗号分隔，最多 5 个' },
        sub_domain: { type: 'string', description: '子域，如 finance.quote。先向 get_sub_domains 要' },
        tag: { type: 'string', description: '能力标签，如 finance.quote' },
        params: { type: 'string', description: '子域参数。JSON 或 key=value。必填项没有值就写空字符串' },
        max_results: { type: 'json', description: '1 到 10，默认由 CLI 取 10' },
        url: { type: 'string', description: 'extract 的 http(s) 地址' },
        zone: { type: 'string', description: 'cn 或 intl' },
        language: { type: 'string', description: '如 zh-CN' },
      },
      output: {
        schema: { type: 'json' },
        render: (_args, value) => {
          if (typeof value === 'object' && value !== null && 'text' in value) {
            const record = value as { text?: unknown; error?: unknown }
            const text = typeof record.text === 'string' ? record.text : ''
            const error = typeof record.error === 'string' ? record.error : ''
            return [{ type: 'text', text: error ? (text ? `${error}\n${text}` : error) : text }]
          }
          return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
        },
      },
      async execute(toolArgs) {
        const built = buildAnysearchArgv(toolArgs as AnysearchArgs)
        if ('error' in built) return { error: built.error } as unknown as JsonValue
        const cli = resolveCli()
        if (!cli) {
          return {
            error: 'anysearch CLI 不在本机。期望 ~/.agents/skills/anysearch/scripts/anysearch_cli.js，或设置 QINGSHUI_ANYSEARCH_CLI。',
          } as unknown as JsonValue
        }
        const result = await run(cli, built.argv)
        const text = clip(result.stdout)
        if (result.code !== 0) {
          const error = clip(result.stderr || result.stdout || `anysearch 退出码 ${result.code}`)
          return { error, text } as unknown as JsonValue
        }
        return { text } as unknown as JsonValue
      },
    }))
  })
}
