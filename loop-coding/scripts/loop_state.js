#!/usr/bin/env node

const fs = require('fs');

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function normalizePath(file) {
  return String(file || '').replace(/\\/g, '/').replace(/^\.\//, '');
}

function isPathInScope(file, scope) {
  const normalized = normalizePath(file);
  return asArray(scope).some((entry) => {
    const allowed = normalizePath(entry);
    if (!allowed) return false;
    if (allowed === '.') return true;
    if (allowed.endsWith('/')) return normalized.startsWith(allowed);
    return normalized === allowed || normalized.startsWith(`${allowed}/`);
  });
}

function parseFingerprint(value) {
  const match = String(value || '').match(/^\[([^\]]+)\]\s+(.+?)\s+-\s+(.+?)(?:\s+-\s+.*)?$/);
  if (!match) return null;

  const fileWithLine = normalizePath(match[2]);
  const file = fileWithLine.replace(/:\d+(?::\d+)?$/, '');
  return {
    check: match[1],
    file,
    key: `[${match[1]}] ${file} - ${match[3]}`
  };
}

function reliableFingerprints(fingerprints, unreliableCommands) {
  const unreliable = new Set(asArray(unreliableCommands));
  return asArray(fingerprints)
    .map(parseFingerprint)
    .filter((fingerprint) => fingerprint && !unreliable.has(fingerprint.check));
}

function isTaskScopeGreen(state, cycle) {
  if (!Array.isArray(cycle?.fingerprints)) return false;

  const current = reliableFingerprints(cycle.fingerprints, state.unreliable_commands);
  const baseline = new Set(
    reliableFingerprints(state.baseline_failures, state.unreliable_commands).map((fingerprint) => fingerprint.key)
  );

  const scopeFailures = current.filter((fingerprint) => isPathInScope(fingerprint.file, state.contract.scope));
  const newFailures = current.filter((fingerprint) => !baseline.has(fingerprint.key));
  return scopeFailures.length === 0 && newFailures.length === 0;
}

function validateState(state) {
  const errors = [];
  if (!state || typeof state !== 'object') return ['state must be an object'];

  if (!state.version) errors.push('missing version');
  if (!state.task_brief) errors.push('missing task_brief');
  if (!state.project_root) errors.push('missing project_root');

  const contract = state.contract;
  if (!contract) {
    errors.push('missing contract');
    return errors;
  }

  for (const field of ['trigger', 'task', 'confirmed_at', 'start_at']) {
    if (!contract[field]) errors.push(`missing contract.${field}`);
  }

  if (!Array.isArray(contract.scope) || contract.scope.length === 0) {
    errors.push('contract.scope must be a non-empty array');
  }

  const maxCycles = contract.budget?.max_cycles;
  if (!Number.isInteger(maxCycles) || maxCycles < 1) {
    errors.push('contract.budget.max_cycles must be a positive integer');
  }

  const timePerCycle = contract.budget?.max_wall_time_per_cycle_min;
  if (!Number.isInteger(timePerCycle) || timePerCycle < 1) {
    errors.push('contract.budget.max_wall_time_per_cycle_min must be a positive integer');
  }

  for (const condition of ['all_green', 'user_abort', 'cycles_exhausted']) {
    if (!asArray(contract.stop?.main).includes(condition)) {
      errors.push(`contract.stop.main missing ${condition}`);
    }
  }

  if (!asArray(contract.report?.channels).includes('chat')) {
    errors.push('contract.report.channels must include chat');
  }

  for (const cycle of asArray(state.cycles)) {
    const declared = asArray(cycle.builder_changes?.declared_scope);
    for (const file of declared) {
      if (!isPathInScope(file, contract.scope)) {
        errors.push(`cycle ${cycle.n} item scope outside contract.scope: ${file}`);
      }
    }
  }

  return errors;
}

