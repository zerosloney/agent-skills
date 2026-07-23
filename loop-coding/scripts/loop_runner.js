#!/usr/bin/env node

/**
 * loop_runner — loop-coding 状态机骨架
 *
 * 职责：管理 .loop-state.json 的读写、计算下一步动作、判断停止条件。
 * 不负责：实际执行 builder/checker（那是 orchestrator prompt + Agent 工具的事）。
 *
 * CLI:
 *   node scripts/loop_runner.js init <project_root> <task_brief> [--once]
 *   node scripts/loop_runner.js next <state.json>
 *   node scripts/loop_runner.js cycle-start <state.json>
 *   node scripts/loop_runner.js record-builder <state.json> <files_json>
 *   node scripts/loop_runner.js record-checker <state.json> <report> <fingerprints_json>
 *   node scripts/loop_runner.js run-checks <state.json> <commands_json> [--baseline]
 *   node scripts/loop_runner.js judge <state.json>
 *   node scripts/loop_runner.js confirm <state.json>
 *   node scripts/loop_runner.js update-contract <state.json> <field> <value>
 *
 * 设计原则：
 *   - 所有确定性逻辑（计数、比较、判断）在此完成，不依赖 LLM 推理
 *   - orchestrator prompt 只需调用 CLI 并执行返回的 action
 *   - .loop-state.json 是唯一状态源
 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { validateState, evaluateScopeDrift, evaluateStop, decideRecovery, isPathInScope, parseFixPlan } = require('./loop_state');
const { snapshot: vcsSnapshot, changedFilesSince, detect: vcsDetect } = require('./vcs_git');

// ── helpers ──────────────────────────────────────────────

function readState(statePath) {
  if (!fs.existsSync(statePath)) return null;
  return JSON.parse(fs.readFileSync(statePath, 'utf8'));
}

function writeState(statePath, state) {
  fs.writeFileSync(statePath, JSON.stringify(state, null, 2), 'utf8');
}

function now() {
  return new Date().toISOString();
}

function defaultScope(opts) {
  if (opts.scope) return opts.scope;
  if (opts.once) return ['.'];
  return [];
}

function scopeReady(scope) {
  return Array.isArray(scope) && scope.length > 0;
}

function readCurrentItemScope(projectRoot) {
  const fixPlanPath = path.join(projectRoot || process.cwd(), 'fix_plan.md');
  if (!fs.existsSync(fixPlanPath)) return [];
  const parsed = parseFixPlan(fs.readFileSync(fixPlanPath, 'utf8'));
  return parsed['In Progress'][0]?.scope || [];
}

function normalizeCheckCommands(commands) {
  if (Array.isArray(commands)) {
    return commands.map((command, index) => ({
      name: `check_${index + 1}`,
      command: String(command)
    }));
  }

  return Object.entries(commands || {}).flatMap(([name, value]) => {
    if (Array.isArray(value)) {
      return value.map((command, index) => ({
        name: value.length === 1 ? name : `${name}_${index + 1}`,
        command: String(command)
      }));
    }
    return [{ name, command: String(value) }];
  });
}

const CHECK_TIMEOUT_MS = {
  test: 10 * 60 * 1000,
  lint: 3 * 60 * 1000,
  typecheck: 5 * 60 * 1000,
  format: 2 * 60 * 1000,
  default: 5 * 60 * 1000
};

function checkKind(check) {
  const text = `${check.name || ''} ${check.command || ''}`.toLowerCase();
  if (/\b(test|pytest|vitest|jest|mocha)\b/.test(text)) return 'test';
  if (/\b(lint|eslint|oxlint|biome check|ruff check)\b/.test(text)) return 'lint';
  if (/\b(typecheck|type-check|tsc|mypy)\b/.test(text)) return 'typecheck';
  if (/\b(format|prettier --check|black --check)\b/.test(text)) return 'format';
  return 'default';
}

function checkTimeoutMs(check) {
  return CHECK_TIMEOUT_MS[checkKind(check)];
}

function isForbiddenCheckCommand(command) {
  return /\s--fix(?:\s|$)/.test(` ${command} `);
}

function extractFingerprints(checkName, output) {
  return String(output || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/([^\s()]+?\.[A-Za-z0-9]+):(\d+)(?::\d+)?:?\s*(.*)/);
      if (!match) return null;
      const message = match[3] || line;
      const errorType = (message.match(/\b(error|fail(?:ed|ure)?|exception|warning)\b/i) || [])[1] || 'failure';
      return `[${checkName}] ${match[1]}:${match[2]} - ${errorType.toLowerCase()} - ${message}`;
    })
    .filter(Boolean);
}

function runOneCheck(check, cwd) {
  const started = Date.now();
  const timeoutMs = checkTimeoutMs(check);
  if (isForbiddenCheckCommand(check.command)) {
    const output = `refusing to execute forbidden check command: ${check.command}`;
    return {
      name: check.name,
      command: check.command,
      exit_code: 2,
      duration_ms: 0,
      timeout_ms: timeoutMs,
      stdout: '',
      stderr: output,
      fingerprints: [`[${check.name}] CHECK_COMMAND - forbidden - ${output}`]
    };
  }

  const result = spawnSync(check.command, {
    cwd,
    encoding: 'utf8',
    shell: true,
    timeout: timeoutMs
  });
  const stdout = result.stdout || '';
  const stderr = result.stderr || '';
  const output = `${stdout}\n${stderr}`;
  const timedOut = result.error?.code === 'ETIMEDOUT';
  const exitCode = timedOut ? 124 : (typeof result.status === 'number' ? result.status : 1);
  const fingerprints = timedOut
    ? [`[${check.name}] CHECK_COMMAND - timeout - command exceeded ${timeoutMs}ms`]
    : extractFingerprints(check.name, output);

  return {
    name: check.name,
    command: check.command,
    exit_code: exitCode,
    duration_ms: Date.now() - started,
    timeout_ms: timeoutMs,
    stdout,
    stderr,
    error: result.error ? result.error.message : undefined,
    fingerprints: exitCode === 0 ? [] : fingerprints
  };
}

function summarizeChecks(results) {
  const summary = {};
  for (const result of results) {
    summary[result.name] = {
      passed: result.exit_code === 0 ? 1 : 0,
      failed: result.exit_code === 0 ? 0 : 1,
      warnings: 0,
      skipped: 0,
      exit_code: result.exit_code,
      duration_ms: result.duration_ms
    };
  }
  return summary;
}

function checkReport(results) {
  const failed = results.filter(result => result.exit_code !== 0);
  if (failed.length === 0) return 'ALL GREEN';
  return `FAILED ${failed.length}/${results.length} checks: ${failed.map(result => result.name).join(', ')}`;
}

function summarizeVcsAudit(vcsAudit) {
  if (!vcsAudit) return null;
  return {
    match: !!vcsAudit.match,
    error: vcsAudit.error || null,
    vcs_only_count: (vcsAudit.vcs_only || []).length
  };
}

// ── commands ─────────────────────────────────────────────

/**
 * init — 创建初始 .loop-state.json
 * --once 模式：max_cycles=1，跳过契约确认
 */
