/**
 * EV citation affordance: turn plain-text `EV:<hex>` citations in assistant
 * prose into inline-code tokens so MarkdownText's fileMentions seam can
 * render them as interactive chips. Line-based, idempotent; fenced blocks
 * and existing code spans are left untouched.
 */

/** Evidence id token: EV: + 6..64 lowercase/uppercase hex digits. */
export const EV_ID_RE = /\bEV:[0-9a-fA-F]{6,64}\b/g

/** Whether a mention token is an EV citation id. @param value - inline-code token as written. */
export function evIdOf(value: string): string | undefined {
  const trimmed = value.trim()
  return /^EV:[0-9a-fA-F]{6,64}$/.test(trimmed) ? trimmed : undefined
}

/** Whether a full id is the canonical sha256 form (64 hex). */
export function isFullEvId(id: string): boolean {
  return /^EV:[0-9a-fA-F]{64}$/.test(id)
}

const FENCE_RE = /^ {0,3}(```+|~~~+)/

/**
 * Wrap plain-text EV citations in single backticks to promote them into
 * inline-code tokens. Fenced code blocks (```/~~~) and text already inside
 * backtick spans are untouched, so code samples keep their bytes and a
 * second pass over the output is a no-op.
 * @param text - assistant markdown source.
 * @returns transformed markdown source.
 */
export function evCiteTransform(text: string): string {
  if (!text.includes('EV:')) return text
  const lines = text.split('\n')
  let fence = ''
  const out: string[] = []
  for (const line of lines) {
    const fenceMatch = FENCE_RE.exec(line)
    if (fence !== '') {
      out.push(line)
      if (fenceMatch?.[1]?.startsWith(fence[0]) === true && fenceMatch[1].length >= fence.length) {
        fence = ''
      }
      continue
    }
    if (fenceMatch?.[1] !== undefined) {
      fence = fenceMatch[1]
      out.push(line)
      continue
    }
    out.push(transformLine(line))
  }
  return out.join('\n')
}

/** Transform one non-fence line, skipping backtick-delimited code spans. */
function transformLine(line: string): string {
  if (!line.includes('EV:')) return line
  const parts = line.split('`')
  // Even indices are outside code spans; odd indices are inside them.
  let changed = false
  for (let i = 0; i < parts.length; i += 2) {
    const part = parts[i]
    if (part === undefined || !part.includes('EV:')) continue
    const replaced = part.replace(EV_ID_RE, match => `\`${match}\``)
    if (replaced !== part) {
      parts[i] = replaced
      changed = true
    }
  }
  return changed ? parts.join('`') : line
}
