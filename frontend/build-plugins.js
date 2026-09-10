import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'
function sources(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? sources(join(dir, e.name)) : /\.(vue|js)$/.test(e.name) ? [readFileSync(join(dir, e.name), 'utf8')] : []).join('\n')
}
const pascal = s => s.replace(/(^|-)(\w)/g, (_, dash, c) => c.toUpperCase())
export function smallUI() {
  return {
    name: 'eco-small-ui',
    resolveId(id) { if (id.startsWith('virtual:eco-')) return '\0' + id },
    async load(id) {
      if (!id.startsWith('\0virtual:eco-')) return
      const text = sources(new URL('./src', import.meta.url).pathname.replace(/^\/(\w:)/, '$1'))
      if (id.endsWith('components')) {
        const names = [...new Set([...text.matchAll(/<\/?(v-[a-z-]+)\b/g)].map(m => pascal(m[1])))].filter(n => n !== 'VModel' && n !== 'VSlot')
        return `import { ${names.join(',')} } from 'vuetify/components'; export const components = {${names.join(',')}}`
      }
      const aliases = readFileSync(new URL('./node_modules/vuetify/lib/iconsets/mdi.js', import.meta.url), 'utf8')
      const names = [...new Set([...`${text}\n${aliases}`.matchAll(/mdi-[a-z0-9]+(?:-[a-z0-9]+)*/g)].map(m => m[0]))]
      const mdi = await import('@mdi/js')
      const valid = names.filter(n => mdi['mdi' + pascal(n.slice(4))])
      return `import {${valid.map(n => 'mdi' + pascal(n.slice(4))).join(',')}} from '@mdi/js'; export default {${valid.map(n => `${JSON.stringify(n)}:mdi${pascal(n.slice(4))}`).join(',')}}`
    },
    writeBundle(options, bundle) {
      // Vite replaces preload markers late in generateBundle. Compress only
      // finalized bytes on disk, or lazy routes receive invalid JavaScript.
      for (const name of Object.keys(bundle)) {
        if (!/\.(js|css|html|svg)$/.test(name)) continue
        const file = join(options.dir, name)
        writeFileSync(file + '.gz', gzipSync(readFileSync(file), { level: 9 }))
      }
    }
  }
}
