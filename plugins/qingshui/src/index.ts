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
export const inject = ['tools']

export { Config }
export type { QingshuiConfig }

const packageRoot = fileURLToPath(new URL('..', import.meta.url))

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

  const skillsDir = join(packageRoot, 'skills')
  if (existsSync(skillsDir)) {
    ctx.plugin(skillFilesystem, {
      providerName: 'qingshui-skills',
      includeDefaultRoots: false,
      customSkillDirs: [skillsDir],
    })
  }

  ctx.logger.info(
    'qingshui: loaded tools=compare_metric,metric_trend,rollup_metric,fetch_evidence,semantic_search,related_nodes,propagate_along base=%c',
    config.knowledgeBaseUrl,
  )
}
