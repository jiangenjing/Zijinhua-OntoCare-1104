"""Repeat the UNCHANGED judge on identical saved replies; never rewrite old scores."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from ontocare.data import load_json, write_json, digest
from live_grounded_eval import judge, RUBRIC


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--repaired', action='store_true'); args = parser.parse_args()
    folder = ROOT / ('local/workbench-v5/action-fixed-replay/action-fixed' if args.repaired else 'local/workbench-v4/after')
    pool = [load_json(p) for p in folder.glob('*.json' if args.repaired else '*/*.json')]
    target = [r for r in pool if r['case']['family_id'] == 'qa-6c5ab718a89d']
    if len(target) != (2 if args.repaired else 6): raise ValueError('The predeclared reference-gap outputs must be included')
    others = [] if args.repaired else sorted([r for r in pool if r not in target], key=lambda r: digest([r['id'], r['repeat'], 'judge-stability-v1']))[:12]
    selected = target + others
    protocol = {'rubric_sha256': digest(RUBRIC), 'repeats': 3, 'selection': 'both repaired multifloor outputs, each repeated three times' if args.repaired else 'all six previously flagged multifloor executions plus twelve deterministic hash-selected other saved outputs',
                'frozen_rows_sha256': digest(selected), 'score_policy': 'Original five dimensions, >=8 and original hard gates unchanged. No majority-vote replacement. Disagreement is pending review, never an automatic pass.'}
    prefix = 'repaired-' if args.repaired else ''
    write_json(ROOT / 'reports/workbench-v5' / (prefix + 'judge-audit-protocol.json'), protocol)
    folder = ROOT / 'local/workbench-v5/judge-consistency'; folder.mkdir(parents=True, exist_ok=True)
    def one(row, repeat):
        key = digest([row, RUBRIC, repeat]); path = folder / (key + '.json')
        if path.exists(): return load_json(path)
        result = {'source_id': row['id'], 'source_repeat': row['repeat'], 'audit_repeat': repeat, 'input_sha256': digest(row), 'judge': judge(row)}
        write_json(path, result); return result
    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        for future in as_completed([executor.submit(one, row, repeat) for row in selected for repeat in range(1, 4)]):
            results.append(future.result())
            if len(results) % 12 == 0: print('judge consistency', len(results), '/', len(selected) * 3, flush=True)
    cases = []
    for row in selected:
        members = sorted([r for r in results if r['input_sha256'] == digest(row)], key=lambda r: r['audit_repeat'])
        scores = [r['judge'].get('total') for r in members]; passed = [r['judge'].get('passed') for r in members]
        complete = all(r['judge'].get('status') == 'completed' for r in members)
        stable = complete and len(set(passed)) == 1
        cases.append({'id': row['id'], 'source_repeat': row['repeat'], 'input_sha256': digest(row), 'original_passed': row['judge']['passed'],
                      'repeated_totals': scores, 'repeated_passed': passed, 'verdict_agrees': stable,
                      'status': 'stable_machine_verdict_not_human_confirmed' if stable else 'human_adjudication_pending', 'judgments': [r['judge'] for r in members]})
    report = {'protocol': protocol, 'cases': cases, 'complete': len(results) == len(selected) * 3,
              'same_model_bias': True, 'old_scores_modified': False,
              'agreement_rate': sum(c['verdict_agrees'] for c in cases) / len(cases),
              'pending_adjudication': sum(not c['verdict_agrees'] for c in cases)}
    write_json(ROOT / 'reports/workbench-v5' / (prefix + 'judge-consistency.json'), report)
    print({k: v for k, v in report.items() if k not in {'protocol', 'cases'}}, flush=True)


if __name__ == '__main__': main()
