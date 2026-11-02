import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../opencode_tool/convert_document.ts', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '')
  .replace('export default tool(', 'globalThis.wrapper = tool(')
const schema = { string: () => schema, boolean: () => schema, number: () => schema, describe: () => schema, optional: () => schema, default: () => schema }
const tool = Object.assign(value => value, { schema })

test('conversion failure is reported with real line breaks', async () => {
  const context = { tool, path, fs, existsSync: () => false, Bun: { $: () => ({ text: async () => { throw new Error('synthetic failure') } }) } }
  vm.runInNewContext(source, context)
  const result = await context.wrapper.execute({ input_path: '/synthetic/input.xlsx', output_dir: '/synthetic/out', xlsx_max_cells: 10 }, { worktree: '/synthetic' })
  assert.match(result, /^## Conversion Failed\n/)
  assert.match(result, /synthetic failure/)
  assert.doesNotMatch(result, /## Conversion Result/)
})

test('success passes flags and returns the markdown inline', async () => {
  let command
  const fakeFs = {
    existsSync: () => false,
    readFileSync: (file, encoding) => {
      assert.equal(file, '/synthetic/out/in.opencode.md')
      assert.equal(encoding, 'utf-8')
      return '# synthetic markdown'
    },
  }
  const context = {
    tool, path, fs: fakeFs, existsSync: () => false,
    Bun: { $: (_strings, cmd) => { command = cmd; return { text: async () => 'synthetic summary' } } },
  }
  vm.runInNewContext(source, context)
  const result = await context.wrapper.execute({
    input_path: '/synthetic/in.pdf', output_dir: '/synthetic/out',
    extract_images: true, max_page_images: 3, xlsx_max_cells: 10, strict: true,
  }, { worktree: '/synthetic' })
  assert.deepEqual(Array.from(command), [
    'docpipe', 'convert', '--input', '/synthetic/in.pdf', '--out', '/synthetic/out',
    '--format', 'md+json', '--xlsx-max-cells', '10', '--images', '--max-page-images', '3', '--strict',
  ])
  assert.match(result, /^## Conversion Result/)
  assert.ok(result.includes('/synthetic/out/in.opencode.md'))
  assert.ok(result.includes('# synthetic markdown'))
  assert.ok(result.includes('synthetic summary'))
})