function cmdInit(projectRoot, taskBrief, opts = {}) {
  const statePath = path.join(projectRoot, '.loop-state.json');
  const mode = opts.once ? 'once' : 'loop';

  const state = {
    version: '3.2.1',
    task_brief: taskBrief,
    project_root: projectRoot,
    mode,
    contract: {
      trigger: opts.trigger || `/loop-coding${opts.once ? ' --once' : ''} ${taskBrief}`,
      task: taskBrief,
      scope: defaultScope(opts),
      budget: {
        max_cycles: opts.once ? 1 : (opts.maxCycles || 5),
        max_wall_time_per_cycle_min: 30
      },
      stop: {
        main: ['all_green', 'user_abort', 'cycles_exhausted'],
        auxiliary: ['repeat_failure', 'regression', 'no_progress', 'capability_boundary']
      },
      report: { channels: ['chat', 'state_file'] },
      confirmed_at: opts.once ? now() : null,
      start_at: now()
    },
    baseline: null,
    baseline_failures: [],
    unreliable_commands: [],
    cycles: [],
    registry: { cycles: {} },
    result: null
  };

  writeState(statePath, state);

  return {
    action: opts.once ? 'CONTRACT_AUTO_CONFIRMED' : 'AWAIT_CONFIRM',
    state_path: statePath,
    mode,
    message: opts.once
      ? '--once 模式：契约自动确认，直接进入基线检查'
      : '请确认 Loop Contract 后回复 "开始"'
  };
}

