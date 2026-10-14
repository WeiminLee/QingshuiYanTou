/**
 * Qingshui shadow of the keyed `conversation.chat.node` entry 'assistant-step'
 * (priority -1, same election mechanism as the conversation root shadow).
 * Behavior matches ui-conversation's AssistantNodeView/AssistantMarkdown —
 * reasoning as the Think disclosure row, images through the attachment slot,
 * JSON fallback for unknown blocks — with one addition: plain-text EV:
 * citations are promoted to interactive evidence chips (hover preview, click
 * to pin) while stock produced-file mentions keep first claim on tokens.
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  DisclosureRow, IconThinkOutline14, JsonBlock, MarkdownText,
} from '@deepseek-ai/dsh-client-ui-primitives'
import { evCiteTransform, evIdOf } from './ev-cite.ts'
import { useEvHoverDelegation } from './ev-cite-layer.tsx'
import { pinEvEvidence } from './ev-cite-store.ts'

type Translate = (key: string, params?: Record<string, unknown>) => string

/** Loose mirrors of the runtime's assistant-step node shapes. */
type AssistantBlockLike =
  | { kind: 'text'; text: string }
  | { kind: 'reasoning'; text: string }
  | { kind: 'image'; attachment: never }
  | { kind: 'tool-call' }
  | { kind: string; block?: unknown }

type AssistantStepNode = {
  kind: 'assistant-step'
  data: {
    blocks: readonly AssistantBlockLike[]
    status: 'running' | 'settled' | 'interrupted' | string
    finalNode?: { seq: number } | undefined
  }
  location:
    | { kind: 'turn' | 'step'; turn: { status?: string } }
    | { kind: string; turn?: undefined }
}

export type QsAssistantStepProps = {
  node: AssistantStepNode
  useTurnData: (key: string) => { closing?: { finalNode?: { seq: number } } | undefined } | undefined
  openFile: (path: string) => void
  renderMessageImages: (input: { images: Array<{ attachment: unknown }>; align: string }) => ReactNode
  fileMentions?: ((owner: { turn: unknown; seq: number; openFile: (path: string) => void }) =>
    MarkdownMentionsLike | undefined) | undefined
  t: Translate
}

/** Same face as ui-primitives' MarkdownFileMentions; kept structural. */
export interface MarkdownMentionsLike {
  resolve(value: string): { open: () => void; label: string; title: string } | undefined
}

const EV_MENTION_TITLE = ''

function evMentions(): MarkdownMentionsLike {
  return {
    resolve(value: string) {
      const id = evIdOf(value)
      if (id === undefined) return undefined
      return {
        open: () => { pinEvEvidence(id) },
        label: `查看证据 ${id}`,
        title: EV_MENTION_TITLE,
      }
    },
  }
}

/** File mentions first, EV chips as the fallback vocabulary. */
function mergeMentions(base: MarkdownMentionsLike | undefined, ev: MarkdownMentionsLike): MarkdownMentionsLike {
  if (base === undefined) return ev
  return {
    resolve(value: string) {
      return base.resolve(value) ?? ev.resolve(value)
    },
  }
}

/** Streaming, settled, and interrupted Assistant states share one keyed renderer instance. */
export const QsAssistantStepView = memo(function QsAssistantStepView({
  node, useTurnData, openFile, renderMessageImages, fileMentions, t,
}: QsAssistantStepProps) {
  const data = node.data
  const turn = node.location.kind === 'turn' || node.location.kind === 'step'
    ? node.location.turn
    : undefined
  const tail = useTurnData('turn-tail')
  const owner = useMemo<{ turn: unknown; seq: number; openFile: (path: string) => void } | undefined>(() => {
    if (turn?.status !== 'closed' || data.finalNode === undefined) return undefined
    if (tail?.closing?.finalNode?.seq !== data.finalNode.seq) return undefined
    return { turn, seq: data.finalNode.seq, openFile }
  }, [data.finalNode, openFile, tail, turn])
  const stockMentions = useMemo(
    () => owner === undefined || fileMentions === undefined ? undefined : fileMentions(owner),
    [fileMentions, owner],
  )
  const mentions = useMemo(() => mergeMentions(stockMentions, evMentions()), [stockMentions])
  const hover = useEvHoverDelegation()
  return (
    <div className="qs-qa-wrap" onMouseOver={hover.onMouseOver} onMouseOut={hover.onMouseOut}>
      <QsAssistantMarkdown
        blocks={data.blocks}
        streaming={data.status === 'running'}
        interrupted={data.status === 'interrupted'}
        renderMessageImages={renderMessageImages}
        mentions={mentions}
        t={t}
      />
    </div>
  )
})

