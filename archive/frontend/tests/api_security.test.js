/**
 * API 安全测试
 * 检测硬编码密钥和 API Key 配置问题
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

describe("API Security - API Key 配置", () => {
  // 获取当前文件目录
  const currentDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const apiFilePath = resolve(currentDir, "./src/api/index.js");

  /**
   * 测试 API Key 必须从环境变量读取，不能有硬编码 fallback
   */
  it("API Key 不应该有硬编码的 fallback 值", () => {
    const content = readFileSync(apiFilePath, "utf-8");

    // 检测是否有硬编码的 API Key (sk-V- 开头)
    const hasHardcodedKey = content.includes("sk-V-");

    // 如果找到硬编码 key，测试应该失败
    expect(hasHardcodedKey, `发现硬编码 API Key`).toBe(false);
  });

  /**
   * 测试 API Key 应该从 import.meta.env 读取（但不应该是唯一来源）
   */
  it("API Key 应该从 import.meta.env 读取", () => {
    const content = readFileSync(apiFilePath, "utf-8");

    // 应该包含从环境变量读取的逻辑
    const hasEnvImport = content.includes("import.meta.env");
    const hasApiKeyHeader = content.includes("config.headers['x-api-key']");

    expect(hasEnvImport).toBe(true);
    expect(hasApiKeyHeader).toBe(true);
  });

  /**
   * 测试 API Key 环境变量名应该是强制的（VITE_API_KEY）
   */
  it("环境变量名应该是 VITE_API_KEY（Vite 约定）", () => {
    const content = readFileSync(apiFilePath, "utf-8");

    // 应该使用 VITE_API_KEY 而不是其他名称
    const usesVitePrefix = content.includes("VITE_API_KEY");

    expect(usesVitePrefix).toBe(true);
  });
});
