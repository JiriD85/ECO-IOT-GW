import { readFileSync, readdirSync, statSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import assert from 'node:assert/strict'
const files = readdirSync('dist/assets')
for (const file of files.filter(f => f.endsWith('.gz'))) {
  assert.deepEqual(gunzipSync(readFileSync('dist/assets/' + file)), readFileSync('dist/assets/' + file.slice(0, -3)), `${file}: compressed bytes must match final build`)
}
const entry = files.filter(f => /^(index-.*\.(js|css)|Dashboard-.*\.js|_plugin-vue_export-helper-.*\.js)\.gz$/.test(f))
const bytes = entry.reduce((sum, f) => sum + statSync('dist/assets/' + f).size, 0)
assert(bytes < 100000, `Dashboard exceeds 100 KB compressed budget: ${bytes}`)
assert(!files.some(f => /\.(woff2?|ttf|eot)$/.test(f)), 'Unexpected icon font')
console.log(`Dashboard JS + CSS: ${(bytes / 1000).toFixed(1)} KB compressed. All gzip files match their originals.`)
