"""A second, source-agnostic retrieval candidate; validation never enters proposal input."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import digest,load_json,write_json
from ontocare.grounded_eval import Experiment,read_split
from ontocare.query_rewrite import translate_batch,PROMPT


def rewrite(cases):
    items=[{'id':c['id'],'query':c['questions']['zh']} for c in cases]
    directory=ROOT/'local/eval-v2/translated';directory.mkdir(exist_ok=True)
    def batch(rows):
        path=directory/(digest([PROMPT,rows])[:24]+'.json')
        if path.exists():return load_json(path)
        result=translate_batch(rows);write_json(path,result);return result
    translated={};calls=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(batch,items[i:i+12]) for i in range(0,len(items),12)]):
            r=future.result();translated.update(r['queries']);calls+=r['calls'];print('rewritten',len(translated),'of',len(items),flush=True)
    result=deepcopy(cases)
    for c in result:c['questions']['zh']=translated[c['id']]
    return result,calls


if __name__=='__main__':
    out=ROOT/'reports/grounded-eval';exp=Experiment(ROOT);history=load_json(out/'selection-history.json')
    for split in ['development','validation']:
        cases=read_split(split);changed,calls=rewrite(cases)
        tested=exp.evaluate(changed,'translated_body_hybrid',{'title':.35,'body':.50,'lexical':.15})
        tested['translation_model_calls']=calls;tested['translation_prompt_sha256']=digest(PROMPT)
        # Keep original question text in the audit, alongside the translated retrieval query.
        original={c['id']+':'+lang:q for c in cases for lang,q in c['questions'].items()}
        for row in tested['cases']:row['original_query']=original[row['id']]
        write_json(out/('translated-'+split+'.json'),tested)
        print(json.dumps({'split':split,'metrics':tested['metrics']},ensure_ascii=False),flush=True)
    dev=load_json(out/'translated-development.json');val=load_json(out/'translated-validation.json')
    candidate={'candidate':'translated_body_hybrid','weights':dev['weights'],'development':dev['metrics'],'validation':val['metrics'],'translation_prompt_sha256':digest(PROMPT),'accepted':val['metrics']['hit_at_1']>history['selected']['validation']['hit_at_1'],'reason':'source-agnostic Chinese→English query rewrite; no labels or source text in rewrite input; original scope remains binding'}
    history['rounds'].append(candidate)
    if candidate['accepted']:history['selected']={'profile':candidate['candidate'],'weights':candidate['weights'],'development':dev['metrics'],'validation':val['metrics'],'query_rewrite':True,'translation_prompt_sha256':digest(PROMPT)}
    write_json(out/'selection-history.json',history)
