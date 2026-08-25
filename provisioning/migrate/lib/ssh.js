'use strict';
// SSH/SCP transport for migrate-box, shelling out to OpenSSH (proven against the
// RESI box over IPv6 link-local). Two auth modes:
//   - password : bootstrap only. Interactive by default (user types it once); for
//                automation set opts.askpassPassword and we write a throwaway
//                askpass helper. After bootstrap we install a key and never use
//                password again.
//   - key      : silent, non-interactive (-i key -o BatchMode=yes). Used for every
//                step after the key is installed.
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SSH_BIN = process.env.ECO_SSH_BIN || 'ssh';
const SCP_BIN = process.env.ECO_SCP_BIN || 'scp';

const COMMON = [
  // This tool only ever talks to a box on a direct provisioning cable (fixed IP
  // 10.10.10.1, reused across every unit → different host key each time) or over
  // Tailscale. Persisting/checking host keys just produces spurious MITM warnings
  // on that reused IP, so we don't. The link is physically controlled.
  '-o', 'StrictHostKeyChecking=no',
  '-o', 'UserKnownHostsFile=/dev/null',
  '-o', 'LogLevel=ERROR',
  '-o', 'ConnectTimeout=10',
  '-o', 'ServerAliveInterval=5',
  '-o', 'ServerAliveCountMax=3',
];

function askpassEnv(password) {
  // Write a throwaway askpass helper. .sh for msys/OpenSSH-portable; the tool's
  // shipped path uses interactive entry instead, so this is mainly for automation.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eco-askpass-'));
  const script = path.join(dir, 'askpass.sh');
  fs.writeFileSync(script, `#!/bin/sh\nprintf '%s\\n' '${password.replace(/'/g, "'\\''")}'\n`, { mode: 0o700 });
  return {
    env: { ...process.env, SSH_ASKPASS: script, SSH_ASKPASS_REQUIRE: 'force', DISPLAY: process.env.DISPLAY || ':0' },
    cleanup: () => { try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) {} },
  };
}

function authArgs(opts) {
  const a = [];
  if (opts.keyPath) a.push('-o', 'BatchMode=yes', '-o', 'PubkeyAuthentication=yes', '-i', opts.keyPath);
  else a.push('-o', 'PreferredAuthentications=password', '-o', 'PubkeyAuthentication=no', '-o', 'NumberOfPasswordPrompts=1');
  return a;
}

function target(box, user) { return `${user || box.user}@${box.host}`; }

// Run a remote command. Returns {code, stdout, stderr}. Never throws on nonzero.
function run(box, command, opts = {}) {
  const user = opts.user || box.user;
  const args = [...COMMON, ...authArgs(opts), target(box, user), command];
  if (opts.password && !opts.keyPath && opts.interactive !== false && !opts.askpassPassword) {
    // interactive password: inherit stdio so the operator types it once
    const r = spawnSync(SSH_BIN, args, { stdio: 'inherit' });
    return { code: r.status, stdout: '', stderr: '' };
  }
  let env = process.env, cleanup = () => {};
  if (opts.askpassPassword) ({ env, cleanup } = askpassEnv(opts.askpassPassword));
  try {
    const r = spawnSync(SSH_BIN, args, { env, input: '', encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
    return { code: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
  } finally { cleanup(); }
}

// Copy a local file to the box. Returns {code, stderr}.
function put(box, localPath, remotePath, opts = {}) {
  const user = opts.user || box.user;
  const args = [...COMMON, ...authArgs(opts), localPath, `${target(box, user)}:${remotePath}`];
  let env = process.env, cleanup = () => {};
  if (opts.askpassPassword) ({ env, cleanup } = askpassEnv(opts.askpassPassword));
  try {
    const r = spawnSync(SCP_BIN, args, { env, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
    return { code: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
  } finally { cleanup(); }
}

// Run a remote command, STREAMING stdout/stderr live to the caller's onData while
// also capturing it. Returns a Promise<{code, out}>. Used by the wizard so the
// operator watches box scripts run in real time. Password auth uses the askpass
// helper (non-interactive) so it can stream; key auth is silent as usual.
function runStream(box, command, opts = {}, onData = null) {
  const user = opts.user || box.user;
  const args = [...COMMON, ...authArgs(opts), target(box, user), command];
  let env = process.env, cleanup = () => {};
  if (opts.askpassPassword) ({ env, cleanup } = askpassEnv(opts.askpassPassword));
  return new Promise((resolve) => {
    let out = '';
    const p = spawn(SSH_BIN, args, { env, stdio: ['ignore', 'pipe', 'pipe'] });
    const feed = (buf) => { const s = buf.toString(); out += s; if (onData) onData(s); };
    p.stdout.on('data', feed);
    p.stderr.on('data', feed);
    p.on('close', (code) => { cleanup(); resolve({ code, out }); });
    p.on('error', (e) => { cleanup(); resolve({ code: 1, out: out + String(e.message) }); });
  });
}

// Convenience: run and throw with context on failure.
function must(box, command, opts = {}) {
  const r = run(box, command, opts);
  if (r.code !== 0) {
    const err = new Error(`ssh command failed (code ${r.code}): ${command}\n${(r.stderr || r.stdout).trim().slice(0, 500)}`);
    err.result = r;
    throw err;
  }
  return r.stdout;
}

module.exports = { run, put, must, runStream, target };
