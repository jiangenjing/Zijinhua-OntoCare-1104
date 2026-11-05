# ActionType：可执行的行为契约

把一次业务变更需要什么、允许谁做、会改什么、如何追溯表达为明确契约。

日期：2026-11-03。面向 OntoCare 当前实现和目标设计。文中 JSON/TypeScript 为解释性结构，不是 Palantir 官方配置；已实现、部分实现和设计示例以管理界面状态说明为准。

## 先确定业务变更

记录一次检查结果、提交一次复核申请是有意义的操作；任意 setStatus 不是业务契约。Action 参数引用对象，提交前核验适用性、权限和状态；不让模型直接指定最终资格结论。

## 五项核心定义

parameters 定义输入；validation 定义前置条件；rules 定义对象与关系编辑；permissions 定义允许主体及作用范围；audit 定义追溯要求。这里是项目解释性语法，不是 Palantir 官方配置。

## 从建议到真实办理

建议检查不代表已经检查；创建申请不代表审批通过；审批通过不代表外部退款成功。记录检查结果应追加观察；提交复核应返回编号，正式完成依赖受信回执。

## 当前实现与边界

updateSessionCheckState、recordCheckResult、submitManualReview 已接入固定本机处理器，校验服务端角色、用途、任务范围、适用步骤、明确结果、版本与幂等键，保存对象、关联、事件和审计。JSON用于说明契约，代码不解释执行任意表达式。

## 事务与外部副作用

原子性必须由实际存储和执行器保证；外部退款、通知与 Webhook 不因写在同一 JSON 就自动加入同一事务。需处理幂等、重复申请和失败回执。

## 面试表达

我的目标是让模型选择受约束业务动作，后端复核条件并记录结果；当前已实现本地状态跟踪，完整业务 Action 网关仍是待接入能力。

## 为什么不能只封装一个函数名

如果动作只是 updateStatus(id,status)，模型可能把任意对象改成任意状态。业务契约应该表达“记录检查结果”或“提交人工复核”：参数引用哪类对象、必须满足什么、会产生哪些记录、谁可执行、失败如何返回。

| 定义项 | 要回答的问题 |
|---|---|
| parameters | 调用方要提供哪些对象与业务参数？ |
| validation | 状态、适用性和身份条件是否满足？ |
| rules | 哪些对象和关系发生变化？ |
| permissions | 谁对哪个范围有权操作？ |
| audit | 哪些依据、参数和结果必须记录？ |
| idempotency | 网络重试或并发提交如何避免重复？ |

## recordCheckResult 的业务含义

用户说“已经清理，仍报错”时，创建一条 CheckObservation，result=PERSISTS、verificationStatus=REPORTED；关联到任务、检查方案版本及设备上下文。不能把 result=PERSISTS 解释成“硬件故障已确认”。纠正观察应留存更正历史，不覆写旧记录使历史看起来一直正确。

## submitManualReview 的业务含义

材料不充分或检查用尽时，可以登记复核。人工复核与退款申请的门槛不同，不能为了提交复核强制要求所有退款材料齐全。重试应返回原申请编号；申请状态 SUBMITTED、审批 APPROVED、办理 COMPLETED 是三个不同事实。

## 执行保证要由代码证明

当前三个动作已在本机执行台运行；审核不是正式退款或换货，审计属于本地运行记录。

这些 JSON 中 validation 表达式、bind 和引用是项目解释性约定。Palantir Rules 对组合有具体限制，例如 Function rule 不能任意与其他规则混配。外部调用和通知不自动共享内部编辑事务。audit:true 也不会自行生成防篡改日志。

## 可验证的演示

选择“记录会话检查状态”可查看版本行为；点击执行入口进入本机契约台，按真实任务保存检查结果、提交复核，再查看对象关系、事务回执与人工待办。

## 结构示例

