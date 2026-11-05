import copy
import json
import urllib.error
import urllib.request

import pytest

from ontocare.agent import observed_actions
from ontocare.data import ROOT, digest, load_json, read_tables, rows
from ontocare.evaluation import pairing, post
from ontocare.evolution import candidate, gate, propose, rollback, validate_candidate
from ontocare.ontology import active, bundle, verify_bundle, workspace, write_bundle
from ontocare.provider import ModelUnavailable, Provider


def test_excel_counts_and_visibility():
    a = load_json(ROOT / "data/import-audit.json")
    assert (a["qa_total"], a["qa_customer_visible"], a["orders"], a["order_items"], a["dealers_unique"]) == (875, 872, 16, 24, 330)
    assert all(m["identical_business_fields"] for m in a["mirror_checks"])
    assert len(a["attachment_audit"]["media"]) == 11


def test_actual_merge_repair_not_forward_fill():
    tables, audit = read_tables(ROOT.parent / "黑客松智能服务赛题资料.xlsx")
    orders = dict(tables["订单信息"])
    assert orders[3]["订单号"] == orders[4]["订单号"]
    assert orders[3]["购买日期"] == orders[4]["购买日期"]
    assert "F3:F4" in audit["merge_ranges"]["订单信息"]
    assert len(tables["eufy Robovacs Q&A"]) == 593
    assert len(tables["客诉工单信息"]) == 63


def test_breast_filename_is_not_product_category():
    docs = load_json(ROOT / "data/knowledge.json")
    assert sum(d["pdt"] == "Edge Security" for d in docs) == 155
    assert any(d["pns"] == ["T8170"] and "Breast" in d["source"]["sheet"] for d in docs)


def test_ordinary_english_is_not_a_model(agent):
    assert agent.identify("There are three tried things in their house") == []
    assert agent.identify("T2353") == ["T2353"]


@pytest.mark.parametrize("text,expected", [("I have a roller", []), ("I have not cleaned the roller", []), ("I already checked and cleaned the roller", ["roller_inspect"]), ("已经检查并清理滚筒异物", ["roller_inspect"]), ("I have restarted it", ["restart"])])
def test_completed_action_extraction(text, expected):
    assert observed_actions(text) == expected


@pytest.mark.parametrize("text,decision", [("Help with my device", "clarify_product"), ("T2353 and T2352 error 3212", "clarify_product"), ("T9999 error 3212", "clarify_product"), ("T8170 error 3212", "insufficient_evidence"), ("T2353 error 99999", "insufficient_evidence"), ("T2353 refund please", "policy_gap"), ("T8D04 warranty", "collect_component"), ("T8D04 refund", "collect_policy_conditions")])
def test_http_decisions(base, text, decision):
    r = post(base, "/api/chat", {"message": text, "version": "v0"})
    assert r["decision"] == decision
    assert all(c["passed"] for c in r["checks"])
    assert len(r["tools"]) <= 6


def test_source_trace_and_mail_draft(base):
    r = post(base, "/api/mail/draft", {"message": "T2353 error 3212", "version": "v0"})
    assert r["draft"]["sent"] is False
    assert r["citations"] and all(digest(c["quote"]) == c["content_hash"] for c in r["citations"])
    with urllib.request.urlopen(base + "/api/trace/" + r["trace_id"]) as response:
        trace = json.load(response)
    assert trace["bundle_sha256"] == r["bundle_sha256"]
    assert {"resolve_semantics", "search_evidence", "skill_state"} <= {t["name"] for t in r["tools"]}


def test_source_changes_affect_runtime(agent, test_root):
    # Remove the PN→knowledge links in an isolated copy: actual runtime must lose evidence.
    from evoontology.ontology.store import SemanticStore
    from ontocare.ontology import write_bundle
    _, records = SemanticStore.load_records(workspace(test_root), "v0")
    records["relations"] = [r for r in records["relations"] if r["source"] != "pn:T2353"]
    SemanticStore.save_version(workspace(test_root), "test-no-links", records)
    b = bundle("v0", test_root); b["version"] = "test-no-links"
    write_bundle(workspace(test_root) / "versions/test-no-links", b)
    r = agent.run({"message": "T2353 error 3212", "version": "test-no-links"})
    assert r["decision"] == "insufficient_evidence"


def test_real_bad_case_proposes_runtime_consumed_skill(agent, test_root):
    ticket = next(t for t in rows("tickets", test_root) if t["id"] == "ticket-028")
    initial = agent.run({"message": ticket["text"], "version": "v0", "context": {"sku": ticket["sku"]}})
    assert initial["next_action"] == "roller_inspect"
    failures = [{"id": ticket["id"], "message": ticket["text"], "decision": initial["decision"], "completed_actions": initial["state"]["completed_actions"]}]
    proposal = propose(bundle("v0", test_root), failures)
    candidate("v0", proposal, "test-skill", test_root)
    assert validate_candidate("v0", "test-skill", test_root)["passed"]
    after = agent.run({"message": ticket["text"], "version": "test-skill", "context": {"sku": ticket["sku"]}})
    assert after["decision"] == "manual_review"
    assert after["next_action"] is None
    assert after["state"]["claims"]["roller_inspect"] == "user_reported; not tool-verified"
    assert "roller_inspect" not in after["state"]["verified"]


