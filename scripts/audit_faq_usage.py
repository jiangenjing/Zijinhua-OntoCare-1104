"""Source-to-ontology audit and optional real HTTP integration probes."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ontocare.data import ROOT, digest, load_json, read_tables, rows, write_json
from ontocare.manager import snapshot
from ontocare.retrieval import Retriever


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    version = load_json(ROOT / 'ontology/active.json')['active_version']
    graph = snapshot(ROOT, version)
    nodes = {n['id']: n for n in graph['nodes']}
    docs = load_json(ROOT / 'data/knowledge.json')
    stored = {d['id']: d for d in rows('documents')}
    directory = ROOT / 'ontology/versions' / version
    evidence = {r['id']: r for r in load_json(directory / 'evidence.json')}
    mappings = {r['term_id']: r for r in load_json(directory / 'mappings.json')}
    scopes = {r['target']: r for r in load_json(directory / 'constraints.json') if r['constraint_type'] == 'product_applicability'}
    outgoing = {}
    for edge in graph['links']:
        outgoing.setdefault(edge['source'], []).append(edge)
    checks, source_groups = [], []
    def check(name, passed, **detail):
        checks.append(dict(name=name, passed=bool(passed), **detail))

    canonical, _ = read_tables(ROOT.parent / '黑客松智能服务赛题资料.xlsx')
    check('canonical_source_hash', digest((ROOT.parent / '黑客松智能服务赛题资料.xlsx').read_bytes()) == load_json(ROOT / 'data/import-audit.json')['files']['黑客松智能服务赛题资料.xlsx'])
    for sheet in ['eufy Robovacs Q&A', 'eufy Breast Pump Q&A']:
        file = ROOT.parent / (sheet + '.xlsx')
        source, _ = read_tables(file)
        raw = next(iter(source.values()))
        group = [d for d in docs if d['source']['sheet'] == sheet]
        expected = canonical[sheet]
        fields = list(expected[0][1])
        check('split_matches_canonical:' + sheet,
              [{k:r.get(k) for k in fields} for _,r in raw] == [{k:r.get(k) for k in fields} for _,r in expected])
        check('source_hash:' + sheet, digest(file.read_bytes()) == load_json(ROOT / 'data/import-audit.json')['files'][file.name])
        by_row = {number: row for number, row in raw}
        for doc in group:
            row = by_row[doc['source']['row']]
            expected_pns = [p.strip().upper() for p in str(row['PN']).split(';') if p.strip()]
            check('source_row:' + doc['id'], doc['title'] == row['Title'] and doc['content'] == row['Content'] and doc['pns'] == expected_pns
                  and doc['visible'] == (row['Status'] == 'Published' and row['Consumer Visible'] == 'Visible'))
            check('database_and_instance:' + doc['id'], stored[doc['id']] == doc and nodes['knowledge:' + doc['id']]['properties']['content'] == doc['content'])
            if doc['visible']:
                eid, tid = 'ev:' + doc['id'], 'knowledge:' + doc['id']
                actual_pns = {e['source'].removeprefix('pn:') for e in graph['links'] if e['relation'] == 'applies_to' and e['target'] == tid}
                ev = evidence.get(eid, {})
                check('active_graph:' + doc['id'], actual_pns == set(doc['pns']) and ev.get('query') == doc['title'] and ev.get('result') == doc['content']
                      and ev.get('source', '').endswith('sha256=' + doc['source']['sha256'])
                      and mappings.get(tid, {}).get('semantic_filter') == 'id=' + doc['id']
                      and scopes.get(tid, {}).get('scope') == ';'.join(doc['pns'])
                      and any(e['target'] == eid and e['relation'] == 'grounded_in' for e in outgoing.get(tid, [])))
            else:
                check('hidden_excluded:' + doc['id'], 'ev:' + doc['id'] not in evidence and not any(e['relation'] == 'applies_to' and e['target'] == 'knowledge:' + doc['id'] for e in graph['links']))
        source_groups.append(dict(file=file.name, raw_rows=len(raw), imported=len(group), visible=sum(d['visible'] for d in group), hidden=sum(not d['visible'] for d in group), pn_counts=dict(Counter(p for d in group for p in d['pns'])),
                                  source_pdt_counts=dict(Counter(d['pdt'] for d in group)), model_edges=sum(e['relation'] == 'applies_to' and nodes[e['target']]['properties']['source']['sheet'] == sheet for e in graph['links'])))

    retriever = Retriever(ROOT)
    vector_loaded = retriever.vectors is not None
    check('runtime_retriever_population', {d['id'] for d in retriever.docs} == {d['id'] for d in docs if d['visible']})
    check('vector_parents', vector_loaded and set(retriever.vector_ids) == {d['id'] for d in docs if d['visible']})
    # Deterministic diagnostic: no embedding/model calls; known source title is NOT an unseen customer query.
    retriever.vectors = None
    hits, misses = 0, []
    for doc in retriever.docs:
        if not doc['pns']:
            misses.append(dict(id=doc['id'], reason='no_applicable_model'))
            continue
        result = retriever.search(doc['title'], pn=doc['pns'][0], limit=6)
        ids = [d['id'] for d in result['documents']]
        if doc['id'] in ids:
            hits += 1
        else:
            misses.append(dict(id=doc['id'], retrieved=ids))

    live, hybrid_probes = [], []
    if args.live:
        for miss in misses:
            doc = next(d for d in docs if d['id'] == miss['id'])
            try:
                req = urllib.request.Request('http://127.0.0.1:5112/api/chat', data=json.dumps(dict(message=doc['title'], mode='offline', version=version)).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=90) as response:
                    reply = json.load(response)
                hybrid_probes.append(dict(id=doc['id'], retrieved=reply['citation_ids'], recovered=doc['id'] in reply['citation_ids'],
                                          mode='offline HTTP with runtime hybrid retrieval; no model call', trace_id=reply['trace_id']))
            except Exception as exc:
                hybrid_probes.append(dict(id=doc['id'], error_type=type(exc).__name__))
        cases = [dict(question='我的 E25 报错误码3212，应该先检查什么？', expected_id='qa-ae8092257346', expected_sheet='eufy Robovacs Q&A', expected_pn='T2353'),
                 dict(question='How do I use the custom rhythm feature on eufy Wearable Breast Pump S1 Pro(T8D04)?', expected_id=next(d['id'] for d in docs if d['source']['sheet'] == 'eufy Breast Pump Q&A' and d['source']['row'] == 2), expected_sheet='eufy Breast Pump Q&A', expected_pn='T8D04')]
        def probe(case):
            try:
                req = urllib.request.Request('http://127.0.0.1:5112/api/chat', data=json.dumps(dict(message=case['question'], mode='live', version=version)).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=210) as response:
                    reply = json.load(response)
                retrieval = reply.get('retrieval') or {}
                case_checks = dict(model_completed=reply.get('model_status') == 'completed', correct_model=reply['state']['pn'] == case['expected_pn'],
                                   expected_qa_cited=case['expected_id'] in reply.get('citation_ids', []),
                                   expected_qa_in_graph='knowledge:' + case['expected_id'] in [n['id'] for n in retrieval.get('nodes', [])],
                                   correct_sheet_cited=any(c['source']['sheet'] == case['expected_sheet'] for c in reply['citations']),
                                   source_scope_budget=all(c['passed'] for c in reply['checks']))
                return dict(**case, passed=all(case_checks.values()), checks=case_checks, reply=reply)
            except Exception as exc:
                return dict(**case, passed=False, error_type=type(exc).__name__)
        with ThreadPoolExecutor(max_workers=2) as pool:
            live = list(pool.map(probe, cases))
        write_json(ROOT / 'local/faq-usage-live.json', live)
    report = dict(timestamp=datetime.now(timezone.utc).isoformat(), version=version, groups=source_groups,
                  structural_checks=dict(total=len(checks), passed=sum(c['passed'] for c in checks), failed=[c for c in checks if not c['passed']]),
                  source_title_diagnostic=dict(method='BM25-only top-6 using original known title and first source PN; not blind testing or quality measurement', queries=len(retriever.docs), hits=hits, misses=misses),
                  hybrid_miss_probes=hybrid_probes,
                  vectors=dict(loaded=vector_loaded, parents=len(set(retriever.vector_ids or [])), chunks=len(retriever.vector_ids or [])),
                  live=[{k:v for k,v in r.items() if k!='reply'} | dict(model_status=r.get('reply', {}).get('model_status'), citations=r.get('reply', {}).get('citation_ids'), graph_seed_ids=(r.get('reply', {}).get('retrieval') or {}).get('seeds'), trace_id=r.get('reply', {}).get('trace_id')) for r in live],
                  limits=['Structural and source-title checks do not establish user issue resolution or unseen-query quality.', 'Only the two listed requests are real-model integration probes when --live is supplied.', 'Source graph stores check concepts extracted by limited rules, not every detailed FAQ procedure as an independent node.'],
                  implementation_revision=__import__('subprocess').check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    write_json(ROOT / 'reports/faq-usage-audit.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
