# Layouts — single research shell

One screen. No router. Desktop render (the live branch): left sidebar about 280px, main column is the conversation. Details column width is 0 and its content is `display: none`.

## Sidebar chrome

Owned by harness `dsh/packages/client/ui-sidebar/src/client/SidebarRoot.tsx`, occupied by our session list.

Visible order, top to bottom:

1. Brand row: ledger mark + 「清水投研」. Clicking the brand starts a new chat.
2. Full-width button 「新会话」.
3. Region `sidebar.workspaces`: heading 「投研会话」, then a flat list. Active row has a hover wash. Hover reveals ✎ rename and 🗄 archive (second click confirms).
4. Footer: gear 「设置」.

Collapsed rail is 56px: mark, new-chat icon, settings icon. Our list unmounts when narrow.

## Session list

Path: `plugins/qingshui/src/client/SessionBrowser.tsx`. Wide render:

```tsx
return (
  <div className="qs-shell">
    <div className="qs-shell-head">
      <span className="qs-shell-title">{t('sessions.heading')}</span>
    </div>
    <div className="qs-shell-list" role="list">
      {rows.map(row => (
        <div key={row.id} role="listitem" className="qs-shell-item" data-active={list.current === row.id ? 'true' : 'false'}>
          <button type="button" className="qs-shell-row">
            <span className="qs-shell-row-title">{row.title || '新对话'}</span>
          </button>
          <span className="qs-shell-item-actions">
            <button type="button" className="qs-shell-icon-btn">✎</button>
            <button type="button" className="qs-shell-icon-btn">🗄</button>
          </span>
        </div>
      ))}
    </div>
  </div>
)
```

## Conversation column

Path: `plugins/qingshui/src/client/ResearchConversation.tsx`. Blank session pins the composer at the bottom of an otherwise empty column. Placeholder: 「问一只股票、一条公告，或一个预期差」.

Active session: transcript scrolls, composer sticks to the bottom. Composer capsule, left to right: 「+」 (skills), model name 「GLM 5.3」, send arrow. Permission chip, context ring, token stats, and branch button are hidden.

```tsx
return (
  <div className="qs-conv" data-phase={phase} data-qs-conversation="research">
    {renderSlot('conversation.session.header', {})}
    <div className="qs-conv-scroll" data-conversation-scroll="">
      {renderSlot('conversation.session', {})}
      <div className="qs-conv-seat" data-composer-seat="">
        {composer}
      </div>
    </div>
    <EvCiteLayer />
  </div>
)
```

## Settings

Modal from the sidebar gear. Nav: 「通用设置」 (language, appearance) and 「模型」 (API keys, add provider). No plugins, no permission presets, no open-yaml button.
