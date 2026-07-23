"""SQL 安全防护 - 注释剥离、语句提取、标识符引用、只读检查、导出路径校验

本模块包含 SQL 层面与导出路径层面的安全工具函数。密码安全已迁移至 _keyring_security.py。
"""

import ast
import re
from pathlib import Path

_WRITE_KEYWORDS = frozenset(
    w.upper()
    for w in (
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "ALTER",
        "DROP",
        "TRUNCATE",
        "EXEC",
        "EXECUTE",
        "GRANT",
        "REVOKE",
        "DENY",
        "MERGE",
        "CALL",
        "COPY",
        "BACKUP",
        "RESTORE",
        "DBCC",
        "KILL",
        "SHUTDOWN",
        "RENAME",
    )
)

_RE_DROP = re.compile(r"\bDROP\b", re.IGNORECASE)
_RE_DELETE = re.compile(r"\bDELETE\b", re.IGNORECASE)
_RE_TRUNC = re.compile(r"\bTRUNCATE\b", re.IGNORECASE)
_RE_EXEC = re.compile(r"\b(EXEC|EXECUTE)\b", re.IGNORECASE)
_RE_BACKSLASH_CMD = re.compile(r"\bxp_cmdshell\b|\bsp_execute\b", re.IGNORECASE)
_RE_ALTER = re.compile(r"\bALTER\b", re.IGNORECASE)
_RE_MERGE = re.compile(r"\bMERGE\s+INTO\b", re.IGNORECASE)
_RE_INSERT = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)
_RE_SELECT_INTO = re.compile(r"\bSELECT\b[\s\S]*\bINTO\b", re.IGNORECASE)
_RE_UPDATE = re.compile(r"\bUPDATE\b\s+\S+\s+\bSET\b", re.IGNORECASE)
_RE_CREATE = re.compile(r"\bCREATE\b", re.IGNORECASE)
_RE_GRANT = re.compile(r"\bGRANT\b", re.IGNORECASE)
_RE_REVOKE = re.compile(r"\bREVOKE\b", re.IGNORECASE)
_RE_DENY = re.compile(r"\bDENY\b", re.IGNORECASE)
_RE_CALL = re.compile(r"\bCALL\b", re.IGNORECASE)
_RE_COPY = re.compile(r"\bCOPY\b", re.IGNORECASE)
_RE_BACKUP = re.compile(r"\bBACKUP\b", re.IGNORECASE)
_RE_RESTORE = re.compile(r"\bRESTORE\b", re.IGNORECASE)
_RE_DBCC = re.compile(r"\bDBCC\b", re.IGNORECASE)
_RE_KILL = re.compile(r"\bKILL\b", re.IGNORECASE)
_RE_SHUTDOWN = re.compile(r"\bSHUTDOWN\b", re.IGNORECASE)
_RE_RENAME = re.compile(r"\bRENAME\b|\bsp_rename\b", re.IGNORECASE)


def _is_doubled_quote(sql: str, pos: int) -> bool:
    return pos + 1 < len(sql) and sql[pos + 1] == "'"


def _match_dollar_quote_start(sql: str, pos: int) -> tuple[str, int] | None:
    r"""检测 PostgreSQL dollar-quote 开始定界符 ``$tag$`` 或 ``$$``。

    定界符 tag 遵循 unquoted identifier 规则：以字母/下划线开头，后跟字母数字
    下划线；为空（``$$``）也合法。``$1``（位置参数）因无收尾 ``$`` 不被误判。

    Returns:
        ``(定界符含两侧 $, 定界符结束位置)`` 或 ``None``（pos 处无 dollar-quote 起始）。
    """
    if pos >= len(sql) or sql[pos] != "$":
        return None
    j = pos + 1
    tag_start = j
    while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
        j += 1
    # tag 非空时不能以数字开头（unquoted identifier 规则）
    if j > tag_start and sql[tag_start].isdigit():
        return None
    if j < len(sql) and sql[j] == "$":
        return (sql[pos : j + 1], j + 1)
    return None


