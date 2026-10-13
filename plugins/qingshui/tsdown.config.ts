import { join } from 'node:path'
import { defineConfig } from 'tsdown'

const here = import.meta.dirname

const PLATFORM_EXTERNALS = [
  'react',
  'react/jsx-runtime',
  'react-dom',
  'react-dom/client',
  '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-ui-slots',
  '@deepseek-ai/dsh-client-ui-primitives',
]

export default defineConfig([
  {
    entry: [join(here, 'src/index.ts')],
    outDir: join(here, 'lib'),
    format: ['esm'],
    platform: 'node',
    dts: false,
    external: [/^@deepseek-ai\//, /^node:/],
  },
  {
    entry: { client: join(here, 'src/client/index.ts') },
    outDir: join(here, 'lib'),
    format: ['cjs'],
    platform: 'browser',
    dts: false,
    minify: true,
    external: PLATFORM_EXTERNALS,
    // The browser sandbox has no `process`; fold echarts/zrender's
    // dev-vs-prod branches at build time (client bundle only).
    define: { 'process.env.NODE_ENV': '"production"' },
    deps: {
      // Browser host provides only PLATFORM_EXTERNALS via ModuleLoader;
      // everything else the client imports (echarts graph) must be inlined.
      alwaysBundle: [/^echarts(\/.*)?$/, /^zrender(\/.*)?$/, /^tslib(\/.*)?$/],
    },
    outputOptions: {
      entryFileNames: 'client.js',
      sourcemap: true,
      banner: 'window.__ModuleLoader__.load({ id: "qingshui", factory: (require) => {',
      intro: 'var module = { exports: {} }; var exports = module.exports;',
      footer: 'return module.exports; } });',
    },
  },
])
