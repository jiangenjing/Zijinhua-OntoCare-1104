# Reports：从本体资料到经营分析

入口：`http://127.0.0.1:5112/reports`。本体管理与客服页面均已加入入口。

## 可以做什么

选择管理层 / Boss、GTM / 渠道策略、客服运营或数据与风险模板，输入本次分析主题，再选择 DeepSeek 分析或确定性资料简报。报告包含决策摘要、服务端计算的事实数字、角色分析、建议、商品项履约资料流、工单场景与国家名录分布、订单明细和数据缺口。

点击指标卡或段落证据可以核对统计定义和生成时的对象 ID。历史报告保存在本地 `local/reports.sqlite`，刷新页面或重启后仍可读取。查看历史报告时使用当时保存的快照；不会随本体现状变动而悄悄重算。支持 Markdown、完整 JSON 导出，以及浏览器打印／保存为 PDF。

## 模板、Skill 和 Prompt

模板目录为 `data/report-templates.json`，每个模板加载独立 Skill 和 Prompt：

| 角色 | Skill | Prompt | 分析重点 |
|---|---|---|---|
| 管理层 | `skills/reports/executive/SKILL.md` | `prompts/reports/executive.md` | 服务风险、资源取舍、需要拍板的事项 |
| GTM | `skills/reports/gtm/SKILL.md` | `prompts/reports/gtm.md` | 渠道资料、服务准备度、市场验证问题 |
| 客服运营 | `skills/reports/service_ops/SKILL.md` | `prompts/reports/service_ops.md` | 咨询场景、履约与知识、处理缺口 |
| 数据与风险 | `skills/reports/governance/SKILL.md` | `prompts/reports/governance.md` | 来源、未知条件、规则和操作边界 |

页面可查看当前模板的 Skill 与 Prompt；每份报告还保存生成时的文本和指纹，之后修改模板不会改变旧报告的生成记录。它们是本项目报告服务实际加载的角色 Skill，没有擅自安装到用户全局设置。

## 数据与“记忆”的含义

数据来源是当前本体可见对象与关系，不是模型自身记忆，也不是把整张地图塞进提示词。后端先按固定口径生成证据包：对象数、样例场景、国家名录分布、订单与商品履约状态及准确来源 ID，再给模型传递聚合事实与数据缺口。原始客户邮件、地址、附件链接和身份信息不会进入报告模型输入。

报告归档是可回看的分析记忆；本体是业务事实底座。旧报告的策略建议不能自动写回成为新事实，避免模型把上一次的假设当作下一次的证据。

生成时间使用 Asia/Shanghai；原始业务快照采集时间仍为未知。选择本体语义版本不会把订单快照变成那个历史时点的数据。

## 统计与图表口径

- 工单图以来源工单样例为单位，不能推断真实总体故障发生率。
- 国家图是去重销售方名录身份数，不是国家销售覆盖、销量、市场份额或潜力排名。
- 履约资料流以订单商品项为单位；每项在每层只计一次。图的三层为商品项 → 来源商品发货状态 → 是否有物流引用。线宽不是资金金额，也不是包裹数；物流引用不证明包裹内装物。
- 订单表按订单聚合状态展示，保留部分发货；不使用一个包裹推断整单。
- 各型号可见知识数量按明确适用关系计数，同一文章可适用多个型号，不能跨型号直接求和，也不能等同回答质量或知识覆盖率。
- 金额的币种和行／单粒度未核实，因此没有财务汇总。
- 缺少完整销量、营销、转化、成本、工单结案、SLA 与满意度，不生成增长、ROI、解决率或提效结论。

模型负责解释、假设和建议；数字表格与图表由代码计算。模型输出需符合结构、引用已有证据，并遵守定性正文约束；对不合格输出最多请求一次受限纠正，保存校验记录；未通过校验或模型不可用时，明确标为资料保底，保留真实调用状态，不宣称模型分析成功。引用校验不能证明每个定性判断必然成立，策略仍需业务验证。

## 网页与 MCP 是同一套能力

网页通过服务端 API 调用报告引擎。外部智能体通过官方 SDK 的 stdio MCP 调用相同引擎。新增工具：

1. `list_report_templates`：发现模板并读取 Skill / Prompt。
2. `generate_report(template_id, focus, mode, version)`：生成并归档本地报告。
3. `list_reports`：查看本地归档。
4. `get_report(report_id)`：读取完整报告及冻结证据。
5. `get_report_evidence(report_id, evidence_id)`：核查某项指标。

MCP 当前共 22 个工具。`generate_report` 会保存本地报告，明确标记为非只读工具；它不改变订单、工单、授权或其他业务事实，也不会启用售后写入。`mode="live"` 会调用已配置模型，`mode="snapshot"` 不调用模型。原有 `ONTOCARE_MCP_ALLOW_WRITES=0` 仍禁止业务复核写入，不禁止用户已授权的本地报告归档。

外部 Agent 的典型流程：

```text
list_report_templates()
generate_report(template_id="gtm", focus="进入新渠道前还需验证哪些条件？", mode="live")
get_report(report_id="上一步实际返回的id")
get_report_evidence(report_id="该id", evidence_id="country_directory")
```

也可运行独立客户端实际通过 MCP 生成：

```sh
.venv/bin/python scripts/external_agent.py --report-template gtm --message '进入新渠道前应验证什么？' --live
```

不带 `--live` 为不调用模型的资料简报。该参数切换到管理报告流程；原有客服工具白名单没有因此开放报告访问。

本地配置沿用项目 `.mcp.json`。换机器需修改工作区和解释器路径。模型配置读取服务端已有环境配置或本地私密配置文件，密钥不会进入 MCP 工具定义或网页。

## 行业上是否可行

可行。Palantir 官方 Ontology MCP 就是面向外部 Agent 暴露对象、预定义 Action 和查询 Function 的消费接口；Agent Builder 官方示例也用订单输入获取订单和包裹，再通过工具查询和操作。这支持「业务本体 → 查询/规则/动作 → MCP → 外部 Agent → 客服或分析报告」的架构路径，并不证明某个本地演示已经具备生产质量。

- [Ontology MCP](https://www.palantir.com/docs/foundry/ontology-mcp/overview)
- [Agent Builder core concepts](https://www.palantir.com/docs/foundry/agent-builder/core-concepts)

生产交付的关键是有范围的对象访问、真实身份和权限、可靠数据刷新、指标口径、有限工具预算、证据与回执、评测与人工复核。报告和客服可以复用事实与工具，但两者权限范围应区分：客户不应因此获得经营报告或跨客户订单的访问权。当前 Reports 是可信本地管理视图，尚未宣称具备多租户生产授权。
