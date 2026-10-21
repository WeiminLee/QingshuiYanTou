/** Sidebar mark: a short ledger, not the harness fish. */
export function QingshuiBrandMark({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M7 9h10M7 12h10M7 15h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

/** Product name beside the mark. */
export function QingshuiBrandName() {
  return <span className="qs-brand-name">清水投研</span>
}
