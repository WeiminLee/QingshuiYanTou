/**
 * Register qingshui toolviews into the keyed tool.call.toolview slot.
 * Native tools are bare names; Data MCP twins are mcp__qingshui_data__-prefixed.
 */
import { KlineCard } from './kline-card.tsx'
import { EvidenceCard } from './evidence-card.tsx'
import { EvidenceListCard } from './evidence-list-card.tsx'
import { EvidenceTimeline } from './evidence-timeline.tsx'
import { installToolviewStyles } from './styles.ts'

const NS = 'qingshui-shell'
const SLOT = 'tool.call.toolview'

/** [card, tool keys] pairs; each key gets its own keyed registration. */
const TOOLVIEWS: ReadonlyArray<[unknown, readonly string[]]> = [
  [KlineCard, ['get_kline', 'mcp__qingshui_data__get_kline']],
  [EvidenceCard, ['fetch_evidence', 'mcp__qingshui_data__fetch_evidence']],
  [EvidenceListCard, ['semantic_search', 'mcp__qingshui_data__semantic_search']],
  [EvidenceTimeline, ['pull_history', 'mcp__qingshui_data__pull_history']],
]

/**
 * Install toolview styles + slot registrations.
 * @param ctx - client root context (loosely typed; matches plugin client style)
 */
export function registerToolviews(ctx: any): void {
  ctx.effect(() => installToolviewStyles(), 'qingshui: toolview styles')
  ctx.effect(
    () => ctx.slots.inject(SLOT, function* () {
      for (const [component, keys] of TOOLVIEWS) {
        for (const key of keys) {
          yield ctx.slots.register({ name: SLOT, key, locale: NS }, component)
        }
      }
    }),
    'qingshui: toolviews',
  )
}
