# Example 2 — Warehouse_Data(Entity 不全)

> 对应 failure-modes 案例 2(Entity 不完整或缺失)。
> **实战项目**:某物流系统,表名 `JDDR_MMA_Warehouse_Data`,仅有轻量 DTO `WarehouseLookup`(3 字段),需要扩字段生成完整 Entity。

---

## 1. 场景描述

**用户原话**:
> "`JDDR_MMA_Warehouse_Data` 表里有 12 个字段,但项目里有个 `WarehouseLookup.cs` 只有 ID/Code/Name 3 个字段,我想做的是完整仓库管理,不是简单 lookup,字段全要展示。"

**上下文**:
- 完整字段需要查 DB 才能获得完整 schema
- 既有 `WarehouseLookup` 仅 3 字段(GUID/Code/Name)
- 完整表 schema:`ID, Code, Name, Address, Province, City, Phone, ManagerID, ManagerName, Status, CreateTime, Remark`

---

## 2. Step 0 — 目标目录定位

```bash
PROJECT_ROOT = C:\Src\LogisticsSystem
TARGET_DIR   = C:\Src\LogisticsSystem\Modules\Warehouse\UI
MODULE_NAME  = Warehouse
```

---

## 3. Step 0a — 4 项必填门

| # | 确认项 | 取值 |
|---|--------|------|
| 1 | 业务名 / 窗体名 | `WarehouseDataList` / `Frm_WarehouseDataList` |
| 2 | Entity 或字段来源 | 🟡 **`Entity.WarehouseInfo` 可能不全;只有 `WarehouseLookup` DTO**——见 Step 2 处理 |
| 3 | 项目根 + 目标目录 | 见 §2 |
| 4 | 构建入口 | `LogisticsSystem.sln`,Debug/AnyCPU |

⚠️ **Step 0a 卡 1 次**——Entity 不全问题在 Step 2 解决,但**不能臆造字段**。

---

## 4. Step 0b — 项目指纹卡

> **命令**:跑 `references/project-fingerprint.md §0.2` 的 glance 档(6 查询,全部过滤注释 + 文件级去重)。命令权威以 §0.2 为准,此处不重复。

> 本案目标模块 `Modules\Warehouse` 的目录结构(展示 Entity 缺失上下文,非指纹扫描命令):
> ```text
> Modules\Warehouse\
>   DAL\        # 已有 WarehouseLookupDAL.cs(只含 3 字段查询)
>   BLL\        # 已有 LookupSer.cs
>   UI\         # 仅一个 Lookup 对话框
>   Entity\     # 只有 WarehouseLookup.cs(3 字段 DTO)  ← 本案卡点
> ```

**指纹卡**:
| 维度 | 主导 | 占比 | 异类 |
|------|------|------|------|
| 窗体基类 | `frmBase` | 100% | — |
| 数据访问 | `SqlOperate+ListOperate` | 100% | — |
| GridStyle | `"ASS"` | 100% | — |
| DBHelp | `varlist.MainConn`(部分模块用 `LogConn`) | — | — |

**主家族**:**A. Deve-Upgrader**(完全匹配)

**异质性等级**:🟢 **纯一**。

**类名前缀扫描**:
```powershell
Get-ChildItem "$projectRoot\Modules\*\DAL\*.cs" | Select-Object -First 10
DALMM_Warehouse.cs          # ← 模块前缀!
DALMM_Order.cs
DALMM_Inventory.cs
```

→ 前缀约定:**`DALMM_`** 命名 + `Frm_{业务}` + `DlgEdit_{业务}`。

---

## 5. Step 1 — 模式提取表

对照窗体:`Frm_LookupTest.cs`(同模块的简单 lookup 窗体)。

| 提取项 | 提取结果 |
|--------|---------|
| 窗体基类 | `frmBase` |
| 命名空间 | `Logistics.Modules.Warehouse.UI` |
| 数据访问 | `SqlOperate _so + ListOperate _tolist` |
| 是否泛型 | ❌ 非泛型 |
| GridStyle | `"ASS"` |
| DBHelp / 连接名 | `varlist.LogConn`(注意是 LogConn,不是 MainConn) |
| **类名前缀约定** | 🟡 **`DALMM_`**(模块前缀)——与 example 1 不同,这是模块级前缀 |
| WaitDialog | `UICommonBase.StartWaitForm(...) / EndWaitForm()` |
| 消息框 | `UICommonBase.ShowMessageBox(MessageType.Message, msg)` |
| View 接口 | 单向 set + Refresh* |
| 异常处理 | Ser 层 `try-catch → false`,View 层 catch + ShowMessageBox |

