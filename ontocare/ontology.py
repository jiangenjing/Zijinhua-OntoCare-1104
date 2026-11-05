"""EvoOntology native records, plus immutable domain/Skill/tool bundle."""
import copy
import re
from pathlib import Path

from evoontology.ontology.store import SemanticStore
from evoontology.runtime.runtime import SemanticLayer
from evoontology.validate import validate

from .data import ROOT, digest, load_json, write_json

TOOLS = [
    {"name": "browse_semantics", "input": "query, kind, limit<=6", "read_only": True},
    {"name": "resolve_semantics", "input": "mentions<=5, context", "read_only": True},
    {"name": "search_evidence", "input": "pn, query, error_code", "read_only": True},
    {"name": "lookup_order", "input": "order_number", "read_only": True, "data": "local_snapshot"},
    {"name": "skill_state", "input": "session, skill, observed_actions", "read_only": False, "scope": "local_session_only"},
]
SKILLS = {
    "disambiguation": {"steps": ["identify_pn", "ask_if_ambiguous"], "forbidden": ["guess_model"]},
    "troubleshooting": {"steps": ["find_exact_model_evidence", "check_completed_actions", "offer_supported_next_step", "escalate_if_exhausted"], "track_completed": False, "forbidden": ["invent_repair_step", "execute_refund"]},
    "shipping": {"steps": ["collect_order_number", "lookup_snapshot", "report_snapshot_and_gaps"], "forbidden": ["claim_live_tracking"]},
    "aftersales": {"steps": ["identify_product_and_component", "retrieve_policy", "collect_missing_conditions", "request_manual_verification"], "forbidden": ["guarantee_eligibility", "claim_refund_executed"]},
}
DOMAIN_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["pn", "error_code", "completed_actions", "claims", "verified"], "properties": {"pn": {"type": ["string", "null"]}, "error_code": {"type": ["string", "null"]}, "completed_actions": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}, "claims": {"type": "object"}, "verified": {"type": "object"}}, "additionalProperties": False}


def workspace(root=ROOT):
    return Path(root) / "ontology"


def bundle(version, root=ROOT):
    return load_json(workspace(root) / "versions" / version / "bundle.json")


