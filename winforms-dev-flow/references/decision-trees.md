# winforms-dev-flow 可视化决策树

> 所有决策流程的图形化表示，便于 Agent 快速定位正确路径。

---

## 1. Step 0b 异质性判定决策树

```mermaid
graph TD
    A[Step 0a 完成] --> B[跑 glance 档 6 查询]
    B --> C{所有维度主导≥95%?}
    C -->|是 🟢 | D[直接进 Step 1<br/>用 glance 卡]
    C -->|否 | E{任一维度 75-95%?<br/>或 GridStyle≥2 种？}
    E -->|是 🟡 | F[自动升级到 deep 档<br/>跑§1.2-1.4]
    E -->|否 🔴 | G[严重分裂<br/>自动升级到 deep 档]
    F --> H{deep 输出异质性？}
    G --> H
    H -->|主导+少数 🟡 | I[提示用户<br/>默认随主导]
    H -->|严重分裂 🔴 | J[ask_user 三选一<br/>a 主导/b 最近/c 新开]
    H -->|纯一 🟢 | D
    I --> K[进 Step 1]
    J --> K
    D --> K
    
    style D fill:#90EE90
    style I fill:#FFD700
    style J fill:#FF6B6B
```

---

## 2. Designer 模板选择决策树 (4 家族×6 场景)

```mermaid
graph TB
    A[Step 4 生成 Designer] --> B[加载 designer-template-list.md]
    B --> C{Step 0b 项目家族？}
    
    C -->|A. Deve-Upgrader| D[走§A 模板]
    C -->|B. Deve-CRS| E[走§B 模板]
    C -->|C. EQUP| F[走§C 模板]
    C -->|D. CSS.WHXL| G[走§A 模板<br/>D 复用 A]
    
    D --> H{控件场景？}
    E --> H
    F --> H
    G --> H
    
    H -->|基础列表 | I[§X.1.1<br/>GridControl 基础]
    H -->|+ 条件格式 | J[§X.1.2<br/>StyleFormatCondition]
    H -->|+ 汇总 | K[§X.1.3<br/>SummaryItem]
    H -->|+ 条件格式 + 汇总 | L[§X.1.4<br/>两者结合]
    H -->|+ 主从联动 | M[§X.1.5<br/>Master-Detail]
    H -->|+ 多 Tab | N[§X.1.6<br/>多 GridView]
    
    H -->|TreeList| O[§X.2<br/>TreeList 场景]
    H -->|LayoutControl| P[§X.3<br/>表单布局]
    H -->|BandedGridView| Q[§X.4<br/>分组列]
    
    I --> R[复制模板代码<br/>替换字段]
    J --> R
    K --> R
    L --> R
    M --> R
    N --> R
    O --> R
    P --> R
    Q --> R
    
    R --> S[生成.Designer.cs]
    S --> T[生成.resx<br/>所有可见文字]
    T --> U[.csproj 注册 3 件]
    
    style D fill:#FFE4B5
    style E fill:#FFE4B5
    style F fill:#FFE4B5
    style G fill:#FFE4B5
    style L fill:#90EE90
    style R fill:#87CEEB
```

---

## 3. 异常处理风格识别决策树

```mermaid
graph TD
    A[Step 1 模式提取] --> B[扫描参照窗体异常处理]
    B --> C{View 层有 try-catch?}
    
    C -->|是 | D[Upgrader 风格]
    C -->|否 | E{Presenter 层有 try-catch?}
    
    E -->|是 | F[CRS 风格]
    E -->|否 | G[未知风格<br/>ask_user]
    
    D --> H[View try-catch + 弹窗]
    D --> I[Presenter 不处理<br/>冒泡到 View]
    D --> J[Ser catch 返回 false]
    
    F --> K[View 不 try-catch<br/>只看返回值]
    F --> L[Presenter try-catch<br/>转 bool 返回]
    F --> M[Ser catch 返回 false]
    
    H --> N[生成 View 代码<br/>包裹 try-catch]
    I --> O[生成 Presenter 代码<br/>不包裹 try-catch]
    J --> P[生成 Ser 代码<br/>catch 返回 false]
    
    K --> Q[生成 View 代码<br/>不包裹 try-catch]
    L --> R[生成 Presenter 代码<br/>包裹 try-catch]
    M --> P
    
    N --> S[review-checklist A2.7 校验]
    O --> S
    P --> S
    Q --> S
    R --> S
    
    style D fill:#90EE90
    style F fill:#FFD700
    style G fill:#FF6B6B
    style S fill:#87CEEB
```

---

## 4. 架构退化检测决策树

