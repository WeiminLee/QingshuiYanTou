/**
 * Pure helpers for the research-shell conversation shadow.
 *
 * Cordis single slots: lowest `priority` wins (default 0). A second
 * registration must NOT redeclare children — SlotCore throws "already
 * declared". renderSlot is bound to the winning entry's own children table,
 * so the shadow copies the donor entry's children + inject references after
 * register. That is not a second declaration.
 */

export const CONVERSATION_SHADOW_PRIORITY = -1

export type LedgerEntry = {
  component?: unknown
  options?: { priority?: number }
  children?: Record<string, unknown>
  inject?: (...args: unknown[]) => unknown
}

export type ComposerBlockLike = { reason: string }

/**
 * The shipped conversation entry: it owns the children table. Not our shadow.
 * @param entries - raw ledger rows for `conversation`
 * @param shadowComponent - the research root component identity
 */
export function donorConversationEntry(
  entries: readonly LedgerEntry[],
  shadowComponent: unknown,
): LedgerEntry | undefined {
  return entries.find(entry =>
    entry.children !== undefined
    && entry.component !== shadowComponent
    && (entry.options?.priority ?? 0) !== CONVERSATION_SHADOW_PRIORITY)
}

/**
 * Point the shadow entry at the donor's seats and inject face.
 * Mutates `entry` only. Caller must clear these before the shadow unloads,
 * or SlotCore.releaseEntry would collapse donor-declared child slots.
 * @param entry - the priority -1 registration
 * @param donor - the shipped conversation registration
 */
export function graftConversationShadow(entry: LedgerEntry, donor: LedgerEntry): void {
  entry.children = donor.children
  if (donor.inject !== undefined) entry.inject = donor.inject
}

/**
 * Drop grafted seats so shadow unload does not cascade-delete them.
 * @param entry - the priority -1 registration
 */
export function ungraftConversationShadow(entry: LedgerEntry): void {
  entry.children = undefined
  entry.inject = undefined
}

/**
 * Owner share for `conversation.composer.bar` in the research shell.
 * Session presence is the only inert gate. Never passes workspace recovery
 * props: those render「选择工作区」and lock the textarea readOnly.
 * @param opts.sessionId - current session, if any
 * @param opts.hero - blank-session centered composer
 * @param opts.composerBlock - plugin block (model route), if raised
 * @param opts.t - conversation-namespace translator
 */
export function researchComposerOwner(opts: {
  sessionId: string | undefined
  hero: boolean
  composerBlock: ComposerBlockLike | undefined
  t: (key: string) => string
}): Record<string, unknown> {
  const { sessionId, hero, composerBlock, t } = opts
  const inert = sessionId === undefined
  const blocked = !inert && composerBlock !== undefined
  return {
    variant: hero ? 'hero' : 'composer',
    ...(inert
      ? { disabled: true, placeholder: t('placeholder.hero') }
      : blocked
        ? { blocked: composerBlock, placeholder: composerBlock.reason }
        : hero
          ? { placeholder: t('placeholder.hero') }
          : {}),
  }
}
