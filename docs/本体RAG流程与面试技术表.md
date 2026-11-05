# OntoCare 本体约束 RAG：流程图与面试技术表

依据2026-11-03本机5112工作台当前实现核对。主Agent是CustomerWorkflowAgent，检索器是ReferenceRetriever，本体版本candidate-1。图描述实际控制流，不代表每个分支每次都会运行，也不表示系统质量已经达标。

## 先讲清楚这套系统是什么

这是一套“预定义业务Schema＋可追溯本体数据＋型号范围内文本混合召回＋局部图遍历＋受控客服流程”的RAG。Service Ontology提供产品、故障、知识、订单与证据；Decision Ontology提供条件、缺失事实、业务规则和允许动作。两者是同一业务底座的业务视图，不是两个LLM模型。

当前主链：业务资料 → 确定性清洗 → Schema/规则生成本体与来源映射，同时建立文本索引 → Query意图与槽位 → PN/业务对象定位与工具路由 → 混合召回/重排 → 同型号两跳BFS → 组装证据、子图、Skill和状态 → DeepSeek生成 → 硬检查与SOP状态机 → 回复/追问/本地人工待办。

## 技术与算法逐项核对

| 环节 | 算法／技术名词 | 在本项目具体怎么做 | 代码依据 | 面试边界／尚未实现 |
|---|---|---|---|---|
| 01 数据读取与清洗 | openpyxl＋Excel XML解析；确定性ETL | 按真实合并单元格恢复共享字段；核对拆分文件与总表；按业务主键去重；保留型号适用范围、隐藏状态、原行及SHA-256。附件登记，不自动理解。 | data.py:39、89；catalog.py | 不是让LLM改写源数据或补出缺失订单信息。 |
| 02 Schema与本体建图 | Schema-first／规则驱动实例化；Entity Resolution | 类、属性、关系、动作/函数契约由工程侧依据字段与SOP定义；程序生成实例。PN/SKU别名归一化；故障码与检查动作由限定正则识别。 | ontology.py:36；business.py:30；type_catalog.py | 未使用LLM全自动建图；没有Leiden/Louvain社区发现或社区摘要。 |
| 03 图谱语义对象 | Term／Mapping／Evidence／Constraint＋Relation | 概念与实例有来源定位；Mapping指向原始Q&A字段；Evidence保留原文/行号/哈希；Constraint限制产品、状态和业务条件。Service与Decision是同一业务底座的两个视图。 | ontology.py:40；ontology.py:69 | 不是只存“实体—关系—实体”三元组；也未接入OWL推理机。 |
| 04 存储与索引 | EvoOntology SemanticStore JSON＋内存字典/邻接表；SQLite；NumPy NPZ | 语义版本文件承载本体；SQLite存业务、会话、轨迹和缓存；NPZ存文本向量。当前875条Q&A，872条可召回，正文索引1043个窗口。 | ontology.py:94；customer_retrieval.py:13；business.py | 当前没有Neo4j、FAISS、HNSW或独立向量数据库。图形界面本身不是图数据库。 |
| 05 文本向量化 | intfloat/multilingual-e5-small，384维，L2归一化 | query: 与 passage: 前缀；正文按空白词切分，每窗最多200词、步长160词，标题另编码。索引用窗口，生成仍读取完整父Q&A，保留业务限制。 | customer_retrieval.py:47；ranking.py:29 | Embedding负责表示；余弦/点积、BM25与排序才负责匹配。这里是文本向量，不是Graph Embedding。 |
| 06 意图识别 | 有序关键词/正则规则＋结构化LLM分类＋JSON Schema | 9类意图：物流、产品咨询、排障、质保、退款、换货、渠道核验、范围外、澄清。明确规则先返回；混合/隐含意图调用DeepSeek；返回意图、issue_kind、置信度和原文证据。 | intent_router.py:23；customer_workflow.py:29 | 没有独立“意图向量TopK层”；不是加权词打分。规则0.95为固定工程值，不是校准概率。 |
| 07 置信度与上下文继承 | 证据子串校验＋confidence阈值＋会话状态规则 | LLM evidence须出现在脱敏原文中；缺证据或confidence<0.75则澄清；连续追问可继承上次意图。型号、已完成步骤、用户陈述与已核验字段分开保存。 | intent_router.py:56；agent.py:105 | 当前阈值不是0.70/0.82三级；置信度不是退款资格或操作权限。已有漏识别与重复确认的Bad Case。 |
| 08 型号与槽位识别 | 正则＋SKU/别名词典＋有限语境消歧 | 提取PN、型号别名、错误码、订单号；E25可映射T2353；S1 Pro按吸奶器/扫地机语境区分。型号不唯一先追问，不扩大产品范围。 | agent.py:64、110；customer_workflow.py:77 | 没有训练NER模型；错误码主解析偏3—5位长数字，较长复合报码可能漏掉，需要回归修复。 |
| 09 意图如何连接本体 | 类型路由＋规范ID精确定位＋关系适用范围 | 意图枚举选择Skill与SOP分支；PN转pn:T2353等ID，resolve_semantics取该型号的知识关联；命中FAQ后以knowledge:<FAQ_ID>定位节点。物流按订单快照查；渠道按country/seller查。 | agent.py:128、181、208；customer_workflow.py:259 | 不是把整句意图直接向量匹配成一个服务节点。主链存在显式代码路由。 |
| 10 语义查询工具 | ID字典查找；名称/别名匹配；词项重叠消歧 | resolve先精确ID，再名称/别名，再词项包含；多候选用上下文词项重叠消歧。browse用词项重叠/短语加分，每次最多6条。主客服通常直接resolve规范ID。 | EvoOntology runtime.py:163、262 | 不是每轮必调browse；不是向量图搜索，也不是概率逻辑推理。 |
| 11 中文检索预处理 | LLM约束翻译＋数字/型号一致性校验＋查询缓存 | 中文Query翻译成英语搜索表达；保留PN、所有数字及条件；失败退回原Query。当前及最近两轮用户问题可拼接为检索Query。 | query_rewrite.py:12、45；agent.py:135 | 不是HyDE：不生成假答案，也不将翻译文本作为事实证据。数字/型号可程序校验，否定语义保真仍需评测。 |
| 12 当前在线混合召回 | E5精确余弦/点积＋标题BM25＋加权融合 | 在PN及明确错误码适用范围内排序：0.35×标题相似度＋0.50×最大正文窗口相似度＋0.15×BM25/(BM25+10)。默认TopK=6。 | ranking.py:11、43、64；agent.py:221 | 当前在线主路是加权融合；基础/离线分支另有RRF，不要混称。错误码为空时不会强行过滤。 |
| 13 证据重排 | LLM证据校验式Top-1重排 | 对召回候选的原始标题/正文检查是否直接回答；只能选择已给ID，把最佳项前置。第一项已充分时保持原序；失败保留原排序；不新建文档。 | grounded_retrieval_v2.py:8；evidence_rerank.py:14 | 不是Cross-Encoder/BGE-Reranker。当前重排之后才挂接官方正文；重排器未读那些补充正文。 |
| 14 官方链接正文补全 | 域名白名单＋HTML/__NEXT_DATA__解析＋内容哈希＋PN范围交集 | 对支持站文章保存独立正文快照，和父Q&A哈希、型号范围一起核验后attach到证据；未解析视频、只有链接仍算缺口。 | references.py:15、51、107；reference_agent.py:11 | attach发生在召回/重排后；不能说所有官方正文已重新进入E5索引，也不承诺所有链接已补齐。 |
| 15 真正的图搜索 | 产品范围内多源BFS，最多2跳 | 把命中FAQ映射成种子；仅遍历同PN且active/validated的概念关系。邻接表双向扩展，输出保留原关系方向。最多30概念、6证据种子，遇产品中心节点停止扩展；工具预算允许时执行。 | graph_search.py:6、9、22；agent.py:286 | 不是Dijkstra/A*、PPR、社区搜索或GNN。错误码主要约束召回种子，BFS本身没有独立的全路径错误码证明。 |
| 16 图搜索返回什么 | 子图与可追溯路径＋约束＋数据映射 | 返回nodes、edges、paths、constraints、mappings、evidence_ids和版本；这些补充LLM上下文，不自动扩写证据正文，也不自动批准操作。 | graph_search.py:36—40 | BFS用于导航/局部上下文扩展，不代表完成因果推理或形式化证明。 |
| 17 业务检索与决策 | 本地订单/商品/包裹查询；SequenceMatcher；规则/状态机 | 订单号关联商品、包裹快照；国家筛选＋卖家归一化/模糊匹配；SOP条件决定缺什么、下一步与人工待办。未知包裹内容和金额口径保留未知。 | business.py:184、196；decisions.py；customer_workflow.py:53、77 | 存在口径差异待统一：business允许GB/SA/AE别名，SOP dealer要求源国家码；卖家候选阈值/间隔也不同。不能声称已经统一。 |
| 18 Context组装 | Evidence-grounded Context Assembly＋Skill Contract | 输入包含当前问题、最多3条历史会话、结构化状态、完整父Q&A/可用官方正文、本体子图、订单/渠道/决策事实、Skill、Prompt和输出契约。 | agent.py:322；prompting.py:6 | 本体给结构/限制，证据给事实，Skill给步骤；不是把整个知识库都塞给模型，也没有让用户陈述自动变成核验事实。 |
| 19 回复生成与工具调用 | DeepSeek-V4.1-Flash；OpenAI兼容Chat API；有界Function Calling | 系统Prompt＋Skill要求中英文JSON和citation_ids，可含summary/actions/questions/limits；模型仅可额外调用search_evidence与resolve_semantics，受剩余工具预算约束，单请求工具总数≤6。 | provider.py:76；agent.py:300、322 | 不是无限ReAct循环。当前provider非token流式API；网页增量展示不能直接称为模型原生token流式。 |
| 20 输出校验与SOP覆盖 | JSON/引用ID/型号/哈希/业务承诺硬检查；有限重试；状态机 | 生成后校验来源、跨型号及越权措辞；部分失败允许一次修正，否则保底。随后工作流按当前状态可覆盖成追问或本地回执，最终展示不一定来自LLM原文。 | agent.py:320、359；customer_workflow.py:259 | 代码硬检查不是完整Faithfulness裁判；SOP覆盖已造成反复确认、推进不足，不能仅凭架构图声称多轮已做好。 |
| 21 缓存 | 版本绑定LRU＋查询翻译/重排缓存＋固定FAQ缓存 | 最多4版本；每版resolve/graph各256条，文件stamp变化重新核验。图缓存key含PN、错误码、文档ID和BFS契约；固定FAQ限宿主审核的精确问题，并绑定数据/本体版本。 | ontology_cache.py:12、59；agent.py:212 | 不是Transformer KV Cache；上一问命中不能让下一问跳过适用性/权限检查。 |
| 22 MCP如何参与 | FastMCP stdio适配器＋共享OntologyService | 给外部Agent暴露实例、拓扑、知识、订单、经销商与本地受控操作；网页主流程直接调用Python工具。拓扑浏览最多3跳，不等同于回答用的2跳BFS。 | service_mcp.py:9；service_api.py:104 | MCP是工具协议，不是检索、建图或推理算法；本机回执不是外部退款完成。 |
| 23 评测与受控改进 | 硬断言＋五维LLM Judge＋失败归因＋候选配对门控 | 记录版本/证据/工具轨迹；局部候选经来源、兼容与回归检查后采纳或回滚。已有evolution.py主要是宿主辅助的Skill状态继承候选。 | evolution.py:18、67；scripts/run_ticket_evaluation_v1.py | 不等于RLHF、模型参数训练或自主改Schema/工具。63封首轮51/63通过；3组5轮全程0/3，人工校准待完成。 |