/**
 * next — 根据当前状态计算下一步动作
 * 返回 { action, ... } 供 orchestrator 执行
 */
function cmdNext(statePath) {
  const state = readState(statePath);

  // 恢复决策
  const recovery = decideRecovery(state);
  if (recovery.action !== 'CONTINUE') {
    return { action: 'RECOVERY', ...recovery };
  }

  // 停止判断
  const stopCheck = evaluateStop(state);
  if (stopCheck.status === 'STOP') {
    return { action: 'STOP', ...stopCheck };
  }

  const cyclesUsed = state.cycles.length;
  const maxCycles = state.contract.budget.max_cycles;

  return {
    action: 'NEXT_CYCLE',
    cycle_number: cyclesUsed + 1,
    max_cycles: maxCycles,
    mode: state.mode || 'loop'
  };
}

/**
 * cycle-start — 记录本轮 cycle_start 快照（含 VCS 审计信息）
 *
 * 调用 vcs_git.snapshot() 获取当前 VCS 状态，写入 registry.cycles[N].cycle_start，
 * 供后续 record-builder 用 changedFilesSince 做硬审计。
 */
function cmdCycleStart(statePath) {
  const state = readState(statePath);
  const cycleNum = state.cycles.length + 1;
  const projectRoot = state.project_root || process.cwd();

  // 确保 registry 结构存在
  if (!state.registry) state.registry = { cycles: {} };
  if (!state.registry.cycles) state.registry.cycles = {};

  // 尝试获取 VCS 快照
  let vcsData = { timestamp: now() };
  try {
    const vcsType = (state.config && state.config.vcs_type) || vcsDetect(projectRoot);
    if (vcsType === 'git' || vcsType === 'tfs') {
      const snap = vcsSnapshot({ cwd: projectRoot });
      vcsData = {
        type: snap.type,
        vcs_head: snap.commitHash || undefined,
        changeset: snap.changeset || snap.commitHash || undefined,
        local_changes: snap.localChanges || [],
        changed_file_hashes: snap.changedFileHashes || {},
        timestamp: snap.timestamp
      };
    }
  } catch (err) {
    // VCS 命令失败时仍记录时间戳，但标记 vcs_unavailable 原因
    vcsData.vcs_unavailable = err.message || 'VCS snapshot failed';
  }

  state.registry.cycles[String(cycleNum)] = {
    cycle_start: vcsData,
    ...(state.registry.cycles[String(cycleNum)] || {})
  };

  writeState(statePath, state);

  return {
    action: 'CYCLE_START_RECORDED',
    cycle_number: cycleNum,
    timestamp: vcsData.timestamp,
    vcs_head: vcsData.vcs_head || null,
    local_changes_count: (vcsData.local_changes || []).length
  };
}

/**
 * record-builder — 记录 builder 阶段产物（含 VCS 硬审计）
 *
 * builder 自报文件列表 + VCS changedFilesSince(cycle_start) 独立验证。
 * 两者差异记入 scope_drift，供 orchestrator 决策。
 */
