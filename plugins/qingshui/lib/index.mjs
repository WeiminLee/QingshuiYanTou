import { existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import * as skillFilesystem from "@deepseek-ai/dsh-skill-filesystem";
import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
//#region src/config.ts
const Config = z.object({
	knowledgeBaseUrl: z.string().default("http://127.0.0.1:8080"),
	knowledgeApiKeyRef: z.string().default("KNOWLEDGE_API_KEY"),
	mcpBaseUrl: z.string().default("http://127.0.0.1:8100/mcp"),
	requestTimeoutMs: z.number().default(12e4),
	toolCallTimeoutMs: z.number().default(12e4)
});
//#endregion
//#region src/knowledge-client.ts
function createKnowledgeClient(options) {
	const base = options.baseUrl.replace(/\/$/, "");
	const fetchImpl = options.fetchImpl ?? fetch;
	async function request(path, init) {
		const ctrl = new AbortController();
		const timer = setTimeout(() => ctrl.abort(), options.timeoutMs);
		try {
			const res = await fetchImpl(`${base}${path}`, {
				...init,
				signal: ctrl.signal,
				headers: {
					"Content-Type": "application/json",
					"X-API-Key": options.apiKey,
					...init.headers ?? {}
				}
			});
			if (!res.ok) {
				const text = await res.text().catch(() => "");
				throw new Error(`Knowledge API ${res.status}: ${text.slice(0, 200)}`);
			}
			return await res.json();
		} finally {
			clearTimeout(timer);
		}
	}
	const post = (path, body) => request(path, {
		method: "POST",
		body: JSON.stringify(body)
	});
	const get = (path, params) => {
		return request(`${path}${params === void 0 ? "" : `?${new URLSearchParams(params).toString()}`}`, { method: "GET" });
	};
	return {
		semanticSearch(input) {
			return post("/api/v1/knowledge/search/semantic", {
				query: input.query,
				scope: input.scope ?? "entities",
				ts_code: input.ts_code ?? null,
				top_k: input.top_k ?? 5
			});
		},
		fetchEvidence(evidenceId) {
			return request(`/api/v1/knowledge/evidence/${encodeURIComponent(evidenceId)}`, { method: "GET" });
		},
		compareMetric(input) {
			return post("/api/v1/knowledge/agent/compare_metric", {
				dimension: input.dimension,
				scope: input.scope ?? null,
				as_of: input.as_of ?? null,
				top_k: input.top_k ?? 30
			});
		},
		metricTrend(input) {
			return post("/api/v1/knowledge/agent/metric_trend", {
				subject: input.subject,
				dimension: input.dimension ?? null,
				limit: input.limit ?? 50
			});
		},
		rollupMetric(input) {
			return post("/api/v1/knowledge/agent/rollup_metric", {
				parent: input.parent,
				scope: input.scope ?? null,
				top_k: input.top_k ?? 30
			});
		},
		relatedNodes(input) {
			return post("/api/v1/knowledge/agent/related_nodes", {
				keyword: input.keyword,
				layer: input.layer ?? null,
				top_k: input.top_k ?? 20
			});
		},
		propagateAlong(input) {
			return post("/api/v1/knowledge/agent/propagate_along", {
				start: input.start,
				max_hops: input.max_hops ?? 1,
				min_cooccur: input.min_cooccur ?? 5,
				top_k: input.top_k ?? 20
			});
		},
		getKline(input) {
			return get("/api/v1/knowledge/market/kline", {
				ts_code: input.ts_code,
				start_date: input.start_date ?? "",
				end_date: input.end_date ?? "",
				freq: input.freq ?? "D"
			});
		},
		getStockProfile(tsCode) {
			return get("/api/v1/knowledge/market/stock_profile", { ts_code: tsCode });
		},
		writeObservation(input) {
			return post("/api/v1/knowledge/ledger/observation", {
				subject_ts_code: input.subject_ts_code,
				dimension: input.dimension,
				evidence_id: input.evidence_id,
				span_start: input.span_start,
				span_end: input.span_end,
				stage_raw: input.stage_raw ?? null,
				stage_level: input.stage_level ?? null,
				dimension_scope: input.dimension_scope ?? null,
				subject_name: input.subject_name ?? null,
				event_date: input.event_date ?? null,
				published_at: input.published_at ?? null,
				metric_value: input.metric_value ?? null
			});
		},
		writeFinding(input) {
			return post("/api/v1/knowledge/ledger/finding", {
				subject_ts_code: input.subject_ts_code,
				dimension: input.dimension,
				kind: input.kind,
				judgment: input.judgment,
				supports: input.supports,
				dimension_scope: input.dimension_scope ?? null,
				from_state: input.from_state ?? null,
				to_state: input.to_state ?? null,
				delta: input.delta ?? null,
				contradicts: input.contradicts ?? [],
				confidence: input.confidence ?? null,
				supersedes: input.supersedes ?? null,
				created_by: input.created_by ?? null
			});
		}
	};
}
function resolveApiKey(ref) {
	const name = ref.trim() || "KNOWLEDGE_API_KEY";
	const direct = (process.env[name] ?? "").trim();
	if (direct) return direct;
	if (name === "KNOWLEDGE_API_KEY") return (process.env.API_KEY ?? "").trim();
	return "";
}
//#endregion
//#region src/tool-output.ts
function renderJson(value) {
	return [{
		type: "text",
		text: JSON.stringify(value, null, 2)
	}];
}
//#endregion
//#region src/tools.ts
const MAX_EVIDENCE_TEXT = 8e3;
function formatEvidenceText(doc) {
	if (!doc) return "未找到该证据记录（可能 evidence_id 无效或数据已过期）。";
	let text = String(doc.text_excerpt ?? "(无文本内容)") || "(无文本内容)";
	if (text.length > MAX_EVIDENCE_TEXT) text = text.slice(0, MAX_EVIDENCE_TEXT) + `\n...[原文过长已截断：共 ${text.length} 字符，仅显示前 ${MAX_EVIDENCE_TEXT} 字符]`;
	const lines = [
		`证据 ID: ${doc.evidence_id ?? "N/A"}`,
		`来源类型: ${doc.source_type ?? "N/A"}`,
		`来源名称: ${doc.source_name ?? "N/A"}`,
		`发布时间: ${doc.publish_date ?? "N/A"}`,
		`置信度: ${doc.confidence ?? "N/A"}`,
		"--- 原始文本 ---",
		text
	];
	const subject = doc.subject_hint ?? {};
	if (subject.ts_code) lines.splice(2, 0, `关联股票: ${subject.ts_code}`);
	return lines.join("\n");
}
function needClient(options) {
	const client = options.client();
	if (!client) return { error: "Knowledge client not configured (set knowledgeBaseUrl + KNOWLEDGE_API_KEY/API_KEY)" };
	return client;
}
/** Model-facing text for the fetch_evidence canonical value (raw doc or {error}). */
function renderEvidenceValue(value) {
	if (typeof value === "object" && value !== null && "error" in value) return String(value.error);
	return formatEvidenceText(value);
}
function installQingshuiTools(ctx, options) {
	ctx.inject(["tools"], (tctx) => {
		tctx.tools.register(defineTool({
			name: "compare_metric",
			description: "横向预期差：同一标尺(dimension)下跨主体数值排名。返回主体/数值/单位/期间/evidence_id。例：compare_metric(dimension=\"营业收入\", scope=\"硅片\")。period 不同不可直接比。",
			parameters: {
				dimension: {
					type: "string",
					required: true,
					description: "标尺名，如 营业收入/毛利率"
				},
				scope: {
					type: "string",
					description: "产品/主题范围，如 硅片"
				},
				as_of: {
					type: "string",
					description: "可选 ISO 时点，只看该日之前"
				},
				top_k: {
					type: "json",
					description: "返回主体数上限，默认 30"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				return await c.compareMetric({
					dimension: String(args.dimension ?? ""),
					scope: args.scope ? String(args.scope) : null,
					as_of: args.as_of ? String(args.as_of) : null,
					top_k: typeof args.top_k === "number" ? args.top_k : 30
				});
			}
		}));
		tctx.tools.register(defineTool({
			name: "metric_trend",
			description: "纵向预期差：同一主体在时间轴上的数值/表述变化（状态演进）。返回 timeline（value/unit/period/evidence_id）。例：metric_trend(subject=\"600962.SH\", dimension=\"营业收入\")。",
			parameters: {
				subject: {
					type: "string",
					required: true,
					description: "主体 ts_code 或名称"
				},
				dimension: {
					type: "string",
					description: "标尺名；不填则取该主体全部指标"
				},
				limit: {
					type: "json",
					description: "条数上限，默认 50"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				return await c.metricTrend({
					subject: String(args.subject ?? ""),
					dimension: args.dimension ? String(args.dimension) : null,
					limit: typeof args.limit === "number" ? args.limit : 50
				});
			}
		}));
		tctx.tools.register(defineTool({
			name: "rollup_metric",
			description: "层次预期差：粗粒度标尺下的细分子指标及 evidence 命中量。例：rollup_metric(parent=\"营收\")。",
			parameters: {
				parent: {
					type: "string",
					required: true,
					description: "粗粒度标尺，如 营收"
				},
				scope: {
					type: "string",
					description: "可选产品/主题范围"
				},
				top_k: {
					type: "json",
					description: "子指标数上限，默认 30"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				return await c.rollupMetric({
					parent: String(args.parent ?? ""),
					scope: args.scope ? String(args.scope) : null,
					top_k: typeof args.top_k === "number" ? args.top_k : 30
				});
			}
		}));
		tctx.tools.register(defineTool({
			name: "fetch_evidence",
			description: "按 evidence_id（EV:…）拉取 Mongo 证据原文与来源元数据。判断必须引用 EV。",
			parameters: { evidence_id: {
				type: "string",
				required: true,
				description: "证据 ID，格式 EV:…"
			} },
			output: {
				schema: { type: "json" },
				render: (_a, v) => [{
					type: "text",
					text: renderEvidenceValue(v)
				}],
				presentationMeta: (_a, v) => v
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return { error: c.error };
				try {
					return await c.fetchEvidence(String(args.evidence_id ?? ""));
				} catch (e) {
					return { error: `证据查询失败: ${e instanceof Error ? e.message : String(e)}` };
				}
			}
		}));
		tctx.tools.register(defineTool({
			name: "semantic_search",
			description: "语义冷启动（可选）：模糊搜实体/证据片段。判断递进/变化禁止只靠此工具。拿到 evidence_id 后用 fetch_evidence。",
			parameters: {
				query: {
					type: "string",
					required: true,
					description: "自然语言检索词"
				},
				scope: {
					type: "string",
					description: "entities(默认)|chunks|both"
				},
				ts_code: {
					type: "string",
					description: "可选股票代码"
				},
				top_k: {
					type: "json",
					description: "每类条数，默认 5"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v),
				presentationMeta: (_a, v) => v
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				return await c.semanticSearch({
					query: String(args.query ?? ""),
					scope: args.scope ?? "entities",
					ts_code: args.ts_code ? String(args.ts_code) : null,
					top_k: typeof args.top_k === "number" ? args.top_k : 5
				});
			}
		}));
		tctx.tools.register(defineTool({
			name: "related_nodes",
			description: "传导一跳：某关键字关联的主体/指标/阶段节点（共现）。用于板块玩家面。",
			parameters: {
				keyword: {
					type: "string",
					required: true,
					description: "锚点关键字，如 硅片"
				},
				layer: {
					type: "string",
					description: "可选层：subject|dimension|stage 等"
				},
				top_k: {
					type: "json",
					description: "默认 20"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				return await c.relatedNodes({
					keyword: String(args.keyword ?? ""),
					layer: args.layer ? String(args.layer) : null,
					top_k: typeof args.top_k === "number" ? args.top_k : 20
				});
			}
		}));
		tctx.tools.register(defineTool({
			name: "propagate_along",
			description: "传导多跳：从 start 按共现扩展可达节点（指标/阶段/公司）。用于传导面。",
			parameters: {
				start: {
					type: "string",
					required: true,
					description: "起点，如 硅片"
				},
				max_hops: {
					type: "json",
					description: "跳数 1-3，默认 1"
				},
				min_cooccur: {
					type: "json",
					description: "最小共现，默认 5"
				},
				top_k: {
					type: "json",
					description: "默认 20"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				return await c.propagateAlong({
					start: String(args.start ?? ""),
					max_hops: typeof args.max_hops === "number" ? args.max_hops : 1,
					min_cooccur: typeof args.min_cooccur === "number" ? args.min_cooccur : 5,
					top_k: typeof args.top_k === "number" ? args.top_k : 20
				});
			}
		}));
		tctx.tools.register(defineTool({
			name: "get_kline",
			description: "行情 K 线：个股 OHLCV 时间序列（本地行情库）。返回 count 与 items（trade_date/open/high/low/close/pre_close/volume/amount/pct_chg/turnover_rate）及摘要 text。例：get_kline(ts_code=\"300308.SZ\", start_date=\"20250901\", end_date=\"20251013\")。",
			parameters: {
				ts_code: {
					type: "string",
					required: true,
					description: "股票代码，如 300308.SZ"
				},
				start_date: {
					type: "string",
					description: "起始日 YYYYMMDD；缺省为 end_date 前 180 天"
				},
				end_date: {
					type: "string",
					description: "截止日 YYYYMMDD；缺省为今天"
				},
				freq: {
					type: "string",
					description: "周期 D|W|M，默认 D"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v),
				presentationMeta: (_a, v) => v
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				return await c.getKline({
					ts_code: String(args.ts_code ?? ""),
					start_date: args.start_date ? String(args.start_date) : null,
					end_date: args.end_date ? String(args.end_date) : null,
					freq: args.freq ? String(args.freq) : null
				});
			}
		}));
		tctx.tools.register(defineTool({
			name: "get_stock_profile",
			description: "公司概况：主营业务与经营范围（本地股票库）。返回 main_business/business_scope 与摘要 text。例：get_stock_profile(ts_code=\"300308.SZ\")。",
			parameters: { ts_code: {
				type: "string",
				required: true,
				description: "股票代码，如 300308.SZ"
			} },
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				return await c.getStockProfile(String(args.ts_code ?? ""));
			}
		}));
		tctx.tools.register(defineTool({
			name: "write_observation",
			description: "沉淀一条观察到判断台账（observation 层）：主体在某维度的原始表述/指标点，句级锚定 EV。写入即推进水位线；返回 is_new_level 表示是否首次站上新台阶（新台阶=预期差信号）。硬闸门：evidence 必须真实存在且 span 落在原文内，否则拒写。",
			parameters: {
				subject_ts_code: {
					type: "string",
					required: true,
					description: "主体 ts_code，如 003026.SZ"
				},
				dimension: {
					type: "string",
					required: true,
					description: "维度：产线进展/客户认证/毛利率/订单/产能…"
				},
				evidence_id: {
					type: "string",
					required: true,
					description: "证据 ID（EV:…）"
				},
				span_start: {
					type: "json",
					required: true,
					description: "句级锚点起始偏移（含）"
				},
				span_end: {
					type: "json",
					required: true,
					description: "句级锚点结束偏移（不含）"
				},
				stage_raw: {
					type: "string",
					description: "阶梯原始措辞（verbatim），如 增产上量"
				},
				stage_level: {
					type: "json",
					description: "阶梯归一化 level（1 起）"
				},
				dimension_scope: {
					type: "string",
					description: "细化范围，如 8英寸抛光硅片；可空"
				},
				event_date: {
					type: "string",
					description: "事件日期 YYYY-MM-DD；可空"
				},
				published_at: {
					type: "string",
					description: "披露时间 ISO；可空"
				},
				metric_value: {
					type: "json",
					description: "数值型观察：{num, unit, period, metric}"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				const toJson = (v) => {
					if (typeof v !== "string") return v ?? null;
					const sv = v.trim();
					if (!sv) return null;
					try {
						return JSON.parse(sv);
					} catch {
						return v;
					}
				};
				return await c.writeObservation({
					subject_ts_code: String(args.subject_ts_code ?? ""),
					dimension: String(args.dimension ?? ""),
					evidence_id: String(args.evidence_id ?? ""),
					span_start: Number(args.span_start ?? 0),
					span_end: Number(args.span_end ?? 0),
					stage_raw: args.stage_raw ? String(args.stage_raw) : null,
					stage_level: args.stage_level != null ? Number(args.stage_level) : null,
					dimension_scope: args.dimension_scope ? String(args.dimension_scope) : null,
					event_date: args.event_date ? String(args.event_date) : null,
					published_at: args.published_at ? String(args.published_at) : null,
					metric_value: toJson(args.metric_value)
				});
			}
		}));
		tctx.tools.register(defineTool({
			name: "write_finding",
			description: "沉淀一条判断到判断台账（finding 层）：递进/恶化/新增事件/关联传导/矛盾五类之一，supports 必须句级锚定至少一条真实证据（同前 fetch_evidence 的 EV）。判断可持续累积（跨任务复用）：下次先查 history_findings，水位线内不重复断言。幂等：同 (主体,维度,to_level,支撑集) 重写自动合并。",
			parameters: {
				subject_ts_code: {
					type: "string",
					required: true,
					description: "主体 ts_code，如 003026.SZ"
				},
				dimension: {
					type: "string",
					required: true,
					description: "维度名"
				},
				kind: {
					type: "string",
					required: true,
					description: "progression(递进)|regression(恶化)|new_event(新增事件)|association(关联传导)|divergence(矛盾)"
				},
				judgment: {
					type: "string",
					required: true,
					description: "结论文字（自然语言）"
				},
				supports: {
					type: "json",
					required: true,
					description: "支撑锚点列表：[{evidence_id, span_start, span_end, obs_id?}]，每一项都必须句级锚定"
				},
				dimension_scope: {
					type: "string",
					description: "细化范围；可空"
				},
				from_state: {
					type: "json",
					description: "状态 from：{level, stage, date?, obs_id?}"
				},
				to_state: {
					type: "json",
					description: "状态 to：{level, stage, date?, obs_id?}"
				},
				delta: {
					type: "json",
					description: "变化量：{stage_delta, value_delta, pct?}"
				},
				contradicts: {
					type: "json",
					description: "反方证据锚点列表，同 supports 结构"
				},
				confidence: {
					type: "json",
					description: "0-1"
				},
				supersedes: {
					type: "string",
					description: "被本判断取代的 finding_id；可空"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				const toJson = (v) => {
					if (typeof v !== "string") return v ?? null;
					const sv = v.trim();
					if (!sv) return null;
					try {
						return JSON.parse(sv);
					} catch {
						return v;
					}
				};
				const toCors = (list) => {
					const parsed = toJson(list);
					if (!Array.isArray(parsed)) return [];
					return parsed.map((s) => {
						const sup = s ?? {};
						return {
							evidence_id: String(sup.evidence_id ?? ""),
							span_start: Number(sup.span_start ?? 0),
							span_end: Number(sup.span_end ?? 0),
							obs_id: sup.obs_id != null ? String(sup.obs_id) : null
						};
					});
				};
				return await c.writeFinding({
					subject_ts_code: String(args.subject_ts_code ?? ""),
					dimension: String(args.dimension ?? ""),
					kind: String(args.kind ?? ""),
					judgment: String(args.judgment ?? ""),
					supports: toCors(args.supports),
					dimension_scope: args.dimension_scope ? String(args.dimension_scope) : null,
					from_state: toJson(args.from_state),
					to_state: toJson(args.to_state),
					delta: toJson(args.delta),
					contradicts: toCors(args.contradicts),
					confidence: args.confidence != null ? Number(args.confidence) : null,
					supersedes: args.supersedes ? String(args.supersedes) : null
				});
			}
		}));
	});
}
//#endregion
//#region src/mcp-mount.ts
function validateMcpMountConfig(config, options = {}) {
	const mode = options.mode ?? "remote";
	if (mode === "off") return { ok: true };
	const url = (config.mcpBaseUrl ?? "").trim();
	if (!url) return {
		ok: false,
		reason: "mcpBaseUrl is required when MCP mount mode is remote/local"
	};
	if (mode === "remote" && /localhost|127\.0\.0\.1/.test(url)) {}
	try {
		new URL(url);
	} catch {
		return {
			ok: false,
			reason: `mcpBaseUrl is not a valid URL: ${url}`
		};
	}
	return { ok: true };
}
function buildMcpClientConfig(config) {
	const apiKey = resolveApiKey(config.knowledgeApiKeyRef);
	return {
		transport: "streamable-http",
		serverName: "qingshui_data",
		url: config.mcpBaseUrl.trim(),
		headers: apiKey ? { "X-API-Key": apiKey } : {},
		toolCallTimeoutMs: config.toolCallTimeoutMs ?? config.requestTimeoutMs ?? 12e4,
		failOnStartupError: false
	};
}
/**
* Mount read-only Data MCP alongside existing Knowledge HTTP tools (dual-track).
* Failures are logged; plugin activation continues (failOnStartupError=false).
*/
async function mountQingshuiDataMcp(ctx, config) {
	const check = validateMcpMountConfig(config, { mode: "remote" });
	if (!check.ok) {
		ctx.logger.warn("qingshui: skip Data MCP mount — %c", check.reason);
		return;
	}
	const mcpConfig = buildMcpClientConfig(config);
	try {
		const mcpClient = await import("@deepseek-ai/dsh-mcp-client");
		await ctx.plugin(mcpClient, mcpConfig);
		ctx.logger.info("qingshui: Data MCP mounted server=%c url=%c", mcpConfig.serverName, mcpConfig.url);
	} catch (err) {
		ctx.logger.warn("qingshui: Data MCP mount failed (HTTP tools still available): %c", err instanceof Error ? err.message : String(err));
	}
}
//#endregion
//#region src/index.ts
const name = "qingshui";
/** tools for defineTool; skills so nested skill-filesystem can register providers. */
const inject = ["tools", "skills"];
/** Package root = plugins/qingshui (parent of src/ or lib/). */
const packageRoot = fileURLToPath(new URL("..", import.meta.url));
function resolveSkillsDir() {
	const candidates = [join(packageRoot, "skills"), join(packageRoot, "..", "skills")];
	for (const dir of candidates) if (existsSync(join(dir, "divergence-mining", "SKILL.md"))) return dir;
	for (const dir of candidates) if (existsSync(dir)) return dir;
}
function apply(ctx, config) {
	let client;
	const rebuild = () => {
		const apiKey = resolveApiKey(config.knowledgeApiKeyRef);
		if (!apiKey) {
			ctx.logger.warn("qingshui: missing API key (%c or API_KEY); tools will error until set", config.knowledgeApiKeyRef);
			client = void 0;
			return;
		}
		client = createKnowledgeClient({
			baseUrl: config.knowledgeBaseUrl,
			apiKey,
			timeoutMs: config.requestTimeoutMs
		});
	};
	rebuild();
	installQingshuiTools(ctx, { client: () => client });
	mountQingshuiDataMcp(ctx, config);
	const skillsDir = resolveSkillsDir();
	if (skillsDir !== void 0) {
		ctx.plugin(skillFilesystem, {
			providerName: "qingshui-local",
			includeDefaultRoots: false,
			customSkillDirs: [skillsDir]
		});
		ctx.logger.info("qingshui: skill root mounted provider=qingshui-local dir=%c", skillsDir);
	} else ctx.logger.warn("qingshui: skill root missing (expected skills/divergence-mining/SKILL.md under package)");
	ctx.logger.info("qingshui: loaded HTTP tools + Data MCP mount base=%c mcp=%c", config.knowledgeBaseUrl, config.mcpBaseUrl);
}
//#endregion
export { Config, apply, inject, name };
