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
	requestTimeoutMs: z.number().default(12e4)
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
				schema: { type: "string" },
				render: (_a, v) => [{
					type: "text",
					text: String(v)
				}]
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c.error;
				try {
					return formatEvidenceText(await c.fetchEvidence(String(args.evidence_id ?? "")));
				} catch (e) {
					return `证据查询失败: ${e instanceof Error ? e.message : String(e)}`;
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
				render: (_a, v) => renderJson(v)
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
	});
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
	const skillsDir = resolveSkillsDir();
	if (skillsDir !== void 0) {
		ctx.plugin(skillFilesystem, {
			providerName: "qingshui-local",
			includeDefaultRoots: false,
			customSkillDirs: [skillsDir]
		});
		ctx.logger.info("qingshui: skill root mounted provider=qingshui-local dir=%c", skillsDir);
	} else ctx.logger.warn("qingshui: skill root missing (expected skills/divergence-mining/SKILL.md under package)");
	ctx.logger.info("qingshui: loaded tools=compare_metric,metric_trend,rollup_metric,fetch_evidence,semantic_search,related_nodes,propagate_along base=%c", config.knowledgeBaseUrl);
}
//#endregion
export { Config, apply, inject, name };
