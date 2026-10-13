/**
 * EvidenceListCard: semantic_search (native + MCP twin) — evidence chunk rows
 * plus a compact related-entity tag row.
 */
import { IconSearchOutline16 } from '@deepseek-ai/dsh-client-ui-primitives'
import {
  ErrorBody,
  MonoId,
  RawFallback,
  SourceTypeBadge,
  TvCard,
  type QsToolviewProps,
} from './common.tsx'
import {
  asSearchResult,
  blockArgs,
  blockState,
  extractResultJson,
  formatDate,
  isSettled,
  type SearchChunk,
} from './model.ts'

function ChunkRow({ chunk }: { chunk: SearchChunk }) {
  const title = chunk.title ?? chunk.source_name
  const date = formatDate(chunk.publish_date)
  return (
    <div className="qs-tv-row">
      <div className="qs-tv-row-head">
        <SourceTypeBadge sourceType={chunk.source_type} />
        <span className="qs-tv-row-title">{title}</span>
        {date === '' ? null : <span className="qs-tv-row-date">{date}</span>}
        {chunk.score === undefined
          ? null
          : <span className="qs-tv-row-score">{chunk.score.toFixed(3)}</span>}
      </div>
      {chunk.snippet === '' ? null : <div className="qs-tv-snippet">{chunk.snippet}</div>}
      <MonoId id={chunk.evidence_id} />
    </div>
  )
}

export function EvidenceListCard({ block, t }: QsToolviewProps) {
  const state = blockState(block)
  const args = blockArgs(block)
  const query = typeof args.query === 'string' ? args.query : ''

  if (state === 'running') {
    return (
      <TvCard icon={<IconSearchOutline16 size={14} />} title={t('tv.search.title')} summary={query} state={state}>
        <div className="qs-tv-loading">{t('tv.search.loading', { query })}</div>
      </TvCard>
    )
  }
  if (state === 'error') {
    return (
      <TvCard icon={<IconSearchOutline16 size={14} />} title={t('tv.search.title')} summary={query} state={state}>
        <ErrorBody block={block} />
      </TvCard>
    )
  }

  const result = isSettled(block) ? asSearchResult(extractResultJson(block)) : undefined
  if (result === undefined) {
    return (
      <TvCard icon={<IconSearchOutline16 size={14} />} title={t('tv.search.title')} summary={query} state={state}>
        <RawFallback block={block} />
      </TvCard>
    )
  }
  if (result.entities.length === 0 && result.chunks.length === 0) {
    return (
      <TvCard icon={<IconSearchOutline16 size={14} />} title={t('tv.search.title')} summary={query} state={state}>
        <div className="qs-tv-empty">{t('tv.search.empty')}</div>
      </TvCard>
    )
  }
  return (
    <TvCard icon={<IconSearchOutline16 size={14} />} title={t('tv.search.title')} summary={query} state={state}>
      {result.entities.length === 0
        ? null
        : (
          <>
            <div className="qs-tv-section">{t('tv.search.entities')}</div>
            <div className="qs-tv-tags">
              {result.entities.map(entity => (
                <span key={entity.entity_id || entity.name} className="qs-tv-tag">
                  {entity.name}
                  {entity.type === '' ? null : <span className="qs-tv-tag-kind">{entity.type}</span>}
                  {entity.ts_code === undefined || entity.ts_code === ''
                    ? null
                    : <span className="qs-tv-tag-kind">{entity.ts_code}</span>}
                </span>
              ))}
            </div>
          </>
        )}
      {result.chunks.length === 0
        ? null
        : (
          <>
            <div className="qs-tv-section">{t('tv.search.chunks')}</div>
            <div>
              {result.chunks.map((chunk, index) => (
                <ChunkRow key={chunk.evidence_id || String(index)} chunk={chunk} />
              ))}
            </div>
          </>
        )}
    </TvCard>
  )
}
