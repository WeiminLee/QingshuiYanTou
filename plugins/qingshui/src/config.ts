import z from '@deepseek-ai/schemastery'

export interface Config {
  knowledgeBaseUrl: string
  knowledgeApiKeyRef: string
  /** Data MCP Streamable HTTP endpoint (…/mcp). */
  mcpBaseUrl: string
  requestTimeoutMs: number
  /** Alias used by MCP client mount (defaults same as requestTimeoutMs). */
  toolCallTimeoutMs: number
}

export const Config: z<Config> = z.object({
  knowledgeBaseUrl: z.string().default('http://127.0.0.1:8080'),
  knowledgeApiKeyRef: z.string().default('KNOWLEDGE_API_KEY'),
  mcpBaseUrl: z.string().default('http://127.0.0.1:8100/mcp'),
  requestTimeoutMs: z.number().default(120000),
  toolCallTimeoutMs: z.number().default(120000),
})
