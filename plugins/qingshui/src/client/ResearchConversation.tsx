/**
 * Research-shell occupant of the `conversation` slot (priority -1).
 * Same seat tree as ConversationRoot, minus the workspace chip and the
 * `hero && chipTitle === undefined` inert gate. Styles are plugin-local;
 * child slots (chat, input bar) keep their own shipped CSS.
 */
import { useCallback, useRef } from 'react'
import { researchComposerOwner, type ComposerBlockLike } from './conversation-owner.ts'

type Translate = (key: string) => string

type ResearchConversationProps = {
  sessionId: string | undefined
  useSession: <S>(select: (state: any) => S) => S
  useSessions: <S>(select: (state: any) => S) => S
  useInput: <S>(select: (state: any) => S) => S
  useComposerBlock: (select: (block: ComposerBlockLike | undefined) => ComposerBlockLike | undefined) => ComposerBlockLike | undefined
  renderSlot: (key: string, owner: object) => unknown
  renderSlotChain: (key: string, owner: object, opts: { fallback: unknown; overlay?: boolean }) => unknown
  t: Translate
}

/** Resident conversation column for a workspace-less research session. */
export function ResearchConversationRoot(props: ResearchConversationProps) {
  const {
    sessionId, useSession, useSessions, useInput, useComposerBlock,
    renderSlot, renderSlotChain, t,
  } = props
  if (typeof renderSlot !== 'function' || typeof renderSlotChain !== 'function') {
    throw new Error('qingshui: conversation shadow missing renderSlot (donor children were not grafted)')
  }

  const openState = useSession(s => s.openState)
  const composerPhase = useSession(s => s.composerPhase)
  const pending = useSession(s => s.pending) ?? []
  const session = useSession(s => s)
  const inputState = useInput(s => s)
  const summaryBlank = useSessions(s => sessionId === undefined ? undefined : s.byId[sessionId]?.blank)
  const composerBlock = useComposerBlock(block => block)

  const seatObserver = useRef<ResizeObserver | null>(null)
  const seatResizeRef = useCallback((seat: HTMLDivElement | null): void => {
    seatObserver.current?.disconnect()
    seatObserver.current = null
    const scroller = seat?.parentElement ?? null
    if (seat === null || scroller === null) return
    seatObserver.current = new ResizeObserver(() => {
      scroller.style.setProperty('--dsh-composer-height', `${seat.offsetHeight}px`)
    })
    seatObserver.current.observe(seat)
  }, [])

  const settling = sessionId !== undefined && composerPhase === 'blank' && openState === 'loading'
    && summaryBlank !== true
  const hero = sessionId === undefined
    || (composerPhase === 'blank' && (openState === 'open' || summaryBlank === true))
  const zone = session === undefined || inputState === undefined ? undefined : { session, input: inputState }

  const barOwner = researchComposerOwner({ sessionId, hero, composerBlock, t })
  const inputBar = renderSlot('conversation.composer.bar', {
    ...barOwner,
    overlay: renderSlot('conversation.input.overlay', {}),
    leftItems: zone === undefined ? null : renderSlot('conversation.input.left', zone),
    rightItems: zone === undefined ? null : renderSlot('conversation.input.right', zone),
    footer: !hero && zone !== undefined ? renderSlot('conversation.composer.dock', zone) : null,
  })

  const composerBar = (
    <div className={hero ? 'qs-conv-stack qs-conv-stack-hero' : 'qs-conv-stack'}>
      {zone !== undefined && renderSlot('conversation.input.dock', zone)}
      {inputBar}
    </div>
  )

  const phase = settling ? 'settling' : hero ? 'hero' : 'active'
  const composer = renderSlotChain(
    'conversation.composer',
    { interactions: pending, session },
    { fallback: composerBar, overlay: true },
  )

  return (
    <div className="qs-conv" data-phase={phase} data-qs-conversation="research">
      {renderSlot('conversation.session.header', {})}
      <div className="qs-conv-scroll" data-conversation-scroll="">
        {renderSlot('conversation.session', {})}
        <div ref={seatResizeRef} className="qs-conv-seat" data-composer-seat="">
          {composer}
        </div>
      </div>
    </div>
  )
}
