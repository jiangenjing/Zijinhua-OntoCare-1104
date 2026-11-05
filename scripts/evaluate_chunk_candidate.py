"""Fit global weights on development only; fixed validation, no final queries read."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
os.environ.setdefault('ONTOCARE_LLM_CONFIG', str(ROOT / 'local/deepseek-config.json'))
from ontocare.chunk_retrieval import Retriever
from ontocare.data import load_json, write_json, digest
from ontocare.grounded_eval import read_split
from ontocare.benchmark_metrics import retrieval_scores, summarize_retrieval


def main():
    r = Retriever(ROOT); r._encoder(r.vector_meta['revision']); r.prepare_chunks()
    development = read_split('development'); validation = read_split('validation')
    out = ROOT / 'reports/workbench-v5'; local = ROOT / 'local/workbench-v5/chunk'; local.mkdir(parents=True, exist_ok=True)
    protocol = {'hypothesis': '80-word source passages with 48-word stride reduce evidence dilution versus 200-word windows. Only four global nonnegative weights are fitted, no query-answer lookup.',
                'features': ['title', 'body', 'lexical', 'chunk'], 'grid': 'simplex at .1 increments', 'selection': 'maximum development document-set Recall@1, closest to parent on ties',
                'development_sha256': digest(development), 'validation_sha256': digest(validation), 'confirmation_read': False,
                'original_knowledge_sha256': digest(load_json(ROOT / 'data/knowledge.json')), 'references_sha256': r.references.sha256,
                'passage_sha256': load_json(ROOT / 'local/fine-source-passages.json')['sha256']}
    write_json(out / 'chunk-protocol.json', protocol)
    training = []
    r.feature_packet(development[0]['questions']['en'], development[0]['pn'])
    def training_features(case, lang):
        query = case['questions'][lang]; path = local / ('features-' + digest([query, case['pn'], protocol['passage_sha256']]) + '.npz')
        if path.exists():
            saved = np.load(path, allow_pickle=False); matrix, eligible = saved['matrix'], saved['eligible']
        else:
            features, _ = r.feature_packet(query, case['pn']); eligible = np.array(features['eligible'])
            matrix = np.stack([features[k][eligible] for k in protocol['features']], axis=1)
            np.savez_compressed(path, matrix=matrix, eligible=eligible)
        return matrix, eligible, set(case['gold_ids'])
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(training_features, case, lang) for case in development for lang in case['questions']]):
            training.append(future.result())
            if len(training) % 60 == 0: print('development features', len(training), '/', len(development) * 2, flush=True)
    prior = np.array([.35, .50, .15, 0.]); best = None
    for a in range(11):
        for b in range(11 - a):
            for c in range(11 - a - b):
                weights = np.array([a, b, c, 10 - a - b - c]) / 10
                hits = []; recalls = []
                for matrix, eligible, gold in training:
                    scores = matrix @ weights; winner = min(range(len(scores)), key=lambda j: (-scores[j], r.docs[eligible[j]]['id']))
                    hit = r.docs[eligible[winner]]['id'] in gold; hits.append(hit); recalls.append(int(hit) / len(gold))
                key = (float(np.mean(recalls)), -float(np.sum((weights - prior) ** 2)))
                if best is None or key > best[0]: best = (key, weights, float(np.mean(hits)))
    r.weights = dict(zip(protocol['features'], best[1].tolist()))
    write_json(out / 'chunk-fit.json', {'weights': r.weights, 'development_hit_at_1': best[2], 'development_recall_at_1': best[0][0], 'queries': len(training), 'protocol_sha256': digest(protocol)})
    print('fit', r.weights, best[2], best[0][0], flush=True)
    def one(case, lang):
        query = case['questions'][lang]; key = case['id'] + ':' + lang
        path = local / (digest([key, r.weights, protocol]) + '.json')
        if path.exists(): return load_json(path)
        result = r.search(query, case['pn'], allow_rewrite=True, ranking_profile='body_hybrid')
        ids = [d['id'] for d in result['documents']]
        row = {'id': key, 'family_id': case['family_id'], 'language': lang, 'pn': case['pn'], 'original_query': query,
               'gold_ids': case['gold_ids'], 'ranked_ids': ids, 'scores': retrieval_scores(case['gold_ids'], ids),
               'evidence_rerank': result.get('evidence_rerank'), 'retrieval_calls': result['query_rewrite'].get('model_calls', [])}
        write_json(path, row); return row
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(one, case, lang) for case in validation for lang in case['questions']]):
            rows.append(future.result())
            if len(rows) % 30 == 0: print('fine passage validation', len(rows), '/', len(validation) * 2, flush=True)
    result = {'protocol': protocol, 'weights': r.weights, 'metrics': summarize_retrieval(rows), 'cases': sorted(rows, key=lambda r: r['id'])}
    write_json(out / 'chunk-validation.json', result); print(result['metrics'], flush=True)


if __name__ == '__main__': main()
