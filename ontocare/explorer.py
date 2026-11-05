"""Bounded, source-preserving projections for the upstream native explorer."""
from pathlib import Path

from evoontology.ontology.store import SemanticStore
from evoontology.validate import validate
from evoontology.visualization.renderer import visualize

from .data import ROOT, load_json, write_json
from .ontology import active, workspace


PAGE_SIZE = 8


def selection(pn="T2353", page=1, qa_id=None, root=ROOT):
    products = {p["pn"] for p in load_json(Path(root) / "data/products.json")}
    if pn != "all" and pn not in products:
        raise ValueError("Unknown product model")
    _, records = SemanticStore.load_records(workspace(root), active(root))
    topics = [t for t in records["terms"] if t["id"].startswith("knowledge:")]
    applicable = [t for t in topics if pn == "all" or pn in t.get("scope", "").split(";")]
    if qa_id:
        applicable = [t for t in applicable if t["id"] == "knowledge:" + qa_id]
        if not applicable:
            raise ValueError("Q&A is not customer-visible or does not apply to this model")
    pages = max(1, (len(applicable) + PAGE_SIZE - 1) // PAGE_SIZE)
    if not 1 <= page <= pages:
        raise ValueError("Graph page out of range")
    start = (page - 1) * PAGE_SIZE
    chosen = applicable[start:start + PAGE_SIZE]
    return {"pn": pn, "page": page, "pages": pages, "total": len(applicable), "start": start + 1 if chosen else 0, "end": start + len(chosen), "qa_id": qa_id, "ids": [t["id"] for t in chosen], "options": [{"pn": p, "count": sum(p in t.get("scope", "").split(";") for t in topics)} for p in sorted(products)]}


def render(pn="T2353", root=ROOT, page=1, qa_id=None):
    info = selection(pn, page, qa_id, root)
    projection = Path(root) / "local/explorer" / pn / (f"page-{page}-" + (qa_id or "all"))
    counts = {}
    for directory in sorted((workspace(root) / "versions").iterdir()):
        if not directory.is_dir():
            continue
        version, records = SemanticStore.load_records(workspace(root), directory.name)
        chosen = [t for t in records["terms"] if t["id"] in info["ids"]]
        product_ids = {"pn:" + model for t in chosen for model in t.get("scope", "").split(";")} if pn == "all" else {"pn:" + pn}
        selected = product_ids | {t["id"] for t in chosen}
        evidence_ids = {e for t in chosen for e in t.get("evidence", [])}
        for t in records["terms"]:
            if t["type"] in {"check_action", "error_code", "condition", "component"} and set(t.get("evidence", [])) & evidence_ids:
                selected.add(t["id"])
        filtered = {"terms": [t for t in records["terms"] if t["id"] in selected], "mappings": [m for m in records["mappings"] if m["term_id"] in selected], "relations": [r for r in records["relations"] if r["source"] in selected and r["target"] in selected], "constraints": [c for c in records["constraints"] if c["target"] in selected]}
        refs = set()
        for family in filtered.values():
            for item in family:
                refs.update(item.get("evidence", []))
                refs.update(item.get("evidence_refs", []))
        filtered["evidence"] = [e for e in records["evidence"] if e["id"] in refs]
        SemanticStore.save_version(projection, version, filtered)
        if not validate(projection, version)["passed"]:
            raise ValueError("Invalid explorer projection")
        counts[version] = {k: len(v) for k, v in filtered.items()}
    SemanticStore.set_active(projection, active(root))
    write_json(projection / "projection.json", {**info, "source_workspace": "ontology/", "read_only_projection": True, "purpose": "paginated visualization; all original content is in /library", "counts": counts})
    path = visualize(projection, open_browser=False)
    # Pinned upstream opens the outcome overview; this route is specifically a graph view.
    markup = path.read_text()
    marker = "if (!(new URLSearchParams(window.location.search).get('compare'))) showView('overview');"
    if marker not in markup:
        raise ValueError("Pinned explorer template changed; graph default view requires review")
    path.write_text(markup.replace(marker, marker.replace("'overview'", "'content'"), 1))
    return path
