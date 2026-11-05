"""Independent evidence recount, complete-case checks and family-cluster uncertainty."""
from collections import defaultdict
from pathlib import Path
import random
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest


def passed(row):
    j=row['judge'];reply=row['turns'][-1].get('reply',{})
    return (len(row['turns'])==len(row['case']['turns']) and
            all(t.get('reply',{}).get('model_status')=='completed' and all(c['passed'] for c in t['reply'].get('checks',[])) for t in row['turns']) and
            j.get('status')=='completed' and j.get('total',0)>=8 and j.get('task_satisfied') is True and
            all(j['dimensions'][k]['score']>0 for k in ['factual_model_accuracy','evidence_support','business_boundaries']) and
            (not row['case'].get('expected_decision') or reply.get('decision')==row['case']['expected_decision']))


def main():
    out=ROOT/'reports/workbench-v4';protocol=load_json(out/'protocol.json');dataset=load_json(ROOT/'reports/grounded-eval/live-sampling.json')['cases']
    if digest(dataset)!=protocol['dataset_sha256']:raise ValueError('Frozen suite changed')
    expected={(c['id'],r) for c in dataset for r in [1,2,3]};arms={};metrics={};graph_audit={}
    for arm in ['before','after']:
        rows=[load_json(p) for p in (ROOT/'local/workbench-v4'/arm).glob('*/*.json')]
        keys=[(r['id'],r['repeat']) for r in rows]
        if len(set(keys))!=len(keys) or set(keys)!=expected:raise ValueError('Planned arm incomplete or duplicated: '+arm)
        for row in rows:
            for t in row['turns']:
                reply=t.get('reply',{})
                if not reply:continue
                if reply['runtime']['id']!=protocol['runtimes'][arm]['id']:raise ValueError('Runtime mismatch')
                if reply['version']!=protocol['runtimes'][arm]['ontology_version']:raise ValueError('Ontology changed during run')
                if reply['model_status']=='completed' and not any(c.get('status')=='completed' for c in reply.get('model_calls',[])):raise ValueError('Claimed model completion has no successful call receipt')
            j=row['judge']
            if j.get('status')=='completed' and sum(v['score'] for v in j['dimensions'].values())!=j['total']:raise ValueError('Judge total inconsistent')
        graphs=[t['reply']['retrieval'] for row in rows for t in row['turns'] if t.get('reply',{}).get('retrieval')]
        valid=0
        for g in graphs:
            edges={e['id']:e for e in g['edges']};ok=len(g['nodes'])<=30
            for node,path in g['paths'].items():
                reachable=set(g['seeds']);ok=ok and len(path)<=2
                for edge_id in path:
                    e=edges.get(edge_id)
                    if e is None:ok=False;break
                    reachable={b for a,b in [(e['source'],e['target']),(e['target'],e['source'])] if a in reachable}
                ok=ok and node in reachable
            valid+=bool(ok)
        graph_audit[arm]={'returned_graphs':len(graphs),'valid_bounded_paths':valid,'scope':'structural path check only; not proof of factual truth or graph-only causal benefit'}
        arms[arm]={(r['id'],r['repeat']):r for r in rows}
        metrics[arm]={'passed':sum(passed(r) for r in rows),'planned':len(expected)}
    groups=defaultdict(list);gains=losses=0
    for key,a in arms['before'].items():
        d=int(passed(arms['after'][key]))-int(passed(a));groups[a['case']['family_id']].append(d);gains+=d>0;losses+=d<0
    values=[(sum(v),len(v)) for v in groups.values()];rng=random.Random(20261103);boot=[]
    for _ in range(5000):
        sample=rng.choices(values,k=len(values));boot.append(sum(v[0] for v in sample)/sum(v[1] for v in sample))
    boot.sort();result={'status':'verified_with_scope_caveats','metrics':metrics,'paired_improved':gains,'paired_regressed':losses,
                        'graph_path_audit':graph_audit,
                        'source_or_scenario_families':len(groups),'cluster_bootstrap_task_delta_95_interval':[boot[125],boot[4874]],
                        'limits':'Repeated bilingual questions are clustered by source/scenario; comparison is a seen synthetic validation replay, not production resolution or independent final certification.'}
    summary=load_json(out/'summary.json')
    if any(summary['arms'][arm]['pooled']['passed']!=m['passed'] for arm,m in metrics.items()):raise ValueError('Summary pass count disagrees with independent recount')
    write_json(out/'independent-verification.json',result);print(result)


if __name__=='__main__':main()