function cmdRecordBuilder(statePath, filesJson) {
  const state = readState(statePath);
  const cycleNum = state.cycles.length + 1;
  const files = JSON.parse(filesJson);
  const projectRoot = state.project_root || process.cwd();
  const itemScope = readCurrentItemScope(projectRoot);

  // 检查 scope drift（文件是否在 contract.scope 内）
  const outOfScope = files.filter(f => !isPathInScope(f, state.contract.scope));

  // VCS 硬审计：基于 cycle_start 快照独立计算实际变更文件
  let vcsAudit = null;
  const cycleSnap = state.registry?.cycles?.[String(cycleNum)]?.cycle_start;
  if (cycleSnap && (cycleSnap.vcs_head || cycleSnap.changed_file_hashes)) {
    try {
      const vcsType = (state.config && state.config.vcs_type) || vcsDetect(projectRoot);
      if (vcsType === 'git' || vcsType === 'tfs') {
        const actualFiles = changedFilesSince(cycleSnap, { cwd: projectRoot });
        const reportedSet = new Set(files.map(f => f.replace(/\\/g, '/')));
        const actualSet = new Set(actualFiles.map(f => f.replace(/\\/g, '/')));

        // builder 报了但 VCS 没看到 → 可能是未跟踪的新文件
        const builderOnly = [...reportedSet].filter(f => !actualSet.has(f));
        // VCS 看到但 builder 没报 → 漏报（可能是意外修改）
        const vcsOnly = [...actualSet].filter(f => !reportedSet.has(f));

        vcsAudit = {
          vcs_actual: actualFiles,
          builder_reported: files,
          builder_only: builderOnly,
          vcs_only: vcsOnly,
          match: builderOnly.length === 0 && vcsOnly.length === 0
        };
      }
    } catch (err) {
      vcsAudit = { error: err.message || 'VCS audit failed' };
    }
  }

  const auditedFiles = (vcsAudit && Array.isArray(vcsAudit.vcs_actual)) ? vcsAudit.vcs_actual : files;
  const itemDrift = itemScope.length > 0
    ? evaluateScopeDrift(state.contract.scope, itemScope, auditedFiles)
    : null;

  // 确保 cycle 条目存在
  while (state.cycles.length < cycleNum) {
    state.cycles.push({ n: state.cycles.length + 1 });
  }

  const cycle = state.cycles[cycleNum - 1];
  cycle.builder_changes = {
    files_modified: files,
    declared_scope: itemScope,
    timestamp: now()
  };
  cycle.builder_scope_drift = outOfScope.length > 0 ? { out_of_scope: outOfScope } : null;
  if (itemDrift && !itemDrift.ok) {
    cycle.scope_drift = true;
    cycle.builder_scope_drift = {
      ...(cycle.builder_scope_drift || {}),
      ...itemDrift
    };
  }
  if (vcsAudit) {
    cycle.vcs_audit = vcsAudit;
    // 硬审计发现的越界比自报更严重：标记 scope_drift 为 true
    if (vcsAudit.vcs_only && vcsAudit.vcs_only.length > 0) {
      const vcsOutOfScope = vcsAudit.vcs_only.filter(f => !isPathInScope(f, state.contract.scope));
      if (vcsOutOfScope.length > 0) {
        cycle.scope_drift = true;
        cycle.builder_scope_drift = {
          ...(cycle.builder_scope_drift || {}),
          vcs_detected_out_of_scope: vcsOutOfScope
        };
      }
    }
  }

  // P3-2: VCS 硬审计失败时提供回滚建议
  let rollbackSuggestion = null;
  if (vcsAudit && vcsAudit.vcs_only && vcsAudit.vcs_only.length > 0) {
    const outOfScopeFiles = vcsAudit.vcs_only.filter(f => !isPathInScope(f, state.contract.scope));
    if (outOfScopeFiles.length > 0) {
      const vcsType = (state.config && state.config.vcs_type) || 'git';
      rollbackSuggestion = {
        action: 'ROLLBACK_SUGGESTION',
        vcs_type: vcsType,
        out_of_scope_files: outOfScopeFiles,
        commands: vcsType === 'tfs'
          ? `tf undo ${outOfScopeFiles.join(' ')}`
          : `git checkout HEAD -- ${outOfScopeFiles.join(' ')}`,
        message: `VCS audit detected ${outOfScopeFiles.length} file(s) modified outside declared scope. ` +
          `To rollback these unintended changes, run: ${vcsType === 'tfs' ? 'tf undo' : 'git checkout HEAD --'} <files>. ` +
          `Files: ${outOfScopeFiles.join(', ')}`
      };
    }
  }

  writeState(statePath, state);

  return {
    action: 'BUILDER_RECORDED',
    cycle_number: cycleNum,
    files_modified: files,
    declared_scope: itemScope,
    scope_drift: cycle.scope_drift || outOfScope.length > 0
      ? { warning: true, ...(cycle.builder_scope_drift || { out_of_scope: outOfScope }) }
      : { warning: false },
    vcs_audit: summarizeVcsAudit(vcsAudit),
    rollback_suggestion: rollbackSuggestion || null
  };
}

/**
 * record-checker — 记录 checker 阶段产物
 */
