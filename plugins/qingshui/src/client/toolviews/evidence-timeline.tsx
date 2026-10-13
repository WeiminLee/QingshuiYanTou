/**
 * EvidenceTimeline: pull_history (native + MCP twin) — a vertical timeline of
 * evidence grouped by published day.
 */
import { IconListPenOutline16 } from '@deepseek-ai/dsh-client-ui-primitives'
import {
  CollapsibleText,
  ErrorBody,
  MonoId,
  RawFallback,
  SourceTypeBadge,
  TvCard,
  type QsToolviewProps,
  type TranslateFn,
} from './common.tsx'
import {
  asHistoryPayload,
  blockArgs,
  blockState,
  extractResultJson,
  groupHistoryByDate,
  isSettled,
  type HistoryItem,
} from './model.ts'

const MAX_KEYWORD_CHIPS = 6

function TimelineItem({ item, t }: { item: HistoryItem; t: TranslateFn }) {
  const keywords = item.matched_keywords
  const shown = keywords.slice(0, MAX_KEYWORD_CHIPS)
  const rest = keywords.length - shown.length
  return (
    <div className="qs-tl-item">
      <div className="qs-tv-row-head">
        <SourceTypeBadge sourceType={item.source_type} />
        <span className="qs-tv-row-title">{item.source_name}</span>
      </div>
      {shown.length === 0
        ? null
        : (
          <div className="qs-tv-tags">
            {shown.map(keyword => <span key={keyword} className="qs-tv-tag">{keyword}</span>)}
            {rest > 0 ? <span className="qs-tv-tag qs-tv-tag-kind">+{rest}</span> : null}
          </div>
        )}
      <CollapsibleText text={item.text_excerpt} lines={3} t={t} />
      <MonoId id={item.evidence_id} />
    </div>
  )
}

export function EvidenceTimeline({ block, t }: QsToolviewProps) {
  const state = blockState(block)
  const args = blockArgs(block)
  const subject = typeof args.subject === 'string' ? args.subject : ''

  if (state === 'running') {
    return (
      <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.history.title')} summary={subject} state={state}>
        <div className="qs-tv-loading">{t('tv.history.loading')}</div>
      </TvCard>
    )
  }
  if (state === 'error') {
    return (
      <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.history.title')} summary={subject} state={state}>
        <ErrorBody block={block} />
      </TvCard>
    )
  }

  const payload = isSettled(block) ? asHistoryPayload(extractResultJson(block)) : undefined
  if (payload === undefined) {
    return (
      <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.history.title')} summary={subject} state={state}>
        <RawFallback block={block} />
      </TvCard>
    )
  }
  if (payload.items.length === 0) {
    return (
      <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.history.title')} summary={subject} state={state}>
        <div className="qs-tv-empty">{t('tv.history.empty')}</div>
      </TvCard>
    )
  }
  const groups = groupHistoryByDate(payload.items)
  return (
    <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.history.title')} summary={subject} state={state}>
      <div className="qs-tl">
        {groups.map(group => (
          <div key={group.date} className="qs-tl-group">
            <div className="qs-tl-rail">
              <span className="qs-tl-dot" />
              <span className="qs-tl-line" />
            </div>
            <div className="qs-tl-content">
              <div className="qs-tl-date">{group.date}</div>
              {group.items.map((item, index) => (
                <TimelineItem key={item.evidence_id || String(index)} item={item} t={t} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </TvCard>
  )
}
