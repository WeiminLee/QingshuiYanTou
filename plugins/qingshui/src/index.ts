import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import * as skillFilesystem from '@deepseek-ai/dsh-skill-filesystem'
import { Config } from './config.ts'
import type { Config as QingshuiConfig } from './config.ts'
import { createKnowledgeClient, resolveApiKey } from './knowledge-client.ts'
import type { KnowledgeClient } from './knowledge-client.ts'
import { installAnysearchTool } from './anysearch.ts'
import { installQingshuiTools } from './tools.ts'
import { mountQingshuiDataMcp } from './mcp-mount.ts'
import { installEvidenceRoute } from './ev-route.ts'
import { installMarketRoute } from './market-route.ts'
import { installNewsRoute } from './news-route.ts'
import { installSignalRoute } from './signal-route.ts'
import { installHealthRoute } from './health-route.ts'
import { installLedgerRoute } from './ledger-route.ts'

export const name = 'qingshui'
/** tools for defineTool; skills so nested skill-filesystem can register providers. */
export const inject = ['tools', 'skills']

export { Config }
export type { QingshuiConfig }

/** Package root = plugins/qingshui (parent of src/ or lib/). */
const packageRoot = fileURLToPath(new URL('..', import.meta.url))

function resolveSkillsDir(): string | undefined {
  const candidates = [
    join(packageRoot, 'skills'),
    // Belt: if ever loaded from an unexpected bundle layout, prefer package-adjacent skills.
    join(packageRoot, '..', 'skills'),
  ]
  for (const dir of candidates) {
    if (existsSync(join(dir, 'divergence-mining', 'SKILL.md'))) return dir
  }
  for (const dir of candidates) {
    if (existsSync(dir)) return dir
  }
  return undefined
}

/** Test-only overrides. Production Cordis calls `apply(ctx, config)` with two args. */
export interface QingshuiApplyDeps {
  mountDataMcp?: typeof mountQingshuiDataMcp
  skillPlugin?: typeof skillFilesystem
}

/**
 * Plugin entry. Returns a Promise so Cordis waits for Data MCP `listTools()`
 * before the first model turn — `void mountQingshuiDataMcp(...)` raced the
 * first request and left it with 0 MCP tools (review_r1 gap-degraded-ok-001).
 */
export async function apply(
  ctx: Context,
  config: QingshuiConfig,
  deps: QingshuiApplyDeps = {},
): Promise<void> {
  let client: KnowledgeClient | undefined

  const rebuild = (): void => {
    const apiKey = resolveApiKey(config.knowledgeApiKeyRef)
    if (!apiKey) {
      ctx.logger.warn('qingshui: missing API key (%c or API_KEY); tools will error until set', config.knowledgeApiKeyRef)
      client = undefined
      return
    }
    client = createKnowledgeClient({
      baseUrl: config.knowledgeBaseUrl,
      apiKey,
      timeoutMs: config.requestTimeoutMs,
    })
  }

  rebuild()
  installQingshuiTools(ctx, { client: () => client })
  installAnysearchTool(ctx)

  // Browser evidence lookup: same-origin route proxying the Knowledge API
  // (activated only under profiles that compose a web server).
  ctx.inject(['webServer'], webCtx => {
    const server = webCtx as unknown as Parameters<typeof installEvidenceRoute>[0]
    const disposeEvidence = installEvidenceRoute(server, { client: () => client })
    const disposeMarket = installMarketRoute(server, { client: () => client })
    const disposeNews = installNewsRoute(server, { client: () => client })
    const disposeSignals = installSignalRoute(server, { client: () => client })
    const disposeHealth = installHealthRoute(server, { client: () => client })
    const disposeLedger = installLedgerRoute(server, { client: () => client })
    return () => {
      disposeEvidence()
      disposeMarket()
      disposeNews()
      disposeSignals()
      disposeHealth()
      disposeLedger()
    }
  })

  // Dual-track: keep Knowledge HTTP tools; await MCP so first turn sees the 21 tools.
  const mount = deps.mountDataMcp ?? mountQingshuiDataMcp
  await mount(ctx, config)

  // MatDiscovery pattern: nested dsh-skill-filesystem with includeDefaultRoots=false
  // and customSkillDirs pointing at the plugin's skills/ tree.
  const skillsDir = resolveSkillsDir()
  if (skillsDir !== undefined) {
    ctx.plugin(deps.skillPlugin ?? skillFilesystem, {
      providerName: 'qingshui-local',
      includeDefaultRoots: false,
      customSkillDirs: [skillsDir],
    })
    ctx.logger.info('qingshui: skill root mounted provider=qingshui-local dir=%c', skillsDir)
  } else {
    ctx.logger.warn('qingshui: skill root missing (expected skills/divergence-mining/SKILL.md under package)')
  }

  ctx.logger.info(
    'qingshui: loaded HTTP tools + Data MCP mount base=%c mcp=%c',
    config.knowledgeBaseUrl,
    config.mcpBaseUrl,
  )
}
