import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "openbkn" / "anker-customer-service"


def test_openbkn_candidate_is_reproducible():
    subprocess.run([sys.executable, "scripts/build_openbkn_sample.py"], cwd=ROOT, check=True)
    model = json.loads((SAMPLE / "kn/model.json").read_text(encoding="utf-8"))
    lock = json.loads((SAMPLE / "dataset.lock").read_text(encoding="utf-8"))
    assert model["kind"] == "KnowledgeNetwork"
    assert {x["id"] for x in model["spec"]["objectTypes"]} >= {"Product", "KnowledgeArticle", "SupportTicket", "Evidence", "CheckAction"}
    assert {x["id"] for x in model["spec"]["relations"]} >= {"product_supports_knowledge", "knowledge_has_evidence"}
    assert lock["counts"] == {"products": 19, "knowledge": 875, "visible_knowledge": 872, "tickets": 63}


def test_openbkn_candidate_declares_guards_and_skills():
    model = json.loads((SAMPLE / "kn/model.json").read_text(encoding="utf-8"))
    skills = json.loads((SAMPLE / "skills/skills.json").read_text(encoding="utf-8"))
    assert len(model["spec"]["constraints"]) == 4
    assert {x["id"] for x in skills} == {"disambiguation", "troubleshooting", "shipping", "aftersales"}
