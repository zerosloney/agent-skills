#!/usr/bin/env node

/**
 * validate_role_inputs.js — 角色 prompt 注入前校验
 *
 * 加载 prompts/schemas/<role>.schema.json，校验输入对象。
 * 不依赖 AJV，自实现 JSON Schema 子集（type/required/enum/minLength/minimum/items）。
 *
 * 用法：
 *   node scripts/validate_role_inputs.js <role> <inputs.json>
 *   echo '{"task_brief":"...","project_root":"..."}' | node scripts/validate_role_inputs.js <role> -
 *
 * 退出码：
 *   0 = 校验通过
 *   1 = 校验失败
 *   2 = 用法错误
 */

const fs = require('node:fs');
const path = require('node:path');

const SCHEMAS_DIR = path.join(__dirname, '..', 'prompts', 'schemas');

function validateValue(value, schema, path) {
  const errors = [];

  // type
  if (schema.type) {
    const expected = Array.isArray(schema.type) ? schema.type : [schema.type];
    const actualType = value === null
      ? 'null'
      : Array.isArray(value)
        ? 'array'
        : typeof value;
    if (!expected.includes(actualType)) {
      // JSON Schema 区分 integer / number：typeof 都是 'number'，额外校验
      if (expected.includes('integer') && typeof value === 'number' && Number.isInteger(value)) {
        // 通过
      } else {
        errors.push(`${path}: expected type ${expected.join('|')}, got ${actualType}`);
        return errors;
      }
    }
  }

  // enum
  if (schema.enum && !schema.enum.includes(value)) {
    errors.push(`${path}: value must be one of [${schema.enum.join(', ')}], got "${value}"`);
  }

  // minLength
  if (typeof value === 'string' && Number.isInteger(schema.minLength) && value.length < schema.minLength) {
    errors.push(`${path}: string length ${value.length} < minLength ${schema.minLength}`);
  }

  // minimum
  if (typeof value === 'number' && Number.isFinite(schema.minimum) && value < schema.minimum) {
    errors.push(`${path}: value ${value} < minimum ${schema.minimum}`);
  }

  // items（数组元素）
  if (Array.isArray(value) && schema.items) {
    value.forEach((item, i) => {
      errors.push(...validateValue(item, schema.items, `${path}[${i}]`));
    });
  }

  return errors;
}

function validateSchema(input, schema) {
  const errors = [];

  // required
  for (const field of schema.required || []) {
    if (!(field in input) || input[field] === undefined) {
      errors.push(`missing required field: ${field}`);
    }
  }

  // additionalProperties: false → 拒绝未声明字段
  if (schema.additionalProperties === false) {
    const allowed = new Set(Object.keys(schema.properties || {}));
    for (const key of Object.keys(input)) {
      if (!allowed.has(key)) {
        errors.push(`unexpected field: ${key} (not in schema)`);
      }
    }
  }

  // properties
  for (const [key, propSchema] of Object.entries(schema.properties || {})) {
    if (key in input && input[key] !== undefined) {
      errors.push(...validateValue(input[key], propSchema, key));
    }
  }

  return errors;
}

function main(argv) {
  const [role, source] = argv;
  if (!role || !source) {
    console.error('Usage: node scripts/validate_role_inputs.js <role> <inputs.json|->');
    return 2;
  }

  const schemaPath = path.join(SCHEMAS_DIR, `${role}.schema.json`);
  if (!fs.existsSync(schemaPath)) {
    console.error(`Schema not found: ${schemaPath}`);
    return 2;
  }
  const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));

  let input;
  if (source === '-') {
    input = JSON.parse(fs.readFileSync(0, 'utf8'));
  } else if (!fs.existsSync(source)) {
    console.error(`Input file not found: ${source}`);
    return 2;
  } else {
    input = JSON.parse(fs.readFileSync(source, 'utf8'));
  }

  const errors = validateSchema(input, schema);
  if (errors.length === 0) {
    console.log(JSON.stringify({ status: 'VALID', role }, null, 2));
    return 0;
  }
  console.log(JSON.stringify({ status: 'INVALID', role, errors }, null, 2));
  return 1;
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

module.exports = { validateSchema, validateValue };