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
    external: PLATFORM_EXTERNALS,
    outputOptions: {
      entryFileNames: 'client.js',
      sourcemap: true,
      banner: 'window.__ModuleLoader__.load({ id: "qingshui", factory: (require) => {',
      intro: 'var module = { exports: {} }; var exports = module.exports;',
      footer: 'return module.exports; } });',
    },
  },
])
