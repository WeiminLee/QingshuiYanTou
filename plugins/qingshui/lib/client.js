window.__ModuleLoader__.load({
	id: "qingshui",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react = require("react");
		let react_jsx_runtime = require("react/jsx-runtime");
		//#region src/client/session-actions.ts
		/**
		* Create a session with no workspaceId/cwd and open it.
		* @param sessions - client sessions service face
		* @returns the new session id
		*/
		async function createAndOpenSession(sessions) {
			const sessionId = await sessions.create({});
			sessions.open(sessionId);
			return sessionId;
		}
		//#endregion
		//#region src/client/SessionBrowser.tsx
		/** Flat research-session list for sidebar.workspaces (no workspace / path tree). */
		function SessionBrowser(props) {
			const { wide, expandSidebar, useSessions, t, createSession, openSession } = props;
			const list = useSessions((s) => s);
			const [busy, setBusy] = (0, react.useState)(false);
			const onNew = () => {
				if (busy) return;
				if (!wide) expandSidebar();
				setBusy(true);
				createSession().catch((error) => {
					console.warn("qingshui: new session failed", error);
				}).finally(() => {
					setBusy(false);
				});
			};
			if (!wide) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "qs-shell-rail",
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
					type: "button",
					className: "qs-shell-rail-btn",
					"aria-label": t("sessions.new"),
					onClick: onNew,
					disabled: busy,
					children: "+"
				})
			});
			const rows = list.ids.map((id) => list.byId[id]).filter((row) => row !== void 0).slice().sort((a, b) => b.updatedAt - a.updatedAt);
			return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "qs-shell",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "qs-shell-head",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "qs-shell-title",
						children: t("sessions.heading")
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						type: "button",
						className: "qs-shell-new",
						onClick: onNew,
						disabled: busy,
						children: t("sessions.new")
					})]
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "qs-shell-list",
					role: "list",
					children: rows.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "qs-shell-empty",
						children: t("sessions.empty")
					}) : rows.map((row) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						type: "button",
						role: "listitem",
						className: "qs-shell-row",
						"data-active": list.current === row.id ? "true" : "false",
						onClick: () => {
							openSession(row.id);
						},
						children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "qs-shell-row-title",
							children: row.displayTitle || row.title || t("sessions.untitled")
						})
					}, row.id))
				})]
			});
		}
		//#endregion
		//#region src/client/locales.ts
		const zh = {
			"sessions.heading": "投研会话",
			"sessions.new": "新建对话",
			"sessions.empty": "暂无会话",
			"sessions.untitled": "新对话"
		};
		const en = {
			"sessions.heading": "Research chats",
			"sessions.new": "New chat",
			"sessions.empty": "No chats yet",
			"sessions.untitled": "New chat"
		};
		//#endregion
		//#region src/client/theme.ts
		/** Minimal research-shell sidebar styles (dsh semantic tokens only). */
		const SHELL_CSS = `
.qs-shell { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 8px; padding: 0 8px 8px; }
.qs-shell-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 4px 0; }
.qs-shell-title { font: var(--dsw-font-xxs-12); font-weight: 600; color: var(--dsw-alias-label-secondary); }
.qs-shell-new { display: inline-flex; align-items: center; gap: 6px; border: none; border-radius: 6px; padding: 6px 8px; cursor: pointer; font: var(--dsw-font-xs-13); background: var(--dsw-alias-interactive-bg-hover); color: var(--dsw-alias-label-primary); }
.qs-shell-new:hover { background: var(--dsw-alias-interactive-bg-active, var(--dsw-alias-interactive-bg-hover)); }
.qs-shell-new:disabled { opacity: 0.5; cursor: default; }
.qs-shell-list { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
.qs-shell-row { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; border: none; border-radius: 6px; padding: 8px; cursor: pointer; font: var(--dsw-font-xs-13); background: transparent; color: var(--dsw-alias-label-primary); }
.qs-shell-row:hover { background: var(--dsw-alias-interactive-bg-hover); }
.qs-shell-row[data-active="true"] { background: var(--dsw-alias-interactive-bg-hover); font-weight: 600; }
.qs-shell-row-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qs-shell-empty { padding: 12px 4px; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); }
.qs-shell-rail { display: flex; flex-direction: column; align-items: center; gap: 8px; padding-top: 4px; }
.qs-shell-rail-btn { width: 32px; height: 32px; border: none; border-radius: 8px; cursor: pointer; background: transparent; color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xs-13); }
.qs-shell-rail-btn:hover { background: var(--dsw-alias-interactive-bg-hover); }

.qs-conv { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; flex: 1 1 auto; align-self: stretch; background: var(--dsw-alias-bg-base);
  --dsh-chat-content-width: 748px;
  --dsh-composer-card-max-width: calc(var(--dsh-chat-content-width) + 32px);
  --dsh-composer-side-clearance: 16px;
  --dsh-composer-dock-inset: 8px;
}
.qs-conv-scroll { display: flex; flex: 1; flex-direction: column; min-height: 0; overflow-x: hidden; overflow-y: auto; scrollbar-gutter: stable; }
/* Archive Home IA: composer pinned at bottom of the conversation pane
   (not vertically centered like stock dsh hero). */
.qs-conv[data-phase="hero"] .qs-conv-scroll { justify-content: flex-end; }
.qs-conv[data-phase="hero"] .qs-conv-seat,
.qs-conv[data-phase="active"] .qs-conv-seat {
  position: sticky; bottom: 0; z-index: 7;
  background: linear-gradient(180deg, color-mix(in srgb, var(--dsw-alias-bg-base) 0%, transparent) 0px, var(--dsw-alias-bg-base) 36px);
}
.qs-conv[data-phase="active"] { overflow: hidden; }
.qs-conv[data-phase="settling"] .qs-conv-seat { visibility: hidden; }
.qs-conv-seat { display: flex; flex: none; flex-direction: column; --dsh-composer-text-max-height: 336px; }
.qs-conv-stack { display: flex; flex-direction: column; gap: 6px; }
.qs-conv-stack-hero {
  position: relative; align-self: center; gap: 8px; padding-bottom: 16px; z-index: 1;
  width: min(calc(var(--dsh-composer-card-max-width) + 2 * var(--dsh-composer-side-clearance)), 100%);
}
`;
		const TAG_ID = "qingshui-shell";
		/** Idempotent style install; returns disposer. */
		function installClientStyles() {
			if (typeof document === "undefined") return () => void 0;
			let tag = document.querySelector(`style[data-plugin-css="${TAG_ID}"]`);
			if (tag === null) {
				tag = document.createElement("style");
				tag.setAttribute("data-plugin-css", TAG_ID);
				tag.textContent = SHELL_CSS;
				document.head.appendChild(tag);
			}
			return () => {
				tag?.remove();
			};
		}
		/**
		* The shipped conversation entry: it owns the children table. Not our shadow.
		* @param entries - raw ledger rows for `conversation`
		* @param shadowComponent - the research root component identity
		*/
		function donorConversationEntry(entries, shadowComponent) {
			return entries.find((entry) => entry.children !== void 0 && entry.component !== shadowComponent && (entry.options?.priority ?? 0) !== -1);
		}
		/**
		* Point the shadow entry at the donor's seats and inject face.
		* Mutates `entry` only. Caller must clear these before the shadow unloads,
		* or SlotCore.releaseEntry would collapse donor-declared child slots.
		* @param entry - the priority -1 registration
		* @param donor - the shipped conversation registration
		*/
		function graftConversationShadow(entry, donor) {
			entry.children = donor.children;
			if (donor.inject !== void 0) entry.inject = donor.inject;
		}
		/**
		* Drop grafted seats so shadow unload does not cascade-delete them.
		* @param entry - the priority -1 registration
		*/
		function ungraftConversationShadow(entry) {
			entry.children = void 0;
			entry.inject = void 0;
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
		function researchComposerOwner(opts) {
			const { sessionId, hero, composerBlock, t } = opts;
			const inert = sessionId === void 0;
			return {
				variant: hero ? "hero" : "composer",
				...inert ? {
					disabled: true,
					placeholder: t("placeholder.hero")
				} : !inert && composerBlock !== void 0 ? {
					blocked: composerBlock,
					placeholder: composerBlock.reason
				} : hero ? { placeholder: t("placeholder.hero") } : {}
			};
		}
		//#endregion
		//#region src/client/ResearchConversation.tsx
		/**
		* Research-shell occupant of the `conversation` slot (priority -1).
		* Same seat tree as ConversationRoot, minus the workspace chip and the
		* `hero && chipTitle === undefined` inert gate. Styles are plugin-local;
		* child slots (chat, input bar) keep their own shipped CSS.
		*/
		/** Resident conversation column for a workspace-less research session. */
		function ResearchConversationRoot(props) {
			const { sessionId, useSession, useSessions, useInput, useComposerBlock, renderSlot, renderSlotChain, t } = props;
			if (typeof renderSlot !== "function" || typeof renderSlotChain !== "function") throw new Error("qingshui: conversation shadow missing renderSlot (donor children were not grafted)");
			const openState = useSession((s) => s.openState);
			const composerPhase = useSession((s) => s.composerPhase);
			const pending = useSession((s) => s.pending) ?? [];
			const session = useSession((s) => s);
			const inputState = useInput((s) => s);
			const summaryBlank = useSessions((s) => sessionId === void 0 ? void 0 : s.byId[sessionId]?.blank);
			const composerBlock = useComposerBlock((block) => block);
			const seatObserver = (0, react.useRef)(null);
			const seatResizeRef = (0, react.useCallback)((seat) => {
				seatObserver.current?.disconnect();
				seatObserver.current = null;
				const scroller = seat?.parentElement ?? null;
				if (seat === null || scroller === null) return;
				seatObserver.current = new ResizeObserver(() => {
					scroller.style.setProperty("--dsh-composer-height", `${seat.offsetHeight}px`);
				});
				seatObserver.current.observe(seat);
			}, []);
			const settling = sessionId !== void 0 && composerPhase === "blank" && openState === "loading" && summaryBlank !== true;
			const hero = sessionId === void 0 || composerPhase === "blank" && (openState === "open" || summaryBlank === true);
			const zone = session === void 0 || inputState === void 0 ? void 0 : {
				session,
				input: inputState
			};
			const inputBar = renderSlot("conversation.composer.bar", {
				...researchComposerOwner({
					sessionId,
					hero,
					composerBlock,
					t
				}),
				overlay: renderSlot("conversation.input.overlay", {}),
				leftItems: zone === void 0 ? null : renderSlot("conversation.input.left", zone),
				rightItems: zone === void 0 ? null : renderSlot("conversation.input.right", zone),
				footer: !hero && zone !== void 0 ? renderSlot("conversation.composer.dock", zone) : null
			});
			const composerBar = /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: hero ? "qs-conv-stack qs-conv-stack-hero" : "qs-conv-stack",
				children: [zone !== void 0 && renderSlot("conversation.input.dock", zone), inputBar]
			});
			const phase = settling ? "settling" : hero ? "hero" : "active";
			const composer = renderSlotChain("conversation.composer", {
				interactions: pending,
				session
			}, {
				fallback: composerBar,
				overlay: true
			});
			return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "qs-conv",
				"data-phase": phase,
				"data-qs-conversation": "research",
				children: [renderSlot("conversation.session.header", {}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "qs-conv-scroll",
					"data-conversation-scroll": "",
					children: [renderSlot("conversation.session", {}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						ref: seatResizeRef,
						className: "qs-conv-seat",
						"data-composer-seat": "",
						children: composer
					})]
				})]
			});
		}
		//#endregion
		//#region src/client/conversation-shadow.ts
		/**
		* Occupy `conversation` at priority -1 once ui-conversation has registered
		* the shipped root. Lowest priority wins; children are grafted, not redeclared.
		*/
		/**
		* Install the research conversation shadow for the life of this fiber.
		* @param ctx - client root context
		* @returns disposer
		*/
		function installConversationShadow(ctx) {
			let shadow;
			let installing = false;
			let disposeReg;
			const install = () => {
				if (shadow !== void 0 || installing) return shadow !== void 0;
				const donor = donorConversationEntry(ctx.slots.entries("conversation"), ResearchConversationRoot);
				if (donor?.children === void 0) return false;
				installing = true;
				try {
					disposeReg = ctx.slots.register({
						name: "conversation",
						priority: -1,
						locale: "conversation"
					}, ResearchConversationRoot);
					shadow = ctx.slots.entries("conversation").find((entry) => entry.options?.priority === -1);
					if (shadow === void 0) {
						console.warn("qingshui: conversation shadow entry missing after register");
						return false;
					}
					graftConversationShadow(shadow, donor);
					return true;
				} catch (error) {
					console.warn("qingshui: conversation shadow failed", error);
					return false;
				} finally {
					installing = false;
				}
			};
			const offEvent = ctx.on?.("slots/changed", (key) => {
				if (key === "conversation") install();
			});
			const offSub = ctx.slots.subscribe("conversation", () => {
				install();
			});
			install();
			return () => {
				offEvent?.();
				offSub();
				if (shadow !== void 0) ungraftConversationShadow(shadow);
				disposeReg?.();
				shadow = void 0;
				disposeReg = void 0;
			};
		}
		//#endregion
		//#region src/client/index.ts
		/**
		* Qingshui research-shell browser half: flat session list in sidebar.workspaces,
		* cold-open / New chat → sessions.create({}) (no workspaceId).
		*/
		const NS = "qingshui-shell";
		/** Cordis inject: slots + sessions + workspaces + locale. */
		const inject = [
			"slots",
			"sessions",
			"workspaces",
			"locale"
		];
		/**
		* Install research-shell UI.
		* @param ctx - client root context (loosely typed; matches MatDiscovery client style)
		*/
		function apply(ctx) {
			ctx.effect(() => installClientStyles(), "qingshui: shell styles");
			ctx.effect(() => ctx.locale.register(NS, {
				zh,
				en
			}), "qingshui: shell dictionaries");
			const workspaces = ctx.workspaces;
			if (workspaces !== void 0 && typeof workspaces.startSession === "function") workspaces.startSession = (_workspaceId) => {
				createAndOpenSession(ctx.sessions).catch((error) => {
					console.warn("qingshui: startSession redirect failed", error);
				});
			};
			const createSession = () => createAndOpenSession(ctx.sessions);
			const openSession = (sessionId) => {
				ctx.sessions.open(sessionId);
			};
			ctx.effect(() => ctx.slots.inject("sidebar.workspaces", () => ctx.slots.register({
				name: "sidebar.workspaces",
				locale: NS,
				inject: () => ({
					createSession,
					openSession
				})
			}, SessionBrowser)), "qingshui: session browser");
			let bootstrapping = false;
			let bootstrapped = false;
			const maybeBootstrap = () => {
				if (bootstrapped || bootstrapping) return;
				const list = ctx.sessions.list.getSnapshot();
				if (list.phase !== "ready") return;
				if (list.current !== void 0) {
					bootstrapped = true;
					return;
				}
				bootstrapping = true;
				createAndOpenSession(ctx.sessions).then(() => {
					bootstrapped = true;
				}).catch((error) => {
					console.warn("qingshui: cold-open bootstrap failed", error);
				}).finally(() => {
					bootstrapping = false;
				});
			};
			ctx.effect(() => {
				maybeBootstrap();
				return ctx.sessions.list.subscribe(() => {
					maybeBootstrap();
				});
			}, "qingshui: cold-open bootstrap");
			ctx.effect(() => installConversationShadow(ctx), "qingshui: conversation shadow");
		}
		//#endregion
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});

//# sourceMappingURL=client.js.map