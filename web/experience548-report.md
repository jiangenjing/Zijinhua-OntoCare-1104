# 5120新版客服：548题Prompt/Skill评测与改进

新版v1相对同代码控制组任务通过率差值：+0.73个百分点；选择候选experience-v2-stream548相对v1：+0.73个百分点。修复11题，退步7题，仍失败16题。

|版本|任务通过|声明忠实度|首条知识命中|HTTP P50/P99|
|---|---|---|---|---|
|experience-core-control548|517/548 (94.34%)|89.09%|91.25%|8.79s / 20.74s|
|experience-v1-stream548|521/548 (95.07%)|88.90%|90.83%|9.31s / 20.02s|
|experience-v2-stream548|525/548 (95.80%)|89.22%|91.25%|8.32s / 19.40s|
|experience-v4-stream548|520/548 (94.89%)|88.88%|91.67%|7.22s / 16.94s|

## 分项与改进

{
  "experience-core-control548": {
    "knowledge_first_hit": {
      "at_1": {
        "passed": 438,
        "n": 480,
        "value": 0.9125
      },
      "at_3": {
        "passed": 459,
        "n": 480,
        "value": 0.95625
      },
      "at_6": {
        "passed": 459,
        "n": 480,
        "value": 0.95625
      }
    },
    "by_split": {
      "development": {
        "passed": 292,
        "n": 311,
        "assessed_n": 311,
        "unassessed_n": 0,
        "value": 0.9389067524115756,
        "assessed_value": 0.9389067524115756,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      },
      "validation": {
        "passed": 108,
        "n": 118,
        "assessed_n": 118,
        "unassessed_n": 0,
        "value": 0.9152542372881356,
        "assessed_value": 0.9152542372881356,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      },
      "holdout": {
        "passed": 117,
        "n": 119,
        "assessed_n": 119,
        "unassessed_n": 0,
        "value": 0.9831932773109243,
        "assessed_value": 0.9831932773109243,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      }
    },
    "first_status_latency": {
      "n": 0,
      "p50_ms": null,
      "p99_ms": null
    },
    "first_validated_answer_chunk_latency": {
      "n": 0,
      "p50_ms": null,
      "p99_ms": null
    },
    "by_kind": {
      "boundary": {
        "passed": 44,
        "n": 48
      },
      "knowledge": {
        "passed": 453,
        "n": 480
      },
      "multi_turn": {
        "passed": 4,
        "n": 4
      },
      "business": {
        "passed": 16,
        "n": 16
      }
    },
    "http_latency": {
      "n": 552,
      "p50_ms": 8785.427833005087,
      "p99_ms": 20744.49120899197
    },
    "graph_latency": {
      "n": 476,
      "p50_ms": 0.346,
      "p99_ms": 1.7925
    },
    "retrieval_latency": {
      "n": 552,
      "p50_ms": 2011.978,
      "p99_ms": 8776.91589
    },
    "answer_tokens": {
      "prompt_tokens": 4169619,
      "completion_tokens": 401216,
      "total_tokens": 4570835
    },
    "judge_tokens": {
      "prompt_tokens": 530486,
      "completion_tokens": 73594,
      "total_tokens": 604080
    },
    "model_status_counts": {
      "completed": 547,
      "unsafe_business_claim": 4,
      "cross_product_answer": 1
    },
    "policy_flags": 0,
    "failed_validators": {},
    "note": "HTTP includes validated chunk delivery for SSE; not raw model TTFT. Knowledge first-hit uses accepted equivalent-source Gold IDs."
  },
  "experience-v1-stream548": {
    "knowledge_first_hit": {
      "at_1": {
        "passed": 436,
        "n": 480,
        "value": 0.9083333333333333
      },
      "at_3": {
        "passed": 459,
        "n": 480,
        "value": 0.95625
      },
      "at_6": {
        "passed": 459,
        "n": 480,
        "value": 0.95625
      }
    },
    "by_split": {
      "development": {
        "passed": 295,
        "n": 311,
        "assessed_n": 311,
        "unassessed_n": 0,
        "value": 0.9485530546623794,
        "assessed_value": 0.9485530546623794,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      },
      "validation": {
        "passed": 110,
        "n": 118,
        "assessed_n": 118,
        "unassessed_n": 0,
        "value": 0.9322033898305084,
        "assessed_value": 0.9322033898305084,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      },
      "holdout": {
        "passed": 116,
        "n": 119,
        "assessed_n": 119,
        "unassessed_n": 0,
        "value": 0.9747899159663865,
        "assessed_value": 0.9747899159663865,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      }
    },
    "first_status_latency": {
      "n": 552,
      "p50_ms": 5.051686996011995,
      "p99_ms": 25.98845540967888
    },
    "first_validated_answer_chunk_latency": {
      "n": 552,
      "p50_ms": 9082.40879150253,
      "p99_ms": 19814.113583665894
    },
    "by_kind": {
      "boundary": {
        "passed": 44,
        "n": 48
      },
      "knowledge": {
        "passed": 457,
        "n": 480
      },
      "multi_turn": {
        "passed": 4,
        "n": 4
      },
      "business": {
        "passed": 16,
        "n": 16
      }
    },
    "http_latency": {
      "n": 552,
      "p50_ms": 9313.747958498425,
      "p99_ms": 20021.365500411775
    },
    "graph_latency": {
      "n": 476,
      "p50_ms": 0.3535,
      "p99_ms": 4.316750000000001
    },
    "retrieval_latency": {
      "n": 552,
      "p50_ms": 2011.7060000000001,
      "p99_ms": 8941.16472
    },
    "answer_tokens": {
      "prompt_tokens": 4396868,
      "completion_tokens": 410802,
      "total_tokens": 4807670
    },
    "judge_tokens": {
      "prompt_tokens": 553423,
      "completion_tokens": 74300,
      "total_tokens": 627723
    },
    "model_status_counts": {
      "completed": 546,
      "unsafe_business_claim": 4,
      "cross_product_answer": 2
    },
    "policy_flags": 0,
    "failed_validators": {},
    "note": "HTTP includes validated chunk delivery for SSE; not raw model TTFT. Knowledge first-hit uses accepted equivalent-source Gold IDs."
  },
  "experience-v2-stream548": {
    "knowledge_first_hit": {
      "at_1": {
        "passed": 438,
        "n": 480,
        "value": 0.9125
      },
      "at_3": {
        "passed": 459,
        "n": 480,
        "value": 0.95625
      },
      "at_6": {
        "passed": 459,
        "n": 480,
        "value": 0.95625
      }
    },
    "by_split": {
      "development": {
        "passed": 295,
        "n": 311,
        "assessed_n": 311,
        "unassessed_n": 0,
        "value": 0.9485530546623794,
        "assessed_value": 0.9485530546623794,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      },
      "validation": {
        "passed": 115,
        "n": 118,
        "assessed_n": 118,
        "unassessed_n": 0,
        "value": 0.9745762711864406,
        "assessed_value": 0.9745762711864406,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      },
      "holdout": {
        "passed": 115,
        "n": 119,
        "assessed_n": 119,
        "unassessed_n": 0,
        "value": 0.9663865546218487,
        "assessed_value": 0.9663865546218487,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      }
    },
    "first_status_latency": {
      "n": 552,
      "p50_ms": 5.048521008575335,
      "p99_ms": 26.87072533532046
    },
    "first_validated_answer_chunk_latency": {
      "n": 552,
      "p50_ms": 8063.30822900054,
      "p99_ms": 19191.865581250317
    },
    "by_kind": {
      "boundary": {
        "passed": 48,
        "n": 48
      },
      "knowledge": {
        "passed": 457,
        "n": 480
      },
      "multi_turn": {
        "passed": 4,
        "n": 4
      },
      "business": {
        "passed": 16,
        "n": 16
      }
    },
    "http_latency": {
      "n": 552,
      "p50_ms": 8324.705729501147,
      "p99_ms": 19396.668375676385
    },
    "graph_latency": {
      "n": 476,
      "p50_ms": 0.422,
      "p99_ms": 4.377
    },
    "retrieval_latency": {
      "n": 552,
      "p50_ms": 1590.092,
      "p99_ms": 10444.129
    },
    "answer_tokens": {
      "prompt_tokens": 4520051,
      "completion_tokens": 369948,
      "total_tokens": 4889999
    },
    "judge_tokens": {
      "prompt_tokens": 515297,
      "completion_tokens": 72797,
      "total_tokens": 588094
    },
    "model_status_counts": {
      "completed": 547,
      "unsafe_business_claim": 4,
      "cross_product_answer": 1
    },
    "policy_flags": 0,
    "failed_validators": {},
    "note": "HTTP includes validated chunk delivery for SSE; not raw model TTFT. Knowledge first-hit uses accepted equivalent-source Gold IDs."
  },
  "experience-v4-stream548": {
    "knowledge_first_hit": {
      "at_1": {
        "passed": 440,
        "n": 480,
        "value": 0.9166666666666666
      },
      "at_3": {
        "passed": 461,
        "n": 480,
        "value": 0.9604166666666667
      },
      "at_6": {
        "passed": 461,
        "n": 480,
        "value": 0.9604166666666667
      }
    },
    "by_split": {
      "development": {
        "passed": 295,
        "n": 311,
        "assessed_n": 311,
        "unassessed_n": 0,
        "value": 0.9485530546623794,
        "assessed_value": 0.9485530546623794,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      },
      "validation": {
        "passed": 109,
        "n": 118,
        "assessed_n": 118,
        "unassessed_n": 0,
        "value": 0.923728813559322,
        "assessed_value": 0.923728813559322,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      },
      "holdout": {
        "passed": 116,
        "n": 119,
        "assessed_n": 119,
        "unassessed_n": 0,
        "value": 0.9747899159663865,
        "assessed_value": 0.9747899159663865,
        "definition": "source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded"
      }
    },
    "first_status_latency": {
      "n": 552,
      "p50_ms": 4.906479000055697,
      "p99_ms": 28.04217300057644
    },
    "first_validated_answer_chunk_latency": {
      "n": 552,
      "p50_ms": 6962.807021001936,
      "p99_ms": 16695.65589391525
    },
    "by_kind": {
      "boundary": {
        "passed": 48,
        "n": 48
      },
      "knowledge": {
        "passed": 452,
        "n": 480
      },
      "multi_turn": {
        "passed": 4,
        "n": 4
      },
      "business": {
        "passed": 16,
        "n": 16
      }
    },
    "http_latency": {
      "n": 552,
      "p50_ms": 7216.435104499396,
      "p99_ms": 16937.771900166117
    },
    "graph_latency": {
      "n": 478,
      "p50_ms": 0.4045,
      "p99_ms": 2.7921300000000024
    },
    "retrieval_latency": {
      "n": 552,
      "p50_ms": 11.5625,
      "p99_ms": 5523.941140000001
    },
    "answer_tokens": {
      "prompt_tokens": 3936241,
      "completion_tokens": 376483,
      "total_tokens": 4312724
    },
    "judge_tokens": {
      "prompt_tokens": 551405,
      "completion_tokens": 74151,
      "total_tokens": 625556
    },
    "model_status_counts": {
      "completed": 546,
      "unsafe_business_claim": 5,
      "cross_product_answer": 1
    },
    "policy_flags": 0,
    "failed_validators": {},
    "note": "HTTP includes validated chunk delivery for SSE; not raw model TTFT. Knowledge first-hit uses accepted equivalent-source Gold IDs."
  }
}

