import { existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import * as skillFilesystem from "@deepseek-ai/dsh-skill-filesystem";
import z from "@deepseek-ai/schemastery";
import { execFile } from "node:child_process";
import { homedir } from "node:os";
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
		searchStocks(input) {
			const limit = input.limit ?? 10;
			return get("/api/v1/stocks/search", {
				q: input.q,
				limit: String(limit)
			});
		},
		getMarketSnapshot() {
			return get("/api/v1/knowledge/market/snapshot");
		},
		health() {
			return get("/health");
		},
		searchFindings(input) {
			return post("/api/v1/knowledge/ledger/search", { limit: input?.limit ?? 20 });
		},
		listSignals(input) {
			return get("/api/v1/signals", {
				source_type: input.sourceType,
				limit: String(input.limit ?? 4)
			});
		},
		async listRecentEvents(limit = 20) {
			try {
				return await post("/api/v1/knowledge/sources/events/recent", { limit });
			} catch (error) {
				const message = error instanceof Error ? error.message : "";
				if (!message.includes("Knowledge API 404") && !message.includes("Knowledge API 405")) throw error;
				return post("/api/v1/knowledge/sources/events", {
					query: "%",
					top_n: limit
				});
			}
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
//#region src/anysearch.ts
/** Domains accepted by AnySearch CLI 3.1.1. */
const ANYSEARCH_DOMAINS = [
	"general",
	"resource",
	"social_media",
	"finance",
	"academic",
	"legal",
	"health",
	"business",
	"security",
	"ip",
	"code",
	"energy",
	"environment",
	"agriculture",
	"travel",
	"film",
	"gaming"
];
const COMMANDS = [
	"search",
	"batch_search",
	"extract",
	"get_sub_domains"
];
const MAX_TEXT = 6e4;
const QUERY_ITEM_KEYS = /* @__PURE__ */ new Set([
	"query",
	"domain",
	"sub_domain",
	"sub_domain_params",
	"tag",
	"max_results",
	"params"
]);
function clip(text) {
	if (text.length <= MAX_TEXT) return text;
	return `${text.slice(0, MAX_TEXT)}\n...[anysearch 输出已截断，共 ${text.length} 字符]`;
}
function asText(value) {
	return typeof value === "string" ? value.trim() : "";
}
function domainOk(value) {
	return ANYSEARCH_DOMAINS.includes(value);
}
function maxResultsFlag(value) {
	if (value === void 0 || value === null || value === "") return { flag: [] };
	const n = typeof value === "number" ? value : Number(value);
	if (!Number.isInteger(n) || n < 1 || n > 10) return { error: "max_results 必须是 1 到 10 的整数" };
	return { flag: ["--max_results", String(n)] };
}
function pushOptional(argv, flag, value, check) {
	const text = asText(value);
	if (!text) return void 0;
	const problem = check?.(text);
	if (problem) return problem;
	argv.push(flag, text);
}
function buildAnysearchArgv(args) {
	if (asText(args.api_key)) return { error: "不要在工具参数里传 api_key" };
	const command = asText(args.command);
	if (!COMMANDS.includes(command)) return { error: "command 只能是 search、batch_search、extract、get_sub_domains" };
	const argv = [command];
	if (command === "search") {
		const query = asText(args.query);
		if (!query) return { error: "search 需要 query" };
		if (query.length > 2e3) return { error: "query 过长" };
		argv.push(query);
		const domain = asText(args.domain);
		const vertical = domain !== "" && domain !== "general";
		const subDomain = asText(args.sub_domain);
		const tag = asText(args.tag);
		if (vertical && !domainOk(domain)) return { error: `未知 domain：${domain}` };
		if (vertical && !subDomain && !tag) return { error: "垂直检索要带 sub_domain 或 tag。先调用 get_sub_domains。" };
		if (vertical) argv.push("--domain", domain);
		if (vertical && subDomain) argv.push("--sub_domain", subDomain);
		if (vertical && tag) argv.push("--tag", tag);
		const paramsError = pushOptional(argv, "--params", args.params, (text) => text.length > 4e3 ? "params 过长" : void 0);
		if (paramsError) return { error: paramsError };
		const zone = asText(args.zone);
		if (zone && zone !== "cn" && zone !== "intl") return { error: "zone 只能是 cn 或 intl" };
		if (zone) argv.push("--zone", zone);
		const languageError = pushOptional(argv, "--language", args.language, (text) => /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$/.test(text) ? void 0 : "language 格式不对");
		if (languageError) return { error: languageError };
		const max = maxResultsFlag(args.max_results);
		if ("error" in max) return max;
		argv.push(...max.flag);
		return { argv };
	}
	if (command === "get_sub_domains") {
		const domains = asText(args.domains);
		const domain = asText(args.domain);
		const list = domains ? domains.split(",").map((item) => item.trim()).filter(Boolean) : domain ? [domain] : [];
		if (list.length === 0) return { error: "get_sub_domains 需要 domain 或 domains" };
		if (list.length > 5) return { error: "get_sub_domains 最多 5 个 domain" };
		const unknown = list.find((item) => !domainOk(item));
		if (unknown) return { error: `未知 domain：${unknown}` };
		if (domains) argv.push("--domains", list.join(","));
		else argv.push("--domain", list[0] ?? domain);
		return { argv };
	}
	if (command === "extract") {
		const url = asText(args.url);
		if (!url) return { error: "extract 需要 url" };
		let parsed;
		try {
			parsed = new URL(url);
		} catch {
			return { error: "url 只能是 http 或 https" };
		}
		if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return { error: "url 只能是 http 或 https" };
		argv.push("--url", url);
		return { argv };
	}
	const rawQueries = args.queries;
	if (typeof rawQueries === "string" && rawQueries.trim().startsWith("@")) return { error: "queries 不要用 @文件" };
	let parsedQueries = rawQueries;
	if (typeof rawQueries === "string") try {
		parsedQueries = JSON.parse(rawQueries);
	} catch {
		return { error: "queries 必须是 JSON 数组" };
	}
	if (!Array.isArray(parsedQueries) || parsedQueries.length < 1 || parsedQueries.length > 5) return { error: "queries 必须是 1 到 5 条" };
	const cleaned = [];
	for (const item of parsedQueries) {
		if (!item || typeof item !== "object" || Array.isArray(item)) return { error: "queries 的每一项都要有 query" };
		const record = item;
		const query = asText(record.query);
		if (!query) return { error: "queries 的每一项都要有 query" };
		const next = { query };
		for (const key of QUERY_ITEM_KEYS) {
			if (key === "query" || record[key] === void 0) continue;
			next[key] = record[key];
		}
		cleaned.push(next);
	}
	argv.push("--queries", JSON.stringify(cleaned));
	const domain = asText(args.domain);
	const vertical = domain !== "" && domain !== "general";
	if (vertical && !domainOk(domain)) return { error: `未知 domain：${domain}` };
	if (vertical) argv.push("--domain", domain);
	const sharedError = pushOptional(argv, "--sub_domain", args.sub_domain) ?? pushOptional(argv, "--tag", args.tag) ?? pushOptional(argv, "--params", args.params);
	if (sharedError) return { error: sharedError };
	const max = maxResultsFlag(args.max_results);
	if ("error" in max) return max;
	argv.push(...max.flag);
	return { argv };
}
function defaultAnysearchCliPath(env = process.env, home = homedir()) {
	const agentsHome = env.DSH_AGENTS_HOME || join(home, ".agents");
	return [env.QINGSHUI_ANYSEARCH_CLI, join(agentsHome, "skills", "anysearch", "scripts", "anysearch_cli.js")].filter((item) => typeof item === "string" && item.length > 0).find((item) => existsSync(item));
}
async function runAnysearchCli(cliPath, argv) {
	return await new Promise((resolve) => {
		execFile(process.execPath, [cliPath, ...argv], {
			timeout: 45e3,
			maxBuffer: 2e6
		}, (error, stdout, stderr) => {
			const err = error;
			const code = typeof err?.code === "number" ? err.code : err ? 1 : 0;
			resolve({
				code,
				stdout: stdout ?? "",
				stderr: stderr || (err && code !== 0 ? err.message : "")
			});
		});
	});
}
function installAnysearchTool(ctx, options = {}) {
	const resolveCli = options.resolveCli ?? (() => defaultAnysearchCliPath());
	const run = options.run ?? runAnysearchCli;
	ctx.inject(["tools"], (tctx) => {
		tctx.tools.register(defineTool({
			name: "anysearch",
			description: `垂直检索、批量检索和页面摘录（AnySearch）。新闻、资讯和复盘报道用 web_search；web_search 失败时用本工具做普通检索。普通检索只传 query，不传 domain。domain 为 general 也按普通检索。command 为 search、batch_search、extract、get_sub_domains。垂直领域先 get_sub_domains。domain 取值：${ANYSEARCH_DOMAINS.join(", ")}。标了 required 的参数全部放进 params，没有值就传空字符串。本地行情、公告、事件、概念不要用本工具。结果不是 EV 证据。不要传 api_key。`,
			parameters: {
				command: {
					type: "string",
					required: true,
					enum: COMMANDS,
					description: "search、batch_search、extract、get_sub_domains"
				},
				query: {
					type: "string",
					description: "search 的检索词"
				},
				queries: {
					type: "json",
					description: "batch_search 的 JSON 数组，1 到 5 条，每条含 query"
				},
				domain: {
					type: "string",
					description: "垂直领域，如 finance"
				},
				domains: {
					type: "string",
					description: "get_sub_domains 的多个 domain，逗号分隔，最多 5 个"
				},
				sub_domain: {
					type: "string",
					description: "子域，如 finance.quote。先向 get_sub_domains 要"
				},
				tag: {
					type: "string",
					description: "能力标签，如 finance.quote"
				},
				params: {
					type: "string",
					description: "子域参数。JSON 或 key=value。必填项没有值就写空字符串"
				},
				max_results: {
					type: "json",
					description: "1 到 10，默认由 CLI 取 10"
				},
				url: {
					type: "string",
					description: "extract 的 http(s) 地址"
				},
				zone: {
					type: "string",
					description: "cn 或 intl"
				},
				language: {
					type: "string",
					description: "如 zh-CN"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_args, value) => {
					if (typeof value === "object" && value !== null && "text" in value) {
						const record = value;
						const text = typeof record.text === "string" ? record.text : "";
						const error = typeof record.error === "string" ? record.error : "";
						return [{
							type: "text",
							text: error ? text ? `${error}\n${text}` : error : text
						}];
					}
					return [{
						type: "text",
						text: JSON.stringify(value, null, 2)
					}];
				}
			},
			async execute(toolArgs) {
				const built = buildAnysearchArgv(toolArgs);
				if ("error" in built) return { error: built.error };
				const cli = resolveCli();
				if (!cli) return { error: "anysearch CLI 不在本机。期望 ~/.agents/skills/anysearch/scripts/anysearch_cli.js，或设置 QINGSHUI_ANYSEARCH_CLI。" };
				const result = await run(cli, built.argv);
				const text = clip(result.stdout);
				if (result.code !== 0) return {
					error: clip(result.stderr || result.stdout || `anysearch 退出码 ${result.code}`),
					text
				};
				return { text };
			}
		}));
	});
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
function canonicalDecimal(value) {
	let token = null;
	if (typeof value === "number" && Number.isFinite(value)) {
		if (Object.is(value, -0)) return "0";
		const text = value.toString();
		if (/^-?\d+(\.\d+)?$/.test(text)) token = text;
		else if (/^-?\d(?:\.\d+)?e[+-]?\d+$/i.test(text)) token = expandScientific(text);
	} else if (typeof value === "string" && value.trim() !== "") {
		const matched = value.trim().match(/-?\d[\d,.]*/);
		if (matched) token = matched[0].replace(/,/g, "");
	}
	if (!token || !/^-?\d+(\.\d+)?$/.test(token)) return null;
	return normalizeDecimalText(token);
}
function expandScientific(text) {
	const matched = text.toLowerCase().match(/^(-?)(\d)(?:\.(\d+))?e([+-]?\d+)$/);
	if (!matched) return null;
	const sign = matched[1] ?? "";
	const head = matched[2] ?? "";
	const frac = matched[3] ?? "";
	const exp = Number(matched[4]);
	const digits = `${head}${frac}`;
	const point = 1 + exp;
	if (point <= 0) return `${sign}0.${"0".repeat(-point)}${digits}`;
	if (point >= digits.length) return `${sign}${digits}${"0".repeat(point - digits.length)}`;
	return `${sign}${digits.slice(0, point)}.${digits.slice(point)}`;
}
function normalizeDecimalText(token) {
	const neg = token.startsWith("-");
	const [rawInt, rawFrac = ""] = (neg ? token.slice(1) : token).split(".");
	const intPart = (rawInt ?? "0").replace(/^0+(?=\d)/, "") || "0";
	const frac = rawFrac.replace(/0+$/, "");
	const core = frac ? `${intPart}.${frac}` : intPart;
	if (core === "0") return "0";
	return neg ? `-${core}` : core;
}
function decimalParts(text) {
	const [intPart, frac = ""] = text.split(".");
	return {
		digits: `${intPart ?? "0"}${frac}`.replace(/^0+(?=\d)/, "") || "0",
		scale: frac.length
	};
}
function padDigits(parts, scale) {
	return parts.digits + "0".repeat(scale - parts.scale);
}
function finishDigits(digits, scale) {
	const body = digits.join("").replace(/^0+/, "") || "0";
	if (scale === 0) return body;
	const padded = body.padStart(scale + 1, "0");
	const intPart = padded.slice(0, padded.length - scale).replace(/^0+(?=\d)/, "") || "0";
	const frac = padded.slice(padded.length - scale).replace(/0+$/, "");
	return frac ? `${intPart}.${frac}` : intPart;
}
function addPositive(x, y) {
	const sx = decimalParts(x);
	const sy = decimalParts(y);
	const scale = Math.max(sx.scale, sy.scale);
	const width = Math.max(padDigits(sx, scale).length, padDigits(sy, scale).length);
	const a = padDigits(sx, scale).padStart(width, "0");
	const b = padDigits(sy, scale).padStart(width, "0");
	const out = [];
	let carry = 0;
	for (let i = width - 1; i >= 0; i -= 1) {
		const sum = Number(a[i]) + Number(b[i]) + carry;
		out.push(sum % 10);
		carry = Math.floor(sum / 10);
	}
	if (carry) out.push(carry);
	out.reverse();
	return finishDigits(out, scale);
}
function cmpPositive(x, y) {
	const sx = decimalParts(x);
	const sy = decimalParts(y);
	const scale = Math.max(sx.scale, sy.scale);
	const width = Math.max(padDigits(sx, scale).length, padDigits(sy, scale).length);
	const a = padDigits(sx, scale).padStart(width, "0");
	const b = padDigits(sy, scale).padStart(width, "0");
	if (a === b) return 0;
	return a > b ? 1 : -1;
}
function subPositive(x, y) {
	const order = cmpPositive(x, y);
	if (order === 0) return "0";
	if (order < 0) {
		const flipped = subPositive(y, x);
		return flipped === "0" ? "0" : `-${flipped}`;
	}
	const sx = decimalParts(x);
	const sy = decimalParts(y);
	const scale = Math.max(sx.scale, sy.scale);
	const width = Math.max(padDigits(sx, scale).length, padDigits(sy, scale).length);
	const a = padDigits(sx, scale).padStart(width, "0");
	const b = padDigits(sy, scale).padStart(width, "0");
	const out = [];
	let borrow = 0;
	for (let i = width - 1; i >= 0; i -= 1) {
		let diff = Number(a[i]) - Number(b[i]) - borrow;
		if (diff < 0) {
			diff += 10;
			borrow = 1;
		} else borrow = 0;
		out.push(diff);
	}
	out.reverse();
	return finishDigits(out, scale);
}
function subDecimal(a, b) {
	const negA = a.startsWith("-");
	const negB = b.startsWith("-");
	const absA = negA ? a.slice(1) : a;
	const absB = negB ? b.slice(1) : b;
	if (!negA && !negB) return subPositive(absA, absB);
	if (negA && negB) return subPositive(absB, absA);
	if (!negA && negB) return addPositive(absA, absB);
	const sum = addPositive(absA, absB);
	return sum === "0" ? "0" : `-${sum}`;
}
function decimalNumber(text) {
	return Number(text);
}
function periodKey(period) {
	const raw = period.trim();
	if (!raw) return null;
	const pad = (part) => String(part).padStart(2, "0");
	let matched = raw.match(/^(\d{4})A$/i) ?? raw.match(/^(\d{4})$/) ?? raw.match(/^FY\s*(\d{4})$/i) ?? raw.match(/^(\d{4})年$/);
	if (matched?.[1]) {
		const year = Number(matched[1]);
		return {
			freq: "year",
			identity: `Y${year}`,
			sort: [
				year,
				0,
				0
			],
			raw
		};
	}
	matched = raw.match(/^(\d{4})Q([1-4])$/i);
	if (matched?.[1] && matched[2]) {
		const year = Number(matched[1]);
		const quarter = Number(matched[2]);
		return {
			freq: "quarter",
			identity: `Q${year}${quarter}`,
			sort: [
				year,
				quarter,
				0
			],
			raw
		};
	}
	matched = raw.match(/^Q([1-4])\s+(\d{4})$/i);
	if (matched?.[1] && matched[2]) {
		const quarter = Number(matched[1]);
		const year = Number(matched[2]);
		return {
			freq: "quarter",
			identity: `Q${year}${quarter}`,
			sort: [
				year,
				quarter,
				0
			],
			raw
		};
	}
	matched = raw.match(/^Q1-Q3\s+(\d{4})$/i);
	if (matched?.[1]) {
		const year = Number(matched[1]);
		return {
			freq: "ytd-q3",
			identity: `YTDQ3${year}`,
			sort: [
				year,
				0,
				0
			],
			raw
		};
	}
	matched = raw.match(/^(\d{4})H([12])$/i);
	if (matched?.[1] && matched[2]) {
		const year = Number(matched[1]);
		const half = Number(matched[2]);
		return {
			freq: "half",
			identity: `H${year}${half}`,
			sort: [
				year,
				half,
				0
			],
			raw
		};
	}
	matched = raw.match(/^H([12])\s+(\d{4})$/i);
	if (matched?.[1] && matched[2]) {
		const half = Number(matched[1]);
		const year = Number(matched[2]);
		return {
			freq: "half",
			identity: `H${year}${half}`,
			sort: [
				year,
				half,
				0
			],
			raw
		};
	}
	matched = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
	if (matched?.[1] && matched[2] && matched[3]) {
		const year = Number(matched[1]);
		const month = Number(matched[2]);
		const day = Number(matched[3]);
		return {
			freq: "day",
			identity: `D${year}${pad(month)}${pad(day)}`,
			sort: [
				year,
				month,
				day
			],
			raw
		};
	}
	matched = raw.match(/^(\d{4})-(\d{2})$/);
	if (matched?.[1] && matched[2]) {
		const year = Number(matched[1]);
		const month = Number(matched[2]);
		return {
			freq: "month",
			identity: `M${year}${pad(month)}`,
			sort: [
				year,
				month,
				0
			],
			raw
		};
	}
	return {
		freq: `raw:${raw.replace(/\d+/g, "#")}`,
		identity: `R${raw}`,
		sort: [
			0,
			0,
			0
		],
		raw
	};
}
function comparePoints(a, b) {
	for (let i = 0; i < 3; i += 1) {
		const delta = a.sort[i] - b.sort[i];
		if (delta !== 0) return delta;
	}
	return a.rawPeriod.localeCompare(b.rawPeriod, "en", { numeric: true });
}
/** Last three comparable periods of the longest same-cadence series. The model must not recompute this. */
function accelerationFromTimeline(timeline) {
	const rows = Array.isArray(timeline) ? timeline : [];
	const buckets = /* @__PURE__ */ new Map();
	for (const row of rows) {
		if (!row || typeof row !== "object") continue;
		const rec = row;
		const text = canonicalDecimal(rec.value);
		if (text === null) continue;
		const key = periodKey(rec.period == null ? "" : String(rec.period));
		if (!key) continue;
		const metric = rec.metric == null ? null : String(rec.metric);
		const unit = rec.unit == null ? null : String(rec.unit);
		const bucketId = `${metric ?? ""}\0${unit ?? ""}\0${key.freq}`;
		const byPeriod = buckets.get(bucketId) ?? /* @__PURE__ */ new Map();
		byPeriod.set(key.identity, {
			value: decimalNumber(text),
			period: key.raw,
			evidence_id: rec.evidence_id == null ? null : String(rec.evidence_id),
			metric,
			unit,
			text,
			sort: key.sort,
			rawPeriod: key.raw
		});
		buckets.set(bucketId, byPeriod);
	}
	let best = null;
	for (const byPeriod of buckets.values()) if (!best || byPeriod.size > best.size) best = byPeriod;
	const tail = (best ? [...best.values()].sort(comparePoints) : []).slice(-3);
	const points = tail.map(({ value, period, evidence_id }) => ({
		value,
		period,
		evidence_id
	}));
	const metric = tail[0]?.metric ?? null;
	const unit = tail[0]?.unit ?? null;
	if (tail.length < 3) return {
		status: "insufficient_points",
		metric,
		unit,
		points,
		d1: null,
		d2: null,
		a: null,
		note: "二阶导不可计算。点数不足只说明加速度算不出。"
	};
	const d1 = subDecimal(tail[1].text, tail[0].text);
	const d2 = subDecimal(tail[2].text, tail[1].text);
	const a = subDecimal(d2, d1);
	return {
		status: "ok",
		metric,
		unit,
		points,
		d1: decimalNumber(d1),
		d2: decimalNumber(d2),
		a: decimalNumber(a),
		note: "acceleration 已给出最后三个可比期间的 d1、d2、a。不要对 timeline 再心算。"
	};
}
/** Attach acceleration on a metric_trend payload. Errors and objects without timeline pass through. */
function withSeriesAcceleration(payload) {
	if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
	if ("error" in payload) return payload;
	if (!("timeline" in payload)) return payload;
	const rec = payload;
	return {
		...rec,
		acceleration: accelerationFromTimeline(rec.timeline)
	};
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
			description: "纵向预期差：同一主体在时间轴上的数值/表述变化（状态演进）。返回 timeline，并附 acceleration（同一口径、同一披露频率下按期间去重后的最后三点 d1、d2、a；千分位逗号按数值计算；status 不是 ok 表示可比期间不足三点）。用返回的 acceleration，不要对 timeline 再做减法。例：metric_trend(subject=\"600962.SH\", dimension=\"营业收入\")。",
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
				return withSeriesAcceleration(await c.metricTrend({
					subject: String(args.subject ?? ""),
					dimension: args.dimension ? String(args.dimension) : null,
					limit: typeof args.limit === "number" ? args.limit : 50
				}));
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
			description: "行情 K 线：个股 OHLCV 时间序列（本地行情库）。返回 count 与 items（trade_date/open/high/low/close/pre_close/volume/amount/pct_chg/turnover_rate）及摘要 text。amount 单位是千元，10 万千元 = 1 亿元。例：get_kline(ts_code=\"300308.SZ\", start_date=\"20250901\", end_date=\"20251013\")。",
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
			name: "search_stock",
			description: "按公司名或代码查本地股票库。返回 items（ts_code/name/industry/area）。问某只票为什么涨停、或只给了公司名时，先调用本工具，不要猜代码或板块。",
			parameters: {
				q: {
					type: "string",
					required: true,
					description: "公司名或代码，如 大普微"
				},
				limit: {
					type: "json",
					description: "1 到 20，默认 10"
				}
			},
			output: {
				schema: { type: "json" },
				render: (_a, v) => renderJson(v)
			},
			async execute(args) {
				const c = needClient(options);
				if ("error" in c) return c;
				const q = String(args.q ?? "").trim();
				if (!q) return { error: "search_stock 需要 q" };
				const raw = typeof args.limit === "number" ? args.limit : Number(args.limit);
				const limit = Number.isInteger(raw) && raw >= 1 && raw <= 20 ? raw : 10;
				return await c.searchStocks({
					q,
					limit
				});
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
//#region src/ev-route.ts
const EVIDENCE_ROUTE_PATH = "/qingshui/evidence";
const EV_ID_RE = /^EV:[0-9a-fA-F]{6,64}$/;
/** Minimal Host/Origin fence mirroring the /api channel's trust posture. */
function isLoopbackHostRequest(req) {
	const host = req.headers.host;
	if (typeof host !== "string" || host === "") return false;
	const hostname = host.split(":")[0]?.toLowerCase() ?? "";
	const port = host.includes(":") ? host.slice(host.indexOf(":") + 1) : "";
	if (port !== "" && !/^\d*$/.test(port)) return false;
	if (hostname !== "127.0.0.1" && hostname !== "localhost" && hostname !== "::1") return false;
	const site = req.headers["sec-fetch-site"];
	if (typeof site === "string" && site === "cross-site") return false;
	const origin = req.headers.origin;
	if (origin === void 0) return true;
	try {
		return new URL(origin).host === host;
	} catch {
		return false;
	}
}
/** @param id - candidate evidence id. @returns whether it is a well-formed EV id. */
function isValidEvidenceId(id) {
	return EV_ID_RE.test(id);
}
function sendJson$5(res, status, body) {
	const payload = JSON.stringify(body);
	res.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"cache-control": "no-store"
	});
	res.end(payload);
}
/**
* Install the evidence proxy route on the web server when it is available.
* @param webCtx - context carrying the webServer service
* @param deps - knowledge client accessor
* @returns disposer
*/
function installEvidenceRoute(webCtx, deps) {
	return webCtx.webServer.register({
		kind: "prefix",
		path: EVIDENCE_ROUTE_PATH,
		handler: async (req, res) => {
			if (!isLoopbackHostRequest(req)) {
				sendJson$5(res, 403, {
					ok: false,
					error: "forbidden"
				});
				return;
			}
			const url = req.url ?? "/";
			let id = "";
			try {
				id = decodeURIComponent(new URL(url, "http://x").pathname).slice(18).replace(/^\//, "");
			} catch {
				id = "";
			}
			if (!isValidEvidenceId(id)) {
				sendJson$5(res, 400, {
					ok: false,
					error: "bad evidence id (expected EV:<hex>)"
				});
				return;
			}
			const client = deps.client();
			if (client === void 0) {
				sendJson$5(res, 503, {
					ok: false,
					error: "knowledge client not configured (missing API key)"
				});
				return;
			}
			try {
				sendJson$5(res, 200, {
					ok: true,
					doc: await client.fetchEvidence(id)
				});
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				const missing = /Knowledge API 404/.test(message);
				sendJson$5(res, missing ? 404 : 502, {
					ok: false,
					error: missing ? "证据未命中：该 evidence_id 不存在（短 ID 需以完整 64 位十六进制核验）" : `知识库查询失败：${message.slice(0, 200)}`
				});
			}
		}
	});
}
//#endregion
//#region src/quote-strip.ts
/** Board quotes on the research shell. 科创板 uses 科创50, 北交所 uses 北证50. */
const SHANGHAI_TS_CODE = "000001.SH";
const BOARD_INDEXES = [
	{
		tsCode: "000001.SH",
		label: "上证"
	},
	{
		tsCode: "399006.SZ",
		label: "创业板"
	},
	{
		tsCode: "000688.SH",
		label: "科创板"
	},
	{
		tsCode: "899050.BJ",
		label: "北交所"
	}
];
function asRecord$2(value) {
	if (value === null || typeof value !== "object" || Array.isArray(value)) return void 0;
	return value;
}
function formatClose(value) {
	const n = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
	if (!Number.isFinite(n)) return void 0;
	return n.toFixed(2);
}
function formatPct(value) {
	const n = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
	if (!Number.isFinite(n)) return void 0;
	return {
		text: `${n > 0 ? "+" : ""}${n.toFixed(2)}%`,
		up: n > 0
	};
}
/**
* Pick the Shanghai composite from a market snapshot payload.
* @param payload - Knowledge `/market/snapshot` JSON.
* @returns the strip row, or null when that index is absent.
*/
function pickShanghaiQuote(payload) {
	const body = asRecord$2(payload);
	if (body === void 0 || !Array.isArray(body.indices)) return null;
	const tradeDate = typeof body.trade_date === "string" ? body.trade_date : "";
	for (const item of body.indices) {
		const row = asRecord$2(item);
		if (row === void 0 || row.ts_code !== "000001.SH") continue;
		const close = formatClose(row.close);
		const pct = formatPct(row.pct_chg);
		const name = typeof row.name === "string" ? row.name : "";
		if (close === void 0 || pct === void 0 || name === "") return null;
		return {
			tsCode: SHANGHAI_TS_CODE,
			name,
			close,
			pct: pct.text,
			up: pct.up,
			tradeDate
		};
	}
	return null;
}
function quoteFromRow(row, tradeDate, tsCode, label) {
	const absent = {
		tsCode,
		label,
		name: label,
		close: null,
		pct: null,
		direction: "absent",
		tradeDate
	};
	if (row === void 0) return absent;
	const close = formatClose(row.close);
	const pct = formatPct(row.pct_chg);
	const name = typeof row.name === "string" && row.name !== "" ? row.name : label;
	if (close === void 0 || pct === void 0) return {
		...absent,
		name
	};
	const direction = pct.text.startsWith("+") ? "up" : pct.text.startsWith("-") ? "down" : "flat";
	return {
		tsCode,
		label,
		name,
		close,
		pct: pct.text,
		direction,
		tradeDate
	};
}
/**
* Four board rows in display order. A missing index stays in the strip as absent.
* @param payload - Knowledge `/market/snapshot` JSON.
*/
function pickBoardQuotes(payload) {
	const body = asRecord$2(payload);
	const tradeDate = body !== void 0 && typeof body.trade_date === "string" ? body.trade_date : "";
	const byCode = /* @__PURE__ */ new Map();
	if (body !== void 0 && Array.isArray(body.indices)) for (const item of body.indices) {
		const row = asRecord$2(item);
		if (row !== void 0 && typeof row.ts_code === "string") byCode.set(row.ts_code, row);
	}
	return BOARD_INDEXES.map((board) => quoteFromRow(byCode.get(board.tsCode), tradeDate, board.tsCode, board.label));
}
//#endregion
//#region src/market-route.ts
const SNAPSHOT_ROUTE_PATH = "/qingshui/market-snapshot";
function sendJson$4(res, status, body) {
	res.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"cache-control": "no-store"
	});
	res.end(JSON.stringify(body));
}
/**
* Install the snapshot proxy. @param webCtx - web server. @param deps - client accessor.
* @returns disposer.
*/
function installMarketRoute(webCtx, deps) {
	return webCtx.webServer.register({
		kind: "exact",
		path: SNAPSHOT_ROUTE_PATH,
		handler: async (req, res) => {
			if (!isLoopbackHostRequest(req)) {
				sendJson$4(res, 403, {
					ok: false,
					error: "forbidden"
				});
				return;
			}
			const client = deps.client();
			if (client === void 0) {
				sendJson$4(res, 503, {
					ok: false,
					error: "知识库未配置"
				});
				return;
			}
			try {
				const payload = await client.getMarketSnapshot();
				const quotes = pickBoardQuotes(payload);
				const quote = pickShanghaiQuote(payload);
				sendJson$4(res, 200, {
					ok: true,
					quotes,
					...quote === null ? {} : { quote }
				});
			} catch (error) {
				sendJson$4(res, 502, {
					ok: false,
					error: error instanceof Error ? error.message : "知识库查询失败"
				});
			}
		}
	});
}
//#endregion
//#region src/news-tape.ts
function asRecord$1(value) {
	if (value === null || typeof value !== "object" || Array.isArray(value)) return void 0;
	return value;
}
/** Map stored source codes onto the label a reader expects. */
function newsSourceLabel(source) {
	if (source === "tushare" || source === "cls") return "财联社";
	if (source === "eastmoney_flash") return "东财";
	if (source === "wallstreetcn") return "华尔街见闻";
	if (source === "ths") return "同花顺";
	if (source === "sina") return "新浪";
	return source === "" ? "快讯" : source;
}
/** Shanghai clock, `MM-DD HH:mm`. Unparseable strings pass through trimmed. */
function formatNewsTime(raw) {
	const trimmed = raw.trim();
	if (trimmed === "") return "";
	const parsed = new Date(trimmed.includes("T") || trimmed.endsWith("Z") ? trimmed : trimmed.replace(" ", "T"));
	if (Number.isNaN(parsed.getTime())) return trimmed.slice(0, 16);
	const parts = new Intl.DateTimeFormat("en-GB", {
		timeZone: "Asia/Shanghai",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		hourCycle: "h23"
	}).formatToParts(parsed);
	const pick = (type) => parts.find((part) => part.type === type)?.value ?? "";
	return `${pick("month")}-${pick("day")} ${pick("hour")}:${pick("minute")}`;
}
/**
* Shape a knowledge `events/recent` payload into tape rows.
* @param payload - JSON body.
*/
function shapeNewsFeed(payload) {
	const body = asRecord$1(payload);
	if (body === void 0 || !Array.isArray(body.items)) return [];
	const items = [];
	for (const raw of body.items) {
		const row = asRecord$1(raw);
		if (row === void 0) continue;
		const eventId = typeof row.event_id === "string" ? row.event_id.trim() : "";
		const title = typeof row.title === "string" ? row.title.trim() : "";
		if (eventId === "" || title === "") continue;
		const source = newsSourceLabel(typeof row.source === "string" ? row.source : "");
		const publishAt = typeof row.publish_at === "string" ? row.publish_at : "";
		items.push({
			eventId,
			title,
			source,
			publishAt,
			timeLabel: formatNewsTime(publishAt)
		});
	}
	return items;
}
//#endregion
//#region src/news-route.ts
const NEWS_ROUTE_PATH = "/qingshui/news";
function sendJson$3(res, status, body) {
	res.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"cache-control": "no-store"
	});
	res.end(JSON.stringify(body));
}
/**
* Install the news proxy. @param webCtx - web server. @param deps - client accessor.
* @returns disposer.
*/
function installNewsRoute(webCtx, deps) {
	return webCtx.webServer.register({
		kind: "exact",
		path: NEWS_ROUTE_PATH,
		handler: async (req, res) => {
			if (!isLoopbackHostRequest(req)) {
				sendJson$3(res, 403, {
					ok: false,
					error: "forbidden"
				});
				return;
			}
			const client = deps.client();
			if (client === void 0) {
				sendJson$3(res, 503, {
					ok: false,
					error: "知识库未配置"
				});
				return;
			}
			try {
				sendJson$3(res, 200, {
					ok: true,
					items: shapeNewsFeed(await client.listRecentEvents(20))
				});
			} catch (error) {
				sendJson$3(res, 502, {
					ok: false,
					error: error instanceof Error ? error.message : "知识库查询失败"
				});
			}
		}
	});
}
const SIGNAL_LANES = [
	{
		id: "news",
		label: "新闻快讯",
		sources: [{
			sourceType: "news:llm",
			tag: ""
		}, {
			sourceType: "news",
			tag: ""
		}]
	},
	{
		id: "announcement",
		label: "公告",
		sources: [{
			sourceType: "announcement:llm",
			tag: ""
		}, {
			sourceType: "announcement",
			tag: ""
		}]
	},
	{
		id: "event",
		label: "事件",
		sources: [
			{
				sourceType: "event:llm",
				tag: ""
			},
			{
				sourceType: "event",
				tag: ""
			},
			{
				sourceType: "irm:llm",
				tag: ""
			},
			{
				sourceType: "irm",
				tag: ""
			}
		]
	},
	{
		id: "mapping",
		label: "美股 / 台股",
		sources: [
			{
				sourceType: "us_map:llm",
				tag: "美股"
			},
			{
				sourceType: "us_map",
				tag: "美股"
			},
			{
				sourceType: "tw_map:llm",
				tag: "台股"
			},
			{
				sourceType: "tw_map",
				tag: "台股"
			}
		]
	}
];
function asRecord(value) {
	if (value === null || typeof value !== "object" || Array.isArray(value)) return void 0;
	return value;
}
function polarityMark(polarity) {
	if (polarity === "positive" || polarity === "bullish") return {
		mark: "正",
		direction: "up"
	};
	if (polarity === "negative" || polarity === "risk" || polarity === "bearish") return {
		mark: "负",
		direction: "down"
	};
	return {
		mark: "平",
		direction: "flat"
	};
}
/**
* One knowledge list payload into cards. Rows without an id or a sentence are dropped.
*/
function shapeSignalItems(payload, lane, tag) {
	const body = asRecord(payload);
	if (body === void 0 || !Array.isArray(body.items)) return [];
	const cards = [];
	for (const raw of body.items) {
		const row = asRecord(raw);
		if (row === void 0) continue;
		const signalId = typeof row.signal_id === "string" ? row.signal_id.trim() : "";
		const summaryRaw = typeof row.summary === "string" ? row.summary.trim() : "";
		const title = typeof row.title === "string" ? row.title.trim() : "";
		const summary = summaryRaw !== "" ? summaryRaw : title;
		if (signalId === "" || summary === "") continue;
		const subject = typeof row.subject_name === "string" ? row.subject_name.trim() : "";
		const polarity = typeof row.polarity === "string" ? row.polarity : "";
		const valueScore = typeof row.value_score === "number" && Number.isFinite(row.value_score) ? row.value_score : 0;
		const marked = polarityMark(polarity);
		cards.push({
			signalId,
			lane: lane.id,
			label: lane.label,
			tag,
			subject,
			summary,
			mark: marked.mark,
			direction: marked.direction,
			valueScore
		});
	}
	return cards;
}
/** Highest value first. The same signal from two source queries is kept once. */
function mergeSignals(items, limit = 4) {
	const seen = /* @__PURE__ */ new Set();
	const ranked = [...items].sort((a, b) => b.valueScore - a.valueScore);
	const kept = [];
	for (const item of ranked) {
		if (seen.has(item.signalId)) continue;
		seen.add(item.signalId);
		kept.push(item);
		if (kept.length >= limit) break;
	}
	return kept;
}
/**
* Load the four lanes. A source that throws is skipped; a lane is absent only when every source threw.
*/
async function loadSignalBoard(list) {
	return Promise.all(SIGNAL_LANES.map(async (lane) => {
		const batches = await Promise.all(lane.sources.map(async (source) => {
			try {
				return shapeSignalItems(await list(source.sourceType, 4), lane, source.tag);
			} catch {
				return null;
			}
		}));
		const absent = batches.every((batch) => batch === null);
		const items = mergeSignals(batches.flatMap((batch) => batch ?? []));
		return {
			id: lane.id,
			label: lane.label,
			items,
			absent
		};
	}));
}
//#endregion
//#region src/signal-route.ts
const SIGNAL_ROUTE_PATH = "/qingshui/signals";
function sendJson$2(res, status, body) {
	res.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"cache-control": "no-store"
	});
	res.end(JSON.stringify(body));
}
/**
* Install the signal proxy. @param webCtx - web server. @param deps - client accessor.
* @returns disposer.
*/
function installSignalRoute(webCtx, deps) {
	return webCtx.webServer.register({
		kind: "exact",
		path: SIGNAL_ROUTE_PATH,
		handler: async (req, res) => {
			if (!isLoopbackHostRequest(req)) {
				sendJson$2(res, 403, {
					ok: false,
					error: "forbidden"
				});
				return;
			}
			const client = deps.client();
			if (client === void 0) {
				sendJson$2(res, 503, {
					ok: false,
					error: "知识库未配置"
				});
				return;
			}
			try {
				sendJson$2(res, 200, {
					ok: true,
					lanes: await loadSignalBoard((sourceType, limit) => client.listSignals({
						sourceType,
						limit
					}))
				});
			} catch (error) {
				sendJson$2(res, 502, {
					ok: false,
					error: error instanceof Error ? error.message : "知识库查询失败"
				});
			}
		}
	});
}
//#endregion
//#region src/health-route.ts
const HEALTH_ROUTE_PATH = "/qingshui/health";
function sendJson$1(res, status, body) {
	res.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"cache-control": "no-store"
	});
	res.end(JSON.stringify(body));
}
function installHealthRoute(webCtx, deps) {
	return webCtx.webServer.register({
		kind: "exact",
		path: HEALTH_ROUTE_PATH,
		handler: async (req, res) => {
			if (!isLoopbackHostRequest(req)) {
				sendJson$1(res, 403, {
					ok: false,
					error: "forbidden"
				});
				return;
			}
			const client = deps.client();
			if (client === void 0) {
				sendJson$1(res, 503, {
					ok: false,
					error: "知识库未配置"
				});
				return;
			}
			try {
				await client.health();
				sendJson$1(res, 200, { ok: true });
			} catch (error) {
				sendJson$1(res, 502, {
					ok: false,
					error: error instanceof Error ? error.message : "知识库不可达"
				});
			}
		}
	});
}
//#endregion
//#region src/ledger-route.ts
const LEDGER_ROUTE_PATH = "/qingshui/ledger";
function sendJson(res, status, body) {
	res.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"cache-control": "no-store"
	});
	res.end(JSON.stringify(body));
}
/**
* Install the findings proxy. @param webCtx - web server. @param deps - client accessor.
* @returns disposer.
*/
function installLedgerRoute(webCtx, deps) {
	return webCtx.webServer.register({
		kind: "exact",
		path: LEDGER_ROUTE_PATH,
		handler: async (req, res) => {
			if (!isLoopbackHostRequest(req)) {
				sendJson(res, 403, {
					ok: false,
					error: "forbidden"
				});
				return;
			}
			const client = deps.client();
			if (client === void 0) {
				sendJson(res, 503, {
					ok: false,
					error: "知识库未配置"
				});
				return;
			}
			try {
				sendJson(res, 200, {
					ok: true,
					...await client.searchFindings()
				});
			} catch (error) {
				sendJson(res, 502, {
					ok: false,
					error: error instanceof Error ? error.message : "知识库查询失败"
				});
			}
		}
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
/**
* Plugin entry. Returns a Promise so Cordis waits for Data MCP `listTools()`
* before the first model turn — `void mountQingshuiDataMcp(...)` raced the
* first request and left it with 0 MCP tools (review_r1 gap-degraded-ok-001).
*/
async function apply(ctx, config, deps = {}) {
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
	installAnysearchTool(ctx);
	ctx.inject(["webServer"], (webCtx) => {
		const server = webCtx;
		const disposeEvidence = installEvidenceRoute(server, { client: () => client });
		const disposeMarket = installMarketRoute(server, { client: () => client });
		const disposeNews = installNewsRoute(server, { client: () => client });
		const disposeSignals = installSignalRoute(server, { client: () => client });
		const disposeHealth = installHealthRoute(server, { client: () => client });
		const disposeLedger = installLedgerRoute(server, { client: () => client });
		return () => {
			disposeEvidence();
			disposeMarket();
			disposeNews();
			disposeSignals();
			disposeHealth();
			disposeLedger();
		};
	});
	await (deps.mountDataMcp ?? mountQingshuiDataMcp)(ctx, config);
	const skillsDir = resolveSkillsDir();
	if (skillsDir !== void 0) {
		ctx.plugin(deps.skillPlugin ?? skillFilesystem, {
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
