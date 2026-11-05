"""Fail-closed publication gate. No network or Git mutation is performed here."""
import math
from pathlib import Path
from .data import load_json,digest


def threshold_passes(metrics):
    return all(type(metrics.get(k)) in {int,float} and math.isfinite(metrics[k]) and metrics[k]>.90 for k in ['hit_at_1','recall_at_1'])


def recount(dataset,records):
    expected={c['id']+':'+lang:(c,q) for c in dataset['cases'] for lang,q in c['questions'].items()}
    actual=[r['id'] for r in records]
    if len(set(actual))!=len(actual) or set(actual)!=set(expected):raise ValueError('Missing, repeated or unexpected evaluation queries')
    hit=recall=0.
    for row in records:
        case,q=expected[row['id']]
        if row['original_query']!=q or row['pn']!=case['pn'] or set(row['gold_ids'])!=set(case['gold_ids']):raise ValueError('Frozen input or gold changed')
        gold=set(case['gold_ids'])
        if not gold:raise ValueError('Unlabelled case included in answerable Recall denominator')
        found=bool(row['ranked_ids']) and row['ranked_ids'][0] in gold
        hit+=found;recall+=int(found)/len(gold)
    n=len(expected)
    return {'samples':n,'hit_at_1':hit/n,'recall_at_1':recall/n}


def faithful_comparison(inputs, records, expected_ids):
    """Recompute the added non-regression gate from paired raw metric records."""
    expected = {(case_id, arm) for case_id in expected_ids for arm in ['parent', 'candidate']}
    if len(expected_ids) < 60 or len(set(expected_ids)) != len(expected_ids):
        raise ValueError('Faithfulness needs the frozen independent sample of at least 60 queries')
    actual = {(r['case_id'], r['arm']) for r in inputs['cases']}
    if actual != expected or len(inputs['cases']) != len(expected):
        raise ValueError('Missing or repeated paired faithfulness inputs')
    by_id = {r['id']: r for r in inputs['cases']}
    if len(by_id) != len(expected) or len(records) != len(expected) or {r['id'] for r in records} != set(by_id):
        raise ValueError('Missing or repeated raw faithfulness results')
    scores = {'parent': [], 'candidate': []}
    for row in records:
        source = by_id[row['id']]; score = row.get('metrics', {}).get('faithfulness')
        if source.get('model_status') != 'completed' or type(score) not in {int, float} or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Incomplete independent faithfulness evaluation')
        if not row.get('model_calls') or any(c.get('status') != 'completed' for c in row['model_calls']):
            raise ValueError('Faithfulness evaluator receipt missing or incomplete')
        scores[source['arm']].append(score)
    means = {arm: sum(values) / len(values) for arm, values in scores.items()}
    return {'passed': means['candidate'] >= means['parent'], 'means': means, 'paired_queries': len(expected_ids),
            'definition': 'Same frozen independent questions and same Ragas evaluator; candidate mean must not fall below parent, no rounding tolerance.'}


def assess(root):
    root=Path(root);out=root/'reports/reranker-v3';freeze=load_json(out/'release-freeze.json')
    if any(digest((root/name).read_bytes())!=sha for name,sha in freeze['runtime_files'].items()):raise ValueError('Runtime changed since confirmation freeze')
    results={}
    for name,namespace,n in [('legacy','grounded-reserve-v2',300),('confirmation','confirmation-v3',600)]:
        manifest=load_json(root/'evaluation'/namespace/'manifest.json');data=load_json(root/'evaluation'/namespace/'final.json')
        if digest(manifest)!=freeze['dataset_manifest_sha256'][name] or digest(data)!=manifest['split_sha256']['final']:raise ValueError('Frozen benchmark changed')
        rows=load_json(out/(name+'-result.json'))['cases'];metrics=recount(data,rows)
        if metrics['samples']!=n:raise ValueError('Unexpected benchmark size')
        results[name]=metrics
    faith_inputs = load_json(root / 'local/confirmation-faithfulness-input.json')
    if digest(faith_inputs) != freeze['faithfulness_input_sha256']:
        raise ValueError('Frozen independent faithfulness input changed')
    faith = faithful_comparison(faith_inputs, load_json(out / 'confirmation-faithfulness-raw.json')['cases'], freeze['faithfulness_case_ids'])
    return {'allowed':all(threshold_passes(m) for m in results.values()) and faith['passed'],'threshold':'Both strict first-hit and document-set Recall@1 > 90%, on legacy regression and fresh-wording confirmation; paired independent faithfulness must not decline','results':results,'faithfulness':faith,'human_gold_review':'pending','source_exposure':'Confirmation uses new query wording on known, previously evaluated source families; not new-source or real-customer testing.'}
