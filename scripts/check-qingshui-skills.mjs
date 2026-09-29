#!/usr/bin/env node
/**
 * Factory gate: plugins/qingshui/skills must contain parseable divergence-mining.
 * Catches YAML frontmatter regressions (unquoted "EV:" previously broke discovery).
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const packageRoot = join(here, '..', 'plugins', 'qingshui')
const skillsRoot = join(packageRoot, 'skills')
const EXPECTED = ['divergence-mining']
const NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

const require = createRequire(join(here, '..', 'dsh', 'packages', 'skill', 'skill-filesystem', 'package.json'))
const { parse: parseYaml } = require('yaml')

function parseFrontmatter(text) {
  const lines = text.split(/\r?\n/)
  if ((lines[0] ?? '').trim() !== '---') return null
  let end = -1
  for (let i = 1; i < lines.length; i += 1) {
    if (lines[i].trim() === '---') {
      end = i
      break
    }
  }
  if (end === -1) return null
  return parseYaml(lines.slice(1, end).join('\n'))
}

function main() {
  if (!existsSync(skillsRoot)) {
    console.error(`missing skills root: ${skillsRoot}`)
    process.exit(1)
  }
  const found = []
  for (const entry of readdirSync(skillsRoot)) {
    const dir = join(skillsRoot, entry)
    if (!statSync(dir).isDirectory()) continue
    const skillMd = join(dir, 'SKILL.md')
    if (!existsSync(skillMd)) {
      console.error(`skill dir without SKILL.md: ${entry}`)
      process.exit(1)
    }
    if (!NAME_RE.test(entry)) {
      console.error(`invalid skill directory name: ${entry}`)
      process.exit(1)
    }
    let parsed
    try {
      parsed = parseFrontmatter(readFileSync(skillMd, 'utf8'))
    } catch (error) {
      console.error(`YAML frontmatter parse failed for ${entry}: ${error.message}`)
      process.exit(1)
    }
    if (!parsed || typeof parsed !== 'object') {
      console.error(`missing frontmatter for ${entry}`)
      process.exit(1)
    }
    if (parsed.name !== entry) {
      console.error(`frontmatter name "${parsed.name}" !== dir "${entry}"`)
      process.exit(1)
    }
    if (typeof parsed.description !== 'string' || parsed.description.length === 0) {
      console.error(`missing description for ${entry}`)
      process.exit(1)
    }
    found.push(entry)
  }
  for (const name of EXPECTED) {
    if (!found.includes(name)) {
      console.error(`expected skill missing: ${name}`)
      process.exit(1)
    }
  }
  console.log(`ok: ${found.length} skill(s) — ${found.join(', ')}`)
}

main()