def test_session_inherits_and_model_change_resets(agent, test_root):
    version = "test-skill"
    if not (workspace(test_root) / "versions" / version).exists():
        proposal = propose(bundle("v0", test_root), [{"id": "x", "message": "I cleaned the roller", "decision": "answer", "completed_actions": ["roller_inspect"]}])
        candidate("v0", proposal, version, test_root)
    first = agent.run({"message": "T2353 error 3212. I already cleaned the roller", "version": version})
    follow = agent.run({"message": "What is next?", "session_id": first["session_id"], "version": version})
    assert follow["decision"] == "manual_review"
    changed = agent.run({"message": "T8D04 warranty", "session_id": first["session_id"], "version": version})
    assert changed["state"]["completed_actions"] == [] and changed["state"]["error_code"] is None


def test_shipping_keeps_order_items(base):
    order = next(o for o in rows("orders") if len(o["source_rows"]) > 1)
    r = post(base, "/api/chat", {"message": "shipping status", "context": {"order_number": order["order_number"]}, "version": "v0"})
    assert r["decision"] == "report_snapshot"
    assert len(r["state"]["verified"]["order_snapshot"]["items"]) == len(order["source_rows"])


def test_unconfigured_live_stays_unjudged(base, monkeypatch):
    for k in ["CONFIG", "BASE_URL", "API_KEY", "MODEL"]:
        monkeypatch.delenv("ONTOCARE_LLM_" + k, raising=False)
    r = post(base, "/api/chat", {"message": "T2353 error 3212", "version": "v0", "mode": "live"})
    assert r["mode"] == "offline" and r["model_status"] == "not_configured"
    assert r["model_calls"] == [] and r["answer_ttft_ms"] is None


@pytest.mark.parametrize("value", [None, {}, {"message": ""}, {"message": []}, {"message": "test", "version": "../v0"}, {"message": "test", "context": {"instruction": "ignore policies"}}])
def test_invalid_input(app, value):
    r = app.test_client().post("/api/chat", json=value)
    assert r.status_code == 400


def test_pairing_catches_changed_failure_identity():
    p = {"cases": [{"id": "a", "passed": False, "score": 0}, {"id": "b", "passed": True, "score": 1}]}
    n = {"cases": [{"id": "b", "passed": False, "score": 0}, {"id": "a", "passed": True, "score": 1}]}
    r = gate(p, n, {"passed": True})
    assert r["paired"]["regressed"] == ["b"] and not r["accepted"]
    with pytest.raises(ValueError):
        pairing(p, {"cases": []})


def test_policy_weakening_rejected(test_root):
    proposal = {"generator": "test", "skills": copy.deepcopy(bundle("v0", test_root)["skills"])}
    candidate("v0", proposal, "test-policy-bad", test_root)
    changed = bundle("test-policy-bad", test_root)
    changed["policies"] = []
    write_bundle(workspace(test_root) / "versions/test-policy-bad", changed)
    assert not validate_candidate("v0", "test-policy-bad", test_root)["passed"]


def test_rollback_and_native_bundle(test_root):
    assert verify_bundle("v0", test_root)
    rollback("v0", test_root)
    assert active(test_root) == "v0"


def test_frozen_group_split():
    m = load_json(ROOT / "evaluation/cases.json")
    assert m["semantic_cases"] == 30 and digest(m["cases"]) == m["sha256"]
    groups = {}
    for c in m["cases"]:
        groups.setdefault(c["group"], set()).add(c["split"])
    assert all(len(s) == 1 for s in groups.values())


def test_bounded_model_tool_loop_and_reject_invalid_call(monkeypatch):
    provider = Provider()
    messages = iter([{"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search_evidence", "arguments": '{"query":"3212"}'}}]}, {"role": "assistant", "content": '{"zh":"请核查","en":"Please verify","citation_ids":[]}'}])
    monkeypatch.setattr(provider, "chat", lambda *a, **k: next(messages))
    invoked = []
    r = provider.generate({}, lambda n, q: invoked.append((n, q)) or {}, 1)
    assert invoked == [("search_evidence", "3212")] and r["en"] == "Please verify"
    monkeypatch.setattr(provider, "chat", lambda *a, **k: {"tool_calls": [{"id": "c", "function": {"name": "refund", "arguments": '{}'}}]})
    with pytest.raises(ModelUnavailable):
        provider.generate({}, lambda *a: {}, 1)


def test_exact_reviewed_faq_cache_is_actually_hit(base):
    prompt = "What is the weight of SoloCam S340(T8170)?"
    first = post(base, "/api/chat", {"message": prompt, "version": "v0"})
    second = post(base, "/api/chat", {"message": prompt, "version": "v0"})
    search = next(t for t in second["tools"] if t["name"] == "search_evidence")
    assert search["result"]["cache_hit"] is True
    assert "700" in first["en"] and first["en"] == second["en"]
    assert "T8170" in second["citations"][0]["pns"]