def _walk_sql(sql: str, *, keep_string_content: bool) -> str:
    """共享 SQL 状态机：剥离注释，可选保留或清空字符串字面量内容。

    当 ``keep_string_content=True`` 时等效于 :func:`strip_comments`（保留字符串内容）；
    当 ``keep_string_content=False`` 时等效于 :func:`strip_strings`（清空字符串字面量内容，仅留引号）。

    MySQL conditional comments ``/\\*!...\\*/`` 始终保留（含可执行代码）。

    PostgreSQL dollar-quoted strings ``$$...$$`` / ``$tag$...$tag$`` 被识别为
    字符串字面量（与单引号字符串同等处理），防止其中的关键字或分号误导注释剥离、
    字符串清空、写操作检测和多语句拆分。
    """
    result: list[str] = []
    in_string = False
    in_block = False
    in_conditional = False
    in_line = False
    in_dollar = False
    dollar_delim = ""
    i = 0
    while i < len(sql):
        # dollar-quote 内部一切原样跳过（含注释标记、引号、分号），优先级最高
        if in_dollar:
            end_idx = sql.find(dollar_delim, i)
            if end_idx == -1:
                # 未闭合 dollar-quote（PostgreSQL 视为语法错误）：安全检查工具
                # 按"已进入字符串字面量"处理，消耗剩余内容，避免内部 token 误判。
                if keep_string_content:
                    result.append(sql[i:])
                i = len(sql)
                break
            if keep_string_content:
                result.append(sql[i : end_idx + len(dollar_delim)])
            else:
                result.append(dollar_delim)
            i = end_idx + len(dollar_delim)
            in_dollar = False
            dollar_delim = ""
            continue

        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if not in_block and not in_line:
            if not in_string:
                dl = _match_dollar_quote_start(sql, i)
                if dl:
                    dollar_delim, end_pos = dl
                    in_dollar = True
                    result.append(dollar_delim)
                    i = end_pos
                    continue
                if ch == "-" and nxt == "-":
                    in_line = True
                    i += 2
                    continue
                if ch == "/" and nxt == "*":
                    rest = sql[i + 2 :] if i + 2 < len(sql) else ""
                    if rest.startswith("!"):
                        in_conditional = True
                        in_block = True
                        result.append(ch)
                        result.append(nxt)
                        i += 2
                        continue
                    in_conditional = False
                    in_block = True
                    i += 2
                    continue
            if ch == "'":
                if in_string and _is_doubled_quote(sql, i):
                    if keep_string_content:
                        result.append(ch)
                        result.append(nxt)
                    # keep_string_content=False 时 doubled quote 也跳过（不输出内容）
                    i += 2
                    continue
                if not in_string:
                    in_string = True
                    result.append("'")
                else:
                    in_string = False
                    result.append("'")
            elif in_string:
                if keep_string_content:
                    result.append(ch)
                # keep_string_content=False: 丢弃字符串内容字符
            else:
                result.append(ch)
        elif in_block:
            if in_conditional:
                result.append(ch)
            if ch == "*" and nxt == "/":
                if in_conditional:
                    result.append(nxt)
                in_block = False
                in_conditional = False
                i += 2
                continue
        elif in_line:
            if ch == "\n":
                in_line = False
                result.append(ch)
        i += 1
    return " ".join("".join(result).split())


def strip_comments(sql: str) -> str:
    """Strip block and line comments from SQL.

    MySQL conditional comments ``/\\*!nnnnn ...\\*/`` and ``/\\*! ...\\*/``
    are **preserved** — they contain executable MySQL-specific code that would
    change semantics if removed (e.g. ``/\\*!50110 SELECT 1\\*/`` executes on
    MySQL 5.1.10+). Stripping them would silently alter the SQL and could
    bypass security checks.
    """
    return _walk_sql(sql, keep_string_content=True)


def extract_first_statement(sql: str) -> str:
    """Strip comments and return only the first SQL statement."""
    parts = split_statements(sql)
    return parts[0].strip() if parts else ""


def strip_strings(sql: str) -> str:
    """剥离注释并将字符串字面量内容替换为空字面量 ``''``。

    用于关键字扫描：避免 ``SELECT 'drop'`` 中的字面量 ``drop`` 被
    误判为写操作关键字。保留引号结构以维持语句形态，仅清空内容。

    MySQL 条件注释 ``/\\*!...\\*/`` 被保留（含可执行代码）。
    """
    return _walk_sql(sql, keep_string_content=False)


def count_statements(sql: str) -> int:
    """统计 SQL 中独立语句数量（剥离注释后按引号外分号切分）。

    用于拒绝多语句注入：cmd_query/repl 只允许单语句，避免
    `SELECT 1; DROP TABLE x` 绕过 check_read_only（后者只扫首句）。
    """
    return len(split_statements(sql))


