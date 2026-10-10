import type { Context } from '@deepseek-ai/cordis'
import type { Config as QingshuiConfig } from './config.ts'
import { resolveApiKey } from './knowledge-client.ts'

export type McpMountMode = 'remote' | 'local' | 'off'

export interface McpMountOptions {
  mode?: McpMountMode
}

/** Strip `mcp__<server>__` prefix for eval assertions. */
export function bareToolName(name: string): string {
  const m = /^mcp__[^_]+(?:_[^_]+)*__(.+)$/.exec(name)
  if (m?.[1]) return m[1]
  // Fallback: last segment after double underscore
  const idx = name.lastIndexOf('__')
  return idx >= 0 ? name.slice(idx + 2) : name
}

export function validateMcpMountConfig(
  config: Pick<QingshuiConfig, 'mcpBaseUrl'>,
  options: McpMountOptions = {},
): { ok: true } | { ok: false; reason: string } {
  const mode = options.mode ?? 'remote'
  if (mode === 'off') return { ok: true }
  const url = (config.mcpBaseUrl ?? '').trim()
  if (!url) {
    return { ok: false, reason: 'mcpBaseUrl is required when MCP mount mode is remote/local' }
  }
  if (mode === 'remote' && /localhost|127\.0\.0\.1/.test(url)) {
    // Soft warning path for prod: still allow local loopback MCP on same host as Knowledge.
    // Callers that mean "cloud harness talking to Mac tunnel" should fail elsewhere.
  }
  try {
    // eslint-disable-next-line no-new
    new URL(url)
  } catch {
    return { ok: false, reason: `mcpBaseUrl is not a valid URL: ${url}` }
  }
  return { ok: true }
}

export function buildMcpClientConfig(config: QingshuiConfig): {
  transport: 'streamable-http'
  serverName: 'qingshui_data'
  url: string
  headers: Record<string, string>
  toolCallTimeoutMs: number
  failOnStartupError: boolean
} {
  const apiKey = resolveApiKey(config.knowledgeApiKeyRef)
  return {
    transport: 'streamable-http',
    serverName: 'qingshui_data',
    url: config.mcpBaseUrl.trim(),
    headers: apiKey ? { 'X-API-Key': apiKey } : {},
    toolCallTimeoutMs: config.toolCallTimeoutMs ?? config.requestTimeoutMs ?? 120000,
    failOnStartupError: false,
  }
}

/**
 * Mount read-only Data MCP alongside existing Knowledge HTTP tools (dual-track).
 * Failures are logged; plugin activation continues (failOnStartupError=false).
 */
export async function mountQingshuiDataMcp(ctx: Context, config: QingshuiConfig): Promise<void> {
  const check = validateMcpMountConfig(config, { mode: 'remote' })
  if (!check.ok) {
    ctx.logger.warn('qingshui: skip Data MCP mount — %c', check.reason)
    return
  }
  const mcpConfig = buildMcpClientConfig(config)
  try {
    const mcpClient = await import('@deepseek-ai/dsh-mcp-client')
    await ctx.plugin(mcpClient, mcpConfig)
    ctx.logger.info(
      'qingshui: Data MCP mounted server=%c url=%c',
      mcpConfig.serverName,
      mcpConfig.url,
    )
  } catch (err) {
    ctx.logger.warn(
      'qingshui: Data MCP mount failed (HTTP tools still available): %c',
      err instanceof Error ? err.message : String(err),
    )
  }
}
