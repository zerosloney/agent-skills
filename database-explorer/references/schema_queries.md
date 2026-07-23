# Schema 查询参考

各数据库的目录查询 SQL，供扩展时参考。

## SQL Server

### 表列表
```sql
SELECT TABLE_NAME, TABLE_TYPE
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = %s
ORDER BY TABLE_NAME
```

### 视图列表
```sql
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA = %s
ORDER BY TABLE_NAME
```

### 存储过程列表
```sql
SELECT ROUTINE_NAME, CREATED, LAST_ALTERED
FROM INFORMATION_SCHEMA.ROUTINES
WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = 'PROCEDURE'
ORDER BY ROUTINE_NAME
```

### 列信息
```sql
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
       IS_NULLABLE, ORDINAL_POSITION, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
ORDER BY ORDINAL_POSITION
```

### 索引信息
```sql
SELECT i.name AS index_name, i.is_unique, i.is_primary_key, i.type_desc,
       STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS columns
FROM sys.indexes i
JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
JOIN sys.tables t ON i.object_id = t.object_id
WHERE SCHEMA_NAME(t.schema_id) = %s AND t.name = %s
GROUP BY i.name, i.is_unique, i.is_primary_key, i.type_desc
ORDER BY i.is_primary_key DESC, i.name
```

### 主键列
```sql
SELECT c.name AS column_name
FROM sys.indexes i
JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
JOIN sys.tables t ON i.object_id = t.object_id
WHERE SCHEMA_NAME(t.schema_id) = %s AND t.name = %s AND i.is_primary_key = 1
ORDER BY ic.key_ordinal
```

### 外键关系
```sql
SELECT f.name AS constraint_name,
       COL_NAME(fc.parent_object_id, fc.parent_column_id) AS column_name,
       OBJECT_NAME(fc.referenced_object_id) AS referenced_table,
       COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS referenced_column,
       delete_referential_action_desc AS delete_rule,
       update_referential_action_desc AS update_rule
FROM sys.foreign_keys f
JOIN sys.foreign_key_columns fc ON f.object_id = fc.constraint_object_id
WHERE OBJECT_SCHEMA_NAME(f.parent_object_id) = %s AND OBJECT_NAME(f.parent_object_id) = %s
```

### 约束信息
```sql
SELECT name AS constraint_name, type_desc AS constraint_type
FROM sys.objects
WHERE parent_object_id = OBJECT_ID(%s)
  AND type IN ('PK', 'UQ', 'C', 'F')
ORDER BY type, name
```

### 视图定义
```sql
SELECT TABLE_NAME AS VIEW_NAME, VIEW_DEFINITION AS definition
FROM INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA LIKE %s
ORDER BY TABLE_NAME
```

### 存储过程定义
```sql
SELECT o.name AS routine_name, m.definition
FROM sys.objects o JOIN sys.sql_modules m ON o.object_id = m.object_id
WHERE o.type IN ('P', 'FN') AND SCHEMA_NAME(o.schema_id) = %s
ORDER BY o.name
```

### 表注释（MS_Description）
```sql
SELECT t.name AS TABLE_NAME, ep.value AS comment
FROM sys.tables t JOIN sys.extended_properties ep
  ON ep.major_id = t.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description'
WHERE SCHEMA_NAME(t.schema_id) = %s AND t.name IN (%s)
```

## MySQL

### 表列表
```sql
SELECT TABLE_NAME, TABLE_TYPE
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = %s
ORDER BY TABLE_NAME
```

### 列信息
```sql
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
       IS_NULLABLE, ORDINAL_POSITION, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
ORDER BY ORDINAL_POSITION
```

### 索引信息
```sql
SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE, SEQ_IN_INDEX
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
ORDER BY INDEX_NAME, SEQ_IN_INDEX
```

### 主键列
```sql
SELECT COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME = 'PRIMARY'
```

### 建表脚本
```sql
SHOW CREATE TABLE `table_name`
```

### 外键关系
```sql
SELECT k.CONSTRAINT_NAME, k.COLUMN_NAME, k.REFERENCED_TABLE_NAME,
       k.REFERENCED_COLUMN_NAME, r.UPDATE_RULE, r.DELETE_RULE
FROM information_schema.KEY_COLUMN_USAGE k
JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON k.CONSTRAINT_NAME = r.CONSTRAINT_NAME
WHERE k.TABLE_SCHEMA = %s AND k.TABLE_NAME = %s
  AND k.REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY k.CONSTRAINT_NAME, k.ORDINAL_POSITION
```

