# Example 3 — Schema 未知 + DB 不可达

> 对应 failure-modes 案例 3(数据库连接缺失 / 无 Entity / 无字段清单)。
> **最坏情况**:用户只给了一个表名,其他都没,DB 也连不上。

---

## 1. 场景描述

**用户原话**:
> "我用你的 skill 做一个叫 `Frm_OrderList` 的窗体,表叫 `t_Order_2024`。我也不知道你能不能连我 DB,反正字段就在表里,你看着办。"

**上下文**:
- ❌ 没有 `Entity.OrderInfo`
- ❌ 没有 ORM 文件
- ❌ SQL 脚本里也没有 `t_Order_2024` 的查询
- ❌ DB 工具不可用(网络限制、密码未知)
- ✅ 只有表名

**触发**:failure-modes 案例 3 + 案例 5 阈值降低(无参照时)。

---

## 2. Step 0 — 目标目录定位

```bash
PROJECT_ROOT = C:\Src\SomeProject
TARGET_DIR   = C:\Src\SomeProject\UI\Order   # 不存在,需创建
MODULE_NAME  = Order
```

---

## 3. Step 0a — 4 项必填门(严重不全)

| # | 确认项 | 现状 | 状态 |
|---|--------|------|------|
| 1 | 业务名 / 窗体名 | `Order` / `Frm_OrderList` | ✅ 有 |
| 2 | Entity 或字段来源 | 🟡 **完全缺失** | ❌ 必须解决 |
| 3 | 项目根 + 目标目录 | SomeProject/UI/Order | ✅ 有 |
| 4 | 构建入口 | SomeProject.sln | ✅ 有 |

**Step 0a 阻断**:**Entity 完全缺失,Step 2 无法启动**。

---

## 4. Step 0b — 项目指纹卡

> **命令**:跑 `references/project-fingerprint.md §0.2` 的 glance 档(6 查询,全部过滤注释 + 文件级去重)。命令权威以 §0.2 为准,此处不重复。

> 本案相关文件清单(展示 schema 不可读时的上下文,非指纹扫描命令):
> ```text
> UI/Lookup/frm_OrderLookup.cs   # 仅一个 lookup,字段几个
> DAL/_OrderDAL.cs                # 仅 SELECT * 单条查询
> BLL/OrderQuery.cs
> ```

| 维度 | 主导 | 占比 |
|------|------|------|
| 窗体基类 | `frmBase` | 100% |
| 数据访问 | `SqlOperate+ListOperate` | 100% |
| GridStyle | `"ASS"` | 100% |
| DBHelp | `varlist.MainConn` | 100% |

**主家族**:**A. Deve-Upgrader**(完全匹配)
**异质性等级**:🟢 **纯一**

**类名前缀扫描**:
```powershell
Get-ChildItem "$projectRoot\DAL\*.cs" | Select-Object -First 10
DAL_Order.cs        # ← 单下划线
DAL_Inventory.cs
DAL_Part.cs
```

→ 前缀:`DAL_{业务}`(无模块前缀)+ `Frm_{业务}List`。

---

## 5. Step 1 — 模式提取表

参照窗体:`UI/Lookup/frm_OrderLookup.cs`(同业务小窗体)。

| 提取项 | 提取结果 |
|--------|---------|
| 窗体基类 | `frmBase` |
| 命名空间 | `SomeProject.UI.{模块}`(具体见项目) |
| 数据访问 | `SqlOperate+ListOperate` 原始 SQL |
| 是否泛型 | ❌ |
| GridStyle | `"ASS"` |
| DBHelp | `varlist.MainConn` |
| 类名前缀 | `DAL_{业务}` / `Frm_{业务}List` |
| WaitDialog | `varlist_Dialog` |
| 消息框 | `XtraMessageBox.Show` |

✅ Step 1 提取成功(有 1 个低相关度参照窗体,够提取家族风格)。

---

## 6. Step 2 — 字段→控件 映射表

### 6.1 字段获取路径(failure-modes 案例 3 解决)

**路径 1:连 DB 查 schema**(首选)
```bash
# Agent 跑 database-explorer MCP
mavis mcp call database-explorer query_table_schema \
    '{"connection": "...", "table": "t_Order_2024"}'
```

**路径 2:用户清单**(备选)
```markdown
请提供 t_Order_2024 表的字段清单:
- 字段名 / 类型 / 是否主键 / 是否可空 / 默认值
- 或者直接给一份 `DESC t_Order_2024` 输出
```

**路径 3:扫 SQL 找 hints**(兜底)
```powershell
& rg -g "*.cs" "INSERT.*t_Order|SELECT.*t_Order|UPDATE t_Order" $projectRoot
(找到 _OrderDAL.cs 的 SELECT * 单条)
Get-Content _OrderDAL.cs
SELECT * FROM t_Order_2024 WHERE OrderID=@id
```

→ 至少有 `OrderID` 主键字段被引用过;其他字段靠用户清单或 DB。

### 6.2 假设用户给了完整字段

| Entity 字段 | 类型 | 控件 | 列名 |
|-------------|------|------|------|
| OrderID | Guid | 隐藏列 | — |
| OrderNo | string | TextEdit | `colOrderNo` |
| CustomerName | string | TextEdit | `colCustomerName` |
| Amount | decimal | SpinEdit | `colAmount` |
| Status | enum | RepositoryItemComboBox | `colStatus` |
| CreateTime | DateTime | RepositoryItemDateEdit | `colCreateTime` |
| DeliveryDate | DateTime | RepositoryItemDateEdit | `colDeliveryDate` |
| CreatorID | Guid | GridLookUpEdit | `colCreator` |
| Remark | string | MemoEdit | `colRemark` |

