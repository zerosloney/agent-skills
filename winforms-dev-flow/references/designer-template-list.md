# Designer 模板库（索引）

> Step 4 生成 Designer 前**必加载本文件**，按决策表选模板后**再加载对应模板文件**。
> 复制模板后按 Step 1 确认的基类 / GridStyle 代号替换。

## 版本参考（DevExpress 21.2）

| 需要查 | 加载 |
|--------|------|
| 21.2 程序集清单、控件精确配置、字段→控件映射 | `references/dev-21.2-reference.md` |
| Skin/Theme 管理、21.2 皮肤名称表 | `references/skin-theme.md` |
| 常见陷阱（RepositoryItem、排序、DateEdit 格式等 14 个坑） | `references/common-pitfalls.md` |

> .NET Framework 4.7.2 项目引用 `Bin\Framework\` 下的程序集。详细说明见 `dev-21.2-reference.md`。

## 模板选择决策

| 场景 | 模板文件 |
|------|----------|
| 单表 CRUD 列表（查询 + 列表 + 增删改） | `designer-template-a-crud.md` |
| 新增 / 修改弹窗（≤8 字段） | `designer-template-b-form.md` |
| 分类树 + 下属列表（主从结构） | `designer-patterns.md` §1.2（已含主从绑定规则） |
| 业务分组多视图（多 Tab 切换） | `designer-patterns.md` §1.6（已含多 Tab 绑定规则） |

混合：A + B（主窗体 A + 弹窗 B）、A + §1.2（左侧分类 + 右侧列表）。

## 通用规则（所有模板通用）

### 控件命名

> 完整命名表见 `three-tier-mvp.md`「控件命名」节(权威来源)。常见控件:`gc{名}` / `gv{名}` / `lcMain` / `lcg{名}` / `txt{名}` / `spn{名}` / `chk{名}` / `dat{名}` 或 `de_{名}` / `btn{名}` / `lbc{名}` / `rlkue{名}`。

### Anchor / Dock 默认

- 查询区：`Dock = Top`
- GridControl：`Dock = Fill`
- 按钮栏：`Dock = Bottom`
- LayoutControl 表单：内部子控件 `Anchor = Top, Left`

### resx 最小化原则

控件初始可见文字（按钮文本等）走 resx；调试期可直接硬编码；不要全本地化。

### .csproj 注册（缺一编译报错）

```xml
<Compile Include="Frm_XXX.cs">
  <SubType>Form</SubType>
</Compile>
<Compile Include="Frm_XXX.Designer.cs">
  <DependentUpon>Frm_XXX.cs</DependentUpon>
</Compile>
<EmbeddedResource Include="Frm_XXX.resx">
  <DependentUpon>Frm_XXX.cs</DependentUpon>
</EmbeddedResource>
```

## 常见错误（预防清单）

- ❌ 控件初始文字硬编码——走 resx
- ❌ 漏 `BeginInit/EndInit` 或 `SuspendLayout/ResumeLayout` 配对
- ❌ GridControl 与 GridView 双向绑定只写一边
- ❌ Designer 里写业务逻辑
- ❌ .csproj 漏注册 3 件
- ❌ LayoutControl 子控件忘用 LayoutControlItem 包裹
- ❌ LayoutControl 不设 `AutoSize = false`（21.2 默认 true，会导致布局膨胀）
- ❌ DateEdit 缺少 `VistaDisplayMode = DefaultBoolean.True`（21.2 推荐）
- ❌ RepositoryItem 未先 `gc.RepositoryItems.Add()` 就绑定到列
- ✅ 所有字段统一放 Designer.cs 文件最底部
- ✅ Dock=Top / Fill / Bottom 三段式标准布局
- ✅ Step 1 确认的基类 / GridStyle 代号替换到模板对应位置
