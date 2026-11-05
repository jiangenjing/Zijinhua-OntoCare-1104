"""Same predeclared twelve queries and same evaluator; use actual expanded evidence."""
from pathlib import Path
import sys
import argparse
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from ontocare.data import load_json, write_json, digest
from ontocare.prompting import contract
from ontocare.references import ReferenceStore

parser = argparse.ArgumentParser(); parser.add_argument('--arm', choices=['reference','action','verified','action-fixed'], default='reference'); args = parser.parse_args()
cases = load_json(ROOT / 'reports/grounded-eval/live-sampling.json')['cases'][:12]
documents = {d['id']: d for d in load_json(ROOT / 'data/knowledge.json')}; rows = []
for case in cases:
    for arm, folder in [('parent', 'parent'), (args.arm, args.arm + '-candidate')]:
        run = 'reference' if arm == 'parent' else arm
        path = ROOT / 'local/workbench-v5' / (run + '-replay') / arm / (case['id'].replace(':', '-') + '.json')
        if not path.exists(): raise SystemExit('Fixed subset incomplete; no substitutions')
        row = load_json(path); reply = row['turns'][-1].get('reply', {}); ids = []
        for tool in reply.get('tools', []):
            if tool['name'] == 'search_evidence': ids.extend(tool['result'].get('ids', []))
        ids = list(dict.fromkeys(ids + reply.get('citation_ids', [])))
        actual = [documents[i] for i in ids if i in documents]
        root = ROOT / 'local/workbench-v5' / folder
        actual = ReferenceStore(root).attach(actual, reply['state']['pn']) if arm != 'parent' else actual
        contexts = [d['title'] + '\nApplicable PN: ' + ', '.join(d['pns']) + '\n' + d['content'] for d in actual]
        contexts += [ref['title'] + '\nApplicable PN: ' + ', '.join(ref['pns']) + '\nURL: ' + ref['url'] + '\n' + ref['text'] for d in actual for ref in d.get('references', [])]
        prompt = contract(reply.get('prompt', {}).get('skill', 'troubleshooting'), root)
        state = 'Customer-reported input (not independently verified): ' + case['turns'][-1] + '\nAgent state: ' + str(reply.get('state'))
        rows.append({'id': case['id'] + ':' + arm, 'arm': arm, 'question': case['turns'][-1], 'response': reply.get('en', ''),
                     'contexts': contexts, 'faithfulness_contexts': contexts + [state, prompt['system'], prompt['skill_text']],
                     'reference': case['reference'], 'model_status': reply.get('model_status'), 'runtime_id': reply['runtime']['id'], 'trace_id': reply['trace_id']})
write_json(ROOT / 'local/workbench-v5' / (args.arm + '-ragas-input.json'), {'cases': rows, 'input_sha256': digest(rows),
           'scope': 'Same first twelve predeclared questions and same Ragas evaluator; original cells plus actually supplied scoped article snapshots; seen regression, not independent confirmation.'})
print('prepared', len(rows), flush=True)
