/**
 * useStreamParser — SSE 流式解析 composable
 *
 * Port from persona packages/widget/src/utils/formatting.ts
 * 支持的格式：JSON / XML / regex-json / plain-text
 *
 * 功能：
 * - parse(content, format) — 按格式解析
 * - autoDetectParse(content) — 自动检测格式并解析
 * - looksStructured(content) — 检测内容是否看起来是结构化格式
 */

import { unescapeJsonString } from '@/utils/stringHelpers'

/** 支持的解析格式 */
export type ParserFormat = 'json' | 'xml' | 'regex-json' | 'plain-text'

/** 解析结果 */
export interface ParseResult {
  /** 解析后的数据对象 */
  data: unknown
  /** 检测到的格式 */
  format: ParserFormat
  /** 是否解析成功 */
  success: boolean
}

/** useStreamParser 返回类型 */
export interface UseStreamParserReturn {
  /** 按指定格式解析内容 */
  parse: (content: string, format: ParserFormat) => ParseResult
  /** 自动检测格式并解析 */
  autoDetectParse: (content: string) => ParseResult
  /** 检测内容是否看起来是结构化格式 */
  looksStructured: (content: string) => boolean
}

/**
 * JSON 检测：内容以 { 或 [ 开头
 */
function looksLikeJson(content: string): boolean {
  const trimmed = content.trim()
  return trimmed.startsWith('{') || trimmed.startsWith('[')
}

/**
 * XML 检测：内容以 < 开头，且匹配 <tag>...</tag> 模式
 */
function looksLikeXml(content: string): boolean {
  const trimmed = content.trim()
  if (!trimmed.startsWith('<')) return false
  // 匹配 <tag>...</tag> 模式
  const xmlRegex = /^<([a-zA-Z_][\w.-]*)[^>]*>([\s\S]*)<\/\1>$/
  return xmlRegex.test(trimmed)
}

/**
 * 提取 XML 标签内容
 */
function extractXmlContent(content: string): unknown {
  const trimmed = content.trim()
  // 匹配 <tag>...</tag> 模式
  const xmlRegex = /^<([a-zA-Z_][\w.-]*)[^>]*>([\s\S]*)<\/\1>$/
  const match = trimmed.match(xmlRegex)
  if (match && match[2]) {
    return match[2]
  }
  return null
}

export function useStreamParser(): UseStreamParserReturn {
  /**
   * 按指定格式解析内容
   */
  function parse(content: string, format: ParserFormat): ParseResult {
    const trimmed = content.trim()

    try {
      switch (format) {
        case 'json': {
          const parsed = JSON.parse(trimmed)
          return { data: parsed, format: 'json', success: true }
        }

        case 'regex-json': {
          // regex-json: 使用正则提取 JSON 中的 text 字段
          const textFieldRegex = /"text"\s*:\s*"((?:[^"\\]|\\.)*)"/
          const match = trimmed.match(textFieldRegex)
          if (match && match[1]) {
            const text = unescapeJsonString(match[1])
            return { data: { text }, format: 'regex-json', success: true }
          }
          // 尝试完整解析
          const parsed = JSON.parse(trimmed)
          return { data: parsed, format: 'regex-json', success: true }
        }

        case 'xml': {
          if (!looksLikeXml(trimmed)) {
            return { data: null, format: 'xml', success: false }
          }
          const content2 = extractXmlContent(trimmed)
          return { data: content2, format: 'xml', success: true }
        }

        case 'plain-text':
        default: {
          // plain-text: 返回原内容作为 data
          return { data: trimmed, format: 'plain-text', success: true }
        }
      }
    } catch (error) {
      // 解析失败，返回原始内容作为 plain-text
      return { data: trimmed, format: 'plain-text', success: false }
    }
  }

  /**
   * 自动检测格式并解析
   * 优先级：JSON -> XML -> plain-text
   */
  function autoDetectParse(content: string): ParseResult {
    const trimmed = content.trim()

    if (!trimmed) {
      return { data: null, format: 'plain-text', success: false }
    }

    // 1. 尝试 JSON
    if (looksLikeJson(trimmed)) {
      try {
        const parsed = JSON.parse(trimmed)
        return { data: parsed, format: 'json', success: true }
      } catch {
        // JSON 解析失败，尝试其他格式
      }
    }

    // 2. 尝试 XML
    if (looksLikeXml(trimmed)) {
      const content2 = extractXmlContent(trimmed)
      return { data: content2, format: 'xml', success: true }
    }

    // 3. 降级为 plain-text
    return { data: trimmed, format: 'plain-text', success: true }
  }

  /**
   * 检测内容是否看起来是结构化格式
   */
  function looksStructured(content: string): boolean {
    return looksLikeJson(content) || looksLikeXml(content)
  }

  return {
    parse,
    autoDetectParse,
    looksStructured,
  }
}
