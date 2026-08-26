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

// On Windows we MUST use the native OpenSSH (System32\OpenSSH), not the Git-Bash/MSYS
// ssh: only the native client understands a Windows IPv6 zone id (fe80::…%37), which is
// exactly how a factory RESI box is reached before 10.10.10.1 exists. Verified live:
// MSYS ssh times out on %37, native ssh connects.
function winTool(exe) {
  if (os.platform() !== 'win32') return null;
  const p = path.join(process.env.WINDIR || 'C:\\Windows', 'System32', 'OpenSSH', exe);
  return fs.existsSync(p) ? p : null;
}
const SSH_BIN = process.env.ECO_SSH_BIN || winTool('ssh.exe') || 'ssh';
const SCP_BIN = process.env.ECO_SCP_BIN || winTool('scp.exe') || 'scp';
const USE_WIN_SSH = /System32[\\/]OpenSSH/i.test(SSH_BIN);
const NULL_DEV = USE_WIN_SSH ? 'NUL' : '/dev/null';

const COMMON = [
  // This tool only ever talks to a box on a direct provisioning cable (link-local, then
  // the fixed IP 10.10.10.1 reused across every unit → different host key each time) or
  // over Tailscale. Persisting/checking host keys just produces spurious MITM warnings
  // on that reused IP, so we don't. The link is physically controlled.
  '-o', 'StrictHostKeyChecking=no',
  '-o', 'UserKnownHostsFile=' + NULL_DEV,
  '-o', 'LogLevel=ERROR',
  '-o', 'ConnectTimeout=10',
  '-o', 'ServerAliveInterval=5',
  '-o', 'ServerAliveCountMax=3',
];

// IPv6 link-local NDP goes stale within seconds and the neighbour drops to a zero MAC,
// after which TCP to it just times out (ping still "works" only while the entry is fresh).
// So re-resolve the neighbour with a single ping immediately before every ssh/scp.
function primeNdp(host) {
  if (!/^fe80:.*%.+$/i.test(host || '')) return;   // only link-local scoped addresses
  try {
    if (os.platform() === 'win32') spawnSync('ping', ['-6', '-n', '1', '-w', '800', host], { stdio: 'ignore' });
    else spawnSync('ping', ['-6', '-c', '1', '-W', '1', host], { stdio: 'ignore' });
  } catch (_) {}
}

// escape a string for `echo <s>` inside a .bat (delayed expansion off)
function batchEchoEscape(s) {
  return String(s).replace(/%/g, '%%').replace(/[\^&<>|()!]/g, ch => '^' + ch);
}

// ---------- transient-failure retry ----------
// The provisioning cable link flaps (eth0 DHCP-retry loop, link-local NDP staleness), so a
// connection can time out or drop mid-handshake even though the box is fine seconds later.
// Retry ONLY on connection-level failures — never on auth failures or a command's own
// nonzero exit. The box scripts are idempotent (the wizard re-runs by design), so re-running
// after a dropped connection is safe.
const DEFAULT_RETRIES = 4;
function isConnError(code, text) {
  if (code === 0) return false;
  return /Connection (timed out|closed|refused|reset)|kex_exchange_identification|banner exchange|Broken pipe|Timeout, server|Operation timed out|No route to host|Host is down|Network is unreachable|client_loop: send disconnect|Connection to .* closed/i.test(text || '');
}
function backoffMs(attempt) { return Math.min(8000, 1500 + attempt * 1500); }  // 1.5,3,4.5,6,7.5…
function sleepSync(ms) { try { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, Math.max(0, ms | 0)); } catch (_) {} }
function sleepAsync(ms) { return new Promise(r => setTimeout(r, ms)); }

