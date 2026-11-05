"""Two-hop BFS around hybrid-search seeds, with source and PN boundaries."""
from collections import defaultdict, deque

from .data import digest

CONTRACT = {"algorithm": "product_scoped_breadth_first_search", "max_hops": 2, "max_terms": 30, "max_evidence": 6, "product_hub_expansion": False, "seeds": "product-scoped retrieved knowledge terms"}


def search(semantic, documents, pn, error_code=None):
    store = semantic.store
    allowed = {t.id for t in store.terms.values() if (pn in t.scope.split(";") or t.id == "pn:" + pn) and t.lifecycle_state in {"active", "validated"}}
    links = defaultdict(list)
    for relation in store.relations.values():
        if relation.source in allowed and relation.target in allowed and relation.lifecycle_state in {"active", "validated"}:
            links[relation.source].append((relation.target, relation.id))
            links[relation.target].append((relation.source, relation.id))
    seeds = ["knowledge:" + d["id"] for d in documents[:CONTRACT["max_evidence"]] if "knowledge:" + d["id"] in allowed]
    queue = deque((seed, 0, []) for seed in seeds)
    discovered, paths = {}, {}
    while queue and len(discovered) < CONTRACT["max_terms"]:
        term_id, depth, path = queue.popleft()
        if term_id in discovered:
            continue
        term = store.terms[term_id]
        discovered[term_id] = {"id": term.id, "name": term.name, "type": term.type, "scope": term.scope, "depth": depth, "evidence_ids": term.evidence_refs}
        paths[term_id] = path
        # Product hubs connect many unrelated faults; never expand them to bypass the error scope.
        if depth >= CONTRACT["max_hops"] or term.type == "product_model":
            continue
        for target, edge_id in sorted(links[term_id]):
            if target not in discovered:
                queue.append((target, depth + 1, path + [edge_id]))
    ids = set(discovered)
    edges = [{"id": r.id, "source": r.source, "target": r.target, "type": r.relation_type, "evidence_ids": r.evidence_refs} for r in store.relations.values() if r.source in ids and r.target in ids and r.lifecycle_state in {"active", "validated"}]
    constraints = [{"id": c.id, "target": c.target, "kind": c.constraint_type, "scope": c.scope, "description": c.description, "evidence_ids": c.evidence_refs} for c in store.constraints.values() if c.target in ids and c.lifecycle_state in {"active", "validated"}]
    mappings = [{"id": m.id, "term_id": m.term_id, "table": m.table, "column": m.column, "filter": m.semantic_filter, "evidence_ids": m.evidence_refs} for m in store.mappings.values() if m.term_id in ids and m.lifecycle_state in {"active", "validated"}]
    result = {"contract": CONTRACT, "contract_sha256": digest(CONTRACT), "version": store.version, "pn": pn, "error_code": error_code, "seeds": seeds, "nodes": list(discovered.values()), "edges": edges, "paths": paths, "constraints": constraints, "mappings": mappings, "evidence_ids": [d["id"] for d in documents if "knowledge:" + d["id"] in ids]}
    return result
