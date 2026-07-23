# 设计与绑定自审清单（Step 5）

> 由 SKILL.md Step 5 加载。生成所有文件后，**逐项核对**本清单。
> 每一项须明确「通过」或「不通过 + 原因」。不通过项须回炉修正后才能交付。

## A. 设计一致性

### A1. 布局 ↔ Entity 字段匹配

- [ ] 每个需展示的 Entity 公开属性都有对应的 UI 控件（列 / 表单项），或已显式标注「不展示原因」
- [ ] 字段类型 → 控件选型合理：
  - 主键（`Guid ID`）→ 不展示或隐藏列
  - 外键 / 关联字段 → `GridLookUpEdit` / `LookUpEdit`（显示名称、绑定 ID）
  - 枚举 / 状态 → 绑定枚举或 RepositoryItemComboBox，必要时带状态颜色
  - 文本 → `TextEdit` 列 / 控件
  - 数值 / 金额 → `SpinEdit` / 数字列（对齐右、格式化）
  - 日期 → `DateEdit` / 日期列（格式化）
  - 布尔 → `CheckEdit` / 复选列
  - 大文本 / 备注 → `MemoEdit` / Memo 列
- [ ] 必填字段在控件层有标识或校验
- [ ] 列顺序符合业务阅读习惯（主键 → 编码 → 名称 → 业务属性 → 时间 → 状态）

### A2. 与参照窗体一致

> 以 Step 1 扫描学习到的真实窗体为基准，不预设模式。
> 本节检查项与 SKILL.md Step 1 提取表一一对应；任一项与参照窗体不符 → 回 Step 1 重新确认。

- [ ] 窗体基类与参照窗体一致（如 `frmBase` / `frm_Base`，不混淆下划线）— 防 failure-modes 案例 5
- [ ] 是否泛型与参照窗体一致（`frmBase` 非泛型 vs `frm_Base<T>` 泛型，不混用）— 防案例 5
- [ ] 数据访问方式与参照窗体一致（`SqlOperate+ListOperate` vs ORM `DbHelp.Query<T>()`）— 防案例 1
- [ ] DBHelp 实例名 / 连接名与参照窗体一致（如 `varlist.ASSConn` / `varlist.ASSDBHelp`，**以 Step 0b 过滤注释后的扫描为准**）— 防案例 1
- [ ] GridStyle 初始化代号与参照窗体一致（`"ASS"` / `"CRS"` / `"CSS"`，大小写敏感）— 防案例 4
- [ ] 类名前缀约定与参照窗体一致（`DALMM_` / `Frm_` / `DlgEdit_` 等）— 防案例 8
- [ ] 命名空间与参照窗体同级
- [ ] `using` 引用集与参照窗体一致（尤其 DAL / Entity / Common 命名空间）
- [ ] WaitDialog 用法与参照窗体一致（`varlist_Dialog` / `UICommonBase.StartWaitForm`）
- [ ] 消息框用法与参照窗体一致（`XtraMessageBox.Show` / `UICommonBase.ShowMessageBox`）
- [ ] 事件处理结构（`try-catch-finally` 包裹、异常提示风格）与参照窗体一致

### A3. 文件位置

- [ ] 所有生成文件路径与参照窗体同级或遵循项目既有目录结构
- [ ] 文件名大小写风格与参照窗体一致（`frm` / `frm_` 前缀、`Ser` 后缀等）
- [ ] Designer 文件与窗体 `.cs` 同目录、同名

## B. 绑定一致性

### B1. 调用链无越级

- [ ] View（窗体）只调 Presenter，不直接调 Ser / DAL
- [ ] Presenter 只调 Ser，不直接调 DAL
- [ ] Ser 只调 DAL，不反向调 Presenter / View
- [ ] 新代码不生成 Collection 层（Ser 直连 DAL）；若参照窗体存在既有 Collection 中间层，已提示用户确认，未擅自合并或删除

### B2. View 接口 ↔ 窗体控件

- [ ] View 接口的每个 `set` 属性，在窗体类中有对应的赋值实现（赋给 `gc.DataSource` 等）
- [ ] 接口属性只有 `{ set; }`（单向数据流，不暴露 `get`）
- [ ] 窗体中 `_presenter = new {业务名}Presenter(this)` 在 `_Load` 中创建
- [ ] `Refresh*()` 方法（或 `RefreshDataSource()`）确实触发 Grid/控件刷新

### B3. Entity ↔ DB ↔ 内存

