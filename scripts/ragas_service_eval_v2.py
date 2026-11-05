"""Run actual Ragas metrics in the pinned isolated evaluation runtime."""
import argparse,asyncio,importlib.metadata,json,math
from pathlib import Path
import httpx
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.metrics.collections import Faithfulness,ContextPrecision,ContextRecall
ROOT=Path(__file__).resolve().parents[1];LOCAL=ROOT/'local/customer-service-v2';OUT=ROOT/'reports/customer-service-v2'

async def main(label,limit):
 cfg=json.loads((ROOT/'local/deepseek-config.json').read_text());usage=[]
 prior_path=OUT/f'ragas-{label}.json';prior=json.loads(prior_path.read_text()) if prior_path.exists() else None
 async def capture(response):
  try:
   await response.aread();body=response.json()
   if isinstance(body,dict) and body.get('usage'):usage.append({'model':body.get('model'),'usage':body['usage']})
  except Exception:pass
 http=httpx.AsyncClient(timeout=90,event_hooks={'response':[capture]})
 client=AsyncOpenAI(api_key=cfg['api_key'],base_url=cfg['base_url'],http_client=http,max_retries=1)
 model=cfg.get('text_model',cfg.get('model'))
 llm=llm_factory(model,client=client,temperature=0,max_tokens=8000,extra_body={'thinking':{'type':'disabled'}})
 scorers={'faithfulness':Faithfulness(llm=llm),'context_precision':ContextPrecision(llm=llm),'context_recall':ContextRecall(llm=llm)}
 corpus={d['id']:d for d in json.loads((ROOT/'data/knowledge.json').read_text())}
 files=sorted((LOCAL/'answers'/label).glob('*-r0.json'));selected=[]
 plan=LOCAL/'ragas-selected-ids.json'
 planned=json.loads(plan.read_text()) if plan.exists() else None
 for p in files:
  v=json.loads(p.read_text());r=v['turns'][-1].get('reply',{})
  if planned is not None:
   if v['id'] in planned:selected.append(v)
  elif v['kind']=='knowledge' and r.get('model_status')=='completed' and r.get('citations') and v['case'].get('reference'):selected.append(v)
 selected=selected[:limit]
 if not plan.exists():plan.write_text(json.dumps([v['id'] for v in selected]))
 results=[];semaphore=asyncio.Semaphore(2)
 async def score(row):
  dest=LOCAL/'ragas'/label/(row['id']+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
  previous=json.loads(dest.read_text()) if dest.exists() else None
  if previous and previous.get('context_boundary')=='all_retrieved_source_packets' and all(previous['metrics'].get(k) is not None for k in scorers):return previous
  r=row['turns'][-1]['reply']
  ids=list(dict.fromkeys([k for t in r['tools'] if t['name']=='search_evidence' for k in t['result'].get('ids',[])] + [c['id'] for c in r['citations']]))
  contexts=['Title: '+corpus[k]['title']+'\nApplicable PN: '+', '.join(corpus[k]['pns'])+'\nContent:\n'+corpus[k]['content'] for k in ids if k in corpus]
  out={'id':row['id'],'metrics':{},'errors':{},'source':'actual_ragas_0.4.3_collections','response_language':'en','context_boundary':'all_retrieved_source_packets','context_ids':ids}
  if previous:out['previous_attempt']=previous
  async with semaphore:
   for name,metric in scorers.items():
    if previous and previous.get('context_boundary')=='all_retrieved_source_packets' and previous['metrics'].get(name) is not None:
     out['metrics'][name]=previous['metrics'][name];continue
    try:
     args={'user_input':row['case']['question'],'retrieved_contexts':contexts}
     if name=='faithfulness':args['response']=r['en']
     else:args['reference']=row['case']['reference']
     result=await metric.ascore(**args);value=float(result.value)
     out['metrics'][name]=value if math.isfinite(value) else None
    except Exception as exc:out['metrics'][name]=None;out['errors'][name]=type(exc).__name__+':'+str(exc)[:160]
  dest.write_text(json.dumps(out,ensure_ascii=False,indent=2));print('ragas',label,row['id'],out['metrics'],flush=True);return out
 results=await asyncio.gather(*(score(r) for r in selected))
 metrics={name:{'n':sum(r['metrics'].get(name) is not None for r in results),'value':sum(r['metrics'][name] for r in results if r['metrics'].get(name) is not None)/sum(r['metrics'].get(name) is not None for r in results) if any(r['metrics'].get(name) is not None for r in results) else None} for name in scorers}
 result={'label':label,'package_version':importlib.metadata.version('ragas'),'api':'collections','sample_selection':'deterministic case-id order; completed answerable knowledge cases with citations; not overall population','sample_n':len(selected),'metrics':metrics,'composite':None,'composite_reason':'Ragas has separate metrics, no universal official aggregate; no invented composite','model':model,'judge_relation':'same model family in separate calls; no independent human quality endorsement','usage':usage or (prior or {}).get('usage',[]),'cache_reused':not usage,'cases':results}
 (OUT/f'ragas-{label}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));await client.close();print(json.dumps(metrics),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('label');p.add_argument('--limit',type=int,default=12);args=p.parse_args();asyncio.run(main(args.label,args.limit))