## 两个核心公式

当前在线加权召回：

`S(d,q) = 0.35·cos(E(q),E(title_d)) + 0.50·max_c cos(E(q),E(chunk_c)) + 0.15·BM25_title(q,d)/(BM25_title(q,d)+10)`

向量已L2归一化，精确矩阵点积等价于余弦相似度；正文的max是同一父Q&A内窗口得分取最大。标题BM25的k1=1.5、b=0.75。型号及可解析的错误码是适用范围条件，不是给高分就能绕过的软偏好。

基础/离线分支的RRF是 `sum_i 1/(60+rank_i)`；它和当前在线主路的加权融合是两个执行分支，不能混称。同样，句子向量不是图向量，BFS也不是向量近邻检索。

## Query到底怎么匹配进图谱？

以“E25报3212，滚筒已经清理过，下一步怎么办”为讲解示例（仅示意，未在本次重新调用模型）：

1. 意图规则/结构化LLM给出排障方向；设备别名表将E25确定为T2353，正则提取3212；会话状态记录已清理为“用户报告”。
2. 用规范ID `pn:T2353` 精确resolve，获取适用于该型号的知识关联。意图本身只负责Skill/流程路由，不负责证明资料适用性。
3. 在T2353和3212范围内进行E5＋BM25混合召回，必要时作证据Top-1重排，再把命中的FAQ ID转成 `knowledge:<FAQ_ID>`。
4. 以这些知识节点为种子做BFS两跳扩展，找到故障概念、检查概念及相关来源/约束。产品中心节点只访问不继续展开，减少串到其他故障。
5. 把真实FAQ/可用官方正文、图路径、已完成步骤、Skill与业务条件一起交给LLM。没有来源支持的下一步不能因为“图上相连”就编造。
6. 生成后由代码检查，再由SOP状态机决定是否显示答复、追问或本地人工待办。当前多轮状态机仍有重复确认缺陷，须继续回归修复。