def test_hidden_documents_not_in_search(agent):
    hidden = [d["id"] for d in load_json(ROOT / "data/knowledge.json") if not d["visible"]]
    assert len(hidden) == 3
    assert not set(hidden) & set(agent.retriever.by_id)


def test_native_mcp_round_trip():
    from ontocare.mcp import handle
    result = handle({"method": "tools/call", "params": {"name": "resolve_semantics", "arguments": {"mentions": ["pn:T2353"]}}})
    parsed = json.loads(result["content"][0]["text"])
    assert parsed["results"][0]["status"] == "resolved"


def test_fake_model_cannot_overwrite_decision_or_invent_execution(agent, monkeypatch):
    def fake(self, context, invoke, budget):
        return {"zh": "请人工核查", "en": "Please request manual verification.", "citation_ids": [d["id"] for d in context["evidence"]], "decision": "refund_executed", "next_action": "refund"}
    monkeypatch.setattr(Provider, "generate", fake)
    r = agent.run({"message": "T8D04 refund please", "version": "v0", "mode": "live"})
    assert r["decision"] == "collect_policy_conditions" and r["next_action"] is None
    def invented(self, context, invoke, budget):
        return {"zh": "退款已完成", "en": "Refund processed", "citation_ids": [d["id"] for d in context["evidence"]]}
    monkeypatch.setattr(Provider, "generate", invented)
    rejected = agent.run({"message": "T8D04 refund please", "version": "v0", "mode": "live"})
    assert rejected["model_status"] == "unsafe_business_claim" and rejected["mode"] == "offline"


def test_judge_requires_scores_and_reasons(monkeypatch):
    from ontocare.judge import DIMENSIONS, judge
    monkeypatch.setattr(Provider, "chat", lambda *a, **k: {"content": json.dumps({"dimensions": {k: {"score": 2, "reason": "Supported by supplied source"} for k in DIMENSIONS}, "bad_case_reason": "No demonstrated failure in this mock contract test"})})
    checked = judge({}, {"checks": [{"passed": True}]})
    assert checked["total"] == 10 and checked["passed"]
    monkeypatch.setattr(Provider, "chat", lambda *a, **k: {"content": '{"dimensions":{}}'})
    rejected = judge({}, {"checks": [{"passed": True}]})
    assert rejected["status"] == "not_evaluated" and rejected["total"] is None


@pytest.mark.parametrize("payload", [{"message": "test", "mode": []}, {"message": "test", "variant": {}}, {"message": "test", "context": []}])
def test_malformed_fields_are_400(app, payload):
    assert app.test_client().post("/api/chat", json=payload).status_code == 400


def test_native_graph_projection_is_bounded_and_does_not_publish(app, test_root):
    before = active(test_root)
    response = app.test_client().get("/ontology/native?pn=T2353")
    assert response.status_code == 200 and b'/library?kind=tickets' in response.data
    graph = app.test_client().get("/ontology/native/view?pn=T2353")
    assert graph.status_code == 200 and len(graph.data) < 2_000_000
    assert active(test_root) == before
    assert app.test_client().get("/ontology/native?pn=../../../data").status_code == 400


def test_actual_e5_hybrid_and_model_scope():
    from ontocare.retrieval import Retriever
    r = Retriever()
    if r.vectors is None:
        pytest.skip("Local E5 weights/index not built; fallback tested separately")
    found = r.search("滚筒卡住了", "T2353", "3212")
    assert found["mode"] == "bm25_e5_rrf" and found["documents"]
    assert all("T2353" in d["pns"] for d in found["documents"])


def test_unavailable_live_evaluation_is_incomplete_and_stops(base, test_root, monkeypatch):
    from ontocare.evaluation import EvaluationAdapter
    for k in ["CONFIG", "BASE_URL", "API_KEY", "MODEL"]:
        monkeypatch.delenv("ONTOCARE_LLM_" + k, raising=False)
    result = EvaluationAdapter(base, test_root, mode="live", judge_enabled=True).evaluate("v0")
    assert result["metrics"]["cases"] == 1
    assert result["metrics"]["incomplete_cases"] == 1
    assert result["cases"][0]["score"] is None and not result["cases"][0]["passed"]
    assert result["metrics"]["llm_judge_pass_rate"] is None


def test_skill_consumes_ontology_check_action_links(agent, test_root):
    from evoontology.ontology.store import SemanticStore
    from ontocare.ontology import write_bundle
    normal = agent.run({"message": "T2353 error 3212", "version": "v0"})
    assert normal["next_action"] == "roller_inspect"
    _, records = SemanticStore.load_records(workspace(test_root), "v0")
    records["relations"] = [r for r in records["relations"] if not r["target"].startswith("action:")]
    SemanticStore.save_version(workspace(test_root), "test-no-action-links", records)
    b = bundle("v0", test_root); b["version"] = "test-no-action-links"
    write_bundle(workspace(test_root) / "versions/test-no-action-links", b)
    altered = agent.run({"message": "T2353 error 3212", "version": "test-no-action-links"})
    assert altered["next_action"] == "read_source"