```json
{
  "ActionType": "recordCheckResult",
  "displayName": "记录检查结果",
  "description": "追加用户明确报告的结果，不直接确认根因或审批售后。",
  "parameters": {
    "task": {
      "type": "ObjectReference",
      "objectType": "ServiceTask"
    },
    "step": {
      "type": "ObjectReference",
      "objectType": "CheckStep"
    },
    "result": {
      "type": "enum",
      "values": [
        "RESOLVED",
        "PERSISTS",
        "INCONCLUSIVE",
        "NOT_PERFORMED"
      ]
    },
    "statement": {
      "type": "string"
    }
  },
  "validation": [
    {
      "rule": "canHandleTask(currentIdentity, task)",
      "errorMessage": "没有处理该任务的权限"
    },
    {
      "rule": "isApplicableCheck(step, task)",
      "errorMessage": "检查不适用于当前产品上下文"
    },
    {
      "rule": "hasExplicitReportedResult(statement, result)",
      "errorMessage": "需要明确的检查结果"
    }
  ],
  "rules": [
    {
      "type": "createObject",
      "objectType": "CheckObservation",
      "bind": "observation",
      "values": {
        "observationId": "serverGeneratedId()",
        "result": "$result",
        "verificationStatus": "REPORTED",
        "reportedAt": "serverTime()",
        "procedureRevision": "$step.revision"
      }
    },
    {
      "type": "createLink",
      "linkType": "HAS_OBSERVATION",
      "from": "$task",
      "to": "$observation"
    }
  ],
  "permissions": {
    "roles": [
      "CustomerServiceAgent",
      "SupportAgent"
    ],
    "scope": "authorized_task"
  },
  "audit": true,
  "idempotency": "requestId",
  "implementationStatus": "已接入 ontocare.type_contracts.execute 的固定处理器"
}
```

```json
{
  "ActionType": "submitManualReview",
  "displayName": "提交人工复核申请",
  "description": "登记复核请求，不批准退款或换货。",
  "parameters": {
    "task": {
      "type": "ObjectReference",
      "objectType": "ServiceTask"
    },
    "reason": {
      "type": "string"
    },
    "evidenceRefs": {
      "type": "array",
      "items": "EvidenceReference"
    }
  },
  "validation": [
    {
      "rule": "canHandleTask(currentIdentity, task)",
      "errorMessage": "没有处理该任务的权限"
    },
    {
      "rule": "hasValidReason(reason)",
      "errorMessage": "缺少复核原因"
    },
    {
      "rule": "allEvidenceAccessible(currentIdentity, evidenceRefs)",
      "errorMessage": "证据不可访问或不属于此任务"
    },
    {
      "rule": "noActiveDuplicateReview(task)",
      "errorMessage": "已有有效复核申请，返回原编号"
    }
  ],
  "rules": [
    {
      "type": "createObject",
      "objectType": "ServiceRequest",
      "bind": "request",
      "values": {
        "requestId": "serverGeneratedId()",
        "kind": "MANUAL_REVIEW",
        "status": "SUBMITTED",
        "executionMode": "LOCAL_REVIEW",
        "submittedAt": "serverTime()"
      }
    },
    {
      "type": "createLink",
      "linkType": "REQUEST_HANDLES_TASK",
      "from": "$request",
      "to": "$task"
    }
  ],
  "permissions": {
    "roles": [
      "CustomerServiceAgent",
      "SupportAgent"
    ],
    "scope": "authorized_task"
  },
  "audit": true,
  "idempotency": "requestId + activeReview(task)",
  "implementationStatus": "已接入本机处理器与待办；未连接正式工单或坐席服务"
}
```

## 参考

- [Palantir Action 概览](https://www.palantir.com/docs/foundry/action-types/overview/)
- [Palantir Rules](https://www.palantir.com/docs/foundry/action-types/rules/)
- [Palantir Functions](https://www.palantir.com/docs/foundry/functions/overview/)

当前增加了本机动作执行、权限、幂等、版本检查和审计；未连接正式退款、换货或坐席系统。

## 本地执行器补充

当前工作区另有已实现的 submitForReview（actions/submit-review.json、ontocare/actions.py），创建 ReviewTask 和 needs_review 关系，带本地事务、幂等、审计与事件出箱。它使用本地演示操作员，不等于生产身份授权或外部真人转接。它与已实现的 submitManualReview 对象粒度不同，界面分别展示；后者关联 ServiceTask、ServiceRequest 和人工待办。动作审计属于独立本地运行层，不随语义版本切换伪装为历史版本执行结果。
