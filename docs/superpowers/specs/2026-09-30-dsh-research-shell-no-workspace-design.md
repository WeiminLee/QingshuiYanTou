# Design: dsh 投研壳去工作区（entry + chrome）

**Date:** 2026-09-30  
**Status:** Approved  
**Branch:** `feat/dsh-research-shell-no-workspace`  
**Related:** `2026-09-29-dsh-agent-runtime-cutover-design.md`, `2026-06-15-qingshui-frontend-redesign.md`, `archive/frontend` (IA reference only)

## 0. Locked gates (Reviewer + Deepresearch)

1. **产品身份**：Qingshui ≠ coding agent。入口**禁止**工作区选择器；`host.listDirectory` 等 host FS API **不得**作为进壳门槛。公网 403 视为正确拒绝，**禁止**为修 UI 而对外开放本机目录 API。
2. **壳目标**：对照 `archive/frontend` 的投研壳 IA（会话侧栏 + 主对话区），在 **dsh web + `plugins/qingshui`** 上收口；不复活整棵 Vue FE，不抄 MatDiscovery。
3. **本波范围**：入口与 chrome（去 workspace、会话如何绑定、哪些 dsh 面板隐藏）。不动 Knowledge / tools / skill 契约；N2（TLS / 内网）另波。
4. **验收**：打开 → 进对话；全程 **零** `listDirectory`（及同类 host FS 浏览调用）。

## 1. Problem

当前云上 dsh web（nginx → `127.0.0.1:3080`）默认挂载 coding 壳：

- 无 workspace → `ConversationRoot` 将 composer 置 `inert`，空态 Hero 要求「选择工作区」。
- 选择路径走 `ui-workspace` + `directory-picker` → `host.listDirectory`。
- 公网 / 非信任 host FS 返回 **403**（正确姿态），用户卡死在入口。

根因是**产品模型错配**（工作区 / 目录），不是「403 坏了」。

## 2. Goals / Non-goals

### Goals

- 冷开与「新建对话」直接进入可输入的投研会话，无工作区 UI。
- 侧栏呈现「投研会话」列表（对话 id），风格对齐 `archive/frontend` Home IA（新建 / 最近 / 分组），不复活 Vue。
- Session 语义与 cwd 语义分离（见 §4）；cwd **不**在 UI 暴露。
- 本波可在 `plugins/qingshui`（+ 必要的 cordis patch）落地，尽量少改 dsh 上游。

### Non-goals（本波明确不做）

- 开放 / 放宽 `host.listDirectory`、`host.pickDirectory`、`host.openPath` 等 host FS API。
- 复活 `archive/frontend` Vue、或移植 MatDiscovery 壳。
- 改 Knowledge HTTP / tools / skill 契约、divergence-mining、Boyue 模型配置。
- N2 TLS / 内网收口。
- 完整视觉像素还原（色板 / 动画）；本波以 **IA + 去门槛** 为主，样式可迭代。
- 市场面板类旧 Sidebar（概念涨跌 / 龙头股 / 资讯）——不在本波。

## 3. Approaches（取舍）

| # | Approach | Pros | Cons | Verdict |
|---|----------|------|------|---------|
| **A** | Cordis **disable** `ui-workspace` + `directory-picker`；`plugins/qingshui` 增加 **client** 半边：占据 `sidebar.workspaces` 为扁平会话列表；冷开 / New chat → `sessions.create`（无 `workspaceId`）并打开 | 对齐门禁；不碰 host FS；改动面在插件 + patch；可回滚 | 需新建 client 包；`ConversationRoot` inert 逻辑靠「永远有 session」绕开 | **推荐** |
| B | Fork / patch dsh `ConversationRoot`：无 workspace 也不 inert | 直改门槛 | 上游债重；仍可能露出 workspace chrome | 不推荐（A 不够再考虑） |
| C | 预置隐藏 default workspace | 仍保留 workspace 实体；易再次触发目录流 | 与「无工作区概念」冲突 | **拒绝** |

**Decision:** Approach **A**.

## 4. Session / cwd 语义（无 workspace）

| Concept | Meaning | UI | Implementation stance |
|---------|---------|-----|------------------------|
| **Session** | 投研会话（对话 id） | 侧栏列表：新建 / 打开 / 重命名 / 归档（若 API 已有） | 使用现有 `sessions.*` API；`create` **省略** `workspaceId` / `cwd` |
| **cwd** | 插件 / Host 内部 scratch | **永不展示**（无 chip、无路径、无「打开目录」） | Wave1：**共用** Host 默认 cwd（`session.create` 省略 cwd → Host cwd，与现有 host sessions API 一致）。不按会话新建可见目录；若后续工具需要隔离，另波加「每会话私有 scratch」，仍不进 UI |
| **Workspace entity** | coding 产物 | 入口与 chrome **不出现** | cordis disable `ui-workspace`；不驱动入口 |

