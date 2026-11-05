"""Source-access intervention, fixed development/validation only."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os
import sys
import argparse
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
os.environ.setdefault('ONTOCARE_LLM_CONFIG', str(ROOT / 'local/deepseek-config.json'))
from ontocare.reference_ranking import Retriever
from ontocare.data import load_json, write_json, digest
from ontocare.grounded_eval import read_split
from ontocare.benchmark_metrics import retrieval_scores, summarize_retrieval

parser = argparse.ArgumentParser(); parser.add_argument('--legacy-only', action='store_true'); args = parser.parse_args()
r = Retriever(ROOT); r._encoder(r.vector_meta['revision'])
protocol = {'hypothesis': 'A verifier that sees only a referral link cannot judge body support. Supply approved scoped article text to ranking too, while preserving original quotes/IDs and the existing verifier prompt.',
            'reference_sha256': r.references.sha256, 'confirmation_read': False, 'gold_and_scoring_changed': False}
write_json(ROOT / 'reports/workbench-v5/reference-ranking-protocol.json', protocol)
for split in (['legacy'] if args.legacy_only else ['development', 'validation']):
    cases = load_json(ROOT / 'evaluation/grounded-reserve-v2/final.json')['cases'] if split == 'legacy' else read_split(split)
    if split == 'development': cases = sorted(cases, key=lambda c: digest(c['family_id']))[:30]
    def one(case, lang):
        query = case['questions'][lang]; key = case['id'] + ':' + lang
        path = ROOT / 'local/workbench-v5/reference-ranking' / split / (digest([key, protocol]) + '.json')
        if path.exists(): return load_json(path)
        result = r.search(query, case['pn'], allow_rewrite=True, ranking_profile='body_hybrid'); ids = [d['id'] for d in result['documents']]
        row = {'id': key, 'family_id': case['family_id'], 'language': lang, 'pn': case['pn'], 'original_query': query,
               'gold_ids': case['gold_ids'], 'ranked_ids': ids, 'scores': retrieval_scores(case['gold_ids'], ids), 'evidence_rerank': result.get('evidence_rerank')}
        write_json(path, row); return row
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(one, case, lang) for case in cases for lang in case['questions']]):
            rows.append(future.result())
            if len(rows) % 30 == 0: print('reference ranking', split, len(rows), '/', len(cases) * 2, flush=True)
    summary = {'protocol': protocol, 'metrics': summarize_retrieval(rows), 'cases': sorted(rows, key=lambda x: x['id'])}
    write_json(ROOT / 'reports/workbench-v5' / ('reference-ranking-' + split + '.json'), summary); print(summary['metrics'], flush=True)
