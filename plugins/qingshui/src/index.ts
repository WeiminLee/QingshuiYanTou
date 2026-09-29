import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import * as skillFilesystem from '@deepseek-ai/dsh-skill-filesystem'
import { Config } from './config.ts'
import type { Config as QingshuiConfig } from './config.ts'
import { createKnowledgeClient, resolveApiKey } from './knowledge-client.ts'
import type { KnowledgeClient } from './knowledge-client.ts'
import { installQingshuiTools } from './tools.ts'

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

export function apply(ctx: Context, config: QingshuiConfig): void {
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

  // MatDiscovery pattern: nested dsh-skill-filesystem with includeDefaultRoots=false
  // and customSkillDirs pointing at the plugin's skills/ tree.
  const skillsDir = resolveSkillsDir()
  if (skillsDir !== undefined) {
    ctx.plugin(skillFilesystem, {
      providerName: 'qingshui-local',
      includeDefaultRoots: false,
      customSkillDirs: [skillsDir],
    })
    ctx.logger.info('qingshui: skill root mounted provider=qingshui-local dir=%c', skillsDir)
  } else {
    ctx.logger.warn('qingshui: skill root missing (expected skills/divergence-mining/SKILL.md under package)')
  }

  ctx.logger.info(
    'qingshui: loaded tools=compare_metric,metric_trend,rollup_metric,fetch_evidence,semantic_search,related_nodes,propagate_along base=%c',
    config.knowledgeBaseUrl,
  )
}