**关键路径差异（实现必须避开）：**

- 客户端 `startSession()` 在无 workspace 时只 `sessions.clear()` → 落到 inert Hero —— **禁止**作为 New chat 实现。
- 正确路径：冷开若无 active session → `sessions.create({})`（或等价）→ open；「新建对话」同理。

## 5. IA（对照 archive，落在 dsh）

参考：`archive/frontend/src/views/Home.vue`（及 `2026-06-15-qingshui-frontend-redesign.md`）。

```
┌─────────────┬──────────────────────────────┐
│ Brand       │                              │
│ 新建对话     │   Welcome / 消息流            │
│ 最近会话     │                              │
│ （可选分组）  │   Composer（始终可输入）        │
│             │                              │
│ footer 状态  │                              │
└─────────────┴──────────────────────────────┘
```

- **不做**旧 `Sidebar.vue` 市场仪表盘。
- 「知识」在本波 = 会话历史 + 既有 Knowledge **tools**（后端契约不变），不新增独立 Knowledge 路由页。
- Brand：可用现有 `ui-brand-official` 或 qingshui 轻量 occupant；不强制新视觉系统。

## 6. Hide / disable 清单（chrome）

基于 `dsh/packages/bundle/web-app/cordis.patch.yml` 客户侧名录（实现时以该文件为准核对）。

### Must disable（入口门槛）

- `ui-workspace`（含 WorkspacePicker / WorkspaceBrowser）
- `directory-picker`（及 browse / native picker 客户端自动挂载）
- 不占据 / 不渲染 `conversation.hero.workspace`（无「选择工作区」chip）

### Strong hide（coding chrome，非投研入口）

- `ui-goal`, `ui-plan`, `ui-jobs`, `ui-subagent`, `ui-workflow-run`, `ui-deliverables`, `ui-trajectory`
- `ui-reference` + host `file-reference-local`（路径 @ 引用）
- `ui-agent-preset`（Hero 预设选择器 —— Wave1 默认隐藏；若影响模型选择再评估）
- `ui-attachment`：Wave1 **默认隐藏**；若投研上传刚需，另开一小波，**仍禁止**依赖目录选择器进壳

### Keep（chat-first）

- `ui-layout`, `ui-sidebar`, `ui-conversation`, `ui-theme`, `ui-locale`
- `ui-model-selection`, `ui-tool`（工具结果呈现）
- `ui-settings*`（可后续再裁）
- Brand occupant

**说明：** 许多 **tools** 在 web patch 已 `disabled: true`；本波只动 **UI chrome / 挂载**，不改 tool / skill 契约。

## 7. `plugins/qingshui` 扩展点

今日插件为 **host-only**（`inject: ['tools','skills']`，`plugins/qingshui/src/index.ts`），无 client / slots。

本波新增（仍归属 `plugins/qingshui` 产品面，可不强制同目录物理拆分，但须可从 web profile 挂上）：

1. **cordis.patch**：disable §6 Must（及 Strong hide 中确认项）；确保不挂 directory-picker。
2. **client 贡献**：
   - 占据 `sidebar.workspaces`（或等价侧栏槽）：扁平「投研会话」列表 + 新建。
   - 启动钩子：无 active session → `sessions.create`（无 workspace）→ open。
   - 不调用 `host.listDirectory` / pickDirectory / openPath。

不修改 dsh submodule pin，除非 A 证明必须上游补丁（那时单开决策，本设计默认 **零上游 fork**）。

## 8. Acceptance（可测）

| # | Check | Pass |
|---|--------|------|
| A1 | 浏览器打开 dsh web（经现有 nginx basic auth） | 无工作区选择器 / Hero workspace chip |
| A2 | 冷开后 composer 可输入 | `sessionId` 已存在；非 inert |
| A3 | DevTools / 代理：打开 → 首屏交互 | **零** `POST/GET …/api/host.listDirectory`（及 pickDirectory） |
| A4 | 「新建对话」 | 新 session 打开，仍无 directory API |
| A5 | 侧栏 | 可见会话列表（至少一个新会话）；无目录树 / 路径 |
| A6 | 回归 | Knowledge tools / skills 仍可在会话内调用（契约未改）；不要求本波重跑硅片成稿 |

## 9. Out of scope / follow-ups

- N2：TLS 或内网，替代公网 HTTP + basic auth。
- 每会话私有 scratch cwd（仍不展示）。
- 附件上传、视觉像素级还原、市场面板。
- 若 A 受 `ConversationRoot` inert 硬编码阻挡：最小上游 PR 或 vendored patch（需另 Approve）。

## 10. Implementation sketch（Approve 后进 plan，非本波开工）

1. Spec Approve → `writing-plans` 出垂直切片 plan。
2. 实现 qingshui client + cordis disables → 本地 / 云 web profile 重建 → A1–A6。
3. Reviewer 对照本设计 + A1–A6 Approve。

