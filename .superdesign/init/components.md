# Shared UI — 清水投研 research shell

Framework: React 18, no Next/Vite app of our own. The product surface is a Cordis client plugin (`plugins/qingshui`) mounted inside DeepSeek harness web (`dsh`). Component library: `@deepseek-ai/dsh-client-ui-primitives` (external; not forked). CSS: plugin-injected vanilla CSS in `plugins/qingshui/src/client/theme.ts`, plus harness CSS modules. No Tailwind in the product shell.

The primitives we own are below. Harness buttons, menus, and the composer capsule stay in `dsh/packages/client` and are not copied here.

## QingshuiBrandMark / QingshuiBrandName

- Path: `plugins/qingshui/src/client/Brand.tsx`
- Sidebar mark (ledger outline) and the product name 清水投研.

```tsx
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
```

## EvidenceCard

- Path: `plugins/qingshui/src/client/toolviews/evidence-card.tsx`
- Settled tool card: title, source badge, date, excerpt, PDF link, evidence id.
- Props: `block`, `t`.

The render branch for a settled document:

```tsx
return (
  <TvCard icon={<IconBrowseOutline16 size={14} />} title={t('tv.evidence.title')} summary={doc.evidence_id} state={state}>
    <div className="qs-tv-doc-title">{title}</div>
    <div className="qs-tv-meta">
      <SourceTypeBadge sourceType={doc.source_type} />
      {meta.map(part => <span key={part}>{part}</span>)}
      <span>{doc.ts_code}</span>
    </div>
    <CollapsibleText text={doc.text_excerpt} lines={6} t={t} />
    <a className="qs-tv-link" href={doc.pdf_url}>{t('tv.evidence.pdf')}</a>
    <MonoId id={doc.evidence_id} />
  </TvCard>
)
```