## 可以直接用于面试的表述

“我没有把客服做成全库向量检索后直接回答。首先用人工定义的业务Schema和程序规则，把型号、故障、Q&A、检查动作、订单与证据组织为带适用范围的本体。在线用规则与结构化LLM识别意图，同时通过PN和SKU别名消歧定位业务对象。知识召回采用多语言E5的标题/正文余弦相似度和BM25加权融合，再以命中的知识节点做最多两跳BFS，补充关系、约束和来源。最后将真实证据、局部子图、会话状态和Skill交给模型，代码负责引用、型号与业务边界，SOP负责流程推进。这里的图推理主要指图导航与条件判断，尚不是自主逻辑推理或模型参数自进化。”

## 必须保留的实现边界

- 当前没有Leiden/Louvain社区发现、社区摘要、PPR/随机游走、Graph Embedding、GNN、Neo4j、FAISS、HyDE或训练式NER。
- 图中的BFS为回答链路最多2跳；MCP拓扑浏览可到3跳，二者不要混称。
- 官方正文补全用于生成证据，不代表已全部重新建立向量索引；重排时目前只读原始Q&A。
- 意图置信度不是已校准概率，规则0.95与模型0.75阈值是工程约定。
- 渠道国家别名与模糊匹配在business和SOP路径存在口径差异；状态机覆盖回答也仍有多轮卡点。本次只绘图与梳理，没有修改这些算法或重新评测。
- 系统保存本地客服处理状态与待办，没有真实承运商、退款、换货或发信接口。
- 最近63封已见首封邮件通过51/63（80.95%）；三组构造五轮对话全程0/3。它们不是独立盲测或真实结案解决率；流程图不是效果证明。

