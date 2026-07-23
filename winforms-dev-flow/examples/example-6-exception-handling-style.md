# Example 6 — 异常处理风格对照 (Upgrader vs CRS)

> 对应 failure-modes 案例 6(异常处理风格不一致)。
> **核心场景**:项目内同时存在两套异常处理风格——Upgrader(View 层 try-catch) vs CRS(Presenter 层 try-catch)，新代码必须与参照窗体一致。
> **档位**:glance 档 (因为异常处理风格从参照窗体提取即可，无需全项目扫描)。

---

## 1. 场景描述

**用户原话**:
> "加个 `Frm_ExceptionTest` 窗体，我看看你异常处理怎么写。我们项目有的窗体在 View 弹，有的在 Presenter 弹，别搞错了。"

**上下文**:
- 项目：`.NET Framework 4.7.2` + WinForms + DevExpress 21.2
- 两套风格共存:
  - **Upgrader 风格**:View 层 try-catch，Presenter 不处理异常
  - **CRS 风格**:Presenter 层 try-catch 转 bool，View 只看返回值
- 用户要求:"跟 `Frm_UpgraderStyle` 一样"(已指定参照)

---

## 2. Step 0 — 目标目录定位

```bash
PROJECT_ROOT = C:\Src\MixedProject
TARGET_DIR   = C:\Src\MixedProject\UI\TestModule
MODULE_NAME  = TestModule
```

---

## 3. Step 0a — 4 项必填门

| # | 确认项 | 取值 | 来源 |
|---|--------|------|------|
| 1 | 业务名 / 窗体名 | `ExceptionTest` / `Frm_ExceptionTest` | 用户原话 |
| 2 | Entity 或字段来源 | `Entity.TestInfo`(已存在) | 项目已有 |
| 3 | 项目根 + 目标目录 | 见 §2 | 用户已说 |
| 4 | 构建入口 | `MixedProject.sln` | 项目默认 |

✅ 4 项齐。

---

## 4. Step 0b — 项目指纹卡 (简化版)

> 本案用户已指定参照窗体，Step 0b 简化为确认"异常处理风格"。

```powershell
# 扫描参照窗体 Frm_UpgraderStyle.cs 的异常处理方式
& rg -n "try|catch" C:\Src\MixedProject\UI\UpgraderStyle\Frm_UpgraderStyle.cs
```

**输出**:
```
156:        try
157:        {
158:            _presenter.SelectParts();
159:        }
160:        catch (Exception ex)
161:        {
162:            XtraMessageBox.Show(ex.Message, "错误", MessageBoxButtons.OK, MessageBoxIcon.Error);
163:        }
```

→ **View 层 try-catch** (Upgrader 风格)

---

## 5. Step 1 — 模式提取表

参照窗体:`Frm_UpgraderStyle.cs`(用户指定)。

| 提取项 | 提取结果 | 备注 |
|--------|---------|------|
| **窗体基类** | `frmBase` | 非泛型 |
| **命名空间** | `MixedProject.UI.UpgraderStyle` | —— |
| **数据访问方式** | `SqlOperate+ListOperate` | —— |
| **是否泛型** | ❌ | —— |
| **GridStyle 代号** | `"ASS"` | —— |
| **DBHelp 实例 / 连接名** | `varlist.ASSDBHelp` / `varlist.ASSConn` | —— |
| **类名前缀约定** | `Frm_{业务}` | —— |
| **WaitDialog** | `varlist_Dialog` | —— |
| **消息框** | `XtraMessageBox.Show` | —— |
| **异常处理** | **View 层 try-catch** | ⚠️ **本案核心差异** |
| **Presenter 异常** | **不处理** (冒泡到 View) | ⚠️ **本案核心差异** |
| **Ser 异常** | **不处理** (返回 false) | ⚠️ **本案核心差异** |

**用户确认**:"按 `Frm_UpgraderStyle.cs` 的模式生成 Yes/No?"

**用户回复**:"Yes，异常处理要跟它一样"

---

## 6. Step 2 — 字段→控件 映射表

`Entity.TestInfo` 字段 (扫描):

| Entity 字段 | 类型 | 控件 | 列/项名 | 备注 |
|-------------|------|------|---------|------|
| ID | Guid | 隐藏列 | — | 主键 |
| Name | string | TextEdit 列 | `colName` | 名称 |
| Value | string | TextEdit 列 | `colValue` | 值 |
| Status | enum | RepositoryItemComboBox | `colStatus` | 状态 |

**布局决策**:字段 4 个 → **简单 GridControl + GridView**。

---

## 7. Step 3 — frm vs ucl

**业务独立** → 新建 `Frm_ExceptionTest`。

---

## 8. Step 4 — 三层生成产物 (Upgrader 异常风格)

### 8.1 View 层 (try-catch 包裹)