- [ ] 每个 Entity 公开属性的 setter 调用 `AddRecordChange(...)`（若参照窗体的 Entity 如此；ORM 变更追踪必需）
- [ ] Ser 内存缓存 `_lst{Entity}` 在增 / 删 / 改后同步更新
- [ ] DAL 的 SQL / ORM 操作字段集与 Entity 属性集一致（无遗漏列、无多余列）
- [ ] 查询 SQL 的 `WHERE` 条件、`ORDER BY` 符合业务需求
- [ ] SQL 参数化（`@param` / `:param`），无字符串拼接注入风险

### B4. 异常处理（对应 failure-modes 案例 6）

- [ ] **Presenter 不独立 try-catch**（异常冒泡到 View）— 防案例 6 双重弹窗
- [ ] **Ser 层不独立 try-catch 转 bool**（除非参照窗体约定如此；Upgrader 风格 Ser catch 返 false 是例外）
- [ ] 异常处理风格与参照窗体一致：
  - Upgrader 风格：Ser 层 `try-catch` 返回 `false`，View 层 `try-catch` 弹 `XtraMessageBox`
  - CRS 风格：Ser 层抛 `Exception`，View 层 `try-catch` 用 `UICommonBase.ShowMessageBox`
- [ ] 无吞异常（`catch (Exception) { }` 空块仅在不向上抛、已返回 false 时可接受）

### B5. 资源与事件安全

- [ ] 事件订阅只发生在 `InitializeComponent` 或 `_Load`，无重复订阅（同一事件挂两次 handler）
- [ ] 长时间操作包裹在等待窗体中（Upgrader: `SetTitleAndCaption / CloseWaitDialog`；CRS: `StartWaitForm / EndWaitForm`）
- [ ] `Dispose` / `FormClosed` 中显式释放 `BindingSource`、`SqlOperate`、`ListOperate` 等资源
- [ ] GridControl 的 RepositoryItem 已在 `gc.RepositoryItems.Add()` 注册（防 21.2 设计期静态创建报错）
- [ ] **Presenter 事件退订**：若 Presenter 订阅了 View 事件，则 Presenter 实现了 `IDisposable`，且 View 在 `FormClosed`/`Dispose` 中调用 `Presenter?.Dispose()`（防长期运行窗体内存泄漏）

## C. 输出完整性

- [ ] 所有应生成的文件都已创建（对照参照窗体的文件清单）
- [ ] 每个文件可独立编译（无缺失 using、无未定义类引用）
- [ ] 占位符（`{业务名}` / `{实体类}` / `{表名}` 等）已全部替换为真实值
- [ ] `.resx` 中按钮文本等初始可见文字与 Designer.cs `InitializeComponent` 一致，不硬编码 `.Text`

## D. MSBuild 验证

### D1. 构建执行

- [ ] 已确认构建入口（`.sln` 优先；没有 `.sln` 时用目标 `.csproj`）
- [ ] 已使用 Windows/.NET Framework 项目的 `MSBuild.exe` 执行构建，未用 `dotnet build` 替代
- [ ] Configuration/Platform 与项目既有配置一致；无法推断时已询问用户

### D2. 失败分类标准（修前必须分类）

构建失败时，按以下 4 类归类，**不混合**：

| 类别 | 判定标准 | 处理方式 |
|------|---------|---------|
| **本次生成错误** | 错误指向本次新建/修改的文件/行号 | 回炉修复后重跑完整自审 |
| **预先存在错误** | 错误在参照窗体或第三方库中，与本次改动无关 | 交付时列出，不修 |
| **环境缺依赖** | `DevExpress.*.dll` 找不到、NuGet 包未还原 | 交付时列出修复步骤，不修 |
| **待用户确认配置** | 连接名 / 路径 / 密钥需要用户提供 | 交付时列出所需信息，不修 |
| **上游项目 P2P 引用失败** | 错误为 `type or namespace not found` 但指向的是另一个被引用的 `.csproj`；`BuildLog.htm` 或 MSBuild 输出显示上游项目先失败 | 先单独编译上游 `.csproj`，确认上游通过后再重新构建当前项目；交付时列出受影响的上游项目 |

- [ ] 构建失败已按上表归类
- [ ] 若属于「本次生成错误」，已回炉修复并重新执行完整自审（A+B+C+D1）
- [ ] 若不属于「本次生成错误」，已在交付物中明确列出：**错误内容 + 分类 + 建议修复方**
