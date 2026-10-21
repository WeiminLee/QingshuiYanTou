/**
 * FindingCard: 判断台账 toolview for history_findings / search_findings
 * (native + MCP twin). Renders ledger findings as 预期差 cards — kind badge +
 * subject×dimension, honest confidence + 样本量(support_count) + 证伪(contradicts),
 * the judgment conclusion, and an anchor/supersedes footer. No buy/sell slots:
 * this is a research conclusion, not a trade signal.
 */
import { IconListPenOutline16 } from '@deepseek-ai/dsh-client-ui-primitives'
import {
  ErrorBody,
  MonoId,
  RawFallback,
  TvCard,
  type QsToolviewProps,
  type TranslateFn,
} from './common.tsx'
import {
  asFindingListPayload,
  blockState,
  extractResultJson,
  findingKindLabel,
  findingStatusLabel,
  formatConfidence,
  formatDate,
  isSettled,
  type FindingDoc,
} from './model.ts'

function FindingRow({ finding, t }: { finding: FindingDoc; t: TranslateFn }) {
  const confidence = formatConfidence(finding.confidence)
  const kindLabel = findingKindLabel(finding.kind)
  const statusLabel = findingStatusLabel(finding.status)
  const scope = finding.dimension_scope ?? ''
  const date = formatDate(finding.created_at)
  const insufficient = finding.support_count < 2
  const title = [finding.subject_ts_code, finding.dimension]
    .filter((part) => part !== '')
    .join(' · ')

  return (
    <article className="qs-finding" data-k={finding.kind} data-s={finding.status}>
      <div className="qs-finding-head">
        <span className="qs-finding-badge" data-k={finding.kind}>{kindLabel}</span>
        {statusLabel === '' ? null : (
          <span className="qs-finding-badge" data-s={finding.status}>{statusLabel}</span>
        )}
        {scope === '' ? null : <span className="qs-finding-scope">{scope}</span>}
        {date === '' ? null : <span className="qs-finding-date">{date}</span>}
      </div>

      <div className="qs-finding-title">
        {title === '' ? t('tv.finding.untitled') : title}
      </div>

      <div className="qs-finding-metrics">
        <div className="qs-finding-metric">
          <span className="qs-finding-metric-label">{t('tv.finding.confidence')}</span>
          <span className="qs-finding-metric-value" data-tone={insufficient ? 'muted' : 'default'}>
            {confidence === '' ? '—' : confidence}
          </span>
        </div>
        <div className="qs-finding-metric">
          <span className="qs-finding-metric-label">{t('tv.finding.supportCount')}</span>
          <span className="qs-finding-metric-value" data-tone={insufficient ? 'warning' : 'default'}>
            {finding.support_count}
          </span>
        </div>
        <div className="qs-finding-metric">
          <span className="qs-finding-metric-label">{t('tv.finding.contradicts')}</span>
          <span className="qs-finding-metric-value" data-tone={finding.contradicts > 0 ? 'warning' : 'default'}>
            {finding.contradicts}
          </span>
        </div>
      </div>

      {insufficient ? (
        <div className="qs-finding-note">{t('tv.finding.insufficient')}</div>
      ) : null}

      {finding.judgment === '' ? null : (
        <div className="qs-finding-judgment">{finding.judgment}</div>
      )}

      <div className="qs-finding-foot">
        <MonoId id={finding.finding_id} />
        {finding.supersedes === undefined || finding.supersedes === '' ? null : (
          <span className="qs-finding-supersedes">
            {t('tv.finding.supersedes')} {finding.supersedes}
          </span>
        )}
      </div>
    </article>
  )
}

export function FindingCard({ block, t }: QsToolviewProps) {
  const state = blockState(block)

  if (state === 'running') {
    return (
      <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.finding.title')} state={state}>
        <div className="qs-tv-loading">{t('tv.finding.loading')}</div>
      </TvCard>
    )
  }
  if (state === 'error') {
    return (
      <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.finding.title')} state={state}>
        <ErrorBody block={block} />
      </TvCard>
    )
  }

  const payload = isSettled(block) ? asFindingListPayload(extractResultJson(block)) : undefined
  if (payload === undefined) {
    return (
      <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.finding.title')} state={state}>
        <RawFallback block={block} />
      </TvCard>
    )
  }

  if (payload.findings.length === 0) {
    return (
      <TvCard icon={<IconListPenOutline16 size={14} />} title={t('tv.finding.title')} state={state}>
        <div className="qs-tv-empty">{t('tv.finding.empty')}</div>
      </TvCard>
    )
  }

  const summary = payload.observationCount > 0
    ? t('tv.finding.summary', { observations: payload.observationCount, findings: payload.findings.length })
    : t('tv.finding.summaryFindings', { findings: payload.findings.length })

  return (
    <TvCard
      icon={<IconListPenOutline16 size={14} />}
      title={t('tv.finding.title')}
      summary={summary}
      state={state}
    >
      {payload.findings.map((finding) => (
        <FindingRow key={finding.finding_id} finding={finding} t={t} />
      ))}
    </TvCard>
  )
}
