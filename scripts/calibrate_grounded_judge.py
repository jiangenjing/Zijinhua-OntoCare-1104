"""Obvious positive/negative controls; calibration is not human validation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from live_grounded_eval import judge
from ontocare.data import write_json

question='I do not know which eufy model I own. Can you give me model-specific repair steps?'
base={'id':'control','case':{'turns':[question],'reference':'Product must be identified before giving model-specific troubleshooting steps. Ask for the PN on the product label.','expected_decision':'clarify_product'}}
correct={'zh':'请先提供产品标签上的 PN 型号，这样才能选择适用的排障资料。','en':'Please provide the PN model on the product label so I can select applicable troubleshooting evidence.','decision':'clarify_product'}
bad=[{'zh':'您的机器就是 T2353，请拆开电池。','en':'Your device is definitely T2353. Open the battery compartment.','decision':'answer'}, {'zh':'退款已经批准，钱已退回银行卡。','en':'Your refund has been approved and returned to your bank card.','decision':'clarify_product'}, {'zh':'不用型号，所有 eufy 产品都终身保修，可以免费更换。','en':'No model is needed. All eufy products have a lifetime warranty and a free replacement.','decision':'clarify_product'}]
def one(spec):
    key,reply,expected=spec
    row={**base,'turns':[{'question':question,'http_ms':0,'reply':{**reply,'model_status':'completed','checks':[{'name':'fixture','passed':True}],'citations':[]}}]}
    return {'id':key,'expected_pass':expected,'judge':judge(row)}
specs=[('positive-clarification',correct,True)]+[(f'negative-{i+1}',r,False) for i,r in enumerate(bad)]
with ThreadPoolExecutor(max_workers=2) as p:rows=list(p.map(one,specs))
write_json(ROOT/'reports/grounded-eval/judge-calibration.json',{'controls':rows,'agreement':sum(r['expected_pass']==r['judge'].get('passed') for r in rows)/len(rows),'n':len(rows),'scope':'Known constructed obvious controls. Same-model independent invocation; not calibrated against a human-labeled production gold set.'})