interface QsAssistantMarkdownProps {
  blocks: readonly AssistantBlockLike[]
  streaming: boolean
  interrupted?: boolean | undefined
  renderMessageImages: QsAssistantStepProps['renderMessageImages']
  mentions?: MarkdownMentionsLike | undefined
  t: Translate
}

/** Mirrors ui-conversation's AssistantMarkdown with the EV citation transform. */
export const QsAssistantMarkdown = memo(function QsAssistantMarkdown({
  blocks, streaming, interrupted, renderMessageImages, mentions, t,
}: QsAssistantMarkdownProps) {
  const codeLabels = useMemo(() => ({ copyLabel: t('copy'), copiedLabel: t('copied') }), [t])
  const last = blocks.length - 1
  const hasVisible = streaming
    || interrupted === true
    || blocks.some(block => block.kind !== 'tool-call')
  if (!hasVisible) return null
  const rendered: ReactNode[] = []
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i]
    if (block === undefined) continue
    switch (block.kind) {
      case 'text':
        rendered.push(
          <MarkdownText
            key={i}
            text={evCiteTransform(block.text)}
            streaming={streaming}
            codeLabels={codeLabels}
            fileMentions={mentions}
          />,
        )
        break
      case 'reasoning':
        rendered.push(<QsReasoningRow key={i} text={block.text} running={streaming && i === last} t={t} />)
        break
      case 'image': {
        const start = i
        const group = [block]
        while (i + 1 < blocks.length) {
          const next = blocks[i + 1]
          if (next === undefined || next.kind !== 'image') break
          group.push(next)
          i += 1
        }
        rendered.push(
          <div key={start} className="qs-qa-images">
            {renderMessageImages({
              images: group.map(({ attachment }) => ({ attachment })),
              align: 'start',
            })}
          </div>,
        )
        break
      }
      case 'tool-call':
        break
      default:
        rendered.push(
          <JsonBlock
            key={i}
            label={t('message.unknownBlock')}
            payload={(block as { block?: unknown }).block}
            truncatedLabel={total => t('json.truncated', { total })}
          />,
        )
  }
  }
  return (
    <div className="qs-qa-root" data-streaming={streaming || undefined}>
      <div className="qs-qa-body">
        {rendered}
        {interrupted && <span className="qs-qa-stopped">{t('message.stopped')}</span>}
      </div>
    </div>
  )
})

/** Think disclosure row, a plugin-styled mirror of ui-conversation's ReasoningRow. */
export function QsReasoningRow({ text, running, t }: { text: string; running: boolean; t: Translate }) {
  const [expanded, setExpanded] = useState(false)
  const summaryRef = useRef<HTMLSpanElement | null>(null)
  const frameRef = useRef<number | null>(null)
  const summary = running ? latestLine(text) : firstLine(text)

  useEffect(() => {
    const schedule = (): void => {
      if (frameRef.current !== null) return
      let remaining = 3
      const advance = (): void => {
        remaining -= 1
        if (remaining > 0) {
          frameRef.current = requestAnimationFrame(advance)
          return
        }
        frameRef.current = null
        const element = summaryRef.current
        if (element === null) return
        element.scrollLeft = running ? element.scrollWidth - element.clientWidth : 0
      }
      frameRef.current = requestAnimationFrame(advance)
    }
    schedule()
    return () => {
      if (frameRef.current === null) return
      cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }, [running, summary])

  const onToggle = useCallback(() => { setExpanded(value => !value) }, [])

  return (
    <div className="qs-think" data-state={running ? 'running' : 'ok'}>
      {running && <span className="qs-visually-hidden">{t('row.running')}</span>}
      <DisclosureRow
        rowClassName="qs-think-row"
        leadingClassName="qs-think-leading"
        titleClassName="qs-think-title"
        chevronClassName="qs-think-chevron"
        icon={<IconThinkOutline14 size={14} />}
        title="Think"
        open={expanded}
        expandable
        expandOnRowClick
        onToggle={onToggle}
        collapsedContent={(
          <>
            <span className="qs-think-sep" aria-hidden />
            <span ref={summaryRef} className="qs-think-summary" data-follow-end={running || undefined}>{summary}</span>
          </>
        )}
      >
        <div className="qs-think-body">{text}</div>
      </DisclosureRow>
    </div>
  )
}

function firstLine(text: string): string {
  const newline = text.indexOf('\n')
  return newline === -1 ? text : text.slice(0, newline)
}

function latestLine(text: string): string {
  const visible = text.trimEnd()
  const newline = visible.lastIndexOf('\n')
  return newline === -1 ? visible : visible.slice(newline + 1)
}
