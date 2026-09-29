import { join } from 'node:path'
import { defineConfig } from 'tsdown'

const here = import.meta.dirname

export default defineConfig([
  {
    entry: [join(here, 'src/index.ts')],
    outDir: join(here, 'lib'),
    format: ['esm'],
    platform: 'node',
    dts: false,
    external: [/^@deepseek-ai\//, /^node:/],
  },
])
