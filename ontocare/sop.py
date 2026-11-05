"""Versioned SOP definitions and explicit data bindings, never case execution history."""
from pathlib import Path

from .data import ROOT, digest, load_json

SOP_FILE = 'data/service-sop-v2.json'
SCHEMA = load_json(ROOT / SOP_FILE)['schema']
RUNTIME_LABELS = {'connected_local':'已接入本地流程', 'connected': '已接入', 'partial': '部分接入', 'not_connected': '待接入',
                  'local_tool_only': '仅本地工具可用'}
ORIGIN_LABELS = {'sop_diagram': '赛题流程原图', 'sop_note_1': '赛题SOP说明第1条',
                 'sop_note_2': '赛题SOP说明第2条', 'tool_requirement': '赛题第五节：自建工具转人工', 'sop_note_3': '赛题SOP说明第3条', 'engineering_guard': '工程补充：未知条件待核查'}


def projection(root, existing_nodes):
    definition = load_json(Path(root) / SOP_FILE)
    steps = definition['steps']
    ids = [s['id'] for s in steps]
    if len(set(ids)) != len(ids):
        raise ValueError('SOP节点标识重复')
    if any(t['source'] not in ids or t['target'] not in ids or not t['condition']
           for t in definition['transitions']):
        raise ValueError('SOP流转缺少有效端点或条件')
    if any(t['origin'] not in ORIGIN_LABELS for t in definition['transitions']):
        raise ValueError('SOP分支来源类型无效')
    if any(s['runtime_status'] not in RUNTIME_LABELS or s['origin'] not in ORIGIN_LABELS for s in steps):
        raise ValueError('SOP接入状态或来源类型无效')
    nodes, links = [], []
    version, source = definition['version'], definition['source']
    existing = {n['id']: n for n in existing_nodes}

    def origin_source(origin):
        if origin == 'tool_requirement':
            return {**{k: v for k, v in source.items() if k != 'image_sha256'},
                    'section': '五、相关工具', 'location': 'word/document.xml：自建工具及转人工要求'}
        if origin == 'engineering_guard':
            return {'file': SOP_FILE, 'section': '工程补充：未知条件待核查', 'basis': '并非赛题原图中的显式分支'}
        return source

    def node(ident, kind, label, properties):
        nodes.append(dict(id=ident, type=kind, label=label,
                          properties={'definition_version': version, 'record_kind': '流程定义，不是工单执行记录', **properties}))

    def link(a, b, relation, **basis):
        links.append(dict(source=a, target=b, relation=relation,
                          basis={'definition_version': version, 'source': source, **basis}))

    node(definition['process_id'], 'ServiceProcess', definition['label'],
         dict(execution_status=definition['execution_status'], execution_scope='LOCAL_ONLY', source=source))
    for binding in definition['bindings']:
        ident = 'sop:binding:' + binding['id']
        node(ident, 'SOPDataBinding', binding['label'],
             dict(object_type=binding['object_type'], fields_used=binding['fields_used'],
                  binding_kind='对象类与字段使用声明；示例不是执行证据', source={'file': 'ontocare/manager.py', 'scope': '工程数据绑定'}))
        examples = sorted((n for n in existing_nodes if n['type'] == binding['object_type']
                           and n.get('properties', {}).get('visible') is not False), key=lambda n: n['id'])[:1]
        for example in examples:
            link(ident, example['id'], 'sop_binding_example',
                 meaning='该类型的可见源记录示例，不表示该工单执行过此流程或满足售后条件')
    for material in definition['materials']:
        ident = 'sop:material:' + material['id']
        node(ident, 'RequiredMaterial', material['label'],
             {k: v for k, v in material.items() if k not in {'id', 'label'}} |
             dict(receipt_status='定义不记录已收到', verification_status='定义不记录已核验', source=source))
        link(ident, 'brief:required-materials', 'sop_based_on_rule')
    for action in definition['actions']:
        node('sop:action:' + action['id'], 'SOPAction', action['label'],
             {k: v for k, v in action.items() if k not in {'id', 'label'}} |
             dict(runtime_label=RUNTIME_LABELS[action['runtime_status']], source=source))
    for step in steps:
        node(step['id'], 'SOPStep', step['label'],
             {k: v for k, v in step.items() if k not in {'id', 'label', 'bindings', 'materials', 'actions'}} |
             dict(runtime_label=RUNTIME_LABELS[step['runtime_status']], origin_label=ORIGIN_LABELS[step['origin']], source=origin_source(step['origin'])))
        link(definition['process_id'], step['id'], 'process_has_step')
        for rule in step['rule_ids']:
            link(step['id'], rule, 'sop_based_on_rule')
        for family, relation, key in [('binding', 'sop_uses_data', 'bindings'),
                                      ('material', 'sop_requires_material', 'materials'),
                                      ('action', 'sop_proposes_action', 'actions')]:
            for target in step[key]:
                link(step['id'], 'sop:' + family + ':' + target, relation)
    for transition in definition['transitions']:
        link(transition['source'], transition['target'], 'sop_next_step',
             transition_id=transition['id'], condition=transition['condition'],
             display_label=transition.get('display_label', transition['condition']),
             origin=transition['origin'], origin_label=ORIGIN_LABELS[transition['origin']],
             source=origin_source(transition['origin']),
             execution='定义分支，不是已发生的流转')
    available = set(existing) | {n['id'] for n in nodes}
    if any(e['source'] not in available or e['target'] not in available for e in links):
        raise ValueError('SOP关联引用了不存在的对象')
    metadata = {k: definition[k] for k in ['version', 'process_id', 'label', 'notice', 'implementation_checked_at', 'source']}
    metadata.update(definition_sha256=digest(definition), file=SOP_FILE, step_ids=ids,
                    step_count=len(steps), branch_count=len(definition['transitions']),
                    runtime_status_counts={label: sum(s['runtime_status'] == status for s in steps)
                                           for status, label in RUNTIME_LABELS.items()})
    return dict(nodes=nodes, links=links, metadata=metadata)