→ 9 字段 → **GridControl + GridView**。

---

## 7. Step 3 — frm vs ucl

独立菜单 → `frm`。

---

## 8. Step 4 — 三层生成产物

⚠️ 与之前 Example 不同:**没有现成 Entity**,要先建。

```
Entity/OrderInfo.cs                      # 新建(全 9 字段)
DAL/DAL_Order.cs                         # 新建(BLL 直连)
BLL/OrderSer.cs                          # 新建
BLL/OrderPresenter.cs                    # 新建
UI/IOrderListView.cs                     # 新建
UI/Frm_OrderList.cs                      # 新建
UI/Frm_OrderList.Designer.cs             # 新建
UI/Frm_OrderList.resx                    # 新建
+ .csproj 3 件注册
```

### 关键代码:Entity(完整新建)

```csharp
[Serializable]
[DBTableAttribute("t_Order_2024")]
public class OrderInfo : DBUpdateObjectBase
{
    private Guid _OrderID;
    [DBColumnAttribute(IsPrimaryKey = true)]
    public Guid OrderID
    {
        get { return _OrderID; }
        set { AddRecordChange("OrderID", _OrderID, value); _OrderID = value; }
    }

    private string _OrderNo;
    public string OrderNo
    {
        get { return _OrderNo; }
        set { AddRecordChange("OrderNo", _OrderNo, value); _OrderNo = value; }
    }

    // ... 其他 7 个字段同理,每个 setter 调 AddRecordChange ...
}
```

### 关键代码:DAL(全 SQL 直连)

```csharp
public class DAL_Order
{
    private readonly SqlOperate _so = new SqlOperate();
    private readonly ListOperate _tolist = new ListOperate();
    private const string CONN = "MainConn";   // ← 指纹确认

    public List<OrderInfo> Query(string keyword, int? status)
    {
        // ⚠️ 字段名严格按用户提供清单
        string sql = @"SELECT OrderID, OrderNo, CustomerName, Amount,
                       Status, CreateTime, DeliveryDate, CreatorID, Remark
                       FROM t_Order_2024 WHERE 1=1 ";
        var pars = new List<SqlParameter>();
        if (!string.IsNullOrEmpty(keyword))
        {
            sql += "AND (OrderNo LIKE @kw OR CustomerName LIKE @kw) ";
            pars.Add(new SqlParameter("@kw", "%" + keyword + "%"));
        }
        if (status.HasValue)
        {
            sql += "AND Status = @st ";
            pars.Add(new SqlParameter("@st", status.Value));
        }
        sql += "ORDER BY CreateTime DESC";

        var dt = _so.ReadDataToDataTable(sql, CONN, pars.ToArray());
        return _tolist.FillModel<OrderInfo>(dt);
    }

    public bool Insert(OrderInfo e) { /* 类似结构 */ }
    public bool Update(OrderInfo e) { /* 类似结构 */ }
    public bool Delete(Guid orderId) { /* 类似结构 */ }
}
```

---

## 9. Step 5a — review-checklist 关键项

- ✅ **B3.1** Entity 9 字段全部 `AddRecordChange`
- ✅ **B3.3** DAL SELECT 字段与 Entity 公共属性 1:1
- 🟡 **A2.4** DBHelp = `MainConn`(单连接,指纹确认)
- ✅ **A3** 命名空间 `SomeProject.UI.Order`
- ✅ **C.4** `.csproj` 3 件注册

---

## 10. Step 5b — MSBuild

```powershell
$ & "...\MSBuild.exe" .\SomeProject.sln /p:Configuration=Debug /p:Platform="Any CPU"
Build succeeded.
    0 Warning(s)
    0 Error(s)
Time Elapsed 00:00:21.50
```

✅ 通过。

---

## 11. 失败点 + 沉淀

| 时间点 | 失败 | 修复 | 沉淀 |
|--------|------|------|------|
| Step 2 启动 | 没有 Entity,DB 也不可达 | 触发案例 3,提供 3 个字段获取路径 | **failure-modes 案例 3** |
| Step 0a | Entity 来源缺失 | **必问用户**——本案例是"完全要新建",不能让用户给残缺字段 | **NEED_ENTITY 流程** |
| Step 4 Designer | 手写 InitializeComponent 错 | 加载 `designer-patterns.md` §1.1 复制 | **failure-modes 案例 7** |

---

## 12. 本案例的可复用价值

1. **"无 Entity 无 DB"的最坏情况**——3 步解决路径(连 DB / 用户清单 / 扫 SQL)
2. **NEED_ENTITY 流程模板**——Step 2 启动前必问
3. **从已有 SQL 推断字段**——即使 DB 不通,从 `_OrderDAL.cs` 的 `SELECT *` 也能猜到至少有一个主键字段

---

## 附:无障碍路径总结

| 字段获取方式 | 优先级 | 适用 |
|------------|-------|------|
| **A. 连 DB 查 INFORMATION_SCHEMA** | ⭐⭐⭐ 首选 | DB 可达,Agent 有 database-explorer MCP |
| **B. 用户给字段清单** | ⭐⭐ 备选 | DB 不通,用户愿意写 |
| **C. 扫现有 SQL 倒推字段** | ⭐ 兜底 | DB 不通,用户懒得写,只能蒙 |
| **D. 全用 SELECT *** | 🚫 禁用 | 会带来 NetworkBandwidth 浪费 + 字段名错版风险 |

**禁止**:任何从 0 臆造字段的写法(违反 SKILL.md Constraints #2)。
