# ObjectType：带语义的对象声明

定义现实业务里有什么，以及每类对象有哪些可以解释、检索和核验的属性。

日期：2026-11-03。面向 OntoCare 当前实现和目标设计。文中 JSON/TypeScript 为解释性结构，不是 Palantir 官方配置；已实现、部分实现和设计示例以管理界面状态说明为准。

## 从客服问题出发

客户说“我的 E25 报错”，先识别产品型号；有购买记录时再关联订单与订单项。型号不是具体设备，订单项也不等于一台设备。按业务身份划分对象，避免把一行 Excel 当成一个实体。

## 字段必须有业务含义

对象声明包含名称、语义说明、主键及属性。PN 用于型号身份；别名用于消歧；枚举用于表达有限合法状态。源文件、工作表、行号保留在证据和映射中，不挤进每个业务对象的主体。

## 类型与实例

ProductModel 是类型，pn:T2353 是实例；CheckObservation 是建议新增的记录类型，demo: 开头只用于解释，没有持久化到真实实例集合。

## 当前实现与边界

现有类主要是管理投影，本地运行层另有 ReviewTask，properties 从实例汇总，observedTypes 不代表已经落实必填、枚举、搜索索引或写入校验。ServiceTask、CheckObservation、ServiceRequest 已接入本机事务存储；仅统计实际创建的对象，不把讲解示例计为实例。

## 面试表达

我先用产品、订单、问题和检查结果这些业务概念定义对象身份，再把多来源数据映射进来；结构与来源映射分开管理。

## 沿一次客服请求理解对象

“我的 E25 报 3212，清理后仍然出现。”这句话包含型号候选、错误报告、一次检查和一次结果报告。它不是一个拥有几十列的 EmailData 对象。型号需要消歧；错误含义需要适用范围；检查结果需要设备与任务上下文。

产品型号 ProductModel 与物理设备 Device 的粒度不同。一个订单项 quantity=2 也不能被当作一台设备。当前管理界面已经展示型号、工单、订单项；Device 仍是后续建模方向；独立 CheckObservation 已实现，不能把目标对象数量加进真实实例统计。

## 字段设计逐项解释

| 字段 | 作用 | 本项目边界 |
|---|---|---|
| ObjectType | 类型的稳定业务名称 | ProductModel 代表工程型号 |
| displayName / description | 面向人和 Agent 的含义 | 业务名称不从表名照搬 |
| primaryKey | 区分实例身份 | 当前图节点有带命名空间的 id |
| properties | 属性含义、类型与允许值 | 当前观察到的字段类型，不自动形成写入校验 |
| enum / values | 受控状态空间 | 设计示例需实际验证器落实 |

“带语义”不是多写一段 description 就完成：还要保证同名消歧、来源依据、关系范围和运行校验一致。当前没有因 JSON 中出现 searchable 就自动创建索引，也没有因 enum 就自动生成业务表单。

## 可验证的演示

进入 Object Type → ProductModel → 实例 / 记录 → 点击具体 PN → 打开实际实例拓扑。然后切到 CheckObservation，指出其真实记录为零，示例 demo: 对象只用于说明记录粒度。

## 结构示例

```json
{
  "ObjectType": "ProductModel",
  "displayName": "产品型号",
  "description": "具有独立工程标识的产品型号，不是某台设备或源表。",
  "primaryKey": "pn",
  "properties": {
    "pn": {
      "type": "string",
      "description": "工程型号"
    },
    "displayName": {
      "type": "string"
    },
    "category": {
      "type": "string"
    },
    "approvedAliases": {
      "type": "array",
      "items": "string"
    }
  },
  "currentMapping": "terms.type=product_model → 管理界面 ProductModel；属性命名为设计整理"
}
```

```json
{
  "ObjectType": "KnowledgeArticle",
  "displayName": "知识文章",
  "primaryKey": "articleId",
  "properties": {
    "articleId": {
      "type": "string"
    },
    "title": {
      "type": "string"
    },
    "content": {
      "type": "string"
    },
    "publicationStatus": {
      "type": "enum",
      "values": [
        "DRAFT",
        "PUBLISHED",
        "RETIRED"
      ]
    },
    "audience": {
      "type": "enum",
      "values": [
        "CUSTOMER",
        "INTERNAL"
      ]
    },
    "revision": {
      "type": "string"
    }
  },
  "currentMapping": "terms.type=knowledge_topic；正文来自 knowledge.json；现有 visible 合并发布与可见判断"
}
```

## 参考

- [Palantir Action 概览](https://www.palantir.com/docs/foundry/action-types/overview/)
- [Palantir Rules](https://www.palantir.com/docs/foundry/action-types/rules/)
- [Palantir Functions](https://www.palantir.com/docs/foundry/functions/overview/)

当前增加了本机契约执行与审计；原始资料保持只读，未连接正式退款、换货或坐席系统。

## 本地执行器补充

当前工作区另有已实现的 submitForReview（actions/submit-review.json、ontocare/actions.py），创建 ReviewTask 和 needs_review 关系，带本地事务、幂等、审计与事件出箱。它使用本地演示操作员，不等于生产身份授权或外部真人转接。它与已实现的 submitManualReview 对象粒度不同，界面分别展示；后者关联 ServiceTask、ServiceRequest 和人工待办。动作审计属于独立本地运行层，不随语义版本切换伪装为历史版本执行结果。
