# Example 4 — GridStyle 多值共存(Step 0b 异质性 🔴)

> 对应 failure-modes 案例 4(GridStyle 代号错配)+ 案例 5(同项目两套风格混用)。
> **核心场景**:**Step 0b 自动探测发现严重异质性,必须停下来让用户二选一**。
> **档位**:本例演示的是 **deep 档** 完整流程;实际触发顺序是 **glance → 自动升级到 deep**(因为 GridStyle 多值)。

---

## 1. 场景描述

**用户原话**:
> "老项目里一半窗体用 `GridStyle("ASS")`,一半用 `GridStyle("CSS")`,我想新加的窗体跟哪个?让我看你 skill 怎么处理。"

**上下文**:
- 老项目处于"两个旧项目合并"的过渡期
- `GridStyle` 在 `Program.cs` 有两种注册:`"ASS"` 走老逻辑,`"CSS"` 走新逻辑
- 业务模块划分模糊,无法从目录区分

---

## 2. Step 0 — 目标目录定位

```bash
PROJECT_ROOT = C:\Src\MergedProject
TARGET_DIR   = C:\Src\MergedProject\UI\CrossModule
MODULE_NAME  = CrossModule
```

---

## 3. Step 0a — 4 项必填门

| # | 确认项 | 取值 |
|---|--------|------|
| 1 | 业务名 / 窗体名 | `CrossModule` / `Frm_CrossModuleList` |
| 2 | Entity 或字段来源 | `Entity.CrossInfo`(已存在) |
| 3 | 项目根 + 目标目录 | 见 §2 |
| 4 | 构建入口 | `MergedProject.sln` |

✅ 4 项齐。

---

## 4. Step 0b — 项目指纹卡(本案核心)

> **命令**:跑 `references/project-fingerprint.md §0.2` 的 glance 档(6 查询,全部过滤注释 + 文件级去重)。命令权威以 §0.2 为准,此处不重复。

### 4.0 glance 触发(为什么进入 deep 档)

> 默认跑 glance 档(`§0.2` 的 6 查询),输出迷你指纹卡。

**glance 结果(关键维度)**:
```text
GridStyle 代号集合: "ASS","CSS","CRS"   ← ≥2 种 → 触发升级判定
```

> 注:代号集合的提取见 `§0.2` 查询 3(过滤注释后取 distinct 代号)。本案代号 ≥2 种,按 `§0.5` 升级规则判定是否进入 deep。

**glance 决策**:GridStyle 多值(3 种)→ **🔴 严重分裂风险** → 自动升级到 deep 档,跑 `§1.1-1.4` 完整探测。

### 4.1 deep 档完整探测

> deep 档命令见 `references/project-fingerprint.md §1`(1.1-1.5 全套),此处只展示结果。

**deep 结果(关键数据)**:
```text
GridStyle 代号分布(过滤注释后):
  89 "ASS"        # 老模块
 103 "CSS"        # 新模块
   2 "CRS"        # 异常值,只在 Tool 模块用

窗体基类:frmBase 192 / frm_Base<T> 2(仅 EQUP 老接口保留)
数据访问:SqlOperate 180 / DbHelp.Query 14(新模块开始迁移 ORM)
```

### 指纹卡输出

| 维度 | 主导 | 占比 | 异类 |
|------|------|------|------|
| 窗体基类 | `frmBase` | 99% | `frm_Base<T>`(1% 保留) |
| 数据访问 | `SqlOperate` | 93% | `DbHelp.Query`(7%) |
| **GridStyle** | **均衡!** | **"ASS" 46%, "CSS" 54%, "CRS" 1%** | **三值共存** |
| DBHelp | `varlist.MainConn` | 95% | `varlist.CSSDBHelp`(5%) |
| 命名空间 | `MergedProject.UI.*` | — | — |

### 异质性等级判定

```text
GridStyle 维度:
  - "ASS" 89 个 (46%)
  - "CSS" 103 个 (54%)
  - "CRS" 2 个 (1%)
  - 主导占比 54% → <75% 阈值 → 🔴 严重分裂

数据访问维度:
  - SqlOperate 180 个 (93%)
  - DbHelp.Query 14 个 (7%)
  - 主导 93% → 🟢 纯一

窗体基类维度:
  - frmBase 99%
  - 主导 99% → 🟢 纯一
```

**综合判定**:
- **GridStyle 维度** 🔴 **严重分裂**
- **其他维度** 🟢 纯一

→ **Step 0b 触发"严重分裂"分支** → 必须停下,问用户选择。

---

## 5. Step 0b 的 ask_user 处置

**必须**用 `ask_user` 让用户二选一,不能默认。