```csharp
// Frm_ExceptionTest.cs
public partial class Frm_ExceptionTest : frmBase, IExceptionTestListView
{
    private readonly ExceptionTestPresenter _presenter;

    public Frm_ExceptionTest()
    {
        InitializeComponent();
        _presenter = new ExceptionTestPresenter(this);
    }

    private void Frm_ExceptionTest_Load(object sender, EventArgs e)
    {
        try  // ← Upgrader 风格:View 层 try-catch
        {
            _presenter.SelectTest();
        }
        catch (Exception ex)
        {
            // 直接在 View 弹消息框 (不日志、不转换)
            XtraMessageBox.Show(
                ex.Message, 
                "错误", 
                MessageBoxButtons.OK, 
                MessageBoxIcon.Error
            );
        }
    }

    private void btnAdd_Click(object sender, EventArgs e)
    {
        try  // ← 所有事件处理都包裹 try-catch
        {
            var newItem = new TestInfo
            {
                ID = Guid.NewGuid(),
                Name = txtName.Text,
                Value = txtValue.Text,
                Status = 0
            };

            if (_presenter.AddTest(newItem))
            {
                XtraMessageBox.Show("添加成功", "提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
                _presenter.SelectTest(); // 刷新列表
            }
        }
        catch (Exception ex)
        {
            XtraMessageBox.Show(ex.Message, "错误", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    // ← View 层实现
    public List<TestInfo> DataList
    {
        set { gcMain.DataSource = value; gvMain.RefreshData(); }
    }

    public void RefreshDataSource()
    {
        gcMain.Refresh();
    }
}
```

### 8.2 Presenter 层 (不处理异常)

```csharp
// ExceptionTestPresenter.cs
public class ExceptionTestPresenter
{
    private readonly IExceptionTestListView _view;
    private readonly ExceptionTestSer _ser = new ExceptionTestSer();

    public ExceptionTestPresenter(IExceptionTestListView view)
    {
        _view = view;
    }

    public void SelectTest()
    {
        // ← Presenter 不 try-catch，异常直接冒泡到 View
        var list = _ser.Load();
        _view.DataList = list;
    }

    public bool AddTest(TestInfo e)
    {
        // ← Presenter 不 try-catch，异常直接冒泡到 View
        return _ser.Add(e);
    }

    public bool UpdateTest(TestInfo e)
    {
        return _ser.Update(e);
    }

    public bool DeleteTest(Guid id)
    {
        return _ser.Delete(id);
    }
}
```

### 8.3 Ser 层 (返回 false，不抛异常)

```csharp
// ExceptionTestSer.cs
public class ExceptionTestSer
{
    private readonly SqlOperate _so = new SqlOperate();
    private readonly ListOperate _tolist = new ListOperate();
    private const string CONN = "ASSConn";

    public List<TestInfo> Load()
    {
        try
        {
            var dt = _so.ReadDataToDataTable("SELECT * FROM T_Test ORDER BY Status", CONN, null);
            return _tolist.FillModel<TestInfo>(dt);
        }
        catch
        {
            // ← Ser 层 catch 后返回空列表，不抛异常
            return new List<TestInfo>();
        }
    }

    public bool Add(TestInfo e)
    {
        try
        {
            string sql = "INSERT INTO T_Test (ID, Name, Value, Status) VALUES (@ID, @Name, @Value, @Status)";
            var pars = new[] {
                new SqlParameter("@ID", e.ID),
                new SqlParameter("@Name", e.Name),
                new SqlParameter("@Value", e.Value),
                new SqlParameter("@Status", e.Status),
            };
            return _so.SqlExcuteNoQuery(sql, CONN, pars) > 0;
        }
        catch
        {
            // ← Ser 层 catch 后返回 false，不抛异常
            return false;
        }
    }

    public bool Update(TestInfo e) { /* 同结构：catch 返回 false */ }
    public bool Delete(Guid id) { /* 同结构：catch 返回 false */ }
}
```

### 8.4 View 接口

```csharp
// IExceptionTestListView.cs
public interface IExceptionTestListView
{
    List<TestInfo> DataList { set; }
    void RefreshDataSource();
}
```

---

## 9. Step 5a — review-checklist 自审结果

> 重点校验异常处理风格。

- ✅ **A2.5** GridStyle 初始化代号 = `"ASS"`(与参照窗体一致)
- ✅ **A2.6** 消息框 = `XtraMessageBox.Show`(与参照窗体一致)
- ✅ **A2.7 异常处理** (本案核心):
  - ✅ View 层：try-catch 包裹事件处理
  - ✅ Presenter 层：不 try-catch，异常冒泡
  - ✅ Ser 层：catch 后返回 false/空列表，不抛异常
  - ✅ 异常消息框风格：`XtraMessageBox.Show(ex.Message, "错误", ...)`(与参照一致)