function askpassEnv(password) {
  // Throwaway askpass helper. Windows native ssh cannot exec a .sh, so on Windows we write
  // a .bat that echoes the password (verified against the live RESI box); elsewhere a .sh.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eco-askpass-'));
  let script;
  if (os.platform() === 'win32') {
    script = path.join(dir, 'askpass.bat');
    fs.writeFileSync(script, `@echo off\r\necho ${batchEchoEscape(password)}\r\n`);
  } else {
    script = path.join(dir, 'askpass.sh');
    fs.writeFileSync(script, `#!/bin/sh\nprintf '%s\\n' '${password.replace(/'/g, "'\\''")}'\n`, { mode: 0o700 });
  }
  return {
    env: { ...process.env, SSH_ASKPASS: script, SSH_ASKPASS_REQUIRE: 'force', DISPLAY: process.env.DISPLAY || 'localhost:0' },
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
// scp needs an IPv6 literal bracketed so its colons aren't read as host:path
function scpTarget(box, user) {
  const h = box.host.includes(':') ? `[${box.host}]` : box.host;
  return `${user || box.user}@${h}`;
}

// Run a remote command. Returns {code, stdout, stderr}. Never throws on nonzero.
// Retries on connection-level failures (opts.retries, default 4; pass 0 to fail fast).
function run(box, command, opts = {}) {
  const user = opts.user || box.user;
  // interactive password (operator types once): no askpass, no retry
  if (opts.password && !opts.keyPath && opts.interactive !== false && !opts.askpassPassword) {
    primeNdp(box.host);
    const args = [...COMMON, ...authArgs(opts), target(box, user), command];
    const r = spawnSync(SSH_BIN, args, { stdio: 'inherit' });
    return { code: r.status, stdout: '', stderr: '' };
  }
  const retries = opts.retries != null ? opts.retries : DEFAULT_RETRIES;
  let last = { code: 1, stdout: '', stderr: '' };
  for (let attempt = 0; attempt <= retries; attempt++) {
    primeNdp(box.host);
    const args = [...COMMON, ...authArgs(opts), target(box, user), command];
    let env = process.env, cleanup = () => {};
    if (opts.askpassPassword) ({ env, cleanup } = askpassEnv(opts.askpassPassword));
    try {
      const r = spawnSync(SSH_BIN, args, { env, input: '', encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
      last = { code: r.status == null ? 1 : r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
    } finally { cleanup(); }
    if (attempt === retries || !isConnError(last.code, last.stderr + last.stdout)) return last;
    sleepSync(backoffMs(attempt));
  }
  return last;
}

// Copy a local file to the box. Returns {code, stderr}. Retries on connection failures.
function put(box, localPath, remotePath, opts = {}) {
  const user = opts.user || box.user;
  const retries = opts.retries != null ? opts.retries : DEFAULT_RETRIES;
  let last = { code: 1, stdout: '', stderr: '' };
  for (let attempt = 0; attempt <= retries; attempt++) {
    primeNdp(box.host);
    const args = [...COMMON, ...authArgs(opts), localPath, `${scpTarget(box, user)}:${remotePath}`];
    let env = process.env, cleanup = () => {};
    if (opts.askpassPassword) ({ env, cleanup } = askpassEnv(opts.askpassPassword));
    try {
      const r = spawnSync(SCP_BIN, args, { env, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
      last = { code: r.status == null ? 1 : r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
    } finally { cleanup(); }
    if (attempt === retries || !isConnError(last.code, last.stderr + last.stdout)) return last;
    sleepSync(backoffMs(attempt));
  }
  return last;
}

// Copy a local file to the box, ASYNC (spawn, non-blocking) so the caller can animate a
// progress bar on the event loop while the transfer runs. scp gives us no byte-level
// progress without a TTY, so the caller estimates; this just needs to not block. Retries
// on connection failures like put(). Returns a Promise<{code, stderr}>.
function putStream(box, localPath, remotePath, opts = {}) {
  const user = opts.user || box.user;
  const retries = opts.retries != null ? opts.retries : DEFAULT_RETRIES;
  return (async () => {
    let last = { code: 1, stderr: '' };
    for (let attempt = 0; attempt <= retries; attempt++) {
      primeNdp(box.host);
      const args = [...COMMON, ...authArgs(opts), localPath, `${scpTarget(box, user)}:${remotePath}`];
      let env = process.env, cleanup = () => {};
      if (opts.askpassPassword) ({ env, cleanup } = askpassEnv(opts.askpassPassword));
      last = await new Promise((resolve) => {
        let err = '';
        const p = spawn(SCP_BIN, args, { env, stdio: ['ignore', 'ignore', 'pipe'] });
        p.stderr.on('data', (b) => { err += b.toString(); });
        p.on('close', (code) => { cleanup(); resolve({ code: code == null ? 1 : code, stderr: err }); });
        p.on('error', (e) => { cleanup(); resolve({ code: 1, stderr: err + String(e.message) }); });
      });
      if (attempt === retries || !isConnError(last.code, last.stderr)) return last;
      await sleepAsync(backoffMs(attempt));
    }
    return last;
  })();
}

// Run a remote command, STREAMING stdout/stderr live to the caller's onData while
// also capturing it. Returns a Promise<{code, out}>. Used by the wizard so the
// operator watches box scripts run in real time. Password auth uses the askpass
// helper (non-interactive) so it can stream; key auth is silent as usual.
async function runStream(box, command, opts = {}, onData = null) {
  const user = opts.user || box.user;
  const retries = opts.retries != null ? opts.retries : DEFAULT_RETRIES;
  let last = { code: 1, out: '' };
  for (let attempt = 0; attempt <= retries; attempt++) {
    primeNdp(box.host);
    const args = [...COMMON, ...authArgs(opts), target(box, user), command];
    let env = process.env, cleanup = () => {};
    if (opts.askpassPassword) ({ env, cleanup } = askpassEnv(opts.askpassPassword));
    last = await new Promise((resolve) => {
      let out = '';
      const p = spawn(SSH_BIN, args, { env, stdio: ['ignore', 'pipe', 'pipe'] });
      const feed = (buf) => { const s = buf.toString(); out += s; if (onData) onData(s); };
      p.stdout.on('data', feed);
      p.stderr.on('data', feed);
      p.on('close', (code) => { cleanup(); resolve({ code, out }); });
      p.on('error', (e) => { cleanup(); resolve({ code: 1, out: out + String(e.message) }); });
    });
    if (attempt === retries || !isConnError(last.code, last.out)) return last;
    if (onData) onData(`\n  [link dropped — retrying (${attempt + 1}/${retries}) in ${Math.round(backoffMs(attempt) / 1000)}s…]\n`);
    await sleepAsync(backoffMs(attempt));
  }
  return last;
}

// Liveness probe that needs NO credentials: ask the box to authenticate with "none",
// which a running sshd rejects with "Permission denied (publickey,password)". That
// rejection proves an sshd is answering, so discovery can identify the box over a flaky
// IPv6 link-local address before we know whether password/key auth will succeed. A real
// network failure (timeout / no route / unresolved) gives a different error and code.
// Returns {alive, out}. ConnectTimeout from COMMON bounds it.
function probe(box, opts = {}) {
  const user = opts.user || box.user || 'resi';
  const ct = opts.connectTimeout || 6;
  const retries = opts.retries != null ? opts.retries : 1;   // one retry: NDP may flap
  let out = '';
  for (let attempt = 0; attempt <= retries; attempt++) {
    primeNdp(box.host);
    // ConnectTimeout first: ssh uses the first value seen, so this overrides COMMON's 10s
    const args = ['-o', 'ConnectTimeout=' + ct, ...COMMON, '-o', 'BatchMode=yes',
      '-o', 'PreferredAuthentications=none', '-o', 'PubkeyAuthentication=no', target(box, user), 'true'];
    const r = spawnSync(SSH_BIN, args, { encoding: 'utf8' });
    out = (r.stderr || '') + (r.stdout || '');
    if (r.status === 0 || /Permission denied|authenticat|publickey|password|Too many/i.test(out)) return { alive: true, out };
    if (attempt < retries) sleepSync(700);
  }
  return { alive: false, out };
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

module.exports = { run, put, putStream, must, runStream, probe, target };
