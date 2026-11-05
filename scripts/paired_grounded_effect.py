"""Family-clustered paired bootstrap; bilingual forms are not independent trials."""
from collections import defaultdict
from pathlib import Path
import random
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json

results={}
for label,left,right in [('initial_final','baseline-final.json','candidate-final.json'),('reserve_final','baseline-reserve.json','candidate-reserve.json')]:
    a={r['id']:r for r in load_json(ROOT/'reports/grounded-eval'/left)['cases']};b=load_json(ROOT/'reports/grounded-eval'/right)['cases'];groups=defaultdict(list);gain=loss=0
    for r in b:
        before=a[r['id']]['scores']['hit_at_1'];after=r['scores']['hit_at_1'];groups[r['family_id']].append(after-before)
        gain+=after>before;loss+=after<before
    means=[sum(v)/len(v) for v in groups.values()];rng=random.Random(20261103)
    draws=sorted(sum(rng.choices(means,k=len(means)))/len(means) for _ in range(5000))
    results[label]={'query_n':len(b),'source_families':len(means),'paired_delta':sum(means)/len(means),'delta_95_family_bootstrap':[draws[125],draws[4874]],'improved_queries':gain,'regressed_queries':loss,'scope':'Same frozen queries and source labels; family is the resampling unit. Supports benchmark improvement, not real-world resolution causality.'}
write_json(ROOT/'reports/grounded-eval/paired-effect.json',results);print(results)
