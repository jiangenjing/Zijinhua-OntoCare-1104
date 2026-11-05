"""Start the selected frozen customer release, without touching port5112."""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'local/customer-service-v2/experience548'
manifest=BASE/'deployment.json'
version=json.loads(manifest.read_text())['version'] if manifest.exists() else 'v1'
if version not in {'v1','v2','v4','v2-sop-map','v3-workflow'}:raise ValueError('Unrecognized frozen customer release')
release=BASE/version
if not release.exists():raise FileNotFoundError('Frozen customer release not prepared')
env={**os.environ,'PYTHONPATH':str(release),'ONTOCARE_LLM_CONFIG':str(ROOT/'local/deepseek-config.json')}
os.chdir(release)
os.execve(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),'-m','ontocare.cli','serve','--port','5120'],env)