function evaluateStop(state) {
  const errors = validateState(state);
  if (errors.length > 0) return { status: 'INVALID', errors };

  if (state.result?.result) {
    return { status: 'STOP', reason: state.result.result };
  }

  const cyclesUsed = asArray(state.cycles).length;
  const maxCycles = state.contract.budget.max_cycles;
  const lastCycle = asArray(state.cycles)[cyclesUsed - 1];

  if (lastCycle?.checker_report && /^ALL GREEN\b/.test(lastCycle.checker_report.trim())) {
    return { status: 'STOP', reason: 'all_green', cycles_used: cyclesUsed, max_cycles: maxCycles };
  }

  if (isTaskScopeGreen(state, lastCycle)) {
    return { status: 'STOP', reason: 'task_scope_green', cycles_used: cyclesUsed, max_cycles: maxCycles };
  }

  if (cyclesUsed >= maxCycles) {
    return { status: 'STOP', reason: 'cycles_exhausted', cycles_used: cyclesUsed, max_cycles: maxCycles };
  }

  return { status: 'CONTINUE', cycles_used: cyclesUsed, max_cycles: maxCycles };
}

function evaluateScopeDrift(contractScope, itemScope, changedFiles) {
  const outOfItemScope = asArray(changedFiles).filter((file) => !isPathInScope(file, itemScope));
  const itemOutsideContract = asArray(itemScope).filter((file) => !isPathInScope(file, contractScope));
  return {
    ok: outOfItemScope.length === 0 && itemOutsideContract.length === 0,
    out_of_item_scope: outOfItemScope,
    item_outside_contract: itemOutsideContract
  };
}

function decideRecovery(state) {
  if (!state) return { action: 'START_FRESH', reason: '无状态文件' };
  if (state.result) return { action: 'EXIT', reason: '已有结果', result: state.result };

  if (!state.cycles || state.cycles.length === 0) {
    if (!state.contract?.confirmed_at) return { action: 'AWAIT_CONFIRM', reason: 'Loop Contract 尚未确认' };
    if (state.baseline) return { action: 'CONTINUE', reason: '基线已就绪，等待循环开始' };
    return { action: 'RUN_BASELINE', reason: '契约已确认，缺少 baseline' };
  }

  const lastCycle = state.cycles[state.cycles.length - 1];

  if (!lastCycle.checker_report) {
    const registryCycleCount = state.registry?.cycles
      ? Object.keys(state.registry.cycles).length
      : 0;
    if (registryCycleCount >= state.cycles.length) {
      return { action: 'RUN_CHECKER', reason: '缺少 checker 报告，回退到 registry 快照' };
    }
    return { action: 'BLOCKED', reason: '缺少 checker 报告且无 registry 快照，无法安全恢复' };
  }

  if (!state.baseline) {
    return { action: 'RUN_BASELINE', reason: '缺少 baseline，重跑' };
  }

  return { action: 'CONTINUE', reason: '状态正常，继续循环' };
}

function parseFixPlan(content) {
  const sections = { 'In Progress': [], 'Pending': [], 'Done': [] };
  let currentSection = null;

  for (const line of String(content || '').split(/\r?\n/)) {
    const sectionMatch = line.match(/^##\s+(.+)$/);
    if (sectionMatch) {
      const name = sectionMatch[1].trim();
      if (Object.prototype.hasOwnProperty.call(sections, name)) {
        currentSection = name;
      } else {
        currentSection = null;
      }
      continue;
    }
    if (!currentSection) continue;

    const itemMatch = line.match(/^-\s+\[([ x~])\]\s+(\S+)(?:\s+(.*))?$/);
    if (!itemMatch) continue;
    const [, status, id, rest = ''] = itemMatch;
    const scopeMatch = rest.match(/\(scope:\s*([^)]+)\)/);
    const scope = scopeMatch
      ? scopeMatch[1].split(',').map((s) => s.trim()).filter(Boolean)
      : [];
    sections[currentSection].push({ id, status: status.trim(), scope });
  }

  return sections;
}

