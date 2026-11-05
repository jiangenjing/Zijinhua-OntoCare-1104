"""Candidate: finer source passages, fitted global fusion, unchanged evidence verifier."""
from pathlib import Path
import re
from threading import RLock
import numpy as np
from .data import digest, load_json, write_json
from .grounded_retrieval import Retriever as HybridRetriever
from .reference_agent import ReferenceRetriever
from .evidence_rerank import rerank, VERIFY_PROMPT


class Retriever(ReferenceRetriever):
    def __init__(self, root):
        super().__init__(root); self.chunk_lock = RLock(); self.chunk_vectors = None
        self.weights = {'title': .25, 'body': .25, 'lexical': .10, 'chunk': .40}

    def prepare_chunks(self):
        if self.chunk_vectors is not None: return
        texts = []; parents = []; scopes = []
        for i, doc in enumerate(self.docs):
            bodies = [(doc['content'], doc['pns'])]
            for pn in doc['pns']:
                for ref in self.references.attach([doc], pn)[0]['references']:
                    bodies.append((ref['text'], [pn]))
            seen = set()
            for body, pns in bodies:
                words = re.sub(r'https?://\S+', ' ', body).split()
                for start in range(0, max(1, len(words)), 48):
                    text = doc['title'] + '\n' + ' '.join(words[start:start + 80])
                    key = digest([text, pns])
                    if key in seen: continue
                    seen.add(key); texts.append('passage: ' + text); parents.append(i); scopes.append(pns)
        stamp = digest([texts, scopes, self.vector_meta['revision']])
        path = Path(self.root) / 'local/fine-source-passages.npz'; meta = path.with_suffix('.json')
        with self.chunk_lock:
            if path.exists() and meta.exists() and load_json(meta).get('sha256') == stamp:
                self.chunk_vectors = np.load(path, allow_pickle=False)['vectors']
            else:
                self.chunk_vectors = self._encoder(self.vector_meta['revision']).encode(texts, batch_size=48, normalize_embeddings=True, show_progress_bar=False)
                np.savez_compressed(path, vectors=self.chunk_vectors); write_json(meta, {'sha256': stamp, 'passages': len(texts)})
            self.chunk_parents = np.array(parents); self.chunk_scopes = scopes

    def feature_packet(self, query, pn, error_code=None, allow_rewrite=True):
        self.prepare_chunks()
        result = HybridRetriever.search(self, query, pn, error_code, 10000, True, allow_rewrite, 'body_hybrid')
        pivot = result['search_query']; features = self.grounded_index.features(pivot, pn, error_code)
        similarity = self.chunk_vectors @ self.query_vectors[pivot]
        allowed = np.array([pn in pns for pns in self.chunk_scopes])
        chunk = np.full(len(self.docs), -1.)
        np.maximum.at(chunk, self.chunk_parents[allowed], similarity[allowed])
        return {**features, 'chunk': chunk}, result

    def search(self, query, pn=None, error_code=None, limit=6, use_scope=True,
               allow_rewrite=False, ranking_profile=None):
        if not pn or not use_scope or not allow_rewrite:
            return super().search(query, pn, error_code, limit, use_scope, allow_rewrite, ranking_profile)
        features, result = self.feature_packet(query, pn, error_code, allow_rewrite)
        score = sum(self.weights[k] * features[k] for k in self.weights)
        indices = sorted(features['eligible'], key=lambda i: (-score[i], self.docs[i]['id']))[:limit]
        documents = [self.docs[i] for i in indices]
        documents, info = rerank(result['search_query'], documents, self.root, prompt=VERIFY_PROMPT)
        return {**result, 'documents': self.references.attach(documents, pn), 'fine_chunk_weights': self.weights,
                'evidence_rerank': info, 'query_rewrite': {**result['query_rewrite'], 'model_calls': result['query_rewrite'].get('model_calls', []) + info.get('model_calls', [])}}
