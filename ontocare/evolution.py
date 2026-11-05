"""Host-assisted, bounded Skill proposals with native paired acceptance gate."""
import copy
import json
from pathlib import Path
import re
import subprocess

import jsonschema
from evoontology.evaluation.evaluation import EvaluationGate
from evoontology.ontology.store import SemanticStore
from evoontology.validate import validate

from .data import ROOT, connect, load_json, rows, write_json
from .evaluation import EvaluationAdapter, pairing, regression_cases
from .ontology import active, bundle, verify_bundle, workspace, write_bundle


def propose(parent, development_failures):
    """No benchmark reader, expected-answer reader, final inputs or final labels here."""
    skills = copy.deepcopy(parent["skills"])
    observed = []
    for failure in development_failures:
        if failure["decision"] == "answer" and (failure["completed_actions"] or re.search(r"no blockage (?:seen|found)|roller mop area is clear", failure["message"], re.I)):
            observed.append(failure["id"])
    if not observed or skills["troubleshooting"].get("track_completed"):
        return None
    skills["troubleshooting"]["track_completed"] = True
    skills["troubleshooting"]["completion_patterns"] = {"roller_inspect": [r"roller(?: mop)? area (?:is|looks) clear", r"no blockage (?:seen|found)"]}
    return {"kind": "skill", "skills": skills, "evidence_case_ids": observed, "hypothesis": "The current Skill does not inherit user-reported completed checks, so it repeats a source action. Track completion and recognize explicit clear-area reports without treating them as tool verification.", "generator": "bounded deterministic host-assisted proposer; no remote LLM", "changes": ["inherit completed checks", "recognize explicit clear-area reports"], "limitations": "This is a controlled Skill mechanism experiment, not self-improvement of model weights, Schema or tools."}


def candidate(parent_version, proposal, name, root=ROOT):
    root = Path(root)
    target = workspace(root) / "versions" / name
    if target.exists():
        raise ValueError("Candidate version already exists")
    _, records = SemanticStore.load_records(workspace(root), parent_version)
    parent = bundle(parent_version, root)
    new = copy.deepcopy(parent)
    new.update(version=name, parent=parent_version, origin=proposal["generator"], skills=proposal["skills"], change=proposal)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
    except subprocess.CalledProcessError:
        revision = "uncommitted_build"
    new["implementation_revision"] = revision
    SemanticStore.save_version(workspace(root), name, records)
    write_bundle(target, new)
    return new


def validate_candidate(parent_version, candidate_version, root=ROOT):
    parent, new = bundle(parent_version, root), bundle(candidate_version, root)
    errors = []
    native = validate(workspace(root), candidate_version)
    if not native["passed"] or not verify_bundle(candidate_version, root):
        errors.append("native records or bundle integrity failed")
    if parent["policies"] != new["policies"] or parent["data_sha256"] != new["data_sha256"]:
        errors.append("Skill candidate cannot weaken policies or replace the source snapshot")
    if parent["tools"] != new["tools"]:
        errors.append("Tool changes require implementation revision and dedicated compatibility tests; not a Skill-only patch")
    jsonschema.Draft202012Validator.check_schema(new["domain_schema"])
    with connect(root) as conn:
        for row in conn.execute("SELECT payload FROM sessions"):
            try:
                jsonschema.validate(json.loads(row[0]), new["domain_schema"])
            except jsonschema.ValidationError:
                errors.append("Schema does not accept an existing session; explicit migration required")
                break
    return {"passed": not errors, "errors": errors, "native": native}


def gate(parent, new, validation):
    compared = pairing(parent, new)
    native = EvaluationGate.decide_gt([c["score"] for c in parent["cases"]], [c["score"] for c in new["cases"]])
    accept = validation["passed"] and native["accept"] and not compared["regressed"]
    return {"accepted": accept, "reason": "Paired engineering assertions improve with no per-case regression and compatible source/policy/schema/tool contracts." if accept else "Candidate lacks a strict paired gain, regresses a previous pass, or fails contract checks.", "validation": validation, "paired": compared, "native_gate": native, "quality_scope": "offline behavioral assertions only; no LLM/human outcome certification"}


def run(base_url, root=ROOT, max_rounds=3):
    root = Path(root)
    if not 1 <= max_rounds <= 3:
        raise ValueError("This run is capped at three candidates")
    history_path = root / "reports/evolution-history.json"
    if history_path.exists():
        raise ValueError("Run already recorded. Preserve it; create a separate experiment before rerunning evolution.")
    manifest = load_json(root / "evaluation/cases.json")
    # Final split is never evaluated or supplied to the proposer during candidate selection.
    development = [c for c in manifest["cases"] if c["split"] == "development"]
    evaluation_cases = [c["id"] for c in manifest["cases"] if c["split"] != "final"] + [c["id"] for c in regression_cases(root)]
    adapter = EvaluationAdapter(base_url, root)
    parent_version = active(root)
    parent = adapter.evaluate(parent_version, evaluation_cases, root / "reports/parent-selection.json")
    history = {"protocol": "offline paired HTTP mechanism experiment", "max_rounds": max_rounds, "benchmark_sha256": manifest["sha256"], "baseline_version": parent_version, "baseline": parent["metrics"], "rounds": [], "llm_calls": 0, "manual_review": "pending"}
    messages = {c["id"]: c["turns"][0] for c in development}
    messages.update({t["id"]: t["text"] for t in rows("tickets", root)})
    for turn in range(1, max_rounds + 1):
        failures = []
        for case in parent["cases"]:
            if case["passed"] or case["split"] not in {"development", "regression"}:
                continue
            with connect(root) as conn:
                trace = conn.execute("SELECT payload FROM traces WHERE id=?", (case["reply"]["trace_id"],)).fetchone()
            trace = json.loads(trace[0])
            failures.append({"id": case["id"], "message": messages[case["id"]], "decision": trace["decision"], "completed_actions": trace["state"]["completed_actions"]})
        proposal = propose(bundle(parent_version, root), failures)
        if proposal is None:
            history["stop_reason"] = "No supported additional Skill hypothesis in development failures; no synthetic extra rounds."
            break
        name = f"candidate-{turn}"
        candidate(parent_version, proposal, name, root)
        compatibility = validate_candidate(parent_version, name, root)
        tested = adapter.evaluate(name, evaluation_cases, root / f"reports/{name}-selection.json")
        decision = gate(parent, tested, compatibility)
        record = {"round": turn, "parent": parent_version, "candidate": name, "proposal": proposal, "metrics": tested["metrics"], "decision": decision}
        history["rounds"].append(record)
        write_json(history_path, history)
        if decision["accepted"]:
            # Version is immutable; publication moves only the active pointer.
            SemanticStore.set_active(workspace(root), name)
            parent_version, parent = name, tested
    history["active_version"] = active(root)
    history["candidate_attempts"] = len(history["rounds"])
    history["accepted_versions"] = sum(r["decision"]["accepted"] for r in history["rounds"])
    history.setdefault("stop_reason", "Candidate budget exhausted")
    write_json(history_path, history)
    return history


def rollback(version, root=ROOT):
    if not verify_bundle(version, root):
        raise ValueError("Cannot activate invalid version")
    previous = active(root)
    SemanticStore.set_active(workspace(root), version)
    path = Path(root) / "local/rollback-log.json"
    log = load_json(path) if path.exists() else []
    log.append({"previous": previous, "active": version, "reason": "explicit local CLI rollback"})
    write_json(path, log)
