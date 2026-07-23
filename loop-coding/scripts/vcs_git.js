#!/usr/bin/env node

/**
 * VCS implementation for loop-coding.
 *
 * Supports Git and a conservative TFS command subset. TFS check-in is
 * intentionally not implemented; loop-coding may checkout, inspect, undo, and
 * shelve/unshelve, but must never submit changes automatically.
 */

const { execFileSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

function run(bin, args, opts = {}) {
  try {
    return execFileSync(bin, args, {
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe'],
      cwd: opts.cwd || process.cwd(),
      timeout: opts.timeout || 30000
    }).trim();
  } catch (err) {
    if (opts.throw !== false) {
      const e = new Error(`${bin} ${args.join(' ')} failed: ${err.stderr?.trim() || err.message}`);
      e.exitCode = err.status;
      throw e;
    }
    return null;
  }
}

function git(args, opts = {}) {
  return run('git', args, opts);
}

function tf(args, opts = {}) {
  return run('tf', args, opts);
}

function normalizePath(file) {
  return String(file || '').replace(/\\/g, '/').replace(/^\.\//, '');
}

function fileHash(filePath, cwd) {
  try {
    const abs = path.resolve(cwd || process.cwd(), filePath);
    const content = fs.readFileSync(abs);
    return `sha256:${crypto.createHash('sha256').update(content).digest('hex').slice(0, 16)}`;
  } catch {
    return null;
  }
}

function uniqueSorted(files) {
  return [...new Set(files.map(normalizePath).filter(Boolean))].sort();
}

// ── Git ──────────────────────────────────────────────────

function gitSnapshot(opts = {}) {
  const cwd = opts.cwd || process.cwd();
  const commitHash = git(['rev-parse', 'HEAD'], { cwd, throw: false });
  const dirty = git(['status', '--porcelain'], { cwd, throw: false }) || '';
  const localChanges = dirty
    ? dirty.split('\n').filter(Boolean).map(line => line.slice(3).trim())
    : [];

  const changedFileHashes = {};
  for (const file of localChanges) {
    const hash = fileHash(file, cwd);
    if (hash) changedFileHashes[normalizePath(file)] = hash;
  }

  return {
    type: 'git',
    commitHash: commitHash || undefined,
    localChanges: uniqueSorted(localChanges),
    changedFileHashes,
    timestamp: new Date().toISOString()
  };
}

function gitChangedFilesSince(snap, opts = {}) {
  const cwd = opts.cwd || process.cwd();

  if (!snap || !snap.commitHash) {
    const all = git(['ls-files', '--cached', '--others', '--exclude-standard'], { cwd, throw: false }) || '';
    return uniqueSorted(all.split('\n'));
  }

  const committed = git(['diff', '--name-only', snap.commitHash, 'HEAD'], { cwd, throw: false }) || '';
  const uncommitted = git(['diff', '--name-only', 'HEAD'], { cwd, throw: false }) || '';
  const untracked = git(['ls-files', '--others', '--exclude-standard'], { cwd, throw: false }) || '';
  const fileSet = new Set(uniqueSorted([...committed.split('\n'), ...uncommitted.split('\n'), ...untracked.split('\n')]));

  if (snap.changedFileHashes) {
    for (const [file, oldHash] of Object.entries(snap.changedFileHashes)) {
      if (fileHash(file, cwd) === oldHash) fileSet.delete(normalizePath(file));
    }
  }

  return [...fileSet].sort();
}

function gitRestore(snap, opts = {}) {
  const cwd = opts.cwd || process.cwd();
  if (!snap?.commitHash) return { success: false, message: 'no commitHash in snapshot, cannot restore' };

  const dirtyBefore = (git(['status', '--porcelain'], { cwd, throw: false }) || '').length > 0;
  if (dirtyBefore) {
    git(['stash', 'push', '-u', '-m', 'loop-coding: auto-stash before restore'], { cwd, throw: false });
  }

  const result = git(['checkout', snap.commitHash, '--', '.'], { cwd, throw: false });
  if (result === null) return { success: false, message: `git checkout ${snap.commitHash} failed` };

  return {
    success: true,
    message: `restored to ${snap.commitHash}${dirtyBefore ? ' (previous changes stashed)' : ''}`
  };
}

function gitIsDirty(opts = {}) {
  const status = git(['status', '--porcelain'], { cwd: opts.cwd || process.cwd(), throw: false }) || '';
  return status.length > 0;
}

function gitStashPush(message, opts = {}) {
  const cwd = opts.cwd || process.cwd();
  git(['stash', 'push', '-u', '-m', String(message || 'loop-coding stash')], { cwd });
  const ref = git(['stash', 'list', '--format=%gd%n%H'], { cwd, throw: false });
  return ref ? ref.split('\n')[0] : 'stash@{0}';
}

function gitStashRestore(ref, opts = {}) {
  git(['stash', 'pop', ref], { cwd: opts.cwd || process.cwd() });
}

// ── TFS ──────────────────────────────────────────────────

function parseTfStatus(output) {
  const files = [];
  for (const line of String(output || '').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || /^(\$\/|Local|User|Workspace|There are no pending changes)/i.test(trimmed)) continue;

    const match = trimmed.match(/^(?:edit|add|delete|rename|branch|merge|lock|rollback|undelete|encoding|type)\s+(.+)$/i);
    if (match) files.push(match[1].trim());
  }
  return uniqueSorted(files);
}

function tfsStatus(opts = {}) {
  return tf(['status', '/recursive'], { cwd: opts.cwd || process.cwd(), throw: false }) || '';
}

function tfsSnapshot(opts = {}) {
  const cwd = opts.cwd || process.cwd();
  const status = tfsStatus({ cwd });
  const localChanges = parseTfStatus(status);
  const changedFileHashes = {};
  for (const file of localChanges) {
    const hash = fileHash(file, cwd);
    if (hash) changedFileHashes[normalizePath(file)] = hash;
  }

  return {
    type: 'tfs',
    changeset: opts.changeset || undefined,
    localChanges,
    changedFileHashes,
    timestamp: new Date().toISOString()
  };
}

function tfsChangedFilesSince(snap, opts = {}) {
  const cwd = opts.cwd || process.cwd();
  const current = new Set(parseTfStatus(tfsStatus({ cwd })));
  const baseline = new Set((snap?.localChanges || []).map(normalizePath));

  for (const file of baseline) {
    if (!snap?.changedFileHashes || fileHash(file, cwd) === snap.changedFileHashes[file]) {
      current.delete(file);
    }
  }

  return [...current].sort();
}

function tfsIsDirty(opts = {}) {
  return parseTfStatus(tfsStatus({ cwd: opts.cwd || process.cwd() })).length > 0;
}

function tfsLogin(opts = {}) {
  const args = ['login'];
  if (opts.collection) args.push(`/collection:${opts.collection}`);
  const out = tf(args, { cwd: opts.cwd || process.cwd(), throw: false });
  return {
    success: out !== null,
    message: out === null ? 'tf login failed' : out
  };
}

function tfsCheckout(files, opts = {}) {
  const list = Array.isArray(files) ? files : [files];
  if (list.length === 0 || list.every(file => !file)) {
    return { success: false, message: 'no files to checkout' };
  }
  const out = tf(['checkout', ...list], { cwd: opts.cwd || process.cwd(), throw: false });
  return { success: out !== null, message: out === null ? 'tf checkout failed' : out };
}

function tfsUndo(files, opts = {}) {
  const cwd = opts.cwd || process.cwd();
  const list = Array.isArray(files) ? files : [files];
  const args = list.length > 0 && list.some(Boolean)
    ? ['undo', ...list, '/recursive']
    : ['undo', '.', '/recursive'];
  const out = tf(args, { cwd, throw: false });
  return { success: out !== null, message: out === null ? 'tf undo failed' : out };
}

function tfsRestore(snap, opts = {}) {
  void snap;
  return tfsUndo([], opts);
}

function tfsStashPush(message, opts = {}) {
  const name = opts.name || `loop-coding-${Date.now()}`;
  tf(['shelve', name, '/replace', `/comment:${String(message || 'loop-coding shelve')}`], {
    cwd: opts.cwd || process.cwd()
  });
  return name;
}

function tfsStashRestore(ref, opts = {}) {
  tf(['unshelve', ref], { cwd: opts.cwd || process.cwd() });
}

// ── Unified API ──────────────────────────────────────────

function detect(cwd) {
  const root = cwd || process.cwd();
  if (fs.existsSync(path.join(root, '.git'))) return 'git';
  if (fs.existsSync(path.join(root, '.tf'))) return 'tfs';
  return 'other';
}

function snapshot(opts = {}) {
  return detect(opts.cwd) === 'tfs' ? tfsSnapshot(opts) : gitSnapshot(opts);
}

function changedFilesSince(snap, opts = {}) {
  return snap?.type === 'tfs' ? tfsChangedFilesSince(snap, opts) : gitChangedFilesSince(snap, opts);
}

function restore(snap, opts = {}) {
  return snap?.type === 'tfs' ? tfsRestore(snap, opts) : gitRestore(snap, opts);
}

function isDirty(opts = {}) {
  return detect(opts.cwd) === 'tfs' ? tfsIsDirty(opts) : gitIsDirty(opts);
}

function stashPush(message, opts = {}) {
  return detect(opts.cwd) === 'tfs' ? tfsStashPush(message, opts) : gitStashPush(message, opts);
}

function stashRestore(ref, opts = {}) {
  return detect(opts.cwd) === 'tfs' ? tfsStashRestore(ref, opts) : gitStashRestore(ref, opts);
}

function parseSnapshotArg(value) {
  if (!value) return null;
  if (value.endsWith('.json')) return JSON.parse(fs.readFileSync(value, 'utf8'));
  return { type: 'git', commitHash: value };
}

function main(argv) {
  const [command, ...args] = argv;
  const cwd = process.cwd();

  switch (command) {
    case 'snapshot':
      console.log(JSON.stringify(snapshot({ cwd }), null, 2));
      return 0;
    case 'changed': {
      const snap = parseSnapshotArg(args[0]);
      if (!snap) {
        console.error('Usage: vcs_git.js changed <commit-hash | snapshot.json>');
        return 2;
      }
      console.log(JSON.stringify(changedFilesSince(snap, { cwd }), null, 2));
      return 0;
    }
    case 'restore': {
      const snap = parseSnapshotArg(args[0]);
      if (!snap) {
        console.error('Usage: vcs_git.js restore <commit-hash | snapshot.json>');
        return 2;
      }
      const result = restore(snap, { cwd });
      console.log(JSON.stringify(result, null, 2));
      return result.success ? 0 : 1;
    }
    case 'dirty':
      console.log(isDirty({ cwd }));
      return 0;
    case 'stash':
      console.log(stashPush(args.join(' ') || 'loop-coding stash', { cwd }));
      return 0;
    case 'stash-restore':
      if (!args[0]) {
        console.error('Usage: vcs_git.js stash-restore <ref>');
        return 2;
      }
      stashRestore(args[0], { cwd });
      return 0;
    case 'detect':
      console.log(detect(cwd));
      return 0;
    case 'tfs-login': {
      const collectionArg = args.find(arg => arg.startsWith('--collection='));
      const result = tfsLogin({ cwd, collection: collectionArg ? collectionArg.slice('--collection='.length) : undefined });
      console.log(JSON.stringify(result, null, 2));
      return result.success ? 0 : 1;
    }
    case 'tfs-checkout': {
      const result = tfsCheckout(args, { cwd });
      console.log(JSON.stringify(result, null, 2));
      return result.success ? 0 : 1;
    }
    case 'tfs-undo': {
      const result = tfsUndo(args, { cwd });
      console.log(JSON.stringify(result, null, 2));
      return result.success ? 0 : 1;
    }
    default:
      console.error('Usage: vcs_git.js <snapshot|changed|restore|dirty|stash|stash-restore|detect|tfs-login|tfs-checkout|tfs-undo> [args]');
      return 2;
  }
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

module.exports = {
  changedFilesSince,
  detect,
  gitChangedFilesSince,
  gitRestore,
  gitSnapshot,
  isDirty,
  parseTfStatus,
  restore,
  snapshot,
  stashPush,
  stashRestore,
  tfsChangedFilesSince,
  tfsCheckout,
  tfsIsDirty,
  tfsLogin,
  tfsRestore,
  tfsSnapshot,
  tfsUndo
};