def build(root=ROOT):
    root = Path(root)
    documents = load_json(root / "data/knowledge.json")
    products = load_json(root / "data/products.json")
    records = {family: [] for family in ["terms", "mappings", "constraints", "evidence", "relations"]}
    for p in products:
        records["terms"].append({"id": "pn:" + p["pn"], "name": p["pn"], "type": "product_model", "definition": "Product model grounded in PN fields", "scope": ";".join(p["pdt"]), "aliases": p["aliases"], "evidence": ["ev:" + x for x in p["evidence"][:3]]})
    for doc in documents:
        if not doc["visible"]:
            continue
        eid, tid = "ev:" + doc["id"], "knowledge:" + doc["id"]
        records["evidence"].append({"id": eid, "source": f"{doc['source']['file']}#{doc['source']['sheet']}!row={doc['source']['row']};sha256={doc['source']['sha256']}", "query": doc["title"], "result": doc["content"], "validation_method": "published_visible_exact_excel_cell", "timestamp": "source_snapshot_date_unknown"})
        records["terms"].append({"id": tid, "name": doc["title"], "type": "knowledge_topic", "definition": "Knowledge topic; read linked Evidence for the original answer and procedure.", "scope": ";".join(doc["pns"]), "evidence": [eid]})
        records["mappings"].append({"id": "map:" + doc["id"], "term_id": tid, "database_source": "local/service.sqlite", "table": "documents", "column": "payload.content", "semantic_filter": "id=" + doc["id"], "evidence_refs": [eid], "grain": "one source Q&A row"})
        records["constraints"].append({"id": "scope:" + doc["id"], "target": tid, "constraint_type": "product_applicability", "severity": "block", "scope": ";".join(doc["pns"]), "description": "Customer retrieval requires Published + Visible and a matching PN.", "evidence": [eid]})
        for pn in doc["pns"]:
            records["relations"].append({"id": f"rel:{pn}:{doc['id']}", "source": "pn:" + pn, "target": tid, "relation_type": "association", "description": "Knowledge applies to this product model", "evidence": [eid]})
        for action, pattern, label in [("roller_inspect", r"(?:check|clean|remove).{0,150}(?:roller|debris)", "Inspect roller obstruction"), ("restart", r"restart(?:ing)? the robot", "Restart robot")]:
            if re.search(pattern, doc["content"], re.I | re.S):
                aid = "action:" + doc["id"] + ":" + action
                records["terms"].append({"id": aid, "name": label, "type": "check_action", "definition": "Source-supported check concept. Skill owns ordering; parent evidence owns instructions and conditions.", "scope": ";".join(doc["pns"]), "evidence": [eid]})
                records["relations"].append({"id": "knowledge-action:" + aid, "source": tid, "target": aid, "relation_type": "association", "description": "Exact Q&A supports this check; not an unconditional execution instruction", "evidence": [eid]})
        # Error code is modeled only when explicitly named as an error in the title.
        codes = re.findall(r"\b(\d{3,5})\s*(?:error|fault)|(?:error|fault)\s*(?:code)?\s*[:#-]?\s*(\d{3,5})", doc["title"], re.I)
        for pair in codes:
            code = next(x for x in pair if x)
            cid = "code:" + doc["id"] + ":" + code
            records["terms"].append({"id": cid, "name": code, "type": "error_code", "definition": "Source-scoped error code; not globally unique across models", "scope": ";".join(doc["pns"]), "evidence": [eid]})
            records["relations"].append({"id": "code-evidence:" + cid, "source": cid, "target": tid, "relation_type": "association", "description": "Fault description and supported checks", "evidence": [eid]})
            for pn in doc["pns"]:
                records["relations"].append({"id": "product-code:" + pn + ":" + cid, "source": "pn:" + pn, "target": cid, "relation_type": "association", "description": "Error code scoped to an explicitly applicable product model", "evidence": [eid]})
    # Policies are curated from named source answers, not inferred from ticket clusters.
    policies = []
    for doc in documents:
        if not doc["visible"] or doc["pns"] != ["T8D04"]:
            continue
        title, body = doc["title"].lower(), doc["content"].lower()
        if "warranty" in title and "1-year" in body and "3-month" in body:
            policies.append({"id": "warranty:" + doc["id"], "pn": "T8D04", "kind": "warranty", "components": {"pump_hub": {"months": 12}, "washable_parts": {"months": 3}}, "source_id": doc["id"], "scope": "competition_source_snapshot; jurisdiction/effective_date_unspecified"})
        if "refund" in title and "30 days" in body and "unopened" in body:
            policies.append({"id": "refund:" + doc["id"], "pn": "T8D04", "kind": "refund", "requirements": ["purchase_within_30_days", "new", "unopened", "intact_seals", "unused", "original_packaging"], "source_id": doc["id"], "scope": "competition_source_snapshot; jurisdiction/effective_date_unspecified"})
    for policy in policies:
        records["constraints"].append({"id": policy["id"], "target": "pn:" + policy["pn"], "constraint_type": policy["kind"], "severity": "block", "scope": policy["scope"], "description": "Business eligibility requires component and condition verification; see linked evidence.", "evidence": ["ev:" + policy["source_id"]]})
        for key in list(policy.get("components", {})) + policy.get("requirements", []):
            obj = "policy-object:" + policy["id"] + ":" + key
            records["terms"].append({"id": obj, "name": key, "type": "component" if key in policy.get("components", {}) else "condition", "definition": "Source-scoped policy object; customer claims remain unverified.", "scope": policy["pn"], "evidence": ["ev:" + policy["source_id"]]})
            records["relations"].append({"id": "policy-link:" + obj, "source": "pn:" + policy["pn"], "target": obj, "relation_type": "composition" if key in policy.get("components", {}) else "association", "description": "Policy component or eligibility prerequisite", "evidence": ["ev:" + policy["source_id"]]})
    # Product evidence may point to invisible docs; use visible-only links.
    evidence_ids = {e["id"] for e in records["evidence"]}
    for term in records["terms"]:
        term["evidence"] = [e for e in term.get("evidence", []) if e in evidence_ids]
    w = workspace(root)
    if (w / "versions/v0").exists():
        old = load_json(w / "versions/v0/bundle.json")
        if old["data_sha256"] != digest(documents):
            raise ValueError("Source data changed; build a new source version, never overwrite v0")
        return validate(w, "v0")
    SemanticStore.save_version(w, "v0", records)
    # Exact-source, low-risk FAQ selected by the host; not a claim of human sign-off.
    approved = [d["title"].strip().casefold() for d in documents if d["visible"] and d["title"] == "What is the weight of SoloCam S340(T8170)?"]
    write_bundle(w / "versions/v0", {"version": "v0", "parent": None, "data_sha256": digest(documents), "domain_schema": DOMAIN_SCHEMA, "tools": TOOLS, "skills": SKILLS, "policies": policies, "origin": "source-grounded initial build; minimal Skill before completion inheritance", "approved_faq": approved, "faq_review": "host-reviewed exact source question, no human approval claim"})
    result = validate(w, "v0")
    if not result["passed"]:
        raise ValueError(result)
    SemanticStore.set_active(w, "v0")
    return result


def write_bundle(directory, value):
    value = copy.deepcopy(value)
    value.pop("bundle_sha256", None)
    value["record_files_sha256"] = {family: digest((Path(directory) / (family + ".json")).read_bytes()) for family in ["terms", "mappings", "relations", "constraints", "evidence"]}
    value["bundle_sha256"] = digest(value)
    write_json(Path(directory) / "bundle.json", value)


def layer(version=None, root=ROOT):
    return SemanticLayer.load(str(workspace(root)), version)


def active(root=ROOT):
    return SemanticStore.active_version(workspace(root))


def verify_bundle(version, root=ROOT):
    b = bundle(version, root)
    expected = b.pop("bundle_sha256")
    files = {family: digest((workspace(root) / "versions" / version / (family + ".json")).read_bytes()) for family in ["terms", "mappings", "relations", "constraints", "evidence"]}
    return digest(b) == expected and b.get("record_files_sha256") == files and b["data_sha256"] == digest(load_json(Path(root) / "data/knowledge.json")) and validate(workspace(root), version)["passed"]