## 修复、退步、仍失败

{
  "fixed": [
    "kb-qa-aed0c47b4848-en",
    "kb-qa-b0bfcd064ab4-en",
    "kb-qa-e846edbac6cb-zh",
    "kb-qa-e846edbac6cb-en",
    "kb-qa-aff4b82946f4-zh",
    "kb-qa-6250c07e6170-en",
    "kb-qa-f272ea4edc51-zh",
    "boundary-channel_match-0",
    "boundary-channel_match-1",
    "boundary-channel_match-2",
    "boundary-channel_match-3"
  ],
  "regressed": [
    "kb-qa-b0bfcd064ab4-zh",
    "kb-qa-e8a5d7b7b0d5-en",
    "kb-qa-644406c10495-en",
    "kb-qa-f9b7c89c9bcb-en",
    "kb-qa-6250c07e6170-zh",
    "kb-qa-1ca7c8172085-en",
    "kb-qa-f272ea4edc51-en"
  ],
  "still_failed": [
    "kb-qa-a6038863911b-zh",
    "kb-qa-e7b229deb2c2-zh",
    "kb-qa-e7b229deb2c2-en",
    "kb-qa-6ecec6859984-en",
    "kb-qa-da162cd734ec-zh",
    "kb-qa-da162cd734ec-en",
    "kb-qa-6c5ab718a89d-zh",
    "kb-qa-6c5ab718a89d-en",
    "kb-qa-84fca5e9e5d1-zh",
    "kb-qa-84fca5e9e5d1-en",
    "kb-qa-4facffdb876d-en",
    "kb-qa-f9b7c89c9bcb-zh",
    "kb-qa-6f492b370d2d-zh",
    "kb-qa-6f492b370d2d-en",
    "kb-qa-88371fc88575-zh",
    "kb-qa-88371fc88575-en"
  ]
}

## 统计与部署边界

{
  "prompt_v1_vs_control": {
    "groups": 272,
    "delta_95_interval_pp": [
      -0.7207207207207207,
      2.209944751381215
    ],
    "method": "paired source-group bootstrap, query-weighted; includes stochastic judge/generator uncertainty only imperfectly"
  },
  "selected_vs_v1": {
    "groups": 272,
    "delta_95_interval_pp": [
      -0.9090909090909091,
      2.697841726618705
    ],
    "method": "paired source-group bootstrap, query-weighted; includes stochastic judge/generator uncertainty only imperfectly"
  }
}

548题均为已见回归；同模型家族LLM Judge；离线任务通过不等于真实问题解决。控制组与v1只改变体验Prompt/Skill，v4保留v1表达，另含业务路由与有来源证明的配件角色修正。对官方正文未进入主Judge造成的疑点做独立诊断，不改主评分。版本快照与逐题实际回答保留。

方法参考：https://www.palantir.com/docs/foundry/aip-evals/analyze-run-results ，https://www.palantir.com/docs/foundry/aip-evals/experiments ，https://arxiv.org/abs/2408.08067

详见 docs/5120客服评测与BadCase改进方法.md，实际修改见独立冻结候选清单。

所选候选：experience-v2-stream548
选用规则：Pass task/faithfulness/policy/validator gates versus v1, then maximize task passing, faithfulness tie-break. Selection uses seen548; not independent validation.

