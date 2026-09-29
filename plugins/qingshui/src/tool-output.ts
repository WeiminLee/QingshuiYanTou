import type { JsonValue } from '@deepseek-ai/dsh-tools'

export function renderJson(value: JsonValue): Array<{ type: 'text'; text: string }> {
  return [{ type: 'text', text: JSON.stringify(value, null, 2) }]
}