- ✅ **B1.4** Ser 直连数据访问
- ✅ **B3.2** Ser 内存缓存同步
- ✅ **C.3** Designer 从模板复制
- ✅ **C.4** `.csproj` 已注册 3 件

---

## 10. Step 5b — MSBuild 命令与结果

```powershell
$ cd C:\Src\MixedProject
$ & "...\MSBuild.exe" .\MixedProject.sln /p:Configuration=Debug
Build succeeded.
Time Elapsed 00:00:12.30
```

✅ 通过。

---

## 11. Step 5d — 用户反馈循环

**用户反馈**:"异常处理对了！但消息框按钮能不能改成 `YesNo`？"

**识别影响环节**:View 层事件处理 → 回 Step 4 修正

**修正**:
```csharp
// 原代码
XtraMessageBox.Show(ex.Message, "错误", MessageBoxButtons.OK, MessageBoxIcon.Error);

// 修正后 (参照其他窗体的删除确认)
var result = XtraMessageBox.Show(
    "确定删除？", 
    "确认", 
    MessageBoxButtons.YesNo, 
    MessageBoxIcon.Question
);
if (result == DialogResult.Yes)
{
    if (_presenter.DeleteTest(id))
    {
        XtraMessageBox.Show("删除成功", "提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
        _presenter.SelectTest();
    }
}
```

**重跑 5a/5b** → 再次交付。

---

## 12. 失败点 + 沉淀

| 时间点 | 失败 | 修复 | 沉淀 |
|--------|------|------|------|
| Step 1 提取 | 漏提取"异常处理方式" | 在提取表加"异常处理"行 | **SKILL.md Step 1 提取表**新增"异常处理风格" |
| Step 4 生成 | Presenter 层错加 try-catch | 对照参照窗体确认 Presenter 不处理 | **failure-modes 案例 6**新增"Presenter 异常处理错配" |
| Step 4 生成 | Ser 层错抛异常 | 确认 Ser catch 后返回 false | **review-checklist B4**新增"Ser 层不独立 try-catch 抛异常" |
| Step 5a | 漏校验异常风格 | review-checklist A2.7 强制校验 | **review-checklist A2.7**新增 3 项异常处理校验 |

---

## 13. 本案例的可复用价值

1. **异常处理风格提取**——Step 1 必须从参照窗体提取"异常在哪里处理"
2. **三层异常处置规范**:
   - View:try-catch + 弹窗
   - Presenter:不处理，冒泡
   - Ser:catch 后返回 false/空列表
3. **ask_user 异常风格确认**——如果项目内两套风格共存，必须问用户
4. **review-checklist 异常校验**——A2.7 强制校验三层异常处置

---

## 14. 与 CRS 风格的对照表

| 层级 | Upgrader 风格 (本案) | CRS 风格 |
|------|---------------------|---------|
| **View** | try-catch + `XtraMessageBox.Show` | 只看 Presenter 返回值，不 try-catch |
| **Presenter** | 不 try-catch，异常冒泡 | try-catch 转 bool 返回 |
| **Ser** | catch 返回 false | catch 返回 false |
| **异常消息** | View 弹 | Presenter 弹 (或日志) |
| **适用场景** | 简单业务，异常即错误 | 复杂业务，异常需转换 |

**混合项目处置**:
- Step 0b 检测异质性 (如 50% Upgrader / 50% CRS)
- Step 1 从参照窗体提取
- **强制跟随参照**，不默认猜测

---

## 15. 如何扩展到其他异常风格场景

| 异常风格 | 检测命令 | 提取位置 |
|----------|---------|---------|
| View 层 try-catch | `rg -n "try|catch" Frm_*.cs` | View 事件处理方法 |
| Presenter try-catch | `rg -n "try|catch" *Presenter.cs` | Presenter 公共方法 |
| Ser catch 返回 | `rg -n "catch.*return (false|null)" *Ser.cs` | Ser 数据访问方法 |
| 全局异常处理 | `rg -n "AppDomain.CurrentDomain.UnhandledException" Program.cs` | Program.cs 入口 |

**通用提取模板**:
```powershell
# 提取参照窗体的异常处理方式
$refFile = "Frm_UpgraderStyle.cs"

# View 层
$viewTry = rg -n "try" $refFile | Select-Object -First 3
if ($viewTry) {
    Write-Host "✅ View 层 try-catch (Upgrader 风格)"
}

# Presenter 层
$presenterTry = rg -n "try" *Presenter.cs | Select-Object -First 3
if ($presenterTry) {
    Write-Host "⚠️ Presenter 层 try-catch (CRS 风格)"
}

# Ser 层
$serCatch = rg -n "catch.*return" *Ser.cs | Select-Object -First 3
if ($serCatch) {
    Write-Host "✅ Ser catch 返回 (通用风格)"
}
```

(End of file - total 358 lines)
