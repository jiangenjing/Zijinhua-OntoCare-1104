import argparse
import json
import os
import subprocess

from .data import ROOT, digest, ingest, load_json, write_json


def main():
    p = argparse.ArgumentParser(description="OntoCare reproducible local workflow")
    sub = p.add_subparsers(dest="command", required=True)
    source = sub.add_parser("ingest")
    source.add_argument("--source", required=True)
    catalog = sub.add_parser("catalog")
    catalog.add_argument("--source", required=True)
    for name in ["build", "vectors", "validate", "experiment", "report", "model-probe"]:
        sub.add_parser(name)
    business = sub.add_parser("business-build")
    business.add_argument("--source", required=True)
    sub.add_parser("service-mcp")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=5112)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("version")
    live = sub.add_parser("live-evaluate")
    live.add_argument("--repeat", type=int, default=3, choices=[3])
    args = p.parse_args()
    result = None
    if args.command == "service-mcp":
        from .service_mcp import main as run_mcp
        run_mcp()
    elif args.command == "business-build":
        from .business import build
        result = build(args.source)
    elif args.command == "ingest":
        result = ingest(args.source)
    elif args.command == "catalog":
        from .catalog import build
        result = build(args.source)
    elif args.command == "build":
        from .ontology import build
        from .evaluation import make_cases
        result = {"ontology": build(), "benchmark": make_cases()["sha256"]}
    elif args.command == "vectors":
        from .retrieval import Retriever
        result = Retriever().build_vectors()
    elif args.command == "validate":
        from .ontology import active, verify_bundle
        result = {"version": active(), "passed": verify_bundle(active())}
    elif args.command in {"experiment", "report", "live-evaluate"}:
        from .app import create_app
        from .evaluation import EvaluationAdapter, http_server
        from .ontology import active
        with http_server(create_app()) as base:
            if args.command == "experiment":
                from .evolution import run
                from .reporting import build_report
                run(base)
                result = build_report(base)
                runtime = {str(f.relative_to(ROOT)): digest(f.read_bytes()) for f in sorted((ROOT / "ontocare").glob("*.py"))}
                try:
                    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
                except subprocess.CalledProcessError:
                    revision = "uncommitted"
                write_json(ROOT / "reports/run-manifest.json", {"runtime_files": runtime, "runtime_sha256": digest(runtime), "implementation_revision": revision, "benchmark_sha256": load_json(ROOT / "evaluation/cases.json")["sha256"], "vectors": load_json(ROOT / "data/vector-manifest.json") if (ROOT / "data/vector-manifest.json").exists() else None, "transport": "actual localhost HTTP", "model_calls": 0})
            elif args.command == "report":
                from .reporting import build_report
                result = build_report(base)
            else:
                cs = [c["id"] for c in load_json(ROOT / "evaluation/cases.json")["cases"] if c["split"] != "final"]
                results = []
                for iteration in range(args.repeat):
                    tested = EvaluationAdapter(base, mode="live", judge_enabled=True).evaluate(active(), cs, ROOT / f"local/live-{iteration + 1}.json")
                    results.append(tested["metrics"])
                    if not any(c["reply"]["model_status"] == "completed" for c in tested["cases"]):
                        break
                result = {"runs": results, "note": "Only completed live answers with completed independent judge calls have a judge score."}
    elif args.command == "serve":
        configured = ROOT / "local/deepseek-config.json"
        if configured.is_file() and not os.environ.get("ONTOCARE_LLM_CONFIG"):
            os.environ["ONTOCARE_LLM_CONFIG"] = str(configured)
        from .app import create_app
        create_app().run(host="127.0.0.1", port=args.port, threaded=True)
    elif args.command == "rollback":
        from .evolution import rollback
        rollback(args.version)
        result = {"active": args.version}
    elif args.command == "model-probe":
        from .provider import ModelUnavailable, Provider
        provider = Provider()
        try:
            provider.chat([{"role": "user", "content": "Reply with OK only."}])
            result = {"status": "completed", "model_calls": provider.calls}
        except ModelUnavailable as exc:
            result = {"status": "blocked", "reason": str(exc)}
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
