# Palantir 官方本体构建 SOP 与 OntoCare 差距审计

日期：2026-11-03。范围：围绕 Object、Link、Action、Function 与本体设计/验证主线核对官方文档及当前 Rebuild 实现。本报告不是对 Palantir 全站所有文档的穷尽阅读，也不是在 Foundry 租户上的部署验收。

## 结论

Palantir 有正式的设计指导、创建向导、函数发布和运行验证流程，可以整理出可复用 SOP。但它不要求按知乎示意语法编写四个固定 JSON 文件，然后自动生成可执行本体。

目前 OntoCare 是“带来源约束的客服语义检索、管理投影和一个本地业务动作闭环”。现有页面真实展示了类型、节点、关系和状态边界，但没有实现 Foundry 的完整类型管理、索引/查询运行时、函数注册、授权治理和变更管理。

我此前用四类 JSON 帮助解释是可行的展示方式；若把它称为 Palantir 官方配置、完整声明式本体实现或证明业务建模已完成，则不准确。92 项工程测试通过也不能证明业务语义模型已通过官方倡导的任务式验证。

## 官方依据阅读路线

设计优先阅读：

1. [Best practices](https://www.palantir.com/docs/foundry/ontology/ontology-best-practices/)：业务对象、属性取舍、共同设计、接口抽象与验证原则。
2. [Structural guidance](https://www.palantir.com/docs/foundry/ontology/ontology-structural-guidance/)：关系、关联对象、命名及接口结构。
3. [Anti-patterns](https://www.palantir.com/docs/foundry/ontology/ontology-anti-patterns/)：源系统映射、字段堆积、职责误用等反模式。
4. [Design validation](https://www.palantir.com/docs/foundry/ontology/ontology-design-validation/)：用未预演的业务问题检验模型可发现性与表达力。

平台操作参考：

5. [Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview/)
6. [Core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts/)
7. [Ontology Manager](https://www.palantir.com/docs/foundry/ontology-manager/overview/)
8. [Create an object type](https://www.palantir.com/docs/foundry/object-link-types/create-object-type/)
9. [Object metadata](https://www.palantir.com/docs/foundry/object-link-types/object-type-metadata/)
10. [Link types overview](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview/)
11. [Create a link type](https://www.palantir.com/docs/foundry/object-link-types/create-link-type/)
12. [Link metadata](https://www.palantir.com/docs/foundry/object-link-types/link-type-metadata/)
13. [Action overview](https://www.palantir.com/docs/foundry/action-types/overview/)
14. [Action getting started](https://www.palantir.com/docs/foundry/action-types/getting-started/)
15. [Rules](https://www.palantir.com/docs/foundry/action-types/rules/)
16. [Submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria/)
17. [Function-backed actions](https://www.palantir.com/docs/foundry/action-types/function-actions-overview/)
18. [Permissions](https://www.palantir.com/docs/foundry/action-types/permissions/)
19. [Consistency and isolation](https://www.palantir.com/docs/foundry/action-types/consistency-guarantees/)
20. [Action test run](https://www.palantir.com/docs/foundry/action-types/test-run/)
21. [Functions overview](https://www.palantir.com/docs/foundry/functions/overview/)
22. [TypeScript v1 getting started](https://www.palantir.com/docs/foundry/functions/typescript-v1-getting-started)
23. [TypeScript v2 getting started](https://www.palantir.com/docs/foundry/functions/typescript-v2-getting-started/)
24. [TypeScript v2 migration](https://www.palantir.com/docs/foundry/functions/typescript-v2-migration/)

## 1. 官方到底怎样构建“地图”

需要区分四种结构：

| 结构 | 代表什么 | OntoCare 示例 |
|---|---|---|
| 业务模型 | 类型、属性、真实关联、允许操作及逻辑 | 产品、设备、工单、检查观察、复核任务 |
| 类型关系图 | ObjectType 之间的 LinkType | 工单关联型号、订单包含订单项 |
| 实例关系图 | 具体对象及具体关联 | ticket-003 关联某订单与某型号 |
| 依赖/调用/来源图 | 类型、函数、动作或数据来源的技术依赖 | Action 编辑 ReviewTask，函数读取知识 |

Ontology Manager 官方页面把属性、Action、Link type graph、依赖、数据和使用情况分别组织展示；函数有配置、版本与可观测页面。不存在“把全部东西连成一个无差别图，就完成本体”的做法。[Ontology Manager](https://www.palantir.com/docs/foundry/ontology-manager/overview/)

当前界面的“类型契约拓扑”属于解释性引用图；它不能取代实例业务关系，也不证明 Function 调用了 Action。当前业务分组层级不表示继承，这一点与官方 Groups 的组织用途是一致的。[Object metadata](https://www.palantir.com/docs/foundry/object-link-types/object-type-metadata/)

## 2. 四类结构的官方含义与正确构建顺序

### ObjectType：带语义的对象声明

先明确一个实例是什么、如何保持身份，再决定属性、主键、显示标题和适用范围。官方向导允许选择既有数据源并自动映射列，但明确允许丢弃列；也支持由 Action 创建数据的无 backing datasource 类型，需相应项目权限和对象安全策略。不是每个类型都必须来自一张既有表。[创建对象](https://www.palantir.com/docs/foundry/object-link-types/create-object-type/)

OntoCare 应定义 ProductModel、Device、SupportCase/SupportTicket、CheckObservation 等不同粒度。主键应指向真实定义的属性，例如 modelId 或 deviceId；图节点的 pn:T2353 是展示/存储标识表达，不应写成属性名。来源行号只能帮助定位原记录，不能长期承担实体身份。

### LinkType：有语义、可双向访问的关联

官方一个 LinkType 有两个类型端点及双侧名称/API 名称，同一关联可双向遍历，不必为反方向复制一条不同业务关系。数据实现可使用外键、关联表或 backing object。外键是合法的底层实现，问题在于仅因字段能 JOIN 就添加没有领域意义的边。[Link overview](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview/)、[创建关联](https://www.palantir.com/docs/foundry/object-link-types/create-link-type/)

直接关联适合没有独立元数据的关系；若关系包含数量、角色、起止时间、状态等，官方结构指导推荐 object-backed link。知乎的 LinkType.properties 示例不能直接当成 Foundry 普通 LinkType 的通用属性能力。[结构指导](https://www.palantir.com/docs/foundry/ontology/ontology-structural-guidance/)

例如订单项承担“这次购买了某规格、数量多少”的业务含义；检查观察承担“谁对哪台设备在何时做了什么、结果如何”。这些都不是简单的两个 ID。

### ActionType：带提交条件的业务变更

官方 Action 包含参数和对象编辑规则，Submission criteria 决定是否允许提交。复杂编辑可使用 function-backed action；不要求把所有行为写成通用配置 DSL。不能因代码承载逻辑就断言设计错误。[提交条件](https://www.palantir.com/docs/foundry/action-types/submission-criteria/)、[Function-backed actions](https://www.palantir.com/docs/foundry/action-types/function-actions-overview/)

应分别定义查看/编辑类型资源、可读取对象范围和提交业务动作的授权。不是简单设置 roles 数组就具备生产权限治理。[Permissions](https://www.palantir.com/docs/foundry/action-types/permissions/)

内部编辑的原子性不覆盖所有通知、Webhook 或外部函数调用。也不能把 startProduction 伪代码中的 invokeFunction 与其他规则任意串联当成官方规则组合；官方 Function rule 有组合限制。[Rules](https://www.palantir.com/docs/foundry/action-types/rules/)、[Consistency](https://www.palantir.com/docs/foundry/action-types/consistency-guarantees/)

### Function：经过开发、发布和版本管理的业务逻辑

用户给出的 TS v1 教程要求创建 TypeScript Functions Repository，在导出的类中声明函数，使用函数装饰器，Live Preview 测试，提交代码，再 Tag and release，成功后在 registry 和消费应用中使用。它不是仅在 JSON 中填写 implementation 字符串。[TS v1](https://www.palantir.com/docs/foundry/functions/typescript-v1-getting-started)

该页现已推荐为更强能力迁移 TS v2；学习 v1 不应被误写成新项目必须用 v1。选定 SDK/版本再看对应导入方式、API 和编辑语义。[迁移说明](https://www.palantir.com/docs/foundry/functions/typescript-v2-migration/)

Function 可以计算，也可用于复杂本体编辑；“所有 Function 都是纯函数”不是官方限制。OntoCare 可自行规定查询 Function 只读、业务写入经 Action，这属于项目设计边界。[Functions overview](https://www.palantir.com/docs/foundry/functions/overview/)

## 3. 整理成 OntoCare 可执行 SOP

以下八步由上述官方流程整理，结合客服领域形成，不是声称官方发布了一张同名通用 SOP。

| 步骤 | 工作 | 交付物 | 验收 |
|---|---|---|---|
| 1 业务问题 | 和客服/售后人员确认有价值的决策 | 5—10 个真实问题、术语解释、责任人 | 不看表名也能解释问题 |
| 2 对象身份 | 区分型号、SKU、设备、订单、问题、观察 | 对象清单、实例粒度、稳定 ID 策略 | 同对象跨来源不重复、不同设备不误合并 |
| 3 类型声明 | 定义属性语义、类型、必填、状态、可见性 | 可校验 Object Schema | 缺字段的实例不会导致类型“消失” |
| 4 关系定义 | 定义两侧名称、基数、范围及关联对象 | Link Schema、必要关联对象 | 业务相关才连线；两向可自然导航 |
| 5 数据映射 | 清洗、身份解析、来源冲突与字段映射 | Mapping、溯源、未确认候选队列 | 不将猜测作为已确认业务事实 |
| 6 逻辑与动作 | 简单编辑用规则，复杂计算/编辑用函数 | 参数、返回、条件、授权、处理器/函数版本 | 声明与执行一致、拒绝和幂等可验证 |
| 7 发布与展示 | 索引、版本、依赖、安全配置与界面 | 可查询实例、可执行受控动作、三种图视图 | 不把布局分组当继承，不把调用轨迹当事实 |
| 8 任务式验证 | 未参与建模的人和 Agent 做未预演任务 | 路径、答案、耗时、歧义与改进清单 | 不靠开发者记忆或预写路径才答对 |

官方特别指出，预先定制的页面可能掩盖弱模型；结构正确和工程测试通过不等于人/Agent 可自然使用。应让参与者从业务问题自行发现起点和关系。[Design validation](https://www.palantir.com/docs/foundry/ontology/ontology-design-validation/)

适合本项目的验收题：同名 S1 Pro 如何消歧？同订单两台设备的检查如何分开？3212 的资料如何限定型号？客户说“清理后仍报错”应新增什么事实？为什么不能判资格？本地复核成功与外部服务完成如何区分？

## 4. 当前代码审计发现

### F1：展示属性反向汇总，尚未形成模型真源（优先）

位置：ontocare/manager.py:140 及 ontocare/type_catalog.py:51。

当前扫描实例字段生成 properties，再用 observedTypes 包成 ObjectType JSON。已有说明承认它是投影，因此页面并没有隐藏此边界；但类型定义会随数据样本变化，不能作为稳定 Schema，也没有全面定义 required/enum/属性主键。

建议：建立项目唯一的、可验证类型声明；实例导入、Action 参数和展示都消费它。observedTypes 降为审计结果，不能反过来覆盖声明。无需改用图数据库。

### F2：多态通用边不等于官方具体 LinkType（优先）

位置：ontocare/manager.py: RELATIONS。

当前 grounded_in 声明 * → Evidence，constrained_by 声明 * → Constraint。快照实测 grounded_in 覆盖 8 组不同端点类型；constrained_by 覆盖 2 组。这是可行的自定义技术图，但不是官方一个具体 LinkType 绑定两个 object types 的直接对应物。

建议：技术溯源图保留通用边；需要成为正式领域类型关系时，为具体类型声明关系，或在适用的接口能力下设计共享契约。不要机械增加一堆用户不需要看到的边。

### F3：身份按来源生成，真实业务概念存在重复（优先）

位置：ontocare/ontology.py:79—82、ontocare/data.py:107/123、ontocare/manager.py:104—106。

按 policy ID 创建部件概念，同型号同部件会随来源重复。快照实测 T8D04 的 pump_hub、washable_parts 各有两条。订单项 id 使用来源行号，经销商 id 使用枚举索引；文件插行或新增排序项可能使身份漂移。

建议：若代表真实部件类型，就按稳定业务身份统一，链接多条政策证据。若坚持表达“某政策中的部件条款”，应重命名并明确粒度，不能称同一业务部件的 canonical identity。原始文章和政策证据仍分别保留。

### F4：Action 定义与执行有双重真源（优先）

位置：actions/submit-review.json 与 ontocare/actions.py:99—104。

JSON.rules 描述状态和创建关系，但主要编辑逻辑固定写在 Python 中；JSON 只部分影响行为（例如角色/用途、允许前态）。此外状态校验读取 validation[1]，依赖数组位置。

本轮临时目录实验：将 JSON 目标 workflow_status 改为 CONFIG_ONLY_SENTINEL，返回状态 200、committed=true，但实际 after.workflow_status 仍为 PENDING_REVIEW。实验只在临时目录复制数据库，未改原定义或原数据库。

结论：固定 handler 本身不是错误，定义也明确写了 registered handler；问题是不能将 rules 的展示理解成通用声明式执行。

建议优先使用注册处理器方案：定义显式 handler/version，将 rules 标为说明或从权威处理器契约生成；对条件按名称查找，并验证契约一致性。另一种方案才是实现受限、可校验的规则解释器。没有必要为了对标制造通用 DSL。

### F5：OpenBKN 导出有语义不一致（应修正）

位置：openbkn/anker-customer-service/kn/model.json:35—38。

CheckAction 对象声明的 source 指向 kn/actions.json；但该文件实际存 identify_product、retrieve_evidence、check_order、collect_eligibility 四个流程能力，不是滚筒检查、重启等物理检查定义。把这份导出称为完整检查动作实例模型，会混淆业务检查与系统工具。

建议：检查方案/步骤应有自身的业务定义；流程工具放在 Function/Skill/Action 的对应注册信息中。统一主模型与导出映射，避免维护两套互不一致的业务含义。

### F6：函数目录可浏览，但没有统一注册/发布机制（能力缺口）

位置：web/type-definitions.json、ontocare/type_catalog.py、ontocare/agent.py。

FunctionType 的 implementation 字符串是说明，不是可解析到已发布函数的权威绑定。部分计算还在 Agent.run 分支内，UI 承认其部分实现。这不是“Python 不行”，而是缺少可验证的函数名、参数/返回 Schema、处理器、版本及调用约束注册。

建议：保留 Python，按需求为真实能力建立轻量注册清单和对应测试，不必迁移 TypeScript 或建设完整平台。

### F7：业务主图混入大量技术记录（展示与可用性问题）

当前 Mapping、Constraint 和来源证据均默认进入主图；Condition 是政策术语，不都是独立现实实体。官方允许必要技术类型存在，但建议默认隐藏非语义类型。不能简单认定“技术对象一概不能建”，也不能让其主导客户服务图。

建议：默认展示产品、设备、案件、检查观察、复核任务；来源与规则作为可展开的治理视图。原有本地 Action 审计边保留。

### F8：SKU 候选依据尚不足以统称已核实（待加强）

位置：ontocare/data.py:117—122。

导入工单时，唯一 PN 前缀会被写入 aliases，后续商品型号关联再以该 alias 的精确匹配为依据。后一步“精确”不代表前一步“已核实”。本轮没有据此证明某一条当前映射确实错误，但它是可追溯性与置信级别缺口。

建议：前缀仅产生候选，正式映射标注来源、核验方法、审核状态；型号主数据、明确产品标签或经审核映射才作为确定依据。保留未解析 SKU，不强行自动连接。

### F9：工程测试与本体验收不可等同（验证缺口）

前轮 92 项测试覆盖实现行为、接口、隔离与交互，不证明模型已经足以支持陌生用户或 Agent 的未预演业务调查。当前没有本轮新取得的这类验收结果。

建议：建立问题集，分别记录答案正确、来源正确、模型可导航、状态不误判和实际执行回执，不能用“结构无悬空边”代替这些指标。

## 5. 哪些做法应保留

- 区分对象类型与实例、真实边与引用边、设计样例与实际记录。
- 型号范围、知识可见性、用户陈述与核验事实的区别。
- 不把没有解析的 SKU 强连主机知识。
- 对完整操作命名，例如提交复核，而不是暴露任意字段编辑。
- 已有本地 Action 的事务、重复检查、幂等、事件出箱和审计。
- 业务分组不当作类继承。
- 本地调用成功不当作外部服务已完成。

## 6. 最小整改次序

1. 统一类型声明和导出语义，修正 Object 主键与 CheckAction 混淆。
2. 明确 Action 处理器与 JSON 定义哪个是权威，并增加一致性验证。
3. 统一实体身份、候选映射和多来源证据；不要因多个来源复制同一部件。
4. 区分业务主图、技术溯源图、函数动作依赖图；补具体关系契约与双侧名称。
5. 逐步补设备、检查观察和任务模型，用未预演问题验证，而非继续增加无业务必要的节点。

本轮仅审查、临时隔离验证与撰写报告，没有修改当前业务逻辑或重新发布本体版本。
