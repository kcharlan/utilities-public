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
