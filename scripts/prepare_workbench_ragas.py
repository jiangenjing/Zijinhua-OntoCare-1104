"""Predeclared 12-query paired subset of repeat one; never choose by scores."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest
from ontocare.prompting import contract

cases=load_json(ROOT/'reports/grounded-eval/live-sampling.json')['cases'][:12]
docs={d['id']:d for d in load_json(ROOT/'data/knowledge.json')};rows=[]
for case in cases:
    for arm in ['before','after']:
        path=ROOT/'local/workbench-v4'/arm/'1'/(case['id'].replace(':','-')+'.json')
        if not path.exists():raise SystemExit('Fixed Ragas subset is not complete yet; no sample substitution.')
        row=load_json(path);reply=row['turns'][-1].get('reply',{});ids=[]
        for tool in reply.get('tools',[]):
            if tool['name']=='search_evidence':ids+=tool['result'].get('ids',[])
        ids+=reply.get('citation_ids',[]);ids=list(dict.fromkeys(i for i in ids if i in docs))
        contexts=[docs[i]['title']+'\nApplicable PN: '+', '.join(docs[i]['pns'])+'\n'+docs[i]['content'] for i in ids]
        prompt=contract(reply.get('prompt',{}).get('skill','troubleshooting'),ROOT)
        runtime='Customer-reported input (not independently verified): '+case['turns'][-1]+'\nAgent state: '+str(reply.get('state'))
        rows.append({'id':case['id']+':'+arm,'arm':arm,'question':case['turns'][-1],'response':reply.get('en',''),
                     'contexts':contexts,'faithfulness_contexts':contexts+[runtime,prompt['system'],prompt['skill_text']],
                     'reference':case['reference'],'model_status':reply.get('model_status'),
                     'runtime_id':reply.get('runtime',{}).get('id'),'trace_id':reply.get('trace_id')})
write_json(ROOT/'local/workbench-v4/ragas-input.json',{'scope':'fixed first 12 questions / 6 source families, repeat one, both arms; original full FAQ contexts plus actually supplied Skill/state for faithfulness; same-model evaluator; not production resolution','cases':rows,'input_sha256':digest(rows)})
print('Prepared',len(rows),'paired responses',flush=True)
