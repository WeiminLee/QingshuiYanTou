/**
 * EvidenceCard: single-evidence toolview for fetch_evidence (native + MCP twin).
 * The native tool's text render is a formatted string (not JSON), so the doc
 * arrives via block.meta (presentationMeta); the MCP twin's text is JSON.
 */
import { IconBrowseOutline16, IconRightUpOutline14 } from '@deepseek-ai/dsh-client-ui-primitives'
import {
  CollapsibleText,
  ErrorBody,
  MonoId,
  RawFallback,
  SourceTypeBadge,
  TvCard,
  type QsToolviewProps,
} from './common.tsx'
import {
  asEvidenceDoc,
  blockArgs,
  blockState,
  extractResultJson,
  formatDate,
  isSettled,
} from './model.ts'

export function EvidenceCard({ block, t }: QsToolviewProps) {
  const state = blockState(block)
  const args = blockArgs(block)
  const argId = typeof args.evidence_id === 'string' ? args.evidence_id : ''

  if (state === 'running') {
    return (
      <TvCard icon={<IconBrowseOutline16 size={14} />} title={t('tv.evidence.title')} state={state}>
        <div className="qs-tv-loading">{t('tv.evidence.loading', { evidence_id: argId })}</div>
      </TvCard>
    )
  }
  if (state === 'error') {
    return (
      <TvCard icon={<IconBrowseOutline16 size={14} />} title={t('tv.evidence.title')} state={state}>
        <ErrorBody block={block} />
      </TvCard>
    )
  }

  const doc = isSettled(block) ? asEvidenceDoc(extractResultJson(block)) : undefined
  if (doc === undefined) {
    return (
      <TvCard icon={<IconBrowseOutline16 size={14} />} title={t('tv.evidence.title')} state={state}>
        <RawFallback block={block} />
      </TvCard>
    )
  }

  const title = doc.title ?? doc.source_name
  const meta: string[] = []
  if (doc.source_name !== '' && doc.source_name !== title) meta.push(doc.source_name)
  const date = formatDate(doc.publish_date)
  if (date !== '') meta.push(date)
  return (
    <TvCard icon={<IconBrowseOutline16 size={14} />} title={t('tv.evidence.title')} summary={doc.evidence_id} state={state}>
      <div className="qs-tv-doc-title">{title}</div>
      <div className="qs-tv-meta">
        <SourceTypeBadge sourceType={doc.source_type} />
        {meta.map(part => <span key={part}>{part}</span>)}
        {doc.confidence === undefined
          ? null
          : <span>{t('tv.evidence.confidence', { value: doc.confidence.toFixed(2) })}</span>}
        {doc.ts_code === undefined ? null : <span>{doc.ts_code}</span>}
      </div>
      <CollapsibleText text={doc.text_excerpt} lines={6} t={t} />
      {doc.pdf_url === undefined
        ? null
        : (
          <a className="qs-tv-link" href={doc.pdf_url} target="_blank" rel="noreferrer">
            {t('tv.evidence.pdf')}
            <IconRightUpOutline14 size={12} />
          </a>
        )}
      <MonoId id={doc.evidence_id} />
    </TvCard>
  )
}
