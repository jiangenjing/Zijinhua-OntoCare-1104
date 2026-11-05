"""Private local line protocol used by isolated Ragas environment; no HTTP endpoint."""
import json
from pathlib import Path
import sys
import os
os.environ['TOKENIZERS_PARALLELISM']='false'
import torch
torch.set_num_threads(2)
from sentence_transformers import SentenceTransformer
root=Path(__file__).resolve().parents[1]
revision=json.load(open(root/'local/vectors.json'))['revision']
model=SentenceTransformer('intfloat/multilingual-e5-small',revision=revision,device='cpu',local_files_only=True)
for line in sys.stdin:
    try:
        texts=json.loads(line)['texts'];vectors=model.encode(['query: '+t for t in texts],normalize_embeddings=True,show_progress_bar=False).tolist()
        print(json.dumps({'vectors':vectors}),flush=True)
    except Exception as exc:print(json.dumps({'error':type(exc).__name__}),flush=True)
