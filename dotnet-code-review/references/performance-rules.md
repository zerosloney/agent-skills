# Performance Rules Reference（P0xx 详解）

> 加载时机：解释规则的检测意图、生成修复方向、判断误报时。
> 数据来源：`scripts/csharp-ast-analyzer/Program.cs`（`LEGACY_P0*`）+ `scripts/csharp-semantic-analyzer/Program.cs`（`P_*` 语义规则）+ `run_review()` 内联（`P021`）+ dotnet build `CA18xx`。
> **口径声明**：Python regex 正则层已从 `run_review()` 移除；P0xx 的正则定义仅作规则目录保留，实际执行来自 Roslyn 层（`LEGACY_P0*`）+ `P021` 内联 + `CA18xx`。

## 严重度速览

| severity | 数量 | 触发原则 |
|----------|------|----------|
| error | 0 | —（性能红线已由 Roslyn `LEGACY_*` 权威覆盖） |
| warning | 16 | 常见性能陷阱，建议修复 |
| info | 5 | 微优化，按团队规范取舍 |

> 计数以 `python scripts/count_rules.py` 输出为准（P0xx 系列 21 条，0 error / 16 warning / 5 info）。

---

## P001 string-concatenation（warning）

**检测**：`+` 拼接字符串（连续 ≥ 2 个字符串字面量/变量）

```csharp
// 反例：循环外大量拼接
string result = "";
for (int i = 0; i < 1000; i++) {
    result = result + items[i].Name + ",";  // O(n²) 内存分配
}

// 正例：
var sb = new StringBuilder(8192);
foreach (var item in items) {
    sb.Append(item.Name).Append(',');
}
return sb.ToString();
```

**误报场景**：
- 2-3 次拼接（如 `"prefix-" + var + "-suffix"`）实际可读性更好
- 日志/异常消息临时拼接

**修复方向**：循环内改 `StringBuilder`；少量拼接保持原样。

---

## P002 string-compare-without-ordinal（info）

**检测**：`==` / `!=` 比较 string 而非 `string.Equals(..., StringComparison.Ordinal)`

```csharp
// 反例：当前 culture 影响比较结果
if (s1 == s2) { ... }  // 实际是 Ordinal 还是 CurrentCulture？取决于 .NET 版本

// 正例（显式意图）：
if (string.Equals(s1, s2, StringComparison.Ordinal)) { ... }
```

**误报场景**：
- 用户可见字符串比较（如 UI 文本）可能需要 culture-aware
- 配置键比较（应 Ordinal，但 `==` 在 .NET Core 3+ 默认 Ordinal）

---

## P003 list-contains-in-loop（warning）

**检测**：`List<T>.Contains` 在 O(n) 循环里调用

```csharp
// 反例：O(n*m)
var knownIds = new List<int> { 1, 2, 3, ..., 1000 };
foreach (var item in items) {
    if (knownIds.Contains(item.Id)) {  // 每次 O(n)
        Process(item);
    }
}

// 正例：O(n+m)
var knownIdSet = new HashSet<int>(knownIds);
foreach (var item in items) {
    if (knownIdSet.Contains(item.Id)) {  // O(1)
        Process(item);
    }
}
```

**误报场景**：
- 列表很小（< 20）时 `List.Contains` 实际更快（HashSet 初始化开销）
- 列表已是有序的，可用二分查找（不在本规则检测范围）

---

## P004 dictionary-contains-in-loop（info）

**检测**：`Dictionary.ContainsKey` 在循环里（应 `TryGetValue` 一次取值）

```csharp
// 反例：2 次查找
if (dict.ContainsKey(key)) {
    var val = dict[key];
}

// 正例：1 次查找
if (dict.TryGetValue(key, out var val)) {
    // use val
}
```

**误报场景**：
- `val` 真的不需要值时，`ContainsKey` 是正确 API

---

## P005 boxing-in-loop（warning）

**检测**：值类型在循环里隐式装箱

