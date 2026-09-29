#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const dshDir = resolve(repoRoot, 'dsh')
const generatedDir = join(tmpdir(), 'qingshui-patches', String(process.pid))

function materializePatch(file) {
  let text
  try {
    text = readFileSync(file, 'utf8')
  } catch {
    return file
  }
  if (!text.includes('$REPO_ROOT')) return file
  mkdirSync(generatedDir, { recursive: true })
  const out = join(generatedDir, basename(file))
  writeFileSync(out, text.split('$REPO_ROOT').join(repoRoot))
  return out
}

const raw = process.argv.slice(2)
const args = []
for (let i = 0; i < raw.length; i += 1) {
  const arg = raw[i]
  if (arg === '--patch' && i + 1 < raw.length) {
    args.push('--patch', materializePatch(resolve(process.cwd(), raw[i + 1])))
    i += 1
    continue
  }
  if (arg.startsWith('--patch=')) {
    args.push(`--patch=${materializePatch(resolve(process.cwd(), arg.slice('--patch='.length)))}`)
    continue
  }
  args.push(arg)
}

const child = spawn(process.execPath, ['--import', 'tsx/esm', 'dsh/apps/cli/src/bin.ts', ...args], {
  cwd: repoRoot,
  env: { ...process.env, TSX_TSCONFIG_PATH: join(dshDir, 'tsconfig.json') },
  stdio: 'inherit',
})

child.on('error', (error) => {
  process.stderr.write(`dsh launcher: ${error.message}\n`)
  process.exit(1)
})

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal)
  else process.exit(code ?? 0)
})