function cmdRecordChecker(statePath, report, fingerprintsJson) {
  const state = readState(statePath);
  const cycleNum = state.cycles.length;
  if (cycleNum === 0) return { action: 'ERROR', message: 'no cycle to record checker into' };

  const fingerprints = JSON.parse(fingerprintsJson || '[]');
  const cycle = state.cycles[cycleNum - 1];
  cycle.checker_report = report;
  cycle.fingerprints = fingerprints;
  cycle.checker_timestamp = now();

  writeState(statePath, state);

  const isAllGreen = /^ALL GREEN\b/.test(report.trim());

  return {
    action: 'CHECKER_RECORDED',
    cycle_number: cycleNum,
    all_green: isAllGreen,
    fingerprint_count: fingerprints.length
  };
}

/**
 * run-checks — 执行检查命令，并把结果写入 baseline 或当前 cycle。
 *
 * commandsJson 支持:
 *   ["npm test", "npm run lint"]
 *   {"test": "npm test", "lint": ["npm run lint", "npm run typecheck"]}
 */
function cmdRunChecks(statePath, commandsJson, opts = {}) {
  const state = readState(statePath);
  if (!state) return { action: 'ERROR', message: 'state file not found' };

  const commands = normalizeCheckCommands(JSON.parse(commandsJson));
  if (commands.length === 0) return { action: 'ERROR', message: 'no check commands provided' };

  const results = commands.map(command => runOneCheck(command, state.project_root || process.cwd()));
  const fingerprints = results.flatMap(result => result.fingerprints || []);

  if (opts.baseline) {
    state.baseline = summarizeChecks(results);
    state.baseline_failures = fingerprints;
    state.check_results = { baseline: results };
    writeState(statePath, state);
    return {
      action: 'BASELINE_RECORDED',
      passed: results.filter(result => result.exit_code === 0).length,
      failed: results.filter(result => result.exit_code !== 0).length,
      fingerprint_count: fingerprints.length
    };
  }

  const cycleNum = state.cycles.length;
  if (cycleNum === 0) return { action: 'ERROR', message: 'no cycle to record checker into' };

  const cycle = state.cycles[cycleNum - 1];
  cycle.checker_report = checkReport(results);
  cycle.fingerprints = fingerprints;
  cycle.checker_timestamp = now();
  cycle.check_results = results;
  writeState(statePath, state);

  return {
    action: 'CHECKER_RECORDED',
    cycle_number: cycleNum,
    all_green: results.every(result => result.exit_code === 0),
    fingerprint_count: fingerprints.length
  };
}

/**
 * judge — 综合判断：继续还是停止
 */
function cmdJudge(statePath) {
  const state = readState(statePath);
  const stopCheck = evaluateStop(state);

  if (stopCheck.status === 'STOP') {
    // 写入 result — 映射到 schema 枚举值 (success / incomplete / aborted_by_user)
    state.result = {
      result: mapResultToSchema(stopCheck.reason),
      stop_reason: stopCheck.reason,
      stopped_at_cycle: state.cycles.length,
      cycles_used: state.cycles.length,
      timestamp: now()
    };
    writeState(statePath, state);

    return { action: 'STOP', ...stopCheck };
  }

  return {
    action: 'CONTINUE',
    cycles_used: state.cycles.length,
    max_cycles: state.contract.budget.max_cycles
  };
}

/**
 * 将停止原因映射到 state.schema.json 的 result.result 枚举值
 * schema 只允许: "success" | "incomplete" | "aborted_by_user"
 */
function mapResultToSchema(reason) {
  if (reason === 'all_green' || reason === 'task_scope_green') return 'success';
  if (reason === 'user_abort') return 'aborted_by_user';
  // cycles_exhausted, repeat_failure, regression, no_progress, capability_boundary, fix_plan_done
  return 'incomplete';
}

/**
 * confirm — 用户确认 Loop Contract，写入 confirmed_at 时间戳
 *
 * CLI: node scripts/loop_runner.js confirm <state.json>
 */
function cmdConfirm(statePath) {
  const state = readState(statePath);
  if (!state) return { action: 'ERROR', message: 'state file not found' };

  if (!scopeReady(state.contract?.scope)) {
    return {
      action: 'ERROR',
      message: 'contract.scope must be set before confirmation'
    };
  }

  if (state.contract.confirmed_at) {
    return {
      action: 'ALREADY_CONFIRMED',
      confirmed_at: state.contract.confirmed_at
    };
  }

  state.contract.confirmed_at = now();
  writeState(statePath, state);

  return {
    action: 'CONTRACT_CONFIRMED',
    confirmed_at: state.contract.confirmed_at
  };
}