function crossCheck(state, options = {}) {
  const { fixPlanPath = null, progressPath = null } = options;
  const issues = [];

  if (!state || typeof state !== 'object') {
    return { ok: false, issues: [{ severity: 'ERROR', check: 'state_present', message: 'state missing or not an object' }] };
  }

  if (!state.contract) {
    return { ok: false, issues: [{ severity: 'ERROR', check: 'contract_present', message: 'state.contract missing' }] };
  }

  const contractScope = asArray(state.contract.scope);

  let fixPlan = null;
  if (fixPlanPath && fs.existsSync(fixPlanPath)) {
    fixPlan = parseFixPlan(fs.readFileSync(fixPlanPath, 'utf8'));
  }

  let progress = null;
  if (progressPath && fs.existsSync(progressPath)) {
    progress = fs.readFileSync(progressPath, 'utf8');
  }

  // 检查 1: contract.scope ⊇ fix_plan 所有 item 的 scope
  if (fixPlan) {
    for (const section of ['In Progress', 'Pending', 'Done']) {
      for (const item of asArray(fixPlan[section])) {
        for (const file of item.scope) {
          if (!isPathInScope(file, contractScope)) {
            issues.push({
              severity: 'ERROR',
              check: 'contract_scope_coverage',
              message: `fix_plan ${section} item "${item.id}" scope "${file}" outside contract.scope`,
              item: item.id,
              section,
              file
            });
          }
        }
      }
    }
  }

  // 检查 2: cycle 编号连续（n 必须从 1 开始且连续）
  const cycles = asArray(state.cycles);
  for (let i = 0; i < cycles.length; i += 1) {
    const expected = i + 1;
    const actual = cycles[i].n;
    if (actual !== expected) {
      issues.push({
        severity: 'ERROR',
        check: 'cycle_continuity',
        message: `cycle index mismatch at position ${i}: expected n=${expected}, got n=${actual === undefined ? 'undefined' : actual}`
      });
    }
  }

  // 检查 3: state.cycles[*].fixed_items ⊇ fix_plan Done 项
  if (fixPlan) {
    const stateFixed = new Set();
    for (const cycle of cycles) {
      for (const item of asArray(cycle.fixed_items)) {
        stateFixed.add(item);
      }
    }
    for (const item of asArray(fixPlan.Done)) {
      if (!stateFixed.has(item.id)) {
        issues.push({
          severity: 'WARN',
          check: 'done_items_unrecorded',
          message: `fix_plan Done item "${item.id}" not recorded in any state.cycles[*].fixed_items`,
          item: item.id
        });
      }
    }
  }

  // 检查 4: progress.md 包含 contract.task 摘要
  if (progress && state.contract.task) {
    const taskSnippet = String(state.contract.task).slice(0, 15).trim();
    if (taskSnippet && !progress.includes(taskSnippet)) {
      issues.push({
        severity: 'WARN',
        check: 'progress_task_ref',
        message: `state.contract.task snippet "${taskSnippet}" not found in progress.md`
      });
    }
  }

  // 检查 5: cycle.started_at 必须晚于 contract.confirmed_at
  if (state.contract.confirmed_at) {
    const confirmedTime = Date.parse(state.contract.confirmed_at);
    if (!Number.isNaN(confirmedTime)) {
      for (const cycle of cycles) {
        if (!cycle.started_at) continue;
        const startedTime = Date.parse(cycle.started_at);
        if (!Number.isNaN(startedTime) && startedTime < confirmedTime) {
          issues.push({
            severity: 'ERROR',
            check: 'cycle_after_confirmation',
            message: `cycle ${cycle.n} started_at (${cycle.started_at}) before contract.confirmed_at (${state.contract.confirmed_at})`
          });
        }
      }
    }
  }

  // 检查 6: state.result 与 cycles 一致性
  if (state.result?.result && cycles.length === 0) {
    issues.push({
      severity: 'ERROR',
      check: 'result_without_cycles',
      message: `state.result.result="${state.result.result}" but state.cycles is empty`
    });
  }

  return {
    ok: issues.filter((i) => i.severity === 'ERROR').length === 0,
    issues
  };
}

