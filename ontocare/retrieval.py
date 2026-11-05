"""PN-filtered BM25 + exact multilingual E5 cosine, with honest fallback."""
import collections
import math
import os
import re

import numpy as np

from .data import ROOT, digest, load_json, write_json

MODEL = "intfloat/multilingual-e5-small"


def tokens(text):
    text = text.lower()
    return re.findall(r"[a-z0-9]+", text) + re.findall(r"[\u4e00-\u9fff]", text)


class Retriever:
    def __init__(self, root=ROOT):
        self.root = root
        self.docs = [d for d in load_json(root / "data/knowledge.json") if d["visible"]]
        self.by_id = {d["id"]: d for d in self.docs}
        self.term_counts = [collections.Counter(tokens(d["title"] + " " + d["content"])) for d in self.docs]
        self.df = collections.Counter(t for counts in self.term_counts for t in counts)
        self.avg_len = sum(sum(c.values()) for c in self.term_counts) / len(self.docs)
        self.encoder = None
        self.query_vectors = {}
        self.vectors = self.vector_ids = self.vector_meta = None
        if (root / "local/vectors.npz").exists():
            meta = load_json(root / "local/vectors.json")
            if meta["data_sha256"] == digest(self.docs):
                a = np.load(root / "local/vectors.npz", allow_pickle=False)
                self.vectors, self.vector_ids, self.vector_meta = a["vectors"], a["ids"].tolist(), meta

    def _encoder(self, revision=None):
        if self.encoder is None:
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer(MODEL, revision=revision, device="cpu", local_files_only=revision is not None and self.vector_meta is not None)
        return self.encoder

    def build_vectors(self):
        from huggingface_hub import HfApi
        revision = HfApi().model_info(MODEL).sha
        texts, ids = [], []
        for d in self.docs:
            words = (d["title"] + "\n" + d["content"]).split()
            # Index windows; generation always sees the complete parent Q&A, including conditions.
            for start in range(0, max(1, len(words)), 160):
                texts.append("passage: " + d["title"] + "\n" + " ".join(words[start:start + 200]))
                ids.append(d["id"])
        vectors = self._encoder(revision).encode(texts, batch_size=24, normalize_embeddings=True, show_progress_bar=True)
        np.savez_compressed(self.root / "local/vectors.npz", vectors=vectors, ids=np.array(ids))
        meta = {"model": MODEL, "revision": revision, "data_sha256": digest(self.docs), "chunks": len(ids), "parents": len(self.docs), "matching": "exact_normalized_dot_product", "prefixes": ["query: ", "passage: "]}
        write_json(self.root / "local/vectors.json", meta)
        write_json(self.root / "data/vector-manifest.json", meta)
        self.vectors, self.vector_ids, self.vector_meta = vectors, ids, meta
        return meta

    def search(self, query, pn=None, error_code=None, limit=6, use_scope=True, allow_rewrite=False, ranking_profile=None):
        if use_scope and not pn:
            return {"documents": [], "mode": "blocked_unknown_product"}
        eligible = [i for i, d in enumerate(self.docs) if not use_scope or pn in d["pns"]]
        if error_code:
            eligible = [i for i in eligible if re.search(r"(?<!\d)" + re.escape(error_code) + r"(?!\d)", self.docs[i]["title"])]
        rewrite_info={'used':False,'status':'disabled','model_calls':[]}
        search_query=query
        if allow_rewrite:
            from .customer_query_rewrite import rewrite
            search_query,rewrite_info=rewrite(query,self.root)
        if ranking_profile is not None:
            from .ranking import RankingIndex, PROFILES
            if ranking_profile not in PROFILES:
                raise ValueError('Unknown ranking profile')
            if self.vectors is not None:
                if not hasattr(self, 'ranking_index'):
                    self.ranking_index = RankingIndex(self)
                result = self.ranking_index.search(search_query, pn, error_code, limit, use_scope, PROFILES[ranking_profile])
                return {**result, 'query_rewrite': rewrite_info, 'search_query': search_query}
        query_terms = tokens(search_query)
        n = len(self.docs)
        def score(i):
            count = self.term_counts[i]
            length = sum(count.values())
            return sum(math.log(1 + (n - self.df[t] + .5) / (self.df[t] + .5)) * count[t] * 2.5 / (count[t] + 1.5 * (.25 + .75 * length / self.avg_len)) for t in query_terms if count[t])
        ranked = sorted(((score(i), self.docs[i]["id"]) for i in eligible), reverse=True)
        ranked = [(s, i) for s, i in ranked if s > 0][:20]
        scores = collections.defaultdict(float)
        for rank, (_, key) in enumerate(ranked, 1):
            scores[key] += 1 / (60 + rank)
        mode = "bm25_only"
        if self.vectors is not None and eligible:
            if search_query not in self.query_vectors:
                self.query_vectors[search_query] = self._encoder(self.vector_meta["revision"]).encode(["query: " + search_query], normalize_embeddings=True)[0]
            q = self.query_vectors[search_query]
            allowed = {self.docs[i]["id"] for i in eligible}
            similarities = self.vectors @ q
            best = {}
            for index in np.argsort(-similarities):
                key = self.vector_ids[int(index)]
                if key in allowed and key not in best:
                    best[key] = float(similarities[index])
                    if len(best) >= 20:
                        break
            for rank, key in enumerate(best, 1):
                scores[key] += 1 / (60 + rank)
            mode = "bm25_e5_rrf"
        selected = sorted(scores, key=lambda k: (-scores[k], k))[:limit]
        return {"documents": [self.by_id[key] for key in selected], "mode": mode, "pn_filter": pn, "error_filter": error_code, "query_rewrite": rewrite_info, "search_query": search_query}
