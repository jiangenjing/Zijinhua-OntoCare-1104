"""Materialize the pre-reserved source families without exposing them to candidate selection."""
from pathlib import Path
import sys
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest
from ontocare.benchmark_dataset import generate_dataset,build_plan

source_plan=ROOT/'local/eval-v2/source-plan.json'
plan=load_json(source_plan) if source_plan.exists() else build_plan(ROOT)
reserved=[{**c,'split':'final'} for c in plan['reserve']]
assert not ({c['family_id'] for c in reserved}&{c['family_id'] for c in plan['cases']})
reserve_plan={**plan,'id':'grounded-reserve-v2','semantic_cases':len(reserved),'cases':reserved,'reserve':[],'reserve_families':0,'split_counts':{'development':0,'validation':0,'final':len(reserved)},'coverage_by_pn':dict(Counter(c['pn'] for c in reserved)),'qualification':'Fresh source-family holdout after v1 final failed at 88%; only five remaining model strata. Not representative of every product, not a replacement that erases the v1 result.'}
write_json(ROOT/'reports/grounded-eval/reserve-protocol.json',{'source_family_ids_sha256':digest(sorted(c['family_id'] for c in reserved)),'selection':'all 150 families reserved before initial experiments; no failures selected by outcome','previous_final_result_retained':True,'stop_rule':'one frozen v2 candidate evaluated once; no v2 final feedback to tuning','coverage':reserve_plan['coverage_by_pn']})
print(generate_dataset(ROOT,workers=3,plan_override=reserve_plan,namespace='grounded-reserve-v2'),flush=True)
