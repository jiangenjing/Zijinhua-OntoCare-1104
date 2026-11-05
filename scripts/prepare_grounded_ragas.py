"""Use a preselected paired subset, with the actual evidence delivered to the Agent."""
from pathlib import Path
import json
import sys
import argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ontocare.prompting import contract
parser=argparse.ArgumentParser();parser.add_argument('--release',action='store_true');args=parser.parse_args()
cases=json.load(open(ROOT/'reports/grounded-eval/live-sampling.json'))['cases'][:12]
docs={d['id']:d for d in json.load(open(ROOT/'data/knowledge.json'))}
rows=[]
for case in cases:
    for arm in (['release'] if args.release else ['baseline','candidate']):
        path=ROOT/'local/eval-v2/live'/arm/(case['id'].replace(':','-')+'.json')
        result=json.load(open(path));reply=result['turns'][-1]['reply'];ids=[]
        for tool in reply['tools']:
            if tool['name']=='search_evidence':ids+=tool['result'].get('ids',[])
        ids+=list(reply.get('citation_ids',[]))
        ids+=reply.get('retrieval',{}).get('evidence_ids',[]) if reply.get('retrieval') else []
        ids=list(dict.fromkeys(k for k in ids if k in docs))
        contexts=[docs[k]['title']+'\nApplicable PN: '+', '.join(docs[k]['pns'])+'\n'+docs[k]['content'] for k in ids]
        response_contract=contract(reply['prompt']['skill'],ROOT)
        runtime='Customer-reported input (not independently verified): '+case['turns'][-1]+'\nAgent state: '+json.dumps(reply['state'],ensure_ascii=False)
        grounded=contexts+[runtime,response_contract['system'],response_contract['skill_text']]
        rows.append({'id':case['id']+':'+arm,'arm':arm,'question':case['turns'][-1],'response':reply['en'],'contexts':contexts,'faithfulness_contexts':grounded,'context_ids':ids,'reference':case['reference'],'model_status':reply['model_status'],'trace_id':reply['trace_id']})
out=ROOT/'local/eval-v2'/('ragas-release-input.json' if args.release else 'ragas-grounded-input.json');out.write_text(json.dumps({'sampling':'first six source families of the predeclared live sample; both query languages, paired arms, no selection by observed scores','context_correction':'Retain original FAQ title, applicability metadata and graph evidence actually seen by the Agent. Faithfulness additionally receives the actual customer input, state, system/Skill permission contract; context precision/recall use retrieved FAQ only. No new retrieval, expected answers or posthoc evidence added to contexts. Body-only diagnostic is retained separately.','cases':rows},ensure_ascii=False,indent=2))
print(out,len(rows))
