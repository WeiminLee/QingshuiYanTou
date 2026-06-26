/**
 * stringHelpers — 字符串处理工具函数
 *
 * 来源：port from persona packages/widget/src/utils/formatting.ts
 */

/**
 * Unescapes JSON string escape sequences that LLMs often double-escape.
 * Converts literal \n, \r, \t sequences to actual control characters.
 */
export function unescapeJsonString(str: string): string {
  return str
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\");
}
