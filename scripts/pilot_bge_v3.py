"""Development-only probe of the pinned multilingual BGE pair reranker."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ontocare.data import load_json, write_json, digest
from ontocare.grounded_eval import Experiment
from train_reranker_v3 import prepare, evaluate


def main():
    rows = load_json(ROOT / 'reports/grounded-eval/translated-development.json')['cases']
    families = sorted({r['family_id'] for r in rows}, key=digest)[:30]
    rows = [r for r in rows if r['family_id'] in families]
    config = load_json(ROOT / 'local/reranker-v3/bge-model.json')
    started = time.perf_counter()
    features = prepare(Experiment(ROOT), 'development-pilot', 'bge', config, rows)
    variants = {'title': [0, 0, 0, 1, 0, 0, 0],
                'body': [0, 0, 0, 0, 1, 0, 0],
                'mixed': [.1, .1, .05, .35, .3, 0, .1]}
    result = {'scope': 'development pilot only; no validation, historical final or confirmation cases',
              'model': config['model'], 'revision': config['revision'],
              'elapsed_s': time.perf_counter() - started,
              'variants': {name: evaluate(features, weights) for name, weights in variants.items()}}
    write_json(ROOT / 'reports/reranker-v3/bge-pilot.json', result)
    print({name: r['metrics'] for name, r in result['variants'].items()}, flush=True)


if __name__ == '__main__':
    main()
