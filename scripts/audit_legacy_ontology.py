"""Reproduce legacy joins without starting the legacy server or loading secrets."""
import ast
import importlib.util
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ontocare.data import ROOT, digest, load_json, write_json


def main():
    legacy = ROOT.parent / 'anker-OntoCare-RSI/OntoCare'
    spec = importlib.util.spec_from_file_location('legacy_dataset', legacy / 'dataset.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    products, orders, _, knowledge, _, summary = module.load_dataset()
    tree = ast.parse((legacy / 'app.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'resolve_product')
    env = dict(re=re, PRODUCTS=products, PROMOTER_WORDS=['pump', 'breast', '吸奶'], ROBOT_WORDS=['robot', 'vacuum', '扫地'])
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(legacy / 'app.py'), 'exec'), env)
    selected = env['resolve_product']('我的 E25 报 3212 错误', 'E235311B')['product']['id']
    assert selected == 'E2353'
    count = sum(k['product_id'] == selected for k in knowledge)
    assert count == 0
    legacy_import = load_json(legacy / 'data/ontology-import-audit.json')
    graph_js = (legacy / 'static/conversation-graph.js').read_text()
    assert "relation:'same_turn'" in graph_js
    report = dict(target='anker-OntoCare-RSI/OntoCare', method='Read dataset.py; execute only resolve_product AST with fixture-independent loaded source products; no model or server calls',
                  source_hashes={name: digest((legacy / name).read_bytes()) for name in ['dataset.py', 'app.py', 'static/conversation-graph.js', 'data/source.json', 'data/qa-workbooks.json', 'data/ontology-import-audit.json']},
                  summary=summary, findings=[
        dict(status='已复现', title='SKU 前缀产生 E2353，与 T2353 知识断开', impact='Anker001 / E235311B 在订单 SKU 优先路径识别为 E2353，该产品下知识条数为 0。',
             evidence=dict(input={'message': '我的 E25 报 3212 错误', 'order_sku': 'E235311B'}, selected_product=selected, matching_knowledge=count,
                           source=['dataset.py: product(row[SKU][:5])', 'app.py: resolve_product / order_sku priority']),
             recommendation='建立明确 SKU—PN 对照；E235311B 的 E25→T2353 映射应经来源核实后采纳。当前 Rebuild 将它标为待核查。'),
        dict(status='展示语义受限', title='对话图使用 same_turn，不是业务语义关系', impact='同轮出现的对象被连成星形图；不能据此推导订单包含产品或知识适用于型号。',
             evidence=dict(source='static/conversation-graph.js: normalize', relation='same_turn', rule='nodes.slice(1) connects nodes[0] to every other node'),
             recommendation='在独立业务图中按字段、类型和来源生成边；保留同轮图作为对话参与记录。'),
        dict(status='导入风险已被旧代码阻断', title='旧步骤父知识 ID 存在跨工作表歧义', impact=f"旧审计记录 {legacy_import['duplicate_legacy_ids']} 个重复知识 ID；{legacy_import['ambiguous_step_count']}/{legacy_import['step_count']} 条步骤无法仅凭 kb_id 唯一定位父知识。",
             evidence={k:v for k,v in legacy_import.items() if k != 'namespaced_ids'},
             recommendation='使用工作表＋行号或稳定知识 ID 关联步骤；旧审计说明这些歧义步骤已排除，不能称为已发生的错误连接。'),
        dict(status='待建模', title='部分商品前缀是配件编码，不能直接等同产品型号', impact='旧数据适配层生成 26 个产品节点，其中 7 个没有对应知识；部分可能是配件，不能一概判错。',
             evidence=dict(product_count=len(products), no_knowledge=[p['id'] for p in products if not any(k['product_id'] == p['id'] for k in knowledge)]),
             recommendation='区分产品型号、SKU 和订单商品；对未解析商品保持独立实例，不强行连接主机知识。'),
    ])
    write_json(ROOT / 'reports/legacy-ontology-audit.json', report)
    print('Legacy audit: SKU mismatch reproduced; same-turn projection verified; import ambiguity recorded.')


if __name__ == '__main__':
    main()
