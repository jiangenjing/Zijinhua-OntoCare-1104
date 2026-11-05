"""Verify actual MCP transport and optionally customer-facing live model requests."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result):
    return result.structuredContent or json.loads(result.content[0].text)


async def mcp_checks():
    params=StdioServerParameters(command=str(ROOT/'.venv/bin/python'),args=['-m','ontocare.service_mcp'],cwd=str(ROOT),env={**os.environ,'PYTHONPATH':str(ROOT),'ONTOCARE_WORKSPACE':str(ROOT),'ONTOCARE_MCP_ALLOW_WRITES':'0'})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize();tools=(await client.list_tools()).tools
            (ROOT/'web/service-tools.json').write_text(json.dumps({'tools':[t.model_dump(mode='json') for t in tools]},ensure_ascii=False,indent=2)+'\n')
            order=await client.call_tool('lookup_order',{'order_number':'Anker008'})
            assert not order.isError and payload(order)['order']['properties']['status']=='PARTIALLY_SHIPPED'
            decision=await client.call_tool('evaluate_service_decision',{'facts':{'intent':'shipping','delivery_status':'DELIVERED','customer_received':False}})
            assert not decision.isError and payload(decision)['outcome']=='DELIVERED_REQUIRES_REVIEW'
            write=await client.call_tool('submit_for_review',{'ticket_id':'ticket-002','reason':'只读联通检查','idempotency_key':'read-only-check'})
            assert payload(write)['status']=='WRITE_DISABLED'
            assert len(tools)==22
            return {'transport':'official_sdk_stdio','tools':len(tools),'order_items_and_shipments':True,'decision_recommendation_only':not payload(decision)['can_execute'],'write_disabled':True}


def live_checks(base):
    results=[]
    cases=[('shipping',{'message':'Anker008 的主机和配件都发货了吗？请分别说明。'}),('dealer',{'message':'这家卖家可以直接保修吗？','context':{'country':'US','seller':'best buy'}}),('troubleshooting',{'message':'我的 E25 报错误码3212，应该先检查什么？'})]
    for name,body in cases:
        request=urllib.request.Request(base+'/api/chat',data=json.dumps({**body,'mode':'live'}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=180) as r:result=json.load(r)
        results.append({'case':name,'model_status':result['model_status'],'model_calls':result['model_calls'],'trace_id':result['trace_id'],'decision':result['decision'],'tools':[t['name'] for t in result['tools']],'zh':result['zh'],'citations':[c['id'] for c in result.get('citations',[])],'service_decision':result.get('business_context',{}).get('service_decision')})
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--base',default='http://127.0.0.1:5112');args=parser.parse_args()
    result={'mcp':asyncio.run(mcp_checks())}
    if args.live:result['live_customer_requests']=live_checks(args.base)
    (ROOT/'reports/final-service-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'mcp':result['mcp'],'live_statuses':[{k:r[k] for k in ['case','model_status','decision','tools']} for r in result.get('live_customer_requests',[])]},ensure_ascii=False))