```mermaid
graph TD
    A[Step 0b 启动] --> B[扫描老代码全量]
    B --> C[扫描新代码近 6 个月]
    
    C --> D{老代码>10 个<br/>新代码=0 个？}
    D -->|是 🔴 | E[检测到架构退化]
    D -->|否 🟢 | F[架构稳定<br/>进 Step 1]
    
    E --> G{哪个维度退化？}
    
    G -->|Collection 层 | H[Ser 直连数据访问<br/>不生成 Collection]
    G -->|独立 DAL 层 | I[Ser 内联数据访问<br/>dalRatio < 0.1]
    G -->|泛型基类 | J[非泛型基类<br/>frmBase 主导]
    G -->|ORM 迁移 | K[SqlOperate 主导<br/>不再用 DbHelp.Query]
    
    H --> L[ask_user 确认<br/>A 跟新/B 跟老/C 自定义]
    I --> L
    J --> L
    K --> L
    
    L --> M[用户选择 A 跟新]
    L --> N[用户选择 B 跟老]
    L --> O[用户选择 C 自定义]
    
    M --> P[生成新架构代码]
    N --> Q[生成老架构代码]
    O --> R[按自定义生成]
    
    P --> S[更新指纹卡 v2<br/>记录用户决策]
    Q --> S
    R --> S
    
    style E fill:#FF6B6B
    style F fill:#90EE90
    style M fill:#90EE90
    style P fill:#87CEEB
    style S fill:#FFD700
```

---

## 5. 三层生成数据流向决策树

```mermaid
graph TB
    A[Step 2 字段映射完成] --> B{Step 0b DAL 层完整性？}
    
    B -->|dalRatio ≥ 0.5<br/>有独立 DAL| C[生成独立 DAL 文件]
    B -->|dalRatio < 0.1<br/>无独立 DAL| D[Ser 内联数据访问<br/>不生成 DAL]
    B -->|0.1 ≤ dalRatio < 0.5| E[ask_user 确认<br/>是否生成 DAL]
    
    C --> F[生成 DAL 文件<br/>*DAL.cs]
    F --> G[生成 Ser 层<br/>直连 DAL]
    
    D --> H[生成 Ser 层<br/>直连 SqlOperate/ListOperate]
    
    E -->|生成 DAL| F
    E -->|不生成 DAL| H
    
    G --> I[生成 Presenter<br/>协调器]
    H --> I
    
    I --> J[生成 View 接口<br/>I*View]
    J --> K[生成窗体主类<br/>frm*.cs]
    K --> L[生成 Designer<br/>从模板复制]
    L --> M[生成.resx<br/>所有可见文字]
    
    style C fill:#90EE90
    style D fill:#FFD700
    style E fill:#FF6B6B
    style F fill:#87CEEB
    style H fill:#87CEEB
```

---

## 6. 复用决策 (frm vs ucl) 决策树

```mermaid
graph TD
    A[Step 2 字段映射完成] --> B{业务独立性？}
    
    B -->|独立业务<br/>需菜单/权限入口 | C[新建 frm 窗体]
    B -->|会被多个窗体嵌入 | D{项目已有可复用 ucl?}
    B -->|与主窗体主从联动 | D
    
    D -->|是 | E[引用现有 ucl<br/>不重复生成]
    D -->|否 | F[抽取 ucl 控件]
    
    C --> G[生成 frm 6 类文件]
    F --> H[生成 ucl 5 类文件<br/>无.resx]
    
    G --> I[review-checklist C.4 校验]
    H --> I
    
    style C fill:#90EE90
    style E fill:#FFD700
    style F fill:#87CEEB
    style I fill:#FF6B6B
```

---

## 7. 失败案例速查决策树

```mermaid
graph TD
    A[任意 Step 卡顿] --> B[查 failure-modes.md 速查表]
    
    B --> C{症状关键词？}
    
    C -->|SqlOperate 找不到 | D[案例 1<br/>DBHelp 命名差异]
    C -->|DALBase<T> 编译失败 | E[案例 2<br/>Entity 不完整]
    C -->|无 Entity/字段不明 | F[案例 3<br/>DB 不可达]
    C -->|GridStyle 未注册 | G[案例 4<br/>代号错配]
    C -->|泛型/非泛型混用 | H[案例 5<br/>结构判定失败]
    C -->|两次弹窗 | I[案例 6<br/>异常处理不当]
    C -->|Designer 错位 | J[案例 7<br/>手写模板]
    C -->|命名不一致 | K[案例 8<br/>前缀约定]
    
    D --> L[加载对应修复方案]
    E --> L
    F --> L
    G --> L
    H --> L
    I --> L
    J --> L
    K --> L
    
    L --> M[执行修复]
    M --> N[回到对应 Step 修正]
    N --> O[重跑 review-checklist]
    
    style B fill:#FF6B6B
    style L fill:#87CEEB
    style O fill:#90EE90
```

---

## 8. Step 5 自审循环决策树