### 约束信息
```sql
SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
ORDER BY CONSTRAINT_TYPE, CONSTRAINT_NAME
```

### 视图定义
```sql
SELECT TABLE_NAME AS VIEW_NAME, VIEW_DEFINITION AS definition
FROM information_schema.VIEWS
WHERE TABLE_SCHEMA = %s
ORDER BY TABLE_NAME
```

### 存储过程定义
```sql
SELECT ROUTINE_NAME, ROUTINE_TYPE, ROUTINE_DEFINITION
FROM information_schema.ROUTINES
WHERE ROUTINE_SCHEMA = %s
ORDER BY ROUTINE_NAME
```

### 表注释
```sql
SELECT TABLE_NAME, TABLE_COMMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN (%s)
```

## PostgreSQL

### 表列表
```sql
SELECT tablename AS TABLE_NAME, 'BASE TABLE' AS TABLE_TYPE
FROM pg_tables WHERE schemaname = %s
UNION ALL
SELECT viewname, 'VIEW' FROM pg_views WHERE schemaname = %s
ORDER BY TABLE_NAME
```

### 列信息
```sql
SELECT column_name, data_type, character_maximum_length,
       is_nullable, ordinal_position, column_default
FROM information_schema.columns
WHERE table_schema = %s AND table_name = %s
ORDER BY ordinal_position
```

### 索引信息
```sql
SELECT i.relname AS index_name, a.attname AS column_name,
       ix.indisunique AS is_unique, ix.indisprimary AS is_primary_key
FROM pg_class t
JOIN pg_index ix ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE t.relname = %s AND t.relkind = 'r'
ORDER BY i.relname, a.attnum
```

### 主键列
```sql
SELECT a.attname AS COLUMN_NAME
FROM pg_index i
JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
JOIN pg_class t ON t.oid = i.indrelid
WHERE t.relname = %s AND i.indisprimary
```

### 外键关系
```sql
SELECT tc.constraint_name, kcu.column_name,
       ccu.table_name AS referenced_table, ccu.column_name AS referenced_column,
       rc.update_rule, rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
JOIN information_schema.referential_constraints rc ON tc.constraint_name = rc.constraint_name
WHERE tc.table_schema = %s AND tc.table_name = %s AND tc.constraint_type = 'FOREIGN KEY'
ORDER BY tc.constraint_name, kcu.ordinal_position
```

### 约束信息
```sql
SELECT conname AS constraint_name, contype AS constraint_type,
       pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = %s::regclass
ORDER BY contype, conname
```

### 视图定义
```sql
SELECT viewname AS VIEW_NAME, definition
FROM pg_views
WHERE schemaname = %s
ORDER BY viewname
```

### 存储过程/函数定义
```sql
SELECT p.proname AS routine_name, pg_get_functiondef(p.oid) AS definition
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = %s
ORDER BY p.proname
```

### 表注释
```sql
SELECT c.relname AS TABLE_NAME, obj_description(c.oid) AS comment
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relname IN (%s)
```

## KingbaseES（人大金仓）

KingbaseES 完全兼容 PostgreSQL 协议，所有查询 SQL 与 PostgreSQL 相同，见上节。

## SQLite

### 表列表
```sql
SELECT name AS TABLE_NAME, type AS TABLE_TYPE
FROM sqlite_master
WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
ORDER BY name
```

### 列信息
```sql
PRAGMA table_info("table_name")
```

### 索引信息
```sql
SELECT name AS index_name, tbl_name, sql
FROM sqlite_master
WHERE type = 'index' AND tbl_name = 'table_name'
```

### 建表脚本
```sql
SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?
```

### 外键关系
```sql
PRAGMA foreign_key_list("table_name")
```

### 约束/DDL 信息
```sql
SELECT sql FROM sqlite_master
WHERE type IN ('table', 'index') AND tbl_name = ? AND sql IS NOT NULL
```

### 视图定义
```sql
SELECT name AS VIEW_NAME, sql AS definition
FROM sqlite_master
WHERE type = 'view' AND name NOT LIKE 'sqlite_%'
ORDER BY name
```
