# LinkType：让关系成为一等公民

声明对象之间的业务含义、方向、基数与关联依据，使关联可以被人和 Agent 正确浏览。

日期：2026-11-03。面向 OntoCare 当前实现和目标设计。文中 JSON/TypeScript 为解释性结构，不是 Palantir 官方配置；已实现、部分实现和设计示例以管理界面状态说明为准。

## 从 ID 匹配到业务语义

两个字段相等只是建立关系的证据之一。references_order 表示工单提及订单，不代表客户身份核验通过；applies_to 表示型号有适用知识，不代表全品类均适用。

## 独立声明关系

LinkType 定义 from、to、cardinality 和 description。Link 是某两个实例的一条具体关系，当前每条边还带 basis，说明原生关系或匹配依据。类图按真实边聚合，实例图显示具体关联。

## 关系属性的边界

basis 是当前管理投影的边属性，不表示底层平台自动提供独立链接权限。若关系有数量、有效期和独立生命周期，可以建成业务关联对象；不要假定任何图或本体平台都支持任意边属性。

## 当前实现与边界

现有关系从语义 JSON、业务记录和本地动作运行层构造，商品型号仅在唯一精确别名匹配时连接。同轮共现不进入业务关系。HAS_OBSERVATION、REQUEST_HANDLES_TASK 等由实际受控动作创建，端点与基数通过事务处理器校验。

## 面试表达

我不仅保存起终点，还保存这条关系到底表示什么、适用什么范围、凭什么连线；未确认的关系保留待核查。

## 从物理关联到业务关联

旧系统若只保存 product_id 和 knowledge_id，调用方仍需知道这是“相关提及”还是“适用知识”。声明 LinkType 后，调用方能看到关系的含义、端点类型、方向及基数；具体 Link 再记录两端实例与来源依据。

| 关系 | 含义 | 不可推出的结论 |
|---|---|---|
| mentions_product | 工单记录涉及型号 | 客户确实拥有该设备 |
| references_order | 工单提及订单号 | 提问者就是购买人 |
| applies_to | 型号有适用知识 | 其他同名型号同样适用 |
| supports_step | 知识原文支持检查 | 客户已经完成检查 |

## 声明与实例

LinkType 的 from/to 是类；具体 Link 的 source/target 是实例 id。当前 relations.json 的 relation_type=association 是原生语义分类；管理界面根据端点类型映射为 applies_to 等业务关系名。不能把二者当成同一个字段系统。

本文示例 APPLIES_TO 按“知识适用于型号”命名；当前界面 applies_to 的方向是“型号→知识”，这是必须明确的映射差异。正式配置不能只改名称而不迁移方向。

## 关系为什么还要保留依据

basis 可以说明原生关系 id、证据 id 或字段匹配规则。订单号精确匹配可以支持提及关系，但不能替代身份验证。SKU 未唯一解析时，不创建确定型号边。同轮共现图单独用于对话轨迹，不能用于业务推理。

若一条关系有独立状态、数量、日期和审阅过程，考虑建立业务关联对象，例如订单项或经销授权；不假定所有平台都支持任意边属性与独立边权限。

## 可验证的演示

Link Type → contains_item → 实例 / 记录 → 点击关系查看 basis → 打开起点或终点拓扑。再切 HAS_OBSERVATION 查看实际检查观察；尚无操作时可以是零条，执行后显示真实关联。

## 结构示例

```json
{
  "LinkType": "APPLIES_TO",
  "displayName": "知识适用于型号",
  "from": "KnowledgeArticle",
  "to": "ProductModel",
  "cardinality": "many-to-many",
  "description": "文章经来源范围核对后适用于该型号，不代表相同产品名均适用。",
  "currentMapping": "界面当前方向为 ProductModel → KnowledgeArticle，关系 id=applies_to；此例按自然业务语句反向命名"
}
```

```json
{
  "LinkType": "SUPPORTS_CHECK",
  "displayName": "知识支持检查",
  "from": "KnowledgeArticle",
  "to": "CheckStep",
  "cardinality": "one-to-many",
  "description": "原文支持该检查概念；不代表客户已经执行。",
  "currentMapping": "界面 supports_step；当前检查节点按文章范围建立，并未全局合并"
}
```

## 参考

- [Palantir Action 概览](https://www.palantir.com/docs/foundry/action-types/overview/)
- [Palantir Rules](https://www.palantir.com/docs/foundry/action-types/rules/)
- [Palantir Functions](https://www.palantir.com/docs/foundry/functions/overview/)

当前已增加实际关系写入、来源与审计；未连接正式退款、换货或坐席系统。

## 本地执行器补充

当前工作区另有已实现的 submitForReview（actions/submit-review.json、ontocare/actions.py），创建 ReviewTask 和 needs_review 关系，带本地事务、幂等、审计与事件出箱。它使用本地演示操作员，不等于生产身份授权或外部真人转接。它与已实现的 submitManualReview 对象粒度不同，界面分别展示；后者关联 ServiceTask、ServiceRequest 和人工待办。动作审计属于独立本地运行层，不随语义版本切换伪装为历史版本执行结果。
