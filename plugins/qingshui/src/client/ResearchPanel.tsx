/**
 * ResearchPanel: persistent right rail in the research shell. Surfaces the
 * latest active 判断 (findings) above the pinned evidence detail, so current
 * conclusions are visible on the landing view without a separate page.
 * Hardcoded zh to match its shell siblings (SignalBoard / NewsTape /
 * QuoteStrip); the toolviews stay the i18n'd layer.
 */
import { useCallback, useEffect, useState } from 'react'
import { openEvidenceArtifact } from './artifact-store.ts'
import { closeEvPinned } from './ev-cite-store.ts'
import { EvBody } from './ev-cite-layer.tsx'
import {
  asFindingListPayload,
  findingKindLabel,
  findingStatusLabel,
  formatConfidence,
  formatDate,
  type FindingDoc,
} from './toolviews/model.ts'

type FindingsState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ok'; findings: FindingDoc[] }

export function ResearchPanel({ pinnedId }: { pinnedId: string | undefined }): React.ReactElement {
  const [state, setState] = useState<FindingsState>({ status: 'loading' })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })
    void fetch('/qingshui/ledger', { headers: { accept: 'application/json' } })
      .then(async (res) => {
        const body = (await res.json().catch(() => ({}))) as Record<string, unknown>
        if (!res.ok || body.ok !== true) throw new Error(String(body.error ?? `HTTP ${res.status}`))
        return asFindingListPayload(body)
      })
      .then((payload) => {
        if (cancelled) return
        if (payload === undefined) throw new Error('判断台账返回格式无法解析')
        setState({ status: 'ok', findings: payload.findings })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setState({ status: 'error', message: err instanceof Error ? err.message : '加载失败' })
      })
    return () => { cancelled = true }
  }, [nonce])

  const retry = useCallback(() => { setNonce(n => n + 1) }, [])

  return (
    <aside className="qs-panel" aria-label="研究面板">
      <div className="qs-panel-head">
        <span className="qs-panel-title">研究结论</span>
        <button type="button" className="qs-panel-refresh" onClick={retry}>刷新</button>
      </div>
      <div className="qs-panel-body">
        <section className="qs-panel-section">
          <h2 className="qs-panel-section-title">最新判断</h2>
          {state.status === 'loading' ? <div className="qs-panel-status">加载中…</div> : null}
          {state.status === 'error' ? (
            <div className="qs-panel-error">
              <div>{state.message}</div>
              <button type="button" className="qs-panel-refresh" onClick={retry}>重试</button>
            </div>
          ) : null}
          {state.status === 'ok' && state.findings.length === 0 ? (
            <div className="qs-panel-empty">暂无判断结论</div>
          ) : null}
          {state.status === 'ok' ? (
            state.findings.map(finding => <PanelFindingRow key={finding.finding_id} finding={finding} />)
          ) : null}
        </section>
        <section className="qs-panel-section">
          <div className="qs-panel-section-title">
            证据原文
            {pinnedId === undefined ? null : (
              <span className="qs-panel-section-actions">
                <button
                  type="button"
                  className="qs-panel-open"
                  onClick={() => { void openEvidenceArtifact(pinnedId) }}
                >
                  展开
                </button>
                <button type="button" className="qs-panel-close" aria-label="关闭" onClick={() => { closeEvPinned() }}>×</button>
              </span>
            )}
          </div>
          {pinnedId === undefined ? (
            <div className="qs-panel-empty">点击对话里的证据引用查看原文</div>
          ) : (
            <EvBody id={pinnedId} lines={12} />
          )}
        </section>
      </div>
    </aside>
  )
}

function PanelFindingRow({ finding }: { finding: FindingDoc }): React.ReactElement {
  const kindLabel = findingKindLabel(finding.kind)
  const statusLabel = findingStatusLabel(finding.status)
  const date = formatDate(finding.created_at)
  const confidence = formatConfidence(finding.confidence)
  const title = [finding.subject_ts_code, finding.dimension].filter(part => part !== '').join(' · ')
  const insufficient = finding.support_count < 2

  return (
    <article className="qs-finding" data-k={finding.kind} data-s={finding.status}>
      <div className="qs-finding-head">
        <span className="qs-finding-badge" data-k={finding.kind}>{kindLabel}</span>
        {statusLabel === '' ? null : <span className="qs-finding-badge" data-s={finding.status}>{statusLabel}</span>}
        {date === '' ? null : <span className="qs-finding-date">{date}</span>}
      </div>
      {title === '' ? null : <div className="qs-finding-title">{title}</div>}
      <div className="qs-finding-metrics">
        <div className="qs-finding-metric">
          <span className="qs-finding-metric-label">置信度</span>
          <span className="qs-finding-metric-value" data-tone={insufficient ? 'muted' : 'default'}>{confidence === '' ? '—' : confidence}</span>
        </div>
        <div className="qs-finding-metric">
          <span className="qs-finding-metric-label">证据锚点</span>
          <span className="qs-finding-metric-value" data-tone={insufficient ? 'warning' : 'default'}>{finding.support_count}</span>
        </div>
        <div className="qs-finding-metric">
          <span className="qs-finding-metric-label">证伪</span>
          <span className="qs-finding-metric-value" data-tone={finding.contradicts > 0 ? 'warning' : 'default'}>{finding.contradicts}</span>
        </div>
      </div>
      {insufficient ? <div className="qs-finding-note">证据锚点不足，置信度有限，请谨慎采信</div> : null}
      {finding.judgment === '' ? null : <div className="qs-finding-judgment">{finding.judgment}</div>}
    </article>
  )
}