function main(argv) {
  const [command, ...rest] = argv;
  if (!command) {
    console.error('Usage: node scripts/loop_state.js <validate|stop|recover|cross-check> <state.json> [--fix-plan <path>] [--progress <path>]');
    return 2;
  }

  if (command === 'cross-check') {
    const statePath = rest[0];
    if (!statePath) {
      console.error('Usage: node scripts/loop_state.js cross-check <state.json> [--fix-plan <path>] [--progress <path>]');
      return 2;
    }
    if (!fs.existsSync(statePath)) {
      console.error(`File not found: ${statePath}`);
      return 1;
    }
    let fixPlanPath = null;
    let progressPath = null;
    for (let i = 1; i < rest.length; i += 1) {
      if (rest[i] === '--fix-plan') fixPlanPath = rest[i + 1];
      if (rest[i] === '--progress') progressPath = rest[i + 1];
    }
    if (!fixPlanPath) {
      const candidate = `${statePath.replace(/\.json$/i, '')}.fix_plan.md`;
      if (fs.existsSync(candidate)) fixPlanPath = candidate;
    }
    if (!progressPath) {
      const candidate = `${statePath.replace(/\.json$/i, '')}.progress.md`;
      if (fs.existsSync(candidate)) progressPath = candidate;
    }
    const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
    const result = crossCheck(state, { fixPlanPath, progressPath });
    console.log(JSON.stringify(result, null, 2));
    return result.ok ? 0 : 1;
  }

  if (command === 'scope-drift') {
    // scope-drift <state.json> <changed_files_json> [--fix-plan <path>]
    // 用确定性逻辑替代 checker 的自然语言 SCOPE_DRIFT 推理。
    const statePath = rest[0];
    const changedFilesJson = rest[1];
    if (!statePath || !changedFilesJson) {
      console.error('Usage: node scripts/loop_state.js scope-drift <state.json> <changed_files_json> [--fix-plan <path>]');
      console.error('  changed_files_json: JSON 数组字符串，如 "[\\"src/a.py\\",\\"src/b.py\\"]"');
      return 2;
    }
    if (!fs.existsSync(statePath)) {
      console.error(`File not found: ${statePath}`);
      return 1;
    }
    let fixPlanPath = null;
    for (let i = 2; i < rest.length; i += 1) {
      if (rest[i] === '--fix-plan') fixPlanPath = rest[i + 1];
    }
    if (!fixPlanPath) {
      const candidate = `${statePath.replace(/\.json$/i, '')}.fix_plan.md`;
      if (fs.existsSync(candidate)) fixPlanPath = candidate;
    }

    const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
    const contractScope = asArray(state.contract?.scope);
    if (contractScope.length === 0) {
      console.error('contract.scope empty or missing — cannot evaluate scope drift');
      return 2;
    }

    // item scope：优先从 fix_plan.md 解析 In Progress 项；无 fix_plan 时退化为 contract.scope
    let itemScope = contractScope;
    let itemSource = 'contract.scope (fix_plan missing)';
    if (fixPlanPath && fs.existsSync(fixPlanPath)) {
      const fixPlan = parseFixPlan(fs.readFileSync(fixPlanPath, 'utf8'));
      const inProgress = asArray(fixPlan['In Progress']);
      if (inProgress.length > 0 && inProgress[0].scope.length > 0) {
        itemScope = inProgress[0].scope;
        itemSource = `fix_plan In Progress: ${inProgress[0].id}`;
      }
    }

    let changedFiles;
    try {
      changedFiles = JSON.parse(changedFilesJson);
      if (!Array.isArray(changedFiles)) throw new Error('not an array');
    } catch (err) {
      console.error(`changed_files_json parse error: ${err.message}`);
      return 2;
    }

    const result = evaluateScopeDrift(contractScope, itemScope, changedFiles);
    const output = {
      ...result,
      contract_scope: contractScope,
      item_scope: itemScope,
      item_scope_source: itemSource,
      changed_files: changedFiles
    };
    console.log(JSON.stringify(output, null, 2));
    return result.ok ? 0 : 1;
  }

  const statePath = rest[0];
  if (!command || !statePath || !['validate', 'stop', 'recover'].includes(command)) {
    console.error('Usage: node scripts/loop_state.js <validate|stop|recover|cross-check|scope-drift> <state.json>');
    return 2;
  }

  if (!fs.existsSync(statePath)) {
    if (command === 'recover') {
      console.log(JSON.stringify(decideRecovery(null), null, 2));
      return 0;
    }
    console.error(`File not found: ${statePath}`);
    return 1;
  }

  const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  const errors = validateState(state);

  let result;
  if (command === 'validate') {
    result = { status: errors.length === 0 ? 'VALID' : 'INVALID', errors };
  } else if (command === 'stop') {
    result = evaluateStop(state);
  } else {
    result = decideRecovery(state);
  }

  console.log(JSON.stringify(result, null, 2));
  return result.status === 'INVALID' ? 1 : 0;
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

module.exports = {
  crossCheck,
  decideRecovery,
  evaluateScopeDrift,
  evaluateStop,
  isPathInScope,
  parseFixPlan,
  validateState
};