## 官方资料对照

E5的384维、query:/passage:前缀及归一化用法见[模型官方说明](https://huggingface.co/intfloat/multilingual-e5-small)。Microsoft GraphRAG默认索引包括实体/关系抽取、社区发现与社区报告；本项目未复现这一整套[默认GraphRAG数据流](https://microsoft.github.io/graphrag/index/default_dataflow/)。Palantir的对象、属性、关联及操作语义可参考[Ontology官方概览](https://www.palantir.com/docs/foundry/ontology/overview)，本项目运行在本机Python，并非Foundry部署。

## 代码入口

- [ontology.py](/Users/jiangenjing/Desktop/anker创新-黑客松/anker决赛/OntoCare-RSI-Rebuild-SOP-Integration/ontocare/ontology.py:36)
- [intent_router.py](/Users/jiangenjing/Desktop/anker创新-黑客松/anker决赛/OntoCare-RSI-Rebuild-SOP-Integration/ontocare/intent_router.py:23)
- [ranking.py](/Users/jiangenjing/Desktop/anker创新-黑客松/anker决赛/OntoCare-RSI-Rebuild-SOP-Integration/ontocare/ranking.py:43)
- [graph_search.py](/Users/jiangenjing/Desktop/anker创新-黑客松/anker决赛/OntoCare-RSI-Rebuild-SOP-Integration/ontocare/graph_search.py:9)
- [agent.py](/Users/jiangenjing/Desktop/anker创新-黑客松/anker决赛/OntoCare-RSI-Rebuild-SOP-Integration/ontocare/agent.py:322)
- [customer_workflow.py](/Users/jiangenjing/Desktop/anker创新-黑客松/anker决赛/OntoCare-RSI-Rebuild-SOP-Integration/ontocare/customer_workflow.py:259)
- [service_mcp.py](/Users/jiangenjing/Desktop/anker创新-黑客松/anker决赛/OntoCare-RSI-Rebuild-SOP-Integration/ontocare/service_mcp.py:9)
- [ontology_cache.py](/Users/jiangenjing/Desktop/anker创新-黑客松/anker决赛/OntoCare-RSI-Rebuild-SOP-Integration/ontocare/ontology_cache.py:12)
