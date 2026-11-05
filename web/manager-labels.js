/* Display explanations only. Identifiers and source data remain unchanged. */
window.OntoCareLabels=(()=>{
 const names={USER_REPORTED:'客户陈述（未独立核验）',MATCHED_BY_BRIEF_RULE:'按赛题名单规则匹配',NOT_MATCHED_BY_BRIEF_RULE:'按赛题名单规则未匹配',FUZZY_LIST_MATCH:'高置信模糊匹配',REVIEW_REQUIRED:'需要人工核查',NEEDS_REVIEW:'待核查',LIST_MATCH_SCOPE_UNKNOWN:'名单匹配，售后范围待核查',NOT_IN_SNAPSHOT:'本地快照未收录',NEED_COUNTRY_AND_SELLER:'缺少购买国家或销售方',SOURCE_LINE_ALIGNMENT:'按来源行次序对应',ACCESSORY_CANDIDATE:'配件候选',MAIN_OR_BUNDLE_CANDIDATE:'主机或套装候选',SOURCE_TEXT_CANDIDATE:'按来源描述分类，待业务核实',NOT_FETCHED:'尚未抓取',NOT_INTERPRETED:'尚未理解',PARTIALLY_SHIPPED:'部分商品已发货',NOT_SHIPPED:'未发货',SHIPPED:'已发货',DELIVERED:'已送达',IN_TRANSIT:'运输中',RETURN_TO_SENDER:'退回寄件人',UNKNOWN:'未知',LISTED_SCOPE_UNKNOWN:'名录出现，授权范围未知',SOURCE_ROW_AMOUNT_UNCONFIRMED:'金额粒度待确认',shipping_date_not_scalar:'发货日期非单一日期',shipment_before_purchase:'发货早于购买日期',
  purchase_within_30_days:'购买后 30 天内',new:'全新状态',unopened:'未拆封',intact_seals:'封条完好',unused:'未使用过',original_packaging:'保留原包装',
  pump_hub:'吸奶器主机',washable_parts:'可清洗配件','Restart robot':'重启扫地机器人','Inspect roller obstruction':'检查滚筒是否受阻',
  browse_semantics:'搜索本体概念',resolve_semantics:'解析本体关联',search_evidence:'检索适用证据',lookup_order:'查询本地订单',skill_state:'读取和记录处理步骤状态',
  product_applicability:'产品适用范围',warranty:'质保条件',refund:'退款条件',
  'Customer retrieval requires Published + Visible and a matching PN.':'客户检索要求：已发布、客户可见，并匹配当前产品型号。',
  'Business eligibility requires component and condition verification; see linked evidence.':'判断售后资格前，需要核实部件与适用条件，具体以关联证据为准。',
  'Shipping inquiry':'物流查询','Troubleshooting/Product usage':'故障排查／产品使用',
  'Return/Refund':'退货／退款','Warranty inquiry':'质保咨询',
  unresolved_ticket_model:'工单型号待确认',order_not_in_snapshot:'订单不在本地快照中',unresolved_item_model:'商品型号待确认',missing_endpoint:'关系端点缺失',unknown_relation:'关系类型未识别',
  str:'文本',int:'整数',float:'小数',bool:'布尔值',list:'列表',dict:'对象',NoneType:'空值',
  OPEN:'待处理',WAITING_CUSTOMER:'等待客户',PENDING_REVIEW:'待复核',local_demo:'本地演示',local_outbox:'本地事件表（未外部投递）',CustomerServiceAgent:'客服操作员',CustomerServiceSupervisor:'客服主管',
  true:'是',false:'否',active:'激活',validated:'已验证',block:'阻断',review:'待核查',error:'错误',
  Published:'已发布',Visible:'客户可见',Hidden:'隐藏',
 };
 const fields={ServiceRule:'服务决策规则',statement:'规则原文含义',subjects:'适用对象类型',DealerCheck:'销售方核验记录',country_claim:'客户陈述的购买国家',seller_claim:'客户陈述的销售方',claim_status:'陈述核验状态',competition_authorization:'比赛名单规则判断',eligible:'真实售后资格（未知）',match_policy:'匹配规则',session_reference:'会话匿名索引',offering_kind:'商品规格分类',classification_status:'分类核验状态',association_status:'关联核验状态',source_code:'来源国家代码',path:'目录路径',ProductOffering:'可售商品规格',Shipment:'物流包裹',Country:'国家与市场',KnowledgeCategory:'知识目录',ExternalMaterial:'外部材料引用',fulfillment_status:'此商品项发货状态',amount_raw:'来源金额原值',amount:'金额数值（不可直接汇总）',currency_code:'已核实币种',currency_symbol:'来源币种符号',amount_grain:'金额粒度',tracking_number:'包裹运单号',source_status:'来源物流状态',actual_shipped_at:'实际发货日期',contents_verified:'包裹内容是否已核实',snapshot_as_of:'快照采集时间',authorization_status:'授权核验状态',valid_from:'授权生效日期',valid_until:'授权截止日期',product_scope:'授权产品范围',fetch_status:'材料读取状态',understanding_status:'内容理解状态',
  id:'唯一标识',name:'名称',label:'显示名称',type:'类型',owner:'所属类',types:'数据类型',count:'数量',
  workflow_status:'本地处理状态',ticket_id:'关联工单标识',revision:'处理状态版本',reason:'复核理由',created_at:'创建时间',created_by:'创建操作员',action_id:'动作审计标识',ReviewTask:'复核任务',
  address:'订单地址',aliases:'型号别名／SKU 别名',carrier:'物流承运商',column:'字段列',constraint_type:'约束类型',content:'原始答案正文',content_hash:'正文校验指纹',country:'国家／地区',database_source:'数据来源位置',definition:'定义',description:'说明',evidence:'证据引用',evidence_refs:'证据引用列表',evidence_ids:'证据标识列表',grain:'数据粒度',order_number:'订单号',pdt:'产品团队标识',pn:'产品型号编码',pns:'适用产品型号列表',purchase_date:'购买日期',quantity:'商品数量',query:'原始问题',result:'原始结果／答案',scene:'咨询场景',scope:'适用范围',seller:'卖家／经销商',semantic_filter:'数据定位条件',severity:'约束等级',ship_date:'发货日期',shipping_status:'物流状态',sku:'商品编码',source:'来源／关系起点',source_row:'原始行号',source_rows:'原始行号列表',status:'状态',table:'数据表',target:'关系终点／约束对象',term_id:'关联概念标识',text:'工单邮件正文',timestamp:'来源时间',title:'原始标题',tracking:'物流单号',validation_method:'验证方法',visible:'是否允许客户召回',warranty_end:'质保结束日期',
  sha256:'文件校验指纹',file:'来源文件',sheet:'来源工作表',row:'原始行号',relation:'关系类型',basis:'关联依据',native_relation:'原生关系标识',source_title_sha256:'英文标题校验指纹',
  cardinality:'关系基数',rule:'匹配规则',read_only:'是否只读',input:'输入参数',data:'数据来源',level:'级别',code:'检查项',node:'对象标识',detail:'核查说明',zh:'中文解释',
  ProductModel:'产品型号',KnowledgeArticle:'知识条目',ErrorCode:'错误码记录',CheckStep:'检查步骤',Component:'部件',Condition:'资格条件',Evidence:'来源证据',Mapping:'数据映射',Constraint:'业务约束',SupportTicket:'客诉工单',Order:'订单',OrderItem:'订单商品',Dealer:'经销商',
 };
 const classes={ProductModel:'产品型号',KnowledgeArticle:'知识条目',ErrorCode:'错误码记录',CheckStep:'检查步骤',Component:'部件',Condition:'资格条件',Evidence:'来源证据',Mapping:'数据映射',Constraint:'业务约束',SupportTicket:'客诉工单',Order:'订单',OrderItem:'订单商品',Dealer:'经销商'};
 Object.assign(fields,{name:'名称（产品概念使用PN）',definition_version:'流程定义版本',record_kind:'记录性质',kind:'节点种类',instruction:'业务含义',runtime_status:'运行接入状态',runtime_label:'接入状态说明',runtime_note:'接入缺口',origin:'来源分类',origin_label:'来源说明',position:'地图布局坐标',rule_ids:'关联业务规则',required_for:'适用申请类型',condition:'适用条件',receipt_status:'材料接收状态',verification_status:'材料核验状态',action_type:'动作标识',execution_scope:'执行边界',handler:'已有处理器',object_type:'绑定对象类',fields_used:'读取字段',binding_kind:'绑定性质',execution_status:'运行闭环状态',transition_id:'分支标识',execution:'执行边界'});
 Object.assign(names,{connected_local:'已接入本地流程',connected:'已接入',partial:'部分接入',not_connected:'待接入',local_tool_only:'仅本地工具可用',input:'输入',activity:'处理',decision:'判断',terminal:'终点',replacement:'换货',refund:'退款'});
 Object.assign(fields,{taskId:'服务任务编号',observationId:'检查观察编号',requestId:'服务申请编号',stepId:'检查步骤编号',sessionId:'会话编号',caseId:'服务案件编号',ontologyVersion:'本体版本',procedureRevision:'步骤来源版本',evidenceRefs:'证据引用',completedChecks:'已报告完成的检查',revision:'记录版本',owner:'任务负责人',sourceObject:'来源业务对象',verificationStatus:'核验状态',reportedAt:'客户报告时间',previousObservationId:'上一条观察记录',creationActionId:'创建动作编号',humanTaskId:'人工待办编号',reason:'处理理由',executionMode:'执行范围',externalExecution:'是否已执行外部操作',submittedAt:'提交时间',submittedBy:'提交人',reviewNote:'人工审核意见',reviewedAt:'人工审核时间',resolutionBasis:'处理结果依据'});
 Object.assign(names,{NEW:'待开始',IN_PROGRESS:'处理中',ESCALATED:'已进入人工复核',RESOLVED:'已报告解决',PERSISTS:'问题仍存在',INCONCLUSIVE:'结果不明确',NOT_PERFORMED:'尚未执行',REPORTED:'客户报告',CONFLICT:'报告冲突待核查',SUBMITTED:'已提交',UNDER_REVIEW:'待补充／复核中',REJECTED:'未通过本地复核',COMPLETED:'本地复核已完成',ServiceTask:'服务任务',CheckObservation:'检查观察',ServiceRequest:'本地服务复核申请'});
 const translated=value=>names[value]||fields[value]||null;
 const field=name=>fields[name]||'原始业务字段';
 const value=x=>translated(x)?`${x}（${translated(x)}）`:x;
 function explain(n,titles){
  if(['ServiceProcess','SOPStep','RequiredMaterial','SOPAction','SOPDataBinding'].includes(n.type))return n.label;
  if(names[n.label])return names[n.label];
  const p=n.properties,match=(n.id+' '+(p.term_id||'')).match(/qa-[a-z0-9]+/),qa=match&&titles[match[0]]?.title;
  if(n.type==='KnowledgeArticle')return qa||'知识条目，原始问题与答案见详情';
  if(n.type==='Evidence')return '来源证据'+(qa?'：'+qa:'，用于核对原始资料');
  if(n.type==='Mapping')return '数据映射'+(qa?'：'+qa:'，定位到原始知识记录');
  if(n.type==='Constraint')return '业务约束：'+(names[p.constraint_type]||'适用范围与核验条件');
  if(n.type==='ProductModel')return '产品型号：'+n.label+(p.scope?'；产品团队：'+p.scope:'');
  if(n.type==='ErrorCode')return '错误码 '+n.label+'；适用型号：'+(p.scope||'见来源');
  if(n.type==='SupportTicket')return '客诉工单：'+(names[p.scene]||'客户咨询')+'；原表第 '+p.source_row+' 行';
  if(n.type==='ReviewTask')return '本地复核任务：'+p.reason+'；关联工单 '+p.ticket_id;
  if(n.type==='ServiceRule')return '服务决策规则：'+p.name+'；'+p.statement;
  if(n.type==='ProductOffering')return '可售规格：'+p.sku;
  if(n.type==='Shipment')return '包裹：'+p.tracking_number+'；'+(names[p.status]||p.status);
  if(n.type==='Country')return '来源国家／市场：'+p.source_code;
  if(n.type==='KnowledgeCategory')return '知识目录：'+p.path.join(' / ');
  if(n.type==='ExternalMaterial')return n.label+'（尚未读取理解）';
  if(n.type==='Order')return '订单记录，包含订单状态及商品行';
  if(n.type==='OrderItem')return '订单商品行：'+p.sku+'；数量 '+p.quantity;
  if(n.type==='Dealer')return '经销商记录：'+p.seller+'；国家／地区代码 '+p.country;
  return (classes[n.type]||'业务')+'记录，原始标识保留供核对';
 }
 function annotate(item){
  if(Array.isArray(item))return item.map(annotate);
  if(item&&typeof item==='object')return Object.fromEntries(Object.entries(item).map(([key,v])=>[fields[key]?`${key} · ${fields[key]}`:key,annotate(v)]));
  return typeof item==='string'?value(item):item;
 }
 const cardinality=c=>c+'（'+({'1:1':'一对一','1:N':'一对多','N:1':'多对一','N:N':'多对多'}[c]||'见关系定义')+'）';
 return {explain,field,value,annotate,cardinality};
})();
