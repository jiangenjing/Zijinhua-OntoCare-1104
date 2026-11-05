from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "openbkn" / "anker-customer-service"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    products = json.loads((ROOT / "data/products.json").read_text(encoding="utf-8"))
    knowledge = json.loads((ROOT / "data/knowledge.json").read_text(encoding="utf-8"))
    tickets = json.loads((ROOT / "data/regression-manifest.json").read_text(encoding="utf-8"))

    product_rows = [
        {"id": p["pn"], "pn": p["pn"], "pdt": ",".join(p.get("pdt", [])), "aliases": ",".join(p.get("aliases", []))}
        for p in products
    ]
    knowledge_rows = [
        {
            "id": k["id"],
            "title": k["title"],
            "content": k["content"],
            "pns": ",".join(k.get("pns", [])),
            "pdt": k.get("pdt", ""),
            "visible": str(bool(k.get("visible", False))).lower(),
            "source_file": k.get("source", {}).get("file", ""),
            "source_sheet": k.get("source", {}).get("sheet", ""),
            "source_row": k.get("source", {}).get("row", ""),
        }
        for k in knowledge
    ]
    ticket_rows = [
        {"id": t["id"], "pn": t.get("pn") or "", "scene": t.get("scene", ""), "source_row": t.get("source_row", "")}
        for t in tickets
    ]

    write_jsonl(OUT / "data/products.jsonl", product_rows)
    write_jsonl(OUT / "data/knowledge.jsonl", knowledge_rows)
    write_jsonl(OUT / "data/tickets.jsonl", ticket_rows)

    object_types = [
        {"id": "Product", "displayName": "产品", "key": "pn", "source": "data/products.jsonl"},
        {"id": "KnowledgeArticle", "displayName": "知识条目", "key": "id", "source": "data/knowledge.jsonl"},
        {"id": "SupportTicket", "displayName": "客诉工单", "key": "id", "source": "data/tickets.jsonl"},
        {"id": "Evidence", "displayName": "证据", "key": "source_file+source_sheet+source_row", "source": "KnowledgeArticle.source_*"},
        {"id": "CheckAction", "displayName": "检查动作", "key": "id", "source": "kn/actions.json"},
    ]
    relations = [
        {"id": "product_supports_knowledge", "from": "Product", "to": "KnowledgeArticle", "cardinality": "many", "via": "pns"},
        {"id": "knowledge_has_evidence", "from": "KnowledgeArticle", "to": "Evidence", "cardinality": "one-or-more", "via": "source_*"},
        {"id": "ticket_mentions_product", "from": "SupportTicket", "to": "Product", "cardinality": "zero-or-one", "via": "pn"},
        {"id": "knowledge_recommends_action", "from": "KnowledgeArticle", "to": "CheckAction", "cardinality": "many", "via": "action_tags"},
    ]
    constraints = [
        {"id": "product_scope", "type": "guard", "expression": "knowledge.pns contains ticket.pn OR knowledge.pns is empty", "severity": "error"},
        {"id": "visible_only", "type": "guard", "expression": "knowledge.visible == true", "severity": "error"},
        {"id": "evidence_required", "type": "guard", "expression": "answer.citations.length >= 1", "severity": "error"},
        {"id": "no_unverified_commitment", "type": "policy", "expression": "refund_or_replacement requires verified order and warranty fields", "severity": "error"},
    ]
    actions = [
        {"id": "identify_product", "displayName": "识别型号", "inputs": ["user_text"], "outputs": ["Product"], "skill": "disambiguation"},
        {"id": "retrieve_evidence", "displayName": "检索证据", "inputs": ["Product", "user_text"], "outputs": ["KnowledgeArticle", "Evidence"], "skill": "troubleshooting"},
        {"id": "check_order", "displayName": "查询订单", "inputs": ["order_id"], "outputs": ["order_status", "warranty_status"], "skill": "shipping"},
        {"id": "collect_eligibility", "displayName": "收集售后条件", "inputs": ["user_text"], "outputs": ["missing_conditions"], "skill": "aftersales"},
    ]
    skills = [
        {"id": "disambiguation", "trigger": "product or SKU is ambiguous", "steps": ["extract aliases", "ask one disambiguating question", "pin Product before retrieval"]},
        {"id": "troubleshooting", "trigger": "fault, symptom or error code", "steps": ["retrieve scoped evidence", "skip completed actions", "return ordered checks", "cite source"]},
        {"id": "shipping", "trigger": "delivery or order inquiry", "steps": ["lookup local order snapshot", "state tracking evidence", "do not claim shipment execution"]},
        {"id": "aftersales", "trigger": "warranty, replacement or refund", "steps": ["collect missing conditions", "apply constraints", "escalate if unverified"]},
    ]
    write_json(OUT / "kn/model.json", {"apiVersion": "openbkn.ai/v1alpha1", "kind": "KnowledgeNetwork", "metadata": {"name": "anker-customer-service", "version": "0.1.0"}, "spec": {"objectTypes": object_types, "relations": relations, "constraints": constraints, "actions": actions}})
    write_json(OUT / "skills/skills.json", skills)
    write_json(OUT / "kn/actions.json", actions)
    write_json(OUT / "bkn-eval/questions.json", [{"id": "q1", "question": "我的 E25 报 3212 错误，应该先检查什么？", "expectedProduct": "T2353", "expectedRelation": "product_supports_knowledge"}, {"id": "q2", "question": "我的订单 Anker001 为什么只收到配件？", "expectedProduct": "T2353", "expectedRelation": "ticket_mentions_product"}])

    sample_yaml = """apiVersion: samples.openbkn.ai/v1alpha1
kind: Sample
metadata:
  language: zh-CN
  name: anker-customer-service
  aliases: [ontocare, anker-ontocare]
  displayName: 安克智能客服本体
  summary: 基于 875 条 Q&A、63 条客诉回归用例和产品关系的客服知识网络候选包。
spec:
  studio:
    licenseNote: Internal/private benchmark data; do not use outside the authorized project.
    questions:
      - 当前有哪些产品、知识条目和客诉工单？
      - 某型号和错误码对应哪些有证据的检查动作？
      - 售后建议还缺哪些核验条件？
  database:
    engine: sqlite
    name: anker_customer_service
    expectedTables: 3
  data:
    mode: embedded
  knowledgeNetwork:
    id: anker_customer_service
    displayName: 安克智能客服
  components:
    objects: true
    relations: true
    constraints: true
    actions: true
    skills: true
    metrics: false
    functions: false
  hooks:
    dbInit: db/init.sh
    dbVerify: db/verify.sh
"""
    (OUT / "sample.yaml").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "sample.yaml").write_text(sample_yaml, encoding="utf-8")
    (OUT / "README.md").write_text("""# OpenBKN candidate: Anker customer service\n\nThis package mirrors the OpenBKN sample layout and maps the local OntoCare data into business objects, relations, constraints, actions, evidence and Skills. It is a deterministic local candidate package, not a claim of successful import into a running OpenBKN cluster.\n\n## Contents\n\n- `sample.yaml`: sample identity and declared components.\n- `kn/model.json`: ontology structure (objects, relations, constraints, actions).\n- `data/*.jsonl`: derived records from the processed local data, with source references retained for knowledge rows.\n- `skills/skills.json`: role-based processing Skills.\n- `bkn-eval/questions.json`: small scenario set for import/query smoke tests.\n\n## Rebuild\n\nFrom the repository root run `python scripts/build_openbkn_sample.py`. The output is deterministic from `data/products.json`, `data/knowledge.json` and `data/regression-manifest.json`.\n\n## Boundary\n\nOpenBKN's public samples document the package layout and runtime concepts, but the exact server import contract is version-specific. Final compatibility must be checked against the target OpenBKN version using its sample installer or SDK.\n""", encoding="utf-8")
    manifest = {"schema": 1, "source": {"products": "data/products.json", "knowledge": "data/knowledge.json", "tickets": "data/regression-manifest.json"}, "counts": {"products": len(product_rows), "knowledge": len(knowledge_rows), "visible_knowledge": sum(x["visible"] == "true" for x in knowledge_rows), "tickets": len(ticket_rows)}, "files": {}}
    for p in sorted(OUT.rglob("*")):
        if p.is_file() and p.name != "dataset.lock":
            manifest["files"][str(p.relative_to(OUT))] = sha256(p)
    write_json(OUT / "dataset.lock", manifest)
    print(json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
