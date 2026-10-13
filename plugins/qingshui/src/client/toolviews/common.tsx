/** Shared presentational pieces for qingshui toolviews. */
import { useState, type ReactNode } from 'react'
import { StateDot } from '@deepseek-ai/dsh-client-ui-primitives'
import type { ToolviewBlock, ToolviewState } from './model.ts'
import { blockState, blockText, isSettled, sourceTypeLabel } from './model.ts'

export type TranslateFn = (key: string, params?: Record<string, unknown>) => string

/** Props the tool.call.toolview owner passes, plus the locale seat (declared at register). */
export interface QsToolviewProps {
  callId: string
  toolName: string
  block: ToolviewBlock
  cwd?: string | undefined
  home?: string | undefined
  openFile?: ((path: string) => void) | undefined
  inspect?: (() => void) | undefined
  t: TranslateFn
}

const DOT_STATE: Record<ToolviewState, 'ongoing' | 'done' | 'error'> = {
  running: 'ongoing',
  ok: 'done',
  error: 'error',
}

/** Card chrome: icon + title + summary header with a state dot, body below. */
export function TvCard({ icon, title, summary, state, children }: {
  icon?: ReactNode
  title: ReactNode
  summary?: ReactNode
  state: ToolviewState
  children?: ReactNode
}) {
  return (
    <div className="qs-tv" data-state={state}>
      <div className="qs-tv-head">
        {icon === undefined ? null : <span className="qs-tv-head-icon">{icon}</span>}
        <span className="qs-tv-title">{title}</span>
        {summary === undefined || summary === null || summary === ''
          ? null
          : <span className="qs-tv-summary">{summary}</span>}
        <StateDot state={DOT_STATE[state]} size={10} />
      </div>
      {children === undefined || children === null ? null : <div className="qs-tv-body">{children}</div>}
    </div>
  )
}

/** source_type chip; unknown values render with the neutral style. */
export function SourceTypeBadge({ sourceType }: { sourceType: string | undefined }) {
  const known = sourceType !== undefined && sourceType !== ''
  return (
    <span className="qs-tv-badge" data-t={known ? sourceType : 'unknown'}>
      {sourceTypeLabel(sourceType)}
    </span>
  )
}

/** evidence_id in mono, small. */
export function MonoId({ id }: { id: string }) {
  if (id === '') return null
  return <span className="qs-tv-mono">{id}</span>
}

/** Long text collapsed to `lines` with a 展开/收起 toggle. */
export function CollapsibleText({ text, lines, t }: { text: string; lines: number; t: TranslateFn }) {
  const [open, setOpen] = useState(false)
  if (text === '') return null
  return (
    <>
      <div
        className="qs-tv-text"
        data-collapsed={!open || undefined}
        style={open ? undefined : { WebkitLineClamp: lines }}
      >
        {text}
      </div>
      <button type="button" className="qs-tv-toggle" onClick={() => { setOpen(!open) }}>
        {open ? t('tv.collapse') : t('tv.expand')}
      </button>
    </>
  )
}

/** Parse-failure / non-JSON fallback: the flattened result text, scrollable. */
export function RawFallback({ block }: { block: ToolviewBlock }) {
  if (!isSettled(block)) return null
  return <pre className="qs-tv-raw">{blockText(block)}</pre>
}

/** One-line error body from the settled block. */
export function ErrorBody({ block }: { block: ToolviewBlock }) {
  if (!isSettled(block)) return null
  const text = blockText(block)
  const firstLine = text.split('\n', 1)[0] ?? ''
  return <div className="qs-tv-error">{firstLine === '' ? `${block.error?.name ?? 'Error'}: ${block.error?.code ?? 'unknown'}` : firstLine}</div>
}

export { blockState, isSettled }
