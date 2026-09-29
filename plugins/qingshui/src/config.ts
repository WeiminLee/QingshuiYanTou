import z from '@deepseek-ai/schemastery'

export interface Config {
  knowledgeBaseUrl: string
  knowledgeApiKeyRef: string
  requestTimeoutMs: number
}

export const Config: z<Config> = z.object({
  knowledgeBaseUrl: z.string().default('http://127.0.0.1:8080'),
  knowledgeApiKeyRef: z.string().default('KNOWLEDGE_API_KEY'),
  requestTimeoutMs: z.number().default(120000),
})
