"""All real first emails: offline workflow regression, never a resolution score."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.agent import Agent
from ontocare.app import create_app
from ontocare.data import rows,write_json
from ontocare.evaluation import http_server,post

records=[]
with http_server(create_app(ROOT,Agent(ROOT))) as base:
    for t in rows('tickets',ROOT):
        reply=post(base,'/api/mail/draft',{'message':t['text'],'context':{'sku':t['sku'] or '', 'order_number':t['order_number'] or ''},'mode':'offline'})
        records.append({'ticket_id':t['id'],'trace_id':reply['trace_id'],'expected_pn':t['pn'],'actual_pn':reply['state']['pn'],'decision':reply['decision'],'checks':reply['checks'],'model_status':reply['model_status'],'latency_ms':reply['latency_ms'],'draft_sent':reply['draft']['sent']})
summary={'n':len(records),'scope':'All 63 seen first emails, actual local mail-draft API, offline-only process regression; no model quality, independent blind test or resolution labels.','all_hard_checks_passed':sum(all(c['passed'] for c in r['checks']) for r in records),'source_mapped_cases':sum(bool(r['expected_pn']) for r in records),'source_pn_matched':sum(bool(r['expected_pn']) and r['expected_pn']==r['actual_pn'] for r in records),'model_calls':0,'resolution_rate':None,'cases':records}
write_json(ROOT/'reports/grounded-eval/seen-ticket-regression.json',summary);print({k:v for k,v in summary.items() if k!='cases'})