```mermaid
graph TD
    A[Step 4 生成完成] --> B[Step 5a 加载 review-checklist]
    
    B --> C[逐项过 19 项<br/>A 设计/B 绑定/C 输出]
    C --> D{有🔴不通过项？}
    
    D -->|是 | E{不通过项类型？}
    D -->|否全过 ✅ | F[进 Step 5b MSBuild]
    
    E -->|A 设计问题 | G[回 Step 2/4 修正]
    E -->|B 绑定问题 | H[回 Step 4 修正]
    E -->|C 输出问题 | I[补文件/替占位符]
    
    G --> J[重审全部 checklist]
    H --> J
    I --> J
    
    J --> D
    
    F --> K[MSBuild 构建项目]
    K --> L{构建成功？}
    
    L -->|是 ✅ | M[Step 5d 交付用户]
    L -->|否 🔴 | N{错误类型？}
    
    N -->|新生成代码错误 | O[修复编译错误]
    N -->|预先存在错误 | P[交付时明确列出<br/>不修复]
    N -->|环境缺依赖 | P
    
    O --> K
    P --> M
    
    M --> Q{用户反馈？}
    
    Q -->|确认 ✅ | R[终止]
    Q -->|有问题 🔴 | S{识别影响环节？}
    
    S -->|设计问题 | G
    S -->|绑定问题 | H
    S -->|输出问题 | I
    S -->|编译错误 | O
    
    style D fill:#FF6B6B
    style F fill:#90EE90
    style L fill:#FF6B6B
    style M fill:#87CEEB
    style R fill:#90EE90
```

---

## 9. 完整流程总览决策树

```mermaid
graph TB
    Start[用户请求<br/>"加个 XX 窗体"] --> Step0[Step 0 定位目标目录]
    
    Step0 --> Step0a[Step 0a 4 项必填门]
    Step0a --> Step0b[Step 0b 项目指纹识别]
    
    Step0b --> Decision0{异质性等级？}
    Decision0 -->|🟢 纯一 | Step1
    Decision0 -->|🟡 主导 + 少数 | Step1
    Decision0 -->|🔴 严重分裂 | AskUser0[ask_user 三选一]
    
    AskUser0 --> Step1[Step 1 参照学习]
    
    Step1 --> Decision1{模式可判定？}
    Decision1 -->|否 🔴 | AskUser1[ask_user 列选项]
    Decision1 -->|是 ✅ | Step2
    
    AskUser1 --> Step2[Step 2 数据驱动布局]
    
    Step2 --> Step3[Step 3 复用决策 frm/ucl]
    Step3 --> Step4[Step 4 三层生成 + 绑定]
    
    Step4 --> Step5a[Step 5a review-checklist]
    Step5a --> Decision5a{全通过？}
    Decision5a -->|否 🔴 | Correct[回对应 Step 修正]
    Decision5a -->|是 ✅ | Step5b
    
    Correct --> Step5a
    
    Step5b[Step 5b MSBuild] --> Decision5b{构建成功？}
    Decision5b -->|否 🔴 | FixBuild[修复编译错误]
    Decision5b -->|是 ✅ | Step5d
    
    FixBuild --> Step5b
    
    Step5d[Step 5d 交付用户] --> Feedback{用户反馈？}
    Feedback -->|确认 ✅ | End[终止 ✅]
    Feedback -->|有问题 🔴 | Identify{识别影响环节}
    
    Identify -->|设计 | Correct
    Identify -->|绑定 | Correct
    Identify -->|输出 | Correct
    Identify -->|编译 | FixBuild
    
    style Step0b fill:#FFD700
    style Step1 fill:#87CEEB
    style Step4 fill:#87CEEB
    style Step5a fill:#FF6B6B
    style Step5b fill:#FF6B6B
    style End fill:#90EE90
```

---

## 使用说明

### Agent 快速定位指南

| 场景 | 查看决策树 | 关键节点 |
|------|-----------|---------|
| **项目风格不明** | 图 1 (Step 0b 异质性) | glance → deep 升级规则 |
| **Designer 模板选择** | 图 2 (4 家族×6 场景) | 家族判定 → 场景选择 |
| **异常风格确认** | 图 3 (异常处理识别) | View/Presentation/Ser 三层 |
| **架构退化检测** | 图 4 (架构退化) | 老代码 vs 新代码对比 |
| **分层生成决策** | 图 5 (三层数据流) | DAL 层完整性判定 |
| **复用决策** | 图 6 (frm vs ucl) | 业务独立性判定 |
| **失败案例速查** | 图 7 (失败案例) | 症状→案例映射 |
| **自审循环** | 图 8 (Step 5 自审) | review-checklist → MSBuild |
| **完整流程** | 图 9 (总览) | 8 Steps 全貌 |

### 决策树颜色说明

| 颜色 | 含义 |
|------|------|
| 🟢 绿色 | 正常流程/成功终止 |
| 🟡 黄色 | 警告/需注意 |
| 🔴 红色 | 异常/需用户决策 |
| 🔵 蓝色 | 代码生成动作 |

---

*最后更新：2026-07-10*
*维护指南：新增决策场景时，在本文件追加对应决策树，并同步更新 SKILL.md 的 References 节*