def split_statements(sql: str) -> list[str]:
    """将 SQL 按引号外分号安全拆分为独立语句列表。

    剥离注释后，在引号外的分号处切分，过滤空语句。
    MySQL 条件注释 ``/\\*!nnnnn ...\\*/`` 被保留为可执行语句而非被剥离。

    Returns:
        非空语句列表，按原始顺序。每条语句已 strip。
    """
    cleaned = strip_comments(sql)
    parts = []
    start = 0
    in_string = False
    i = 0
    while i < len(cleaned):
        ch = cleaned[i]
        # dollar-quote 优先级高于单引号：strip_comments 保留了 dollar 内容，
        # 二次扫描必须跳过 $$...$$ / $tag$...$tag$ 内部的分号，否则会误切。
        if ch == "$" and not in_string:
            dl = _match_dollar_quote_start(cleaned, i)
            if dl:
                dollar_delim, end_pos = dl
                next_close = cleaned.find(dollar_delim, end_pos)
                if next_close == -1:
                    i = len(cleaned)
                    break
                i = next_close + len(dollar_delim)
                continue
        if ch == "'":
            if in_string and _is_doubled_quote(cleaned, i):
                i += 2
                continue
            in_string = not in_string
        elif ch == ";" and not in_string:
            part = cleaned[start:i].strip()
            if part:
                parts.append(part)
            start = i + 1
        i += 1
    tail = cleaned[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _decode_bytes_literals(msg: str) -> str:
    """把错误消息里的 bytes 字面量（如 pymssql 的 b'\\xe4\\xb8...')解码为可读文本。

    pymssql 等驱动返回的异常 message 常嵌入 bytes（UTF-8 编码的中文表名/错误信息），
    str(e) 后变成 ``b'\\xe4\\xb8\\xad...'`` 这种乱码。本函数用 ast.literal_eval 安全
    解析每个 ``b'...'`` / ``b"..."`` 片段为 bytes，再 UTF-8 解码。
    """

    def _decode_one(m: re.Match) -> str:
        literal = m.group(0)
        try:
            raw = ast.literal_eval(literal)
            if not isinstance(raw, (bytes, bytearray)):
                return literal
            for enc in ("utf-8", "gbk", "latin-1"):
                try:
                    return raw.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
        except (ValueError, SyntaxError):
            pass
        return literal

    return re.sub(r"""b(["'])(?:\\.|[^\\])*?\1""", _decode_one, msg, flags=re.DOTALL)


def sanitize_error(e: Exception) -> str:
    """净化异常消息：解码 bytes 乱码 + 脱敏敏感信息。

    处理顺序：
    1. 解码 pymssql 等驱动返回的 bytes 字面量（中文表名/错误信息）
    2. 脱敏 IP / 路径 / 密码
    3. 截断过长消息
    """
    msg = str(e)
    # 解码嵌入的 bytes（pymssql 的中文错误信息）
    msg = _decode_bytes_literals(msg)
    msg = re.sub(r"[A-Za-z]:\\[^\s,)\]]*", "<path>", msg)
    msg = re.sub(r"(?<![:/])/(?![a-zA-Z]+://)[^\s,]*", "<path>", msg)
    msg = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?\b", "<ip>", msg)
    # 脱敏连接串/URI 中的 user:pass@ 形态凭据（如 mysql://user:pass@host）
    msg = re.sub(r"(//[^:/\s@]+:)[^@\s]+(@)", r"\1***\2", msg)
    msg = re.sub(r"(password|pwd)\s*[=:]\s*[^;\s,)\]]+", r"\1=***", msg, flags=re.IGNORECASE)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg


def quote_ident(name: str, db_type: str, schema: str | None = None) -> str:
    """按数据库类型引用标识符。

    已引用的标识符直接返回。包含特殊字符的标识符会被正确引用
    （如 ``my table`` → ``[my table]``），替代旧版直接报错的行为。
    引用符内部的引号会被转义（``"`` → ``""`` for PostgreSQL/SQLite，
    ``]`` → ``]]`` for SQL Server，`` ` `` → `` `` `` for MySQL）。
    """
    name = name.strip()
    if any((name.startswith(q[0]) and name.endswith(q[1])) for q in [("[", "]"), ("`", "`"), ('"', '"')]):
        return name

    # 拆成具名函数避免 Python 3.10 不支持的 f-string 引号复用语法（quote-reuse in f-string 是 3.12 新增）
    def _pg_quote(n: str) -> str:
        dq = '"'
        return f"{dq}{n.replace(dq, dq + dq)}{dq}"

    quoter = {
        "sqlserver": lambda n: f"[{n.replace(']', ']]')}]",
        "mysql": lambda n: f"`{n.replace('`', '``')}`",
        "postgresql": _pg_quote,
        "kingbase": _pg_quote,
        "sqlite": _pg_quote,
    }.get(db_type, lambda n: n)
    if schema:
        return f"{quoter(schema)}.{quoter(name)}"
    return quoter(name)


def check_read_only(sql: str, strict: bool = True) -> tuple[bool, str, str | None]:
    """检查 SQL 是否为写操作。

    首关键字判断基于 :func:`strip_comments`（首关键字不在字符串内）；
    strict 模式下的 DROP/DELETE/TRUNCATE/EXEC 等扫描基于 :func:`strip_strings`
    （剥离字符串字面量，避免 ``SELECT 'drop'`` 被误判）。
    """
    stmt = extract_first_statement(sql)
    if not stmt:
        return True, "", None
    first_word = stmt.split()[0].upper() if stmt.split() else ""
    if first_word in _WRITE_KEYWORDS:
        return False, first_word, f"语句以写操作关键字 '{first_word}' 开头"
    if strict:
        # 关键字扫描用剥离字符串后的结构，避免字面量误报
        scanned = strip_strings(stmt)
        if _RE_DROP.search(scanned):
            return False, "DROP", "检测到 DROP 语句"
        if _RE_DELETE.search(scanned):
            return False, "DELETE", "检测到 DELETE 语句"
        if _RE_TRUNC.search(scanned):
            return False, "TRUNCATE", "检测到 TRUNCATE 语句"
        if _RE_EXEC.search(scanned):
            return False, "EXEC", "检测到 EXEC/EXECUTE 动态执行"
        if _RE_BACKSLASH_CMD.search(scanned):
            return False, "SUSPICIOUS", "检测到危险系统存储过程"
        if _RE_ALTER.search(scanned):
            return False, "ALTER", "检测到 ALTER 语句"
        if _RE_MERGE.search(scanned):
            return False, "MERGE", "检测到 MERGE 语句"
        if _RE_INSERT.search(scanned):
            return False, "INSERT", "检测到 INSERT 语句"
        if _RE_SELECT_INTO.search(scanned):
            return False, "SELECT INTO", "检测到 SELECT INTO 建表语句"
        if _RE_UPDATE.search(scanned):
            return False, "UPDATE", "检测到 UPDATE 语句"
        if _RE_CREATE.search(scanned):
            return False, "CREATE", "检测到 CREATE 语句"
        if _RE_GRANT.search(scanned):
            return False, "GRANT", "检测到 GRANT 语句"
        if _RE_REVOKE.search(scanned):
            return False, "REVOKE", "检测到 REVOKE 语句"
        if _RE_DENY.search(scanned):
            return False, "DENY", "检测到 DENY 语句"
        if _RE_CALL.search(scanned):
            return False, "CALL", "检测到 CALL 语句"
        if _RE_COPY.search(scanned):
            return False, "COPY", "检测到 COPY 语句"
        if _RE_BACKUP.search(scanned):
            return False, "BACKUP", "检测到 BACKUP 管理操作"
        if _RE_RESTORE.search(scanned):
            return False, "RESTORE", "检测到 RESTORE 管理操作"
        if _RE_DBCC.search(scanned):
            return False, "DBCC", "检测到 DBCC 管理操作"
        if _RE_KILL.search(scanned):
            return False, "KILL", "检测到 KILL 管理操作"
        if _RE_SHUTDOWN.search(scanned):
            return False, "SHUTDOWN", "检测到 SHUTDOWN 管理操作"
        if _RE_RENAME.search(scanned):
            return False, "RENAME", "检测到 RENAME 管理操作"
    return True, first_word, None


# ─────────────────────────────────────────────────────────────────
# 全表扫描检测
# ─────────────────────────────────────────────────────────────────

_RE_SELECT_STAR = re.compile(
    r"\bSELECT\s+(?:DISTINCT\s+)?\*\s*FROM\b",
    re.IGNORECASE,
)
_RE_HAS_WHERE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_RE_HAS_LIMIT = re.compile(r"\b(?:LIMIT|FETCH\s+NEXT)\b", re.IGNORECASE)
_RE_HAS_TOP = re.compile(r"\bSELECT\s+(?:DISTINCT\s+)?TOP\s+\d+", re.IGNORECASE)


def is_full_table_scan(sql: str) -> bool:
    """检测是否为无 WHERE/LIMIT/TOP 约束的全表 SELECT * 扫描。

    用于警告，返回 True 表示该查询可能扫描全表（大表上代价高）。
    存在 TOP n / LIMIT / FETCH NEXT / WHERE 任一约束即视为受限，返回 False。
    扫描基于 :func:`strip_strings` 的结果，避免 ``SELECT '*'`` 字面量误判。
    """
    cleaned = strip_strings(sql)
    first_stmt = extract_first_statement(cleaned)
    if not first_stmt:
        return False
    if not _RE_SELECT_STAR.search(first_stmt):
        return False
    if _RE_HAS_TOP.search(first_stmt):
        return False
    return not (_RE_HAS_WHERE.search(first_stmt) or _RE_HAS_LIMIT.search(first_stmt))


# ─────────────────────────────────────────────────────────────────
# 导出路径校验
# ─────────────────────────────────────────────────────────────────

# 系统保护路径前缀（用于禁止导出，防止覆盖系统文件）。
# 使用路径前缀而非段包含判断，避免 C:\Users\zhang\WindowsBackup\、/home/zhang/bin/ 等误伤。
# 每个条目为小写路径前缀，导出时用 str(resolved_path).lower().startswith(prefix) 判断。
# 不含末尾斜杠："/etc" 能匹配 "/etc" 和 "/etc/passwd"，但不匹配 "/etcetera"。
_PROTECTED_PREFIXES: tuple[tuple[str, bool], ...] = (
    # Windows 系统目录
    (r"c:\windows", True),
    (r"c:\program files", True),
    (r"c:\program files (x86)", True),
    # Unix 系统核心目录（绝对路径前缀匹配）
    ("/etc", True),
    ("/boot", True),
    ("/proc", True),
    ("/sys", True),
    ("/dev", True),
    ("/sbin", True),
    ("/usr/sbin", True),
    ("/usr/bin", True),
    ("/usr/local/bin", True),
    ("/usr/local/sbin", True),
    ("/bin", True),
)


def is_protected_path(filepath: str) -> bool:
    """判断路径是否落在禁止导出的系统保护目录下。

    使用路径前缀匹配代替段包含判断（v0.5.0 旧实现的 bug）：
    - 旧：检查路径段是否与 "windows"/"bin" 等关键词字面相等
      → 误伤 C:\\Users\\zhang\\WindowsBackup\\file.csv（段 "windowsbackup" 含 "windows"）
      → 误伤 /home/zhang/bin/data.csv（段 "bin" == "bin"）
    - 新：仅匹配精确的系统目录路径前缀（/bin, /usr/bin, C:\\Windows...）
      → 不受用户名/子目录包含关键词影响

    同时用 .resolve() 解析符号链接，防止 /some_symlink → /etc/passwd 绕过。
    路径不存在时用字面路径判断（resolve 失败不影响安全判断）。

    注意：Unix 绝对路径（如 /etc/passwd）在 Windows 上被 resolve 成
    C:\\etc\\passwd，无法匹配 Unix 前缀。安全判断以 resolve 后的真实路径为准，
    Windows 平台通常不存在 /etc/... 等 Unix 路径，安全影响可忽略。
    """
    if not filepath or not filepath.strip():
        return True  # 空路径直接拒绝

    try:
        p = Path(filepath).expanduser()
    except (ValueError, OSError):
        return True  # 无法解析的路径默认拒绝

    # 收集待检查路径（字面 + resolve 后）去重，避免重复检查。
    # Unix 绝对路径（以 / 开头）在 Windows 上 resolve 后变成 C:\...，
    # 所以原始字面值也需要检查。两者都做 normalize 保证跨 OS 兼容。
    candidates: set[str] = set()
    try:
        resolved = p.resolve()
        candidates.add(str(resolved).lower())
    except (OSError, RuntimeError):
        pass  # 路径不存在时 resolve 可能抛异常，仅检查字面值
    literal = str(p).lower().replace("\\", "/")
    candidates.add(literal)

    for cand in candidates:
        for prefix, _ in _PROTECTED_PREFIXES:
            if cand.startswith(prefix):
                return True
    return False