---

## 6. Step 2 — 字段→控件 映射表(本案关键)

**Step 2 启动时字段不清**:
```powershell
Get-ChildItem "$projectRoot\Modules\Warehouse\Entity"
WarehouseLookup.cs    # 只有 ID/Code/Name

& rg -g "*.cs" "SELECT.*FROM JDDR_MMA_Warehouse_Data" $projectRoot
(空)                 # 项目代码里没人查过完整表!
```

**触发 failure-modes 案例 2**(Entity 不全)+ 案例 3(schema 不可读)。

### 选项:3 选 1,**必问用户**

提问模板(必查 case 2 修复方案):
```markdown
Entity.WarehouseInfo 不存在,且仅 WarehouseLookup DTO 有 3 字段。
完整字段需查 DB 或用户提供。3 选 1:

A. 我帮你新建 Entity.WarehouseInfo(列全字段,ORM 风格 setter 调 AddRecordChange)
   → 需查 DB 完整 schema(SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='JDDR_MMA_Warehouse_Data')
   → 适合 长期维护本模块

B. 复用 WarehouseLookup 扩展(保留轻量风格,补 9 个字段)
   → 不查 DB,你提供完整字段清单
   → 适合 临时 lookup 用,长期不建议

C. 走 DataTable 模式(不建 Entity,直接读 DataTable 转内存字典)
   → 复用 GetWarehouseLookup() 模式 + 增加方法 GetWarehouseAll()
   → 适合 临时展示,不修改

请选 A/B/C?
```

**用户回复**:"走 A,我把字段清单给你——ID, Code, Name, Address, Province, City, Phone, ManagerID, ManagerName, Status, CreateTime, Remark"

### 用户确认后的字段映射表

| Entity 字段 | 类型 | 控件 | 列名 | 备注 |
|-------------|------|------|------|------|
| ID | Guid | 隐藏列 | — | 主键 |
| Code | string | TextEdit | `colCode` | 编码 |
| Name | string | TextEdit | `colName` | 仓库名 |
| Address | string | TextEdit | `colAddress` | 地址 |
| Province | string | TextEdit | `colProvince` | 省份 |
| City | string | TextEdit | `colCity` | 城市 |
| Phone | string | TextEdit | `colPhone` | 电话 |
| ManagerID | Guid? | GridLookUpEdit | `colManager` | 显示姓名,绑 ID |
| ManagerName | string | (冗余) | 不显示 | —— |
| Status | enum | RepositoryItemComboBox | `colStatus` | 启用/停用 |
| CreateTime | DateTime | RepositoryItemDateEdit | `colCreateTime` | yyyy-MM-dd |
| Remark | string | MemoEdit 列 | `colRemark` | 备注 |

→ 字段 12 个(去掉冗余 ManagerName 共 11 列)→ **GridControl + GridView**(不是 LayoutControl)。

---

## 7. Step 3 — frm vs ucl

独立菜单入口 → `frm`。

---

## 8. Step 4 — 三层生成产物

```
Modules/Warehouse/Entity/WarehouseInfo.cs           # 新建(完整 12 字段)
Modules/Warehouse/Entity/WarehouseLookup.cs         # 不动
Modules/Warehouse/DAL/DALMM_Warehouse.cs            # 新建(类名前缀!)
Modules/Warehouse/BLL/WarehouseSer.cs               # 新建
Modules/Warehouse/BLL/WarehousePresenter.cs         # 新建
Modules/Warehouse/UI/IWarehouseDataListView.cs      # 新建
Modules/Warehouse/UI/Frm_WarehouseDataList.cs       # 新建
Modules/Warehouse/UI/Frm_WarehouseDataList.Designer.cs
Modules/Warehouse/UI/Frm_WarehouseDataList.resx
```

