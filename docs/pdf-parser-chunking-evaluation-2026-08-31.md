# PDF 解析与 Evidence 切分评测

## 已执行测试

- 服务器：`124.221.188.38`
- 样本：真实研报 PDF 100 份，共 2,615 页
- 基线：线上 PyMuPDF + SmartChunker
- 评测时间：2026-08-31

## 结果

| 指标 | 结果 |
|---|---:|
| 成功解析文件 | 100/100 |
| 平均解析耗时 | 20.19 秒/100 份 |
| 平均 chunks/文件 | 5.92 |
| chunks/文件中位数 | 4 |
| 平均 tokens/文件 | 19,392 |
| P95 最大 chunk | 6,000 |
| 超过 6,000 tokens | 0 |
| 单 chunk 短文档 | 8/100 |

## 当前生产切分方式

章节识别 → 段落聚合 → 超长章节按段落/句子切分 → token 窗口安全阀。

最终安全阀保证每个 chunk 的 `tokens <= 6000`，已同步服务器并通过合成超长文本测试。

## 结论与限制

当前方案适合文本型研报，且速度快、资源占用低。短文档保留单 chunk 是总文本小于上限时的预期行为。

尚未完成 Docling/MinerU 的实测对照：服务器无 GPU、内存约 7.5GB，完整安装会拉取 CUDA/Triton 依赖。还缺少人工标注的问答/字段 ground truth，因此暂不能严谨计算检索 Recall@k 或 LLM 抽取准确率。

后续对照应在 CPU-only 或 GPU 机器上进行，并保留页码、bbox、section_path、block_type 等 metadata。

## 轻量解析器对照（3 份真实研报，前 3 页）

| 工具 | 解析耗时/份 | 输出特征 | 表格能力 |
|---|---:|---|---|
| PyMuPDF | 0.11–0.30 秒 | 纯文本，速度最快 | 需自行重建 |
| PyMuPDF4LLM | 1.95–2.85 秒 | Markdown 标题/段落，适合 LLM | 表格转 Markdown，需抽样校验 |
| pdfplumber | 已安装 | 逐页文本和 `extract_tables()` | 可定位表格，但速度较慢、版式需调参 |

结论：对于“只有文字和表格”的公告 PDF，推荐 PyMuPDF4LLM 作为结构化解析层，PyMuPDF 作为快速 fallback；pdfplumber 仅对检测到表格的页面路由调用，不建议全量替换。
