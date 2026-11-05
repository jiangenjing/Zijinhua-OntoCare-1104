"""Resume bounded, evidence-recorded experiments; never tune against a final set."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json
from ontocare.benchmark_dataset import generate_dataset

def step(result,script,*args):
    if not (ROOT/result).exists():
        subprocess.run([sys.executable,str(ROOT/script),*args],cwd=ROOT,check=True)

def main():
    generate_dataset(ROOT)
    out='reports/grounded-eval/'
    if not (ROOT/out/'selection-history.json').exists():
        from ontocare.grounded_eval import run_selection
        run_selection(ROOT)
    step(out+'translated-validation.json','scripts/evaluate_query_rewrite.py')
    step(out+'final-comparison.json','scripts/final_grounded_eval.py')
    first=load_json(ROOT/out/'final-comparison.json')
    if not first['target_passed']:
        step(out+'rerank-validation.json','scripts/test_evidence_rerank.py')
        step(out+'verify-validation.json','scripts/test_evidence_rerank.py','--verify')
        val=load_json(ROOT/out/'verify-validation.json')['metrics']['hit_at_1']
        parent=load_json(ROOT/out/'translated-validation.json')['metrics']['hit_at_1']
        if val>=parent:
            step('evaluation/grounded-reserve-v2/manifest.json','scripts/generate_reserve_eval.py')
            step(out+'reserve-comparison.json','scripts/reserve_grounded_eval.py')
    second=load_json(ROOT/out/'reserve-comparison.json') if (ROOT/out/'reserve-comparison.json').exists() else None
    met=bool(second['target_passed'] if second else first['target_passed'])
    state={'target':.90,'target_met':met,'status':'passed_frozen_test' if met else 'needs_independent_labels_or_new_tickets','first_final':first['candidate']['hit_at_1'],'new_source_final':second['candidate']['hit_at_1'] if second else None,'finals_never_reused_for_tuning':True,'reason':'Do not keep rerunning or changing frozen gold until a lucky score appears. Keep rejected candidates and both final outcomes. Current source-only gold has pending equivalent-answer review; new real tickets or independently adjudicated gold are needed for a further valid acceptance test.','parameter_training':False,'rlhf':False,'controlled_updates':['retrieval feature fusion','source-agnostic query translation prompt','evidence verification prompt','bounded output validation fixes']}
    write_json(ROOT/out/'workflow-state.json',state)
    print(state)
    return 0 if met else 2

if __name__=='__main__':sys.exit(main())