### 关键代码:Entity(每个 setter 调 AddRecordChange)

```csharp
[Serializable]
[DBTableAttribute("JDDR_MMA_Warehouse_Data")]
public class WarehouseInfo : DBUpdateObjectBase
{
    private Guid _ID;
    [DBColumnAttribute(IsPrimaryKey = true)]
    public Guid ID
    {
        get { return _ID; }
        set { AddRecordChange("ID", _ID, value); _ID = value; }
    }

    private string _Code;
    public string Code
    {
        get { return _Code; }
        set { AddRecordChange("Code", _Code, value); _Code = value; }
    }

    // ... 其他 10 个字段同理 ...

    private DateTime _CreateTime;
    public DateTime CreateTime
    {
        get { return _CreateTime; }
        set { AddRecordChange("CreateTime", _CreateTime, value); _CreateTime = value; }
    }
}
```

### 关键代码:DAL(用类名 `DALMM_Warehouse`)

```csharp
public class DALMM_Warehouse  // ← 类名前缀必须遵循(案例 8)
{
    private readonly SqlOperate _so = new SqlOperate();
    private readonly ListOperate _tolist = new ListOperate();
    private const string CONN = "LogConn";  // ← LogConn 而非 MainConn

    public List<WarehouseInfo> Query(string keyword, int? status)
    {
        // 12 字段全查
        string sql = @"SELECT ID, Code, Name, Address, Province, City, Phone,
                       ManagerID, ManagerName, Status, CreateTime, Remark
                       FROM JDDR_MMA_Warehouse_Data WHERE 1=1 ";
        // ... WHERE 拼接 ...
        var dt = _so.ReadDataToDataTable(sql, CONN, pars);
        return _tolist.FillModel<WarehouseInfo>(dt);
    }
}
```

---

## 9. Step 5a — review-checklist 关键项

- ✅ **B3.1** Entity 12 字段 setter 全部 `AddRecordChange`
- ✅ **B3.2** Ser 内存缓存 `_lstWarehouseInfo` 同步
- ✅ **B3.3** DAL SELECT 字段集与 Entity 12 个公共属性一致
- ✅ **A2.1** 窗体基类 `frmBase`
- ✅ **A2.4** DBHelp 连接名 `LogConn`(从 `Frm_LookupTest.cs` 用 `rg` 确认)
- 🟡 **A3.2** 类名 `DALMM_Warehouse`(模块前缀,案例 8 防御)

---

## 10. Step 5b — MSBuild 命令与结果

```powershell
$ & "C:\Program Files (x86)\MSBuild\...\MSBuild.exe" `
    .\LogisticsSystem.sln /p:Configuration=Debug /p:Platform="Any CPU" /v:minimal
```

**输出**:
```
Build succeeded.
    2 Warning(s)  (warning CS0168: variable 'ex' declared but never used——2 处)
    0 Error(s)
```

✅ 通过(警告可接受)。

---

## 11. 失败点 + 沉淀

| 时间点 | 失败 | 修复 | 沉淀 |
|--------|------|------|------|
| Step 2 启动 | Entity.WarehouseInfo 不全,只有 DTO | 触发案例 2,3 选 1;用户选 A + 提供字段清单 | **failure-modes 案例 2** |
| Step 1 提取 | 类名前缀错写为 `DAL_Warehouse` | 扫描项目全模块,确认是 `DALMM_` 前缀 | **failure-modes 案例 8** |
| Step 1 提取 | 连接名错写为 `MainConn` | `rg "varlist\.[A-Za-z]+Conn"` 找到 `LogConn` | **failure-modes 案例 1** |
| Step 4 Ser 层 | catch 块声明了 `ex` 但没使用 | 加 `_ = ex.Message;` 或删变量 | review-checklist 加:无未使用变量 |

---

## 12. 本案例的可复用价值

1. **Entity 不全时,3 选 1 模板**——可作为 Step 2 启动前的事实标准
2. **`DALMM_` 模块前缀约定**——Deve-Upgrader 项目的子模块可能用模块级前缀
3. **`LogConn` 而非 `MainConn`**——同一项目内多连接名,Step 0b 已能扫描,Step 1 确认即可
