'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
function sha(file) {
  const hash = crypto.createHash('sha256'), fd = fs.openSync(file, 'r'), buffer = Buffer.alloc(1024 * 1024);
  try { let n; while ((n = fs.readSync(fd, buffer, 0, buffer.length, null))) hash.update(buffer.subarray(0, n)); }
  finally { fs.closeSync(fd); }
  return hash.digest('hex');
}
function sourceRevision(repo) {
  const hash = crypto.createHash('sha256');
  function visit(relative) {
    const absolute = path.join(repo, relative);
    if (fs.statSync(absolute).isDirectory()) {
      for (const name of fs.readdirSync(absolute).sort()) {
        if (!['__pycache__', 'node_modules', 'dist'].includes(name)) visit(`${relative}/${name}`);
      }
    } else if (!relative.endsWith('.pyc')) {
      hash.update(relative + '\0'); hash.update(fs.readFileSync(absolute));
    }
  }
  for (const entry of ['backend/app', 'frontend/src', 'frontend/package.json', 'frontend/package-lock.json',
    'frontend/index.html', 'frontend/vite.config.js', 'frontend/build-plugins.js', 'frontend/check-build.js',
    'gateway/extensions', 'tools/prepare-live-telemetry.py', 'provisioning/migrate/box',
    'provisioning/migrate/tui.js', 'provisioning/migrate/lib', 'provisioning/device-maps.js',
    'provisioning/generate-connector.js', 'provisioning/migrate/build-gw-config.js']) visit(entry);
  return hash.digest('hex');
}
function validArtifacts(manifestFile, revision, files) {
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
    return manifest.revision === revision && Object.entries(files).every(([key, file]) =>
      fs.existsSync(file) && manifest.files[key] === sha(file));
  } catch { return false; }
}
module.exports = { sha, sourceRevision, validArtifacts };