```markdown
⚠️ Step 0b 检测到项目处于风格过渡期。GridStyle 代号在项目内严重分裂:

- "ASS" 89 处 (46%) —— 老 Upgrader 模块
- "CSS" 103 处 (54%) —— 新 CSS.WHXL.Extend 模块
- 其他维度(窗体基类 99% / 数据访问 93%)仍是纯一,不必担心

新窗体 Frm_CrossModuleList 跟哪个?请选:

A. 跟随主导("CSS" 103 处)
   → 走新模块风格,逐步往新栈收敛
   → 适合 长期规划要把项目彻底往 CSS 栈统一

B. 跟随最近(最近 6 个月 commit)
   → 按 commit 主流风格
   → 适合 不确定未来,先跟"近期实际工作"

C. 强制走"ASS"(老栈)
   → 适合 这个新窗体属于老模块的工作延续

D. 强制走"CSS"(新栈)
   → 适合 这个新窗体属于新模块,即使是少数也要保持一致

(选 A/B/C/D 或自定义)
```

**用户回复**:"走 B,跟最近 commit"

---

## 6. Step 0b 用户确认后的指纹卡

```markdown
## 项目指纹卡(v2,Step 0b 终版)

主家族:合并过渡态(GridStyle 维度严重分裂,其他维度纯一)

新窗体 GridStyle: 跟随最近 6 个月 commit 主流
(查最近 commit):
git log --since="6 months ago" -p -- "*.cs" | rg -o 'new GridStyle\("[A-Z]+"' | Group-Object | Sort-Object Count -Descending
   35 "ASS"      # 老模块仍有大量提交
   58 "CSS"      # 新模块是当前主要工作区
→ 近期 commit: "CSS" 58 处, "ASS" 35 处 → **跟随 "CSS"**

其他维度仍走主导:
- 窗体基类: frmBase (99%)
- 数据访问: SqlOperate+ListOperate (93%)
- DBHelp: varlist.MainConn (95%)

类名前缀: Frm_{业务}List(从父级扫描)
命名空间: MergedProject.UI.CrossModule
```

---

## 7. Step 1 — 模式提取表

参照窗体(选了"CSS"后,优先找用 "CSS" 的窗体):
```powershell
& rg -l -g "*.cs" 'new GridStyle\("CSS"' $projectRoot | Select-Object -First 5
UI/CrossModule/Frm_StockList.cs    # 同模块("CrossModule")最近窗体
UI/NewModule/Frm_NewModule1.cs
```

→ 用 `Frm_StockList.cs` 作参照。

| 提取项 | 提取结果 |
|--------|---------|
| 窗体基类 | `frmBase` |
| 命名空间 | `MergedProject.UI.CrossModule`(同模块) |
| 数据访问 | `SqlOperate+ListOperate` |
| 是否泛型 | ❌ |
| **GridStyle** | **`"CSS"`**(Step 0b 已对齐最近 commit 主流) |
| DBHelp / 连接名 | `varlist.MainConn` |
| 类名前缀 | `DAL_{业务}` / `Frm_{业务}List` |
| WaitDialog | `varlist_Dialog` |
| 消息框 | `XtraMessageBox.Show` |

✅ 提取完成,记入指纹卡。

---

## 8. Step 2 — 字段→控件 映射表

| Entity 字段 | 类型 | 控件 | 列名 |
|-------------|------|------|------|
| ... |

(同 Example 1 的标准流程,这里略。)

---

## 9. Step 3 — frm vs ucl

独立菜单 → `frm`。

---

## 10. Step 4 — 三层生成产物

产物清单同 Example 1,关键差异在 **Designer 中**:

```csharp
// 顶部 GridStyle 初始化
this._gridStyle = new GridStyle("CSS", this, gcMain, gvMain);  // ← "CSS" 而非 "ASS"
```

---

## 11. Step 5a — review-checklist 关键项

- ✅ **A2.5** GridStyle = `"CSS"`(与本模块最近 commit 主流一致,且交叉验证 Frm_StockList)
- ✅ **A2.4** DBHelp = `varlist.MainConn`(指纹扫描确认)
- ✅ Step 0b 异质性 🔴 已停下问用户,用户已选 B
- ✅ Step 0b 输出指纹卡 v2

---

## 12. Step 5b — MSBuild

```powershell
$ & "...\MSBuild.exe" .\MergedProject.sln /p:Configuration=Debug
Build succeeded.
Time Elapsed 00:00:18.20
```

✅ 通过。

---

## 13. 失败点 + 沉淀

| 时间点 | 失败 | 修复 | 沉淀 |
|--------|------|------|------|
| Step 0b | GridStyle 严重分裂,如果默认猜 "ASS" 会错 | ask_user 让用户选 | **failure-modes 案例 4 + 案例 5 联动** |
| Step 1 提取 | 选参照窗体时,挑到 "ASS" 的窗体做基准 | 跟随 Step 0b 用户决策,从 "CSS" 窗体集中挑参照 | new: Step 1 提取前先看 Step 0b 决策 |
| Step 4 Designer | 漏改 GridStyle("ASS") → ("CSS") | 强制把 Step 0b 决策写进"产出清单" | new: review-checklist 加"GridStyle 与指纹卡 v2 一致"项 |

---

## 14. 本案例的可复用价值

1. **Step 0b 严重分裂处置**——必查维度表,异质性等级判定
2. **path a/b/c/d 选项模板**——可作为通用 ask_user 模板
3. **指纹卡 v2 输出格式**——含"已选决策"的最终交付
4. **跟最近 commit 而非全局主导**——适合不确定未来时的折中
