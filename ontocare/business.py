"""Source-backed business projection for every competition workbook sheet."""
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sqlite3

from .data import ROOT, digest, load_json, read_tables


def connect(root=ROOT, readonly=True):
    path = Path(root) / 'local/business.sqlite'
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) if readonly else sqlite3.connect(path)


def date_value(value):
    text = str(value or '').strip()
    if re.fullmatch(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:T00:00:00)?', text):
        return datetime.strptime(text.split('T')[0].replace('/', '-'), '%Y-%m-%d').date().isoformat()
    return None


def lines(value):
    return [v.strip() for v in str(value or '').splitlines() if v.strip() and v.strip() != '/']


def build(source, root=ROOT):
    """Build a separate local projection; do not rewrite frozen semantic versions."""
    root, source = Path(root), Path(source)
    tables, _ = read_tables(source)
    source_hash = digest(source.read_bytes())
    nodes, edges, diagnostics = {}, [], []
    def node(ident, kind, label, properties):
        nodes[ident] = {'id': ident, 'type': kind, 'label': label, 'properties': properties}
    def edge(a, b, relation, basis):
        edges.append({'source': a, 'target': b, 'relation': relation, 'basis': basis})
    def origin(sheet, row):
        return {'sheet': sheet, 'row': row, 'source_sha256': source_hash}
    products = load_json(root / 'data/products.json')
    item_groups = {}
    for rownum, r in tables['订单信息']:
        oid, sku = str(r['订单号']), str(r['SKU'])
        ident, offering = 'item:' + str(rownum), 'offering:' + sku
        item_groups.setdefault(oid, []).append((rownum, r))
        amount_raw = str(r.get('订单金额') or '').strip()
        try:
            amount = str(Decimal(re.sub(r'[^\d.-]', '', amount_raw))) if amount_raw else None
        except InvalidOperation:
            amount = None
        props = dict(source_row=rownum, order_number=oid, sku=sku, description=r['Product Description'], quantity=r['QTY'],
                     purchase_date=r['购买日期'], warranty_end=r['质保结束日期'], carrier=r['物流承运商'], tracking=r['物流单号'],
                     shipping_status=r['物流状态'], ship_date=r['发货日期'], fulfillment_status=r['订单状态'],
                     amount_raw=amount_raw, amount=amount, currency_symbol='$' if '$' in amount_raw else None,
                     currency_code=None, amount_grain='SOURCE_ROW_AMOUNT_UNCONFIRMED', source=origin('订单信息', rownum))
        node(ident, 'OrderItem', sku, props)
        if offering not in nodes:
            accessory = bool(re.search(r'accessor|replacement|dust\s*bag|filter|solution', str(r['Product Description']), re.I))
            nodes[offering] = {'id': offering, 'type': 'ProductOffering', 'label': sku, 'properties':
                               {'sku': sku, 'description': r['Product Description'], 'offering_kind': 'ACCESSORY_CANDIDATE' if accessory else 'MAIN_OR_BUNDLE_CANDIDATE', 'classification_status': 'SOURCE_TEXT_CANDIDATE', 'source_rows': []}}
        nodes[offering]['properties']['source_rows'].append(rownum)
        edge(ident, offering, 'purchases_offering', origin('订单信息', rownum))
        candidates = [p['pn'] for p in products if sku.upper() in p['aliases']]
        if len(candidates) == 1 and not any(e['source'] == offering and e['relation'] == 'offering_model_candidate' for e in edges):
            edge(offering, 'pn:' + candidates[0], 'offering_model_candidate', {'method': 'existing_alias', 'verification': 'CANDIDATE_NOT_MASTER_VERIFIED'})
        tracking = lines(r['物流单号'])
        carriers, statuses, shipped = [lines(r[k]) for k in ['物流承运商', '物流状态', '发货日期']]
        for index, raw_tracking in enumerate(tracking):
            tracking_number = re.sub(r'^Tracking number\d*:\s*', '', raw_tracking, flags=re.I)
            sid = 'shipment:' + digest([oid, tracking_number])[:16]
            aligned = all(len(x) == len(tracking) for x in [carriers, statuses, shipped])
            status = statuses[index] if aligned else None
            standard = 'UNKNOWN'
            if status:
                standard = 'RETURN_TO_SENDER' if 'return to sender' in status.lower() else 'DELIVERED' if 'delivered' in status.lower() else 'IN_TRANSIT' if re.search('transit|transist', status, re.I) else 'UNKNOWN'
            node(sid, 'Shipment', tracking_number, {'tracking_number': tracking_number,
                 'carrier': carriers[index] if aligned else None, 'status': standard, 'source_status': status,
                 'actual_shipped_at': date_value(shipped[index]) if aligned else None,
                 'source': origin('订单信息', rownum), 'association_status': 'SOURCE_LINE_ALIGNMENT' if aligned else 'NEEDS_REVIEW',
                 'contents_verified': False, 'snapshot_as_of': None})
            edge('order:' + oid, sid, 'has_shipment', origin('订单信息', rownum))
            edge(sid, ident, 'reported_on_item', {'meaning': '物流信息源于此商品行；不确认每个包裹装有什么或数量', **origin('订单信息', rownum)})
        if not date_value(r['发货日期']):
            diagnostics.append({'level': 'review', 'code': 'shipping_date_not_scalar', 'node': ident, 'detail': '多日期或预计发货说明保留原文，未当作单一实际发货日期'})
        buy, ship = date_value(r['购买日期']), date_value(r['发货日期'])
        if buy and ship and ship < buy:
            diagnostics.append({'level': 'review', 'code': 'shipment_before_purchase', 'node': ident, 'detail': '发货早于购买，保留源值待核查'})
    for oid, group in item_groups.items():
        r = group[0][1];states = [str(x['订单状态']) for _, x in group]
        aggregate = 'PARTIALLY_SHIPPED' if any('未发货' in x for x in states) and any('未发货' not in x and '已发货' in x for x in states) else 'NOT_SHIPPED' if all('未发货' in x for x in states) else 'SHIPPED' if all('已发货' in x for x in states) else 'UNKNOWN'
        node('order:' + oid, 'Order', oid, {'order_number': oid, 'address': r['订单地址'], 'status': aggregate,
             'source_order_status': r['订单状态'], 'source_rows': [n for n, _ in group], 'snapshot_as_of': None})
    # Sellers remain source-listed entities, never an invented authorization claim.
    for country, seller in sorted({(str(r['country']).strip(), str(r['seller']).strip()) for _, r in tables['经销商信息']}):
        cid, did = 'country:' + country, 'dealer:' + digest([country, seller])[:16]
        node(cid, 'Country', country, {'source_code': country, 'description': '来源国家/市场代码，保留 UK/KSA/UAE 等原码'})
        node(did, 'Dealer', seller, {'country': country, 'seller': seller, 'authorization_status': 'LISTED_SCOPE_UNKNOWN',
                                   'valid_from': None, 'valid_until': None, 'product_scope': None})
        edge(did, cid, 'listed_in_country', {'sheet': '经销商信息', 'method': 'exact_country_seller_dedup', 'source_sha256': source_hash})
    for sheet in ['eufy Robovacs Q&A', 'eufy Breast Pump Q&A']:
        for rownum, r in tables[sheet]:
            kid = 'knowledge:qa-' + digest([sheet, rownum])[:12]
            parent = None;path = []
            for name in ['First degree directory', 'Second degree directory', 'Third degree directory']:
                if not r.get(name):continue
                path.append(str(r[name]).strip());cid = 'category:' + digest([sheet, path])[:16]
                node(cid, 'KnowledgeCategory', path[-1], {'name': path[-1], 'path': list(path), 'sheet': sheet})
                if parent:edge(parent, cid, 'contains_category', {'sheet': sheet, 'path': list(path)})
                parent = cid
            if parent:edge(kid, parent, 'classified_as', origin(sheet, rownum))
    from .catalog import relationships
    import zipfile
    import xml.etree.ElementTree as ET
    from .data import NS
    with zipfile.ZipFile(source) as archive:
        workbook = ET.fromstring(archive.read('xl/workbook.xml'));sheet_rels = relationships(archive, 'xl/workbook.xml')
        for sh in workbook.find('s:sheets', NS):
            if sh.attrib['name'] != '客诉工单信息':continue
            part = sheet_rels[sh.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            xml = ET.fromstring(archive.read(part));rels_path = part.rsplit('/', 1)[0] + '/_rels/' + part.rsplit('/', 1)[-1] + '.rels'
            external = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(archive.read(rels_path)) if r.attrib.get('TargetMode') == 'External'} if rels_path in archive.namelist() else {}
            for h in xml.findall('s:hyperlinks/s:hyperlink', NS):
                rownum = int(re.search(r'\d+', h.attrib['ref']).group());target = external.get(h.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'))
                if not target:continue
                eid = 'external:' + digest([rownum, target])[:16]
                node(eid, 'ExternalMaterial', '外部材料 · 工单源行 ' + str(rownum), {'url': target, 'fetch_status': 'NOT_FETCHED', 'understanding_status': 'NOT_INTERPRETED', 'source': origin('客诉工单信息', rownum)})
                edge('ticket:ticket-' + str(rownum).zfill(3), eid, 'references_material', origin('客诉工单信息', rownum))
    # Use the same source-bound SOP rules as the decision evaluator.
    rules_path = root / 'data/competition-rules.json'
    if rules_path.exists():
        sop = load_json(rules_path)
        for rule in sop['rules']:
            node(rule['id'], 'ServiceRule', rule['name'], {**rule, 'version': sop['version']})
            for n in list(nodes.values()):
                if n['type'] in rule['subjects']:
                    edge(n['id'], rule['id'], 'governed_by_service_rule', {'source': rule['source'], 'meaning': '适用规则，不表示条件已经满足'})
            if 'ProductModel' in rule['subjects']:
                for p in products:edge('pn:' + p['pn'], rule['id'], 'governed_by_service_rule', rule['source'])
            if 'SupportTicket' in rule['subjects']:
                for rownum, _ in tables['客诉工单信息']:edge('ticket:ticket-' + str(rownum).zfill(3), rule['id'], 'governed_by_service_rule', rule['source'])

    # Deduplicate identical category edges without losing their semantic identity.
    edges = list({(e['source'], e['target'], e['relation']): e for e in edges}.values())
    decisions = {
        '客诉工单信息': '工单、问题原文与材料引用；样例陈述不是核验事实',
        '订单信息': '订单、商品项、可售规格、物流包裹；金额粒度与包裹内容未知则保留未知',
        'eufy Robovacs Q&A': '知识文章、目录、适用型号、原文证据；受发布与可见性限制',
        'eufy Breast Pump Q&A': '知识文章、目录、部件与政策来源；隐藏内容仅管理可见',
        '经销商信息': '销售方和国家名录；名单出现不等于完整授权或售后资格',
    }
    coverage = [{'sheet': name, 'rows': len(records), 'fields': list(records[0][1]) if records else [],
                 'decision': decisions.get(name, '原始资料保留，待明确业务用途'), 'included': True,
                 'not_modeled_as_entities': ['排版序号', '空白填充列', '每个单元格', '重复镜像文件']} for name, records in tables.items()]
    metadata = {'source_file': source.name, 'source_sha256': source_hash, 'sheets': coverage,
                'projection_version': 'business-v1', 'node_counts': dict(Counter(n['type'] for n in nodes.values())),
                'boundary': '本地资料快照；不代表实时订单、已核验授权或图像理解'}
    (root / 'local').mkdir(exist_ok=True)
    with connect(root, False) as conn:
        conn.executescript('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS raw_rows (sheet TEXT,rownum INTEGER,payload TEXT,PRIMARY KEY(sheet,rownum));')
        conn.execute('DELETE FROM records');conn.execute('DELETE FROM raw_rows')
        conn.execute('INSERT INTO records VALUES (?,?)', ('snapshot', json.dumps({'nodes': list(nodes.values()), 'links': edges, 'diagnostics': diagnostics}, ensure_ascii=False)))
        conn.execute('INSERT OR REPLACE INTO metadata VALUES (1,?)', (json.dumps(metadata, ensure_ascii=False),))
        conn.executemany('INSERT INTO raw_rows VALUES (?,?,?)', [(s, n, json.dumps(r, ensure_ascii=False)) for s, records in tables.items() for n, r in records])
    return metadata


def projection(root=ROOT):
    if not (Path(root) / 'local/business.sqlite').exists():return {'nodes': [], 'links': [], 'diagnostics': []}
    with connect(root) as conn:
        result = json.loads(conn.execute("SELECT payload FROM records WHERE id='snapshot'").fetchone()[0])
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='dealer_checks'").fetchone():
            for (payload,) in conn.execute('SELECT payload FROM dealer_checks ORDER BY id'):
                check = json.loads(payload)
                result['nodes'].extend(check['nodes']);result['links'].extend(check['links'])
        return result


def coverage(root=ROOT):
    with connect(root) as conn:return json.loads(conn.execute('SELECT payload FROM metadata WHERE id=1').fetchone()[0])


def order_detail(order_number, root=ROOT):
    p = projection(root);found = [n for n in p['nodes'] if n['id'] == 'order:' + order_number]
    if not found:return {'status': 'NOT_IN_SNAPSHOT', 'order_number': order_number}
    order = dict(found[0]);order['properties'] = {k: v for k, v in order['properties'].items() if k != 'address'}
    return {'status': 'FOUND_LOCAL_SNAPSHOT', 'order': order, 'items': [n for n in p['nodes'] if n['type'] == 'OrderItem' and n['properties']['order_number'] == order_number],
            'shipments': [n for n in p['nodes'] if n['type'] == 'Shipment' and any(e['source'] == order['id'] and e['target'] == n['id'] for e in p['links'])],
            'limitations': ['不是实时物流', '包裹内容和分配数量未核实', '金额币种与粒度待核实', '未核验客户订单归属'],
            'decision': {'allowed_local_actions': ['explain_snapshot', 'collect_missing_evidence', 'suggest_manual_review'], 'approved_remedy': None,
                         'required_before_remedy': ['客户订单归属', '最新物流或质保核验', '购买凭证', '故障申请所需排障结果、产品SN与图片/视频'],
                         'rule_ids': ['brief:reship', 'brief:fault-replacement']}}


def check_seller(country, seller, root=ROOT):
    country, seller = country.strip().upper(), seller.strip()
    if not country or not seller:return {'status': 'NEED_COUNTRY_AND_SELLER', 'eligible': None}
    country = {'GB': 'UK', 'SA': 'KSA', 'AE': 'UAE'}.get(country, country)
    sellers = [n for n in projection(root)['nodes'] if n['type'] == 'Dealer' and n['properties']['country'] == country]
    def clean(s):return re.sub(r'[^\w]', '', s.casefold())
    exact = [n for n in sellers if clean(n['label']) == clean(seller)]
    candidates = exact or sorted((n for n in sellers if SequenceMatcher(None, clean(n['label']), clean(seller)).ratio() >= .72), key=lambda n: SequenceMatcher(None, clean(n['label']), clean(seller)).ratio(), reverse=True)[:5]
    scores = [round(SequenceMatcher(None, clean(n['label']), clean(seller)).ratio(), 4) for n in candidates]
    # The brief specifies fuzzy matching, but no threshold. Ambiguous/weak matches stay pending.
    matched = len(exact) == 1 or bool(scores and scores[0] >= .90 and (len(scores) == 1 or scores[0] - scores[1] >= .10))
    return {'status': 'LIST_MATCH_SCOPE_UNKNOWN' if len(exact) == 1 else 'FUZZY_LIST_MATCH' if matched else 'REVIEW_REQUIRED' if candidates else 'NOT_IN_SNAPSHOT',
            'country': country, 'candidates': candidates, 'eligible': None,
            'competition_authorization': 'MATCHED_BY_BRIEF_RULE' if matched else 'NEEDS_REVIEW' if candidates else 'NOT_MATCHED_BY_BRIEF_RULE',
            'match_scores': scores, 'match_policy': {'country': 'exact after explicit code aliases GB→UK/SA→KSA/AE→UAE', 'seller': 'normalized exact or SequenceMatcher >=0.90, runner-up margin >=0.10', 'candidate_threshold': .72, 'threshold_source': 'engineering choice; brief gives no numeric threshold'},
            'source': '赛题说明第三节：下单国家精准匹配＋卖家名称模糊匹配',
            'reason': '名单命中只证明出现在该国家资料快照；授权有效期、品类范围与售后资格仍需核验。'}


def record_dealer_check(result, country, seller, session_id, order_number='', root=ROOT):
    """Persist a stated purchase context, never fabricate an order's seller."""
    if not (Path(root) / 'local/business.sqlite').exists():return None
    ident = 'dealercheck:' + digest([session_id, country, seller, order_number])[:20]
    props = {'country_claim': country, 'seller_claim': seller, 'claim_status': 'USER_REPORTED',
             'status': result['status'], 'competition_authorization': result.get('competition_authorization', 'NEEDS_REVIEW'),
             'eligible': None, 'reason': result.get('reason', '缺少购买国家或销售方'), 'match_policy': result.get('match_policy'),
             'source': result.get('source'), 'session_reference': digest(session_id)[:16]}
    nodes = [{'id': ident, 'type': 'DealerCheck', 'label': '销售方核验 · ' + seller, 'properties': props}]
    edges = []
    known = {n['id'] for n in projection(root)['nodes']}
    cid = 'country:' + result.get('country', country)
    if cid in known:edges.append({'source': ident, 'target': cid, 'relation': 'stated_purchase_country', 'basis': '客户提供购买国家；不是收货地址推断'})
    for n in result.get('candidates', []):
        edges.append({'source': ident, 'target': n['id'], 'relation': 'candidate_dealer', 'basis': {'status': result['status'], 'meaning': '匹配候选，不代表真实售后资格'}})
    if 'order:' + order_number in known:
        edges.append({'source': ident, 'target': 'order:' + order_number, 'relation': 'claimed_order', 'basis': '当前会话提及该订单；未核验归属，也未改写原订单销售方'})
    with connect(root, False) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS dealer_checks (id TEXT PRIMARY KEY,payload TEXT)')
        conn.execute('INSERT OR REPLACE INTO dealer_checks VALUES (?,?)', (ident, json.dumps({'nodes': nodes, 'links': edges}, ensure_ascii=False)))
    return ident
