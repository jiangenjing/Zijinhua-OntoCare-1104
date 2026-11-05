"""Historical reserve is explicitly exposed regression, never relabelled as blind."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json
from ontocare.grounded_eval import Experiment
from train_reranker_v3 import prepare,evaluate

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--model',choices=['english','multilingual'],default='english');ap.add_argument('--tail',type=int);a=ap.parse_args()
    out=ROOT/'reports/reranker-v3';local=ROOT/'local/reranker-v3'
    if a.tail:
        trials=[x for x in load_json(out/'tail-1e-05-selection.json')['trials'] if f'epoch{a.tail}-' in x['name']];cfg=trials[0]['config'];name=f'tail-1e-05-epoch{a.tail}'
    else:
        trials=load_json(out/(a.model+'-selection.json'))['trials'];cfg=load_json(local/('english-model.json' if a.model=='english' else 'model.json'));name=a.model
    # Reuse the source-agnostic translations actually produced by the prior runtime.
    rows=load_json(ROOT/'reports/grounded-eval/candidate-reserve.json')['cases'];rows=[{**r,'original_query':r['query'],'query':r['search_query'],'split':'exposed_regression'} for r in rows]
    exp=Experiment(ROOT);features=prepare(exp,'legacy',name,cfg,rows);history=[]
    for t in trials:
        result=evaluate(features,t['weights']);result['scope']='exposed historical regression, not blind';history.append({'name':t['name'],'metrics':result['metrics']})
        for row,original in zip(result['cases'],rows):row['original_query']=original['original_query']
        write_json(out/(t['name']+'-legacy.json'),result)
    write_json(out/(name+'-legacy-summary.json'),history);print(history,flush=True)
if __name__=='__main__':main()
