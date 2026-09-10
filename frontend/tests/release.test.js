import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { sha, validArtifacts, sourceRevision } = require('../../provisioning/migrate/lib/release.js')

test('installer rejects stale or corrupted application archives', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eco-release-'))
  try {
    const file = path.join(dir, 'backend.tgz'), manifest = path.join(dir, 'release.json')
    fs.writeFileSync(file, 'build A')
    fs.writeFileSync(manifest, JSON.stringify({revision: 'source-a', files: {backend: sha(file)}}))
    assert.equal(validArtifacts(manifest, 'source-a', {backend: file}), true)
    assert.equal(validArtifacts(manifest, 'source-b', {backend: file}), false)
    fs.writeFileSync(file, 'corrupt')
    assert.equal(validArtifacts(manifest, 'source-a', {backend: file}), false)
  } finally { fs.rmSync(dir, {recursive: true, force: true}) }
})

test('source revision is deterministic and covers current source', () => {
  const repo = path.resolve(import.meta.dirname, '../..')
  const revision = sourceRevision(repo)
  assert.match(revision, /^[a-f0-9]{64}$/)
  assert.equal(sourceRevision(repo), revision)
})