```csharp
// 反例：每次循环 boxing
ArrayList list = new ArrayList();
for (int i = 0; i < 1000; i++) {
    list.Add(i);  // int → object boxing
}

// 正例：泛型避免 boxing
List<int> list = new List<int>();
for (int i = 0; i < 1000; i++) {
    list.Add(i);
}
```

**误报场景**：几乎无——装箱是确定的反模式。

---

## P006 reflection-in-loop（warning）

**检测**：`MethodInfo.Invoke` / `Activator.CreateInstance` 在循环里

```csharp
// 反例：每次反射开销 ~μs 级
for (int i = 0; i < 10000; i++) {
    var result = methodInfo.Invoke(target, args);  // 反射调用
}

// 正例：缓存委托
var del = (Func<Args, Result>)Delegate.CreateDelegate(typeof(Func<Args, Result>), target, methodInfo);
for (int i = 0; i < 10000; i++) {
    var result = del(args);  // 直接调用
}
```

**误报场景**：循环次数 < 100 时反射开销可忽略。

---

## P007 string-format-in-loop（warning）

**检测**：`string.Format` 在循环里调用（无变化参数）

```csharp
// 反例：每次重新解析 format string
foreach (var item in items) {
    Console.WriteLine(string.Format("Item: {0}, {1}", item.Name, item.Value));
}

// 正例：提取 format string（实际上 string.Format 本身无缓存，仅是代码组织建议）
// 或用 interpolation：
foreach (var item in items) {
    Console.WriteLine($"Item: {item.Name}, {item.Value}");
}
```

---

## P008 regex-not-cached（info）

**检测**：`new Regex(...)` 在方法体内（应在 static readonly 字段）

```csharp
// 反例：每次调用重新编译 pattern
public bool IsValid(string s) {
    return new Regex(@"^\d+$").IsMatch(s);
}

// 正例：编译结果缓存
private static readonly Regex DigitRegex = new Regex(@"^\d+$", RegexOptions.Compiled);
public bool IsValid(string s) {
    return DigitRegex.IsMatch(s);
}
```

**误报场景**：动态 pattern（必须每次构造）无法缓存。

---

## P009 linq-multiple-enumeration（warning）

**检测**：同一 IEnumerable 被枚举多次

```csharp
// 反例：每次 Count/Any/ToList 都会重新执行 LINQ
public IEnumerable<int> GetActiveIds() {
    return items.Where(i => i.IsActive).Select(i => i.Id);
}

var ids = GetActiveIds();
if (ids.Count() > 0) {       // 枚举 1
    foreach (var id in ids) { // 枚举 2
        Process(id);
    }
}

// 正例：物化一次
var idList = GetActiveIds().ToList();
if (idList.Count > 0) {
    foreach (var id in idList) {
        Process(id);
    }
}
```

**误报场景**：
- LINQ 已经在源头实现为非延迟（少见）
- 性能不敏感的代码路径

---

## P010 string-empty-comparison（info）

**检测**：`"" == str` 而非 `string.IsNullOrEmpty(str)`

```csharp
// 反例：只检查空串，不检查 null
if (s == "") { ... }
// s == null 时不进 if，可能后续 NRE

// 正例：
if (string.IsNullOrEmpty(s)) { ... }
```

---

## P011 unnecessary-boxing（warning）

**检测**：隐式装箱（值类型 → object）

```csharp
// 反例：
object o = 42;        // boxing
int x = (int)o;       // unboxing
Console.WriteLine($"value is {42}");  // 隐式 boxing（但 interpolation 已优化）

// 正例：用泛型
List<int> list = ...;
```

---

## P012 unnecessary-allocation（warning）

> regex 定义为 `new string(char, int)` 特定模式（即 `new string('\t', n)` 这类按字符重复构造字符串），并由 Roslyn `LEGACY_new_string_char_int` 权威覆盖。

