# Function type：复杂逻辑的代码下沉

承载型号消歧、知识检索、完成识别和下一步计算；Action 管变更契约，Function 管具体怎么算。

日期：2026-11-03。面向 OntoCare 当前实现和目标设计。文中 JSON/TypeScript 为解释性结构，不是 Palantir 官方配置；已实现、部分实现和设计示例以管理界面状态说明为准。

## 为什么需要 Function

声明可以说明输入输出和约束，但候选型号识别、两跳关联检索、否定句识别和检查过滤仍需算法。把逻辑放在明确的函数入口，才能复用与独立验证。

## 输入输出与副作用

identifyProduct 返回候选 PN 列表；observed_actions 返回已报告完成的检查键；lookup_order 返回本地快照。readOnly 只描述这些示例的边界，不代表所有平台 Function 都禁止编辑。

## 与 Action 的协作

Function 建议下一项检查，客户提供结果后由 Action 记录业务事实。Function 返回 UNKNOWN 或多候选时，应追问或复核，不能把未知压成 false。

## 当前实现与边界

现有函数主要是 Python 实现，并非运行在 Palantir Function 平台。suggestNextCheck 已注册独立本机函数，按来源适用性及已报告完成状态计算下一步。只有确有本地工具轨迹的入口才展示调用记录；演示输入输出单独标记。

## 面试表达

我把模糊理解和计算放在函数中，将业务变更交给明确契约；这样更容易定位错误是在识别、检索、判断还是执行阶段。

## 从声明到计算

Object 和 Link 让系统知道有哪些事实，Action 规定合法变更，Function 则实现具体计算：识别候选型号、处理否定句、检索适用证据、过滤已经完成的检查。输入输出应明确，失败和多候选要保留。

| 函数 | 输入 | 输出 | 当前落点 |
|---|---|---|---|
| identifyProduct | 用户文本 | 候选 PN 列表 | Agent.identify |
| observed_actions | 用户陈述 | 完成检查键列表 | 正则与否定语句规则 |
| resolve_semantics | mentions/context | 概念、关联与证据 | SemanticLayer/MCP |
| suggestNextCheck | 型号、错误、完成记录 | 下一检查或升级建议 | 本机已注册，返回来源步骤与证据版本 |
| lookup_order | 订单号 | 本地快照摘要 | Agent.shipping |

## 下一步检查的解释性代码

```typescript
// 解释性伪代码，不是现有 SDK 或可直接运行的实现。
function suggestNextCheck(context) {
  if (!context.confirmedModel) return { status: 'NEED_CONTEXT' };
  const supported = findChecksWithApplicableEvidence(context);
  const remaining = supported.filter(check =>
    !context.completedChecks.includes(check.id));
  if (!remaining.length) return { status: 'MANUAL_REVIEW' };
  return { status: 'SUGGEST_CHECK', nextCheck: remaining[0] };
}
```

这里的筛选必须使用当前任务、设备及方案版本。没有新步骤时返回升级建议，不编造新操作。真实当前代码仅持有会话完成状态，因此不能宣称完整跨设备观察对象已经实现。

## Function 与 Action 的边界

本项目查询示例使用 readOnly=true；需要写业务状态时经 Action 约束。但这不是 Palantir 的普遍限制：官方支持可编辑本体的函数和 function-backed actions。当前实现是 Python 代码与本地调用，不等于已经部署在 Palantir 平台。

## 调用记录与示例

本地 traces 中只读工具的出现证明它被调用过，不证明是生产客户请求或正确执行。界面只展示轨迹 id、版本、工具、模式和决策摘要，不带用户原文或地址。只扫描最近 200 条轨迹再按所选版本过滤，因此展示数量不是全量调用统计。

## 可验证的演示

Function Type → resolve_semantics → 实例 / 记录，查看本地轨迹摘要；若所选版本无记录，保持空态。identifyProduct 的示意输入输出带“未执行”标记，不能当成新增测试结果。

## 结构示例

```json
{
  "FunctionType": "resolveProductModel",
  "displayName": "解析产品型号候选",
  "parameters": {
    "text": {
      "type": "string"
    },
    "categoryHint": {
      "type": "string",
      "nullable": true
    }
  },
  "returns": {
    "type": "object",
    "properties": {
      "candidates": "ProductModelReference[]",
      "status": "UNIQUE | AMBIGUOUS | NOT_FOUND",
      "evidenceRefs": "EvidenceReference[]"
    }
  },
  "readOnly": true,
  "logic": [
    "识别明确 PN",
    "匹配已收录 SKU 别名",
    "结合品类识别产品名称",
    "多候选返回 AMBIGUOUS，不自动选第一个"
  ],
  "currentImplementation": "Agent.identify(text)；当前返回排序后的 PN 列表，不是此结构化返回"
}
```

```json
{
  "FunctionType": "suggestNextCheck",
  "displayName": "计算下一步检查建议",
  "parameters": {
    "model": {
      "type": "ObjectReference",
      "objectType": "ProductModel"
    },
    "errorCode": {
      "type": "string",
      "nullable": true
    },
    "completedChecks": {
      "type": "array",
      "items": "string"
    }
  },
  "returns": {
    "type": "object",
    "properties": {
      "nextCheck": "CheckStepReference | null",
      "status": "SUGGEST_CHECK | NEED_CONTEXT | MANUAL_REVIEW",
      "evidenceRefs": "EvidenceReference[]"
    }
  },
  "readOnly": true,
  "logic": [
    "限定型号与可见知识",
    "精确匹配错误码和支持检查关系",
    "过滤本任务已报告完成的步骤",
    "无新步骤则建议人工复核，不编造下一步"
  ],
  "currentImplementation": "ontocare.type_contracts.suggest_next_check；已注册本机函数接口"
}
```

## 参考

- [Palantir Action 概览](https://www.palantir.com/docs/foundry/action-types/overview/)
- [Palantir Rules](https://www.palantir.com/docs/foundry/action-types/rules/)
- [Palantir Functions](https://www.palantir.com/docs/foundry/functions/overview/)

当前已增加实际函数接口与调用审计；不运行于 Palantir 平台，不执行正式售后。

## 本地执行器补充

当前工作区另有已实现的 submitForReview（actions/submit-review.json、ontocare/actions.py），创建 ReviewTask 和 needs_review 关系，带本地事务、幂等、审计与事件出箱。它使用本地演示操作员，不等于生产身份授权或外部真人转接。它与已实现的 submitManualReview 对象粒度不同，界面分别展示；后者关联 ServiceTask、ServiceRequest 和人工待办。动作审计属于独立本地运行层，不随语义版本切换伪装为历史版本执行结果。
