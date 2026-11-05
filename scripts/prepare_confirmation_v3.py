"""Predeclare and freeze fresh wording; historical source exposure is explicitly disclosed."""
from pathlib import Path
import sys
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest
from ontocare.benchmark_dataset import build_plan,generate_dataset,normalize

plan=build_plan(ROOT)
specs=[{**c,'split':'final'} for c in plan['cases'] if c['split']=='final']+[{**c,'split':'final'} for c in plan['reserve']]
assert len(specs)==300 and len({c['family_id'] for c in specs})==300
seen=[]
for namespace in ['grounded-1200','grounded-reserve-v2']:
    for split in ['development','validation','final']:
        seen.extend(load_json(ROOT/'evaluation'/namespace/(split+'.json'))['cases'])
hashes=sorted({digest(normalize(q)) for c in seen for q in c['questions'].values()})
protocol={'id':'confirmation-v3','source_families':300,'query_forms':600,'source_exposure':'All source families have appeared in historical final/reserve retrieval evaluation. This is a fresh-query confirmation test on the known catalog, NOT a fresh-source or production-customer blind test.','training_exclusion':'No confirmation source family is used for fitting the seven global weights; fit only original development, validation for selection. Original final/reserve sets are now exposed regression gates.','generation':'Independent source-only new wording. No old queries, model rankings or model selection results provided to query writer. Exact repeated previous query wording is rejected without querying the retriever. Gold remains original exact-content same-PN references; no post-score widening.','acceptance':{'legacy_reserve_hit_at_1_gt':.90,'legacy_reserve_document_recall_at_1_gt':.90,'confirmation_hit_at_1_gt':.90,'confirmation_document_recall_at_1_gt':.90,'planned_n':600,'no_missing_cases':True,'one_frozen_confirmation_test':True},'failure_policy':'Keep results and remain local on failure. Do not resample a new confirmation set until a lucky score exceeds threshold.','human_gold_review':'pending'}
out=ROOT/'reports/reranker-v3';out.mkdir(exist_ok=True)
pp=out/'confirmation-protocol.json'
if pp.exists() and load_json(pp)!=protocol:raise ValueError('Predeclared protocol changed')
write_json(pp,protocol)
newplan={**plan,'id':'confirmation-v3','case_id_prefix':'v3-','cases':specs,'reserve':[],'semantic_cases':300,'reserve_families':0,'split_counts':{'development':0,'validation':0,'final':300},'coverage_by_pn':dict(Counter(c['pn'] for c in specs)),'excluded_question_hashes':hashes,'generation_instruction':' Independently write a new realistic wording of the customer issue. Cover the specific scope and requested conditions supported by the source. Do not reveal the answer or troubleshooting procedure in the question. Do not merely copy the title; neither old test questions nor retrieval rankings are provided.','source_exposure':protocol['source_exposure']}
print(generate_dataset(ROOT,workers=3,plan_override=newplan,namespace='confirmation-v3')['cases_sha256'],flush=True)
