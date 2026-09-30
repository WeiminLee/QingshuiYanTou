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
		}
		//#endregion
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});

//# sourceMappingURL=client.js.map