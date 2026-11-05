"""Explicit retrieval metrics, family-level intervals and latency units."""
from collections import defaultdict
import math
import random

import numpy as np


def retrieval_scores(gold,ranked):
    gold=set(gold);hits=[int(k in gold) for k in ranked]
    return {'hit_at_1':float(bool(hits and hits[0])),'hit_at_3':float(any(hits[:3])),'hit_at_5':float(any(hits[:5])),
            'recall_at_1':len(set(ranked[:1])&gold)/len(gold) if gold else None,
            'recall_at_3':len(set(ranked[:3])&gold)/len(gold) if gold else None,
            'recall_at_5':len(set(ranked[:5])&gold)/len(gold) if gold else None,
            'mrr':next((1/(i+1) for i,h in enumerate(hits) if h),0.)}


def summarize_retrieval(cases):
    if not cases:return {'samples':0}
    names=['hit_at_1','hit_at_3','hit_at_5','recall_at_1','recall_at_3','recall_at_5','mrr']
    result={'samples':len(cases),'source_families':len({c['family_id'] for c in cases}),**{k:float(np.mean([c['scores'][k] for c in cases])) for k in names}}
    grouped=defaultdict(list)
    for c in cases:grouped[c['family_id']].append(c['scores']['hit_at_1'])
    family=[sum(v)/len(v) for v in grouped.values()];rng=random.Random(20261103)
    boot=sorted(sum(rng.choices(family,k=len(family)))/len(family) for _ in range(2000))
    result['family_bootstrap_hit_at_1_95_interval']=[boot[50],boot[1949]]
    result['by_language']={lang:{k:float(np.mean([c['scores'][k] for c in cases if c['language']==lang])) for k in names} for lang in sorted({c['language'] for c in cases})}
    result['definition']='hit@1 is at least one accepted relevant article in the first result; true set recall@1 is separately reported when several gold articles are valid'
    return result


def latency(values):
    clean=[v for v in values if isinstance(v,(float,int)) and math.isfinite(v)]
    return {'samples':len(clean),'mean_ms':float(np.mean(clean)) if clean else None,'p50_ms':float(np.percentile(clean,50)) if clean else None,'p99_ms':float(np.percentile(clean,99)) if clean else None,'p99_note':'descriptive percentile; unstable for small samples'}
