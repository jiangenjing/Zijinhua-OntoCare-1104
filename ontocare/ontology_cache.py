"""Bounded process-local cache of validated, read-only ontology snapshots."""
from collections import OrderedDict
from copy import deepcopy
from threading import RLock

from .data import digest
from .graph_search import CONTRACT, search
from .ontology import bundle, layer, verify_bundle, workspace


class OntologyCache:
    def __init__(self, root, enabled=True):
        self.root, self.enabled = root, enabled
        self.versions = OrderedDict()
        self.lock = RLock()

    def _stamp(self, version):
        directory = workspace(self.root) / "versions" / version
        paths = [directory / (name + ".json") for name in ["bundle", "terms", "mappings", "relations", "constraints", "evidence"]]
        paths.append(self.root / "data/knowledge.json")
        return tuple((s.st_mtime_ns, s.st_ctime_ns, s.st_size, s.st_ino) for p in paths for s in [p.stat()])

    def snapshot(self, version):
        if not self.enabled:
            return self._load(version), False
        with self.lock:
            stamp = self._stamp(version)
            existing = self.versions.get(version)
            if self.enabled and existing and existing["stamp"] == stamp:
                self.versions.move_to_end(version)
                return existing, True
            self.versions.pop(version, None)
            value = self._load(version)
            value["stamp"] = stamp
            if self._stamp(version) != stamp:
                raise ValueError("Ontology changed while loading; please retry")
            self.versions[version] = value
            if len(self.versions) > 4:
                self.versions.popitem(last=False)
            return value, False

    def _load(self, version):
        if not verify_bundle(version, self.root):
            raise ValueError("Invalid version bundle")
        return {"stamp": None, "bundle": bundle(version, self.root), "semantic": layer(version, self.root), "resolve": OrderedDict(), "graph": OrderedDict()}

    def _query(self, snapshot, family, key, compute):
        if not self.enabled:
            return compute(), False
        with self.lock:
            cache = snapshot[family]
            if self.enabled and key in cache:
                cache.move_to_end(key)
                return deepcopy(cache[key]), True
            result = compute()
            if self.enabled:
                cache[key] = deepcopy(result)
                if len(cache) > 256:
                    cache.popitem(last=False)
            return result, False

    def resolve(self, snapshot, mentions, context):
        semantic = snapshot["semantic"]
        # Native resolve ignores context for exact semantic IDs. Ambiguous names still bind context.
        exact = all(m in semantic.store.terms and semantic.store.terms[m].lifecycle_state in {"active", "validated"} for m in mentions)
        key = (tuple(mentions), None if exact else context)
        return self._query(snapshot, "resolve", key, lambda: semantic.resolve(mentions, context))

    def graph(self, snapshot, documents, pn, error_code):
        key = (pn, error_code, tuple(d["id"] for d in documents), digest(CONTRACT))
        return self._query(snapshot, "graph", key, lambda: search(snapshot["semantic"], documents, pn, error_code))
