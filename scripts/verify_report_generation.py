"""Actual stdio MCP -> ontology report -> model -> archived evidence integration."""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


def unpack(result):
    if result.isError:raise RuntimeError('MCP tool returned an error')
    return result.structuredContent or json.loads(result.content[0].text)


async def verify():
    params=StdioServerParameters(command=str(ROOT/'.venv/bin/python'),args=['-m','ontocare.service_mcp'],cwd=str(ROOT),env={**os.environ,'PYTHONPATH':str(ROOT),'ONTOCARE_WORKSPACE':str(ROOT),'ONTOCARE_MCP_ALLOW_WRITES':'0'})
    async with stdio_client(params) as (r,w):
        async with ClientSession(r,w) as s:
            await s.initialize()
            tools=(await s.list_tools()).tools
            (ROOT/'web/service-tools.json').write_text(json.dumps({'tools':[t.model_dump(mode='json') for t in tools]},ensure_ascii=False,indent=2)+'\n')
            catalog=unpack(await s.call_tool('list_report_templates',{}))
            result={'time':datetime.now().astimezone().isoformat(),'transport':'official_sdk_stdio','mcp_tools':len(tools),'business_writes_enabled':False,'reports':[]}
            semaphore=asyncio.Semaphore(2)
            async def one(template):
                async with semaphore:
                    receipt=unpack(await s.call_tool('generate_report',{'template_id':template['id'],'focus':'请分析本体资料支持的经营决策与下一步验证，明确样例、名录和数据缺口的边界。','mode':'live'}))
                    report=unpack(await s.call_tool('get_report',{'report_id':receipt['id']}))
                    evidence=unpack(await s.call_tool('get_report_evidence',{'report_id':receipt['id'],'evidence_id':'items'}))
                    p=report['snapshot']
                    checks={'live_completed':report['generation_status']=='completed','four_sections':len(report['narrative']['sections'])==4,'item_flow_conserves_count':sum(x['count'] for x in p['charts']['item_flow'])==24,'source_drilldown_matches':evidence['value']==24 and len(evidence['source_ids'])==24,'frozen_lineage':bool(p.get('lineage',{}).get('graph_sha256')),'no_business_write':receipt['business_data_modified'] is False}
                    row={'template':template['id'],'report_id':report['id'],'status':report['generation_status'],'checks':checks,'passed':all(checks.values()),'model':report['model'],'model_calls':report['model_calls'],'validation_checks':report.get('validation_checks',[]),'snapshot':p['fingerprint'],'summary':report['narrative']['summary'],'tools':['generate_report','get_report','get_report_evidence']}
                    result['reports'].append(row)
                    (ROOT/'reports/report-generation-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                    print(json.dumps({'template':row['template'],'status':row['status'],'passed':row['passed'],'id':row['report_id']},ensure_ascii=False),flush=True)
            await asyncio.gather(*(one(t) for t in catalog['templates']))
            graph=unpack(await s.call_tool('get_instance_topology',{'instance_id':'order:Anker008','depth':2,'direction':'outgoing'}))
            result['ontology_drilldown']={'instance_id':'order:Anker008','nodes':len(graph['nodes']),'links':len(graph['links']),'has_shipment':any(n['type']=='Shipment' for n in graph['nodes'])}
            result['all_passed']=all(c['passed'] for c in result['reports']) and result['ontology_drilldown']['has_shipment']
            (ROOT/'reports/report-generation-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            return result['all_passed']


if __name__=='__main__':
    raise SystemExit(0 if asyncio.run(verify()) else 1)