**检测**：`new string(<char>, <count>)` 重复分配字符串（应改用 `string.Create` / `Enumerable.Repeat` / 预分配缓冲等）

```csharp
// 反例：每次构造一个全空白字符串
var pad = new string(' ', width);  // new string(char, int) 分配

// 正例（按场景）：复用缓冲或用更高效 API
// - 缓冲场景：预分配 + 复用
// - 填充场景：string.Concat(Enumerable.Repeat(' ', width))
```

**误报场景**：
- 实际需要每轮独立对象（如线程局部）
- 估算大小不准（> 1KB 启发式保守）

---

## P013 inefficient-collection（warning）

**检测**：`List<T>` 用作频繁 Contains（应 HashSet）/ `Hashtable` 应换 `Dictionary<TKey,TValue>`

---

## P014 inefficient-string-operation（warning）

**检测**：`Substring(0, n)` + 拼接的常见低效模式（应 `string.Concat` 或 `string.Create`）

```csharp
// 反例：3 次分配
var result = s.Substring(0, 5) + "..." + s.Substring(5);

// 正例（C# 10+）：
var result = string.Concat(s.AsSpan(0, 5), "...", s.AsSpan(5));
```

---

## P015 unnecessary-conversion（warning）

> 已移除（broken heuristic：pattern 基于方法名匹配，对 C# 语义无效）。

**检测**：`ToString()` 在已是 string 的对象上调用

---

## P016 unnecessary-cast（warning）

> 已移除（broken heuristic：pattern 靠 `(T)obj` 计数，对 C# 无效）。

**检测**：多余 `(T)obj` 转换

---

## P017 unnecessary-interface（warning）

> 已移除（broken heuristic：按逗号/基类数判定，违反 C# 单继承）。

**检测**：接口仅有一个实现（按团队规范可折叠为具体类）

**误报场景**：
- 接口为可测试性 mock 存在
- 接口为未来扩展预留
- 公开 API 的稳定性

---

## P018 unnecessary-inheritance（warning）

> 已移除（broken heuristic：同 P017，按基类数判定无效）。

**检测**：子类未引入新成员（仅复用基类代码）

**建议**：用组合/扩展方法替代。

---

## P019 unnecessary-abstract（warning）

> 已移除（broken heuristic：pattern 对 C# 抽象类判定无效）。

**检测**：抽象类无抽象成员

**修复**：改 concrete 或 sealed。

---

## P020 unnecessary-sealed（warning）

> 已移除（broken heuristic：pattern 对 sealed 修饰判定无效）。

**检测**：`sealed` 修饰无意义（已是 sealed 缺省值，或类型为 value type）

---

## 性能规则总计

| 类别 | 规则数 | 说明 |
|------|--------|------|
| 内存分配 | P005, P011, P012, P014 | 装箱/重复分配 |
| 集合操作 | P003, P004, P013, P009 | 错误集合类型 / 多枚举 |
| 反射/动态 | P006, P008 | 反射 + Regex 实例化 |
| 字符串 | P001, P002, P007, P010, P014, P015 | 拼接/比较/format |
| 设计冗余 | P016, P017, P018, P019, P020 | 不必要的抽象/转换 |

## 推荐优先级（CI 场景）

> 下述 regex 规则多数已停用，权威检测由 Roslyn `LEGACY_*` 层产出（见 rules-catalog 第三节）。CI 实际阻断以 Roslyn 层结论为准。

1. **warning 建议**：P001 string concat loop, P005 boxing, P006 reflection in loop, P003 List.Contains, P009 LINQ multi-enum
2. **info 视团队规范**：P002, P004, P008, P010, P014（设计冗余类 P015-P020 为 broken heuristic，已 skip）

## 性能 vs 正确性边界

- 性能规则**不保证可测量的性能提升**——规则基于常见反模式启发式，实际提升取决于上下文
- 修复前应**profile** 验证 hot path
- 团队应建立"性能 review checklist"，结合 .NET Profiler / dotnet-trace 输出决策