{
  "name": "experience-v2",
  "observed_baseline_cases_at_freeze": 144,
  "observed_failure_ids": [
    "boundary-channel_match-1",
    "kb-qa-4facffdb876d-en",
    "kb-qa-6c5ab718a89d-en",
    "kb-qa-88371fc88575-zh",
    "kb-qa-e7b229deb2c2-zh",
    "kb-qa-f9b7c89c9bcb-zh"
  ],
  "changes": [
    "Prompt/Skill: factual focus and remove unrequested article extras",
    "Prompt/Skill: preserve conditional diagnostic steps and conclusions",
    "Prompt/Skill: latest turn and known component wording",
    "Code: verified dealer context participates in purchase-evidence routing"
  ],
  "unchanged": [
    "knowledge sources",
    "ontology links and product scope",
    "retrieval/reranking algorithm",
    "gold labels",
    "primary judge/rubric"
  ],
  "files": {
    "ontocare/agent.py": "0deb7f3eeb4fdc8cd62d75be8b0c7796036e7fc35865844f5119cae52f4c909a",
    "ontocare/prompting.py": "ab9b7ce13e93b9401216b2845f88d80d9bfde9c828b3a652622362bccb6087ca",
    "prompts/customer-experience.md": "4a372f0f396215e2155cb015050027445154c67344283df8b18fdae137bfd6f3",
    "prompts/skills/customer-experience/SKILL.md": "518601b44e6ebee13995d14feaa57127109bb1b6ed5021edfaec6e9714684892"
  }
}

延迟受不同阶段并发负载与缓存影响，不把本轮P50/P99差异直接当作算法性能提升。

固定同题12题Ragas（非548题全量）：
{
  "experience-core-control548": {
    "faithfulness": {
      "n": 12,
      "value": 0.8917934303350971
    },
    "context_precision": {
      "n": 12,
      "value": 0.8804232803732733
    },
    "context_recall": {
      "n": 12,
      "value": 1.0
    }
  },
  "experience-v1-stream548": {
    "faithfulness": {
      "n": 12,
      "value": 0.8162087912087913
    },
    "context_precision": {
      "n": 12,
      "value": 0.9054232803615934
    },
    "context_recall": {
      "n": 12,
      "value": 1.0
    }
  },
  "experience-v2-stream548": {
    "faithfulness": {
      "n": 12,
      "value": 0.8209538999012683
    },
    "context_precision": {
      "n": 12,
      "value": 0.8983630951795019
    },
    "context_recall": {
      "n": 12,
      "value": 1.0
    }
  },
  "experience-v4-stream548": {
    "faithfulness": {
      "n": 12,
      "value": 0.7591841029341029
    },
    "context_precision": {
      "n": 12,
      "value": 0.8757936507385896
    },
    "context_recall": {
      "n": 12,
      "value": 1.0
    }
  }
}

## 最终交付结论

5120已切换到experience-v2-stream548；运行runtime与评测v2快照相同，Prompt/Skill为customer-experience-v2，真实流式请求与业务路由再次检查通过。

相对原5120新版：521/548→525/548，+0.73个百分点；修复11题、退步7题、仍失败16题。验证集110/118→115/118；历史留出116/119→115/119，后者下降必须保留。548题现均已见，名称“holdout”不代表本轮仍独立盲测。

声明忠实度88.90%→89.22%；知识首条命中90.83%→91.25%。固定12题Ragas忠实度81.62%→82.10%，但关闭体验Prompt/Skill的控制组为89.18%，因此新版Prompt并非全面改善。

选择候选相对v1的成对来源分组Bootstrap差值95%区间为约[-0.91,+2.70]个百分点，包含0。本轮只能表述为观察到小幅改善，不能声称显著或稳定提升。独立人工金标准和新盲测仍待补齐。

实际采用：事实问答聚焦、减少未被问到的长文步骤、保留诊断条件、复用已知组件和当前轮次，以及销售方核验对象参与代码决策。未更改检索/重排算法、两跳图搜索算法、知识原文、Gold或主评分器。额外校验器试验和配件角色试验保留为未选实验，不冒充当前线上能力。

v2通过22项对话/服务规则回归检查和4个销售方上下文路由检查；CSV548行与525/548计数核对通过；5120界面真实对话和图谱更新再次验证。所有历史结果与失败题均保留。
