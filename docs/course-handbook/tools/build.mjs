// Parse the one Markdown source and rasterize its editable SVG figures.
// Packages come from the bundled runtime; no npm install or project edits.
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'

const here = path.dirname(fileURLToPath(import.meta.url))
const bookDir = path.resolve(here, '..')
const buildDir = path.join(bookDir, '.build')
const deps = process.env.HANDBOOK_NODE_MODULES || path.join(
  process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules',
)
const req = createRequire(path.join(deps, 'package.json'))
const { marked } = await import(pathToFileURL(req.resolve('marked')).href)
const sharp = req('sharp')
await fs.mkdir(path.join(buildDir, 'images'), { recursive: true })
const markdown = await fs.readFile(path.join(bookDir, 'AI-Agent课程知识手册.md'), 'utf8')
await fs.writeFile(path.join(buildDir, 'tokens.json'), JSON.stringify(marked.lexer(markdown)), 'utf8')
for (const name of (await fs.readdir(path.join(bookDir, 'assets'))).filter(n => n.endsWith('.svg'))) {
  await sharp(path.join(bookDir, 'assets', name), { density: 200 })
    .png().toFile(path.join(buildDir, 'images', name.replace(/\.svg$/, '.png')))
}
const python = process.env.HANDBOOK_PYTHON || path.join(
  process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
)
const result = spawnSync(python, ['-X', 'utf8', '-B', path.join(here, 'build_pdf.py')], {
  stdio: 'inherit', cwd: bookDir,
})
if (result.error) throw result.error
process.exit(result.status ?? 1)
