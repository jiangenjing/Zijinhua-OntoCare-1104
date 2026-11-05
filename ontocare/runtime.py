"""Public, secret-free binding between a running service and its evaluation."""
from pathlib import Path

from .data import digest
from .ontology import active
from .provider import Provider


def describe(service, root):
    root = Path(root)
    files = {str(p.relative_to(Path(__file__).parent)): digest(p.read_bytes())
             for p in sorted(Path(__file__).parent.glob('*.py'))}
    prompts = {str(p.relative_to(root)): digest(p.read_bytes())
               for p in sorted((root / 'prompts').rglob('*.md'))}
    data = {name: digest((root / name).read_bytes()) for name in
            ['data/knowledge.json', 'data/products.json', 'data/business-schema.json']
            if (root / name).exists()}
    result = {'agent': type(service).__module__ + '.' + type(service).__name__,
              'retriever': type(service.retriever).__module__ + '.' + type(service.retriever).__name__,
              'ontology_version': active(root), 'code_sha256': digest(files),
              'prompt_sha256': digest(prompts), 'data_sha256': digest(data),
              'model': Provider().public_status(), 'scope': 'local text/mail; no actual refund or sending'}
    if hasattr(service.retriever, 'references'):
        result['reference_snapshot_sha256'] = service.retriever.references.sha256
    return {**result, 'id': digest(result)}
