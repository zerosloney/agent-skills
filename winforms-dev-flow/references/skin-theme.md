# DevExpress Skin / LookAndFeel

> 加载时机：生成窗体时设置皮肤/主题，或处理皮肤不一致问题时。

## 皮肤体系

DevExpress 21.2 皮肤分为三级，子级不设则继承父级：

```
UserLookAndFeel.Default（全局）
  ↓ 窗体.LookAndFeel（窗体级）
  ↓ 控件.LookAndFeel（控件级）
```

## 方案一：全局皮肤（推荐）

在 `Program.cs` 或启动时统一设置：

```csharp
[STAThread]
static void Main()
{
    Application.EnableVisualStyles();
    Application.SetCompatibleTextRenderingDefault(false);

    // 1. 注册 BonusSkins（使用 DevExpress Dark / Metropolis 等时必需）
    DevExpress.UserSkins.BonusSkins.Register();

    // 2. 启用表单皮肤
    DevExpress.Skins.SkinManager.EnableFormSkins();

    // 3. 设置全局皮肤（必须在 Application.Run 之前）
    DevExpress.LookAndFeel.UserLookAndFeel.Default.SetSkinStyle("Office 2019 Colorful");

    // 4. 全局字体（可选）
    Application.SetDefaultFont(new Font("微软雅黑", 9F, FontStyle.Regular));

    Application.Run(new FrmMain());
}
```

### 21.2 可用皮肤名称

> 以下为 v21.2 实际可用的皮肤，`dev-21.2-reference.md` 有完整收录。
> 命名规律：BonusSkins 皮肤通常为 `DevExpress` / `Metropolis` 系列，非 BonusSkins 皮肤通常为 `Office 201x` / `Visual Studio 201x` 系列。

| 皮肤名称 | 说明 | 需要 BonusSkins | 备注 |
|----------|------|:--------------:|------|
| `"Office 2019 Colorful"` | Office 2019 彩色（默认推荐） | 否 | — |
| `"Office 2019 Dark Gray"` | Office 2019 深灰 | 否 | — |
| `"Office 2019 Black"` | Office 2019 黑色 | 否 | — |
| `"Office 2019 White"` | Office 2019 白色 | 否 | v21.2 新增 |
| `"Office 2016 Colorful"` | Office 2016 彩色 | 否 | — |
| `"Office 2016 White"` | Office 2016 白色 | 否 | — |
| `"DevExpress Dark"` | DevExpress 深色主题 | 是 | — |
| `"DevExpress Light"` | DevExpress 浅色主题 | 是 | — |
| `"DevExpress Dark 2"` | DevExpress 深色 2（增强） | 是 | v21.2 新增 |
| `"Visual Studio 2019 Blue"` | VS 2019 蓝色 | 否 | — |
| `"Visual Studio 2019 Dark"` | VS 2019 深色 | 否 | — |
| `"Visual Studio 2019 Light"` | VS 2019 浅色 | 否 | v21.2 新增 |
| `"Metropolis"` | Metro 风格 | 是 | — |
| `"Metropolis Dark"` | Metro 深色风格 | 是 | v21.2 新增 |
| `"Basic"` | 基础无装饰风格 | 否 | — |

> **BonusSkins 注册后才能用**：`UserSkins.BonusSkins.Register()` 须在 `SetSkinStyle` 之前调用。实际项目中皮肤通常固定，不需要最终用户动态切换。

## 方案二：单窗体独立皮肤

```csharp
public partial class Frm_PartList : XtraForm
{
    public Frm_PartList()
    {
        InitializeComponent();
        this.LookAndFeel.SkinName = "Office 2019 Dark Gray";
    }
}
```

## 方案三：让用户选择皮肤

```csharp
// 启动时恢复上次选择的皮肤
private void LoadSkin()
{
    string savedSkin = Properties.Settings.Default.SkinName;
    if (!string.IsNullOrEmpty(savedSkin))
        UserLookAndFeel.Default.SetSkinStyle(savedSkin);
}

// 菜单切换皮肤
private void btnSkin_ItemClick(object sender, ItemClickEventArgs e)
{
    string skinName = e.Item.Tag as string;
    if (!string.IsNullOrEmpty(skinName))
    {
        UserLookAndFeel.Default.SetSkinStyle(skinName);
        Properties.Settings.Default.SkinName = skinName;
        Properties.Settings.Default.Save();
    }
}
```

## 对话框皮肤一致性

```csharp
// 使用 XtraMessageBox（替代 MessageBox）
XtraMessageBox.Show(
    "操作成功",
    "提示",
    MessageBoxButtons.OK,
    DevExpress.Utils.ToolTipIcon.Info
);

// 自定义对话框继承 XtraForm（自动继承当前皮肤）
public partial class DlgEdit_Part : XtraForm
{
    // 自动继承当前皮肤
}
```

## Ribbon 皮肤适配

```csharp
// RibbonControl 自动继承 LookAndFeel
ribbonControl1.ShowDisplayOptionsMenuButton = DevExpress.Utils.DefaultBoolean.False;
ribbonControl1.ShowPageHeadersMode = DevExpress.XtraBars.Ribbon.ShowPageHeadersMode.ShowOnMultiplePages;
```

## 注意事项

1. **SkinName 必须在所有控件创建之前设置**：如果窗体已经创建了控件再改皮肤，需要 `Refresh()` 或重建
2. **性能影响**：每次 `SetSkinStyle` 都会重绘所有控件，启动时设一次即可
3. **混合皮肤**：个别控件可以通过 `LookAndFeel.SkinName` 单独指定，但 UI 一致性建议全局统一
4. **部署时包含皮肤程序集**：如果使用 BonusSkins，确保 `DevExpress.BonusSkins.v21.2.dll` 已部署
