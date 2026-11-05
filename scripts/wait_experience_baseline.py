import json,time,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
while True:
 try:
  p=json.loads((R/'reports/customer-service-v2/experience548-progress.json').read_text());a=p['runs'];labels=['experience-core-control548','experience-v1-stream548']
  if all(a[k]['unique_cases']==548 and a[k].get('judged')==548 for k in labels):break
 except (OSError,ValueError,KeyError):pass
 time.sleep(15)
subprocess.run([str(R/'.venv/bin/python'),str(R/'scripts/analyze_experience548.py')],cwd=R,check=True)
print('BASELINE DIAGNOSED; READY FOR CANDIDATE',flush=True)