/**
 * update-contract — 更新 Loop Contract 字段
 *
 * CLI: node scripts/loop_runner.js update-contract <state.json> <field> <value>
 * 支持字段: scope (逗号分隔), max_cycles, max_wall_time_per_cycle_min, task, stop, report
 */
function cmdUpdateContract(statePath, field, value) {
  const state = readState(statePath);
  if (!state) return { action: 'ERROR', message: 'state file not found' };

  const allowed = ['scope', 'max_cycles', 'max_wall_time_per_cycle_min', 'task', 'stop', 'report'];
  if (!allowed.includes(field)) {
    return { action: 'ERROR', message: `field must be one of: ${allowed.join(', ')}` };
  }

  switch (field) {
    case 'scope':
      state.contract.scope = value.split(',').map(s => s.trim()).filter(Boolean);
      break;
    case 'max_cycles':
      state.contract.budget.max_cycles = parseInt(value);
      break;
    case 'max_wall_time_per_cycle_min':
      state.contract.budget.max_wall_time_per_cycle_min = parseInt(value);
      break;
    case 'task':
      state.contract.task = value;
      break;
    case 'stop':
      state.contract.stop = JSON.parse(value);
      break;
    case 'report':
      state.contract.report = JSON.parse(value);
      break;
  }

  // 更新后需要重新确认
  state.contract.confirmed_at = null;
  writeState(statePath, state);

  return {
    action: 'CONTRACT_UPDATED',
    field,
    value: state.contract[field] || state.contract.budget[field],
    needs_reconfirm: true
  };
}

// ── CLI ──────────────────────────────────────────────────

function main(argv) {
  const [command, ...args] = argv;

  switch (command) {
    case 'init': {
      const projectRoot = args[0];
      const taskBrief = args[1];
      if (!projectRoot || !taskBrief) {
        console.error('Usage: loop_runner.js init <project_root> <task_brief> [--once]');
        return 2;
      }
      const opts = {
        once: args.includes('--once'),
        maxCycles: args.includes('--max-cycles') ? parseInt(args[args.indexOf('--max-cycles') + 1]) : undefined,
        scope: args.includes('--scope') ? args[args.indexOf('--scope') + 1].split(',') : undefined,
        trigger: args.includes('--trigger') ? args[args.indexOf('--trigger') + 1] : undefined
      };
      console.log(JSON.stringify(cmdInit(projectRoot, taskBrief, opts), null, 2));
      return 0;
    }

    case 'next': {
      const result = cmdNext(args[0]);
      console.log(JSON.stringify(result, null, 2));
      return 0;
    }

    case 'cycle-start': {
      const result = cmdCycleStart(args[0]);
      console.log(JSON.stringify(result, null, 2));
      return 0;
    }

    case 'record-builder': {
      const result = cmdRecordBuilder(args[0], args[1]);
      console.log(JSON.stringify(result, null, 2));
      return 0;
    }

    case 'record-checker': {
      const result = cmdRecordChecker(args[0], args[1], args[2]);
      console.log(JSON.stringify(result, null, 2));
      return 0;
    }

    case 'run-checks': {
      const result = cmdRunChecks(args[0], args[1], { baseline: args.includes('--baseline') });
      console.log(JSON.stringify(result, null, 2));
      return result.action === 'ERROR' ? 1 : 0;
    }

    case 'judge': {
      const result = cmdJudge(args[0]);
      console.log(JSON.stringify(result, null, 2));
      return 0;
    }

    case 'confirm': {
      const result = cmdConfirm(args[0]);
      console.log(JSON.stringify(result, null, 2));
      return result.action === 'ERROR' ? 1 : 0;
    }

    case 'update-contract': {
      const result = cmdUpdateContract(args[0], args[1], args[2]);
      console.log(JSON.stringify(result, null, 2));
      return result.action === 'ERROR' ? 1 : 0;
    }

    default:
      console.error('Usage: loop_runner.js <init|next|cycle-start|record-builder|record-checker|run-checks|judge|confirm|update-contract> [args]');
      return 2;
  }
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

module.exports = { checkTimeoutMs, cmdInit, cmdNext, cmdCycleStart, cmdRecordBuilder, cmdRecordChecker, cmdRunChecks, cmdJudge, cmdConfirm, cmdUpdateContract, mapResultToSchema, summarizeVcsAudit };
