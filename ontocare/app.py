import json
from pathlib import Path
import re
import sqlite3

from flask import Flask, jsonify, request, send_file, render_template, url_for

from .customer_workflow_agent import CustomerWorkflowAgent as Agent
from .data import ROOT, connect, load_json
from .ontology import active, bundle, layer, workspace


def create_app(root=ROOT, agent=None):
    root = Path(root)
    app = Flask(__name__, static_folder=str(root / "web"), static_url_path="/static", template_folder=str(root / "web"))
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    service = agent or Agent(root)
    from .runtime import describe
    runtime = describe(service, root)
    app.extensions['ontocare_service'] = service
    from .actions import register as register_actions
    register_actions(app, root)
    from .manager import register
    register(app, root)
    from .reports import register as register_reports
    register_reports(app, root)
    from .service_eval_dashboard import register as register_service_evaluations
    register_service_evaluations(app, root)
    from .quality import register as register_quality
    register_quality(app, root, runtime)
    from .feedback import register as register_feedback
    register_feedback(app, root)
    from .customer_workflow import register as register_workflow
    register_workflow(app, root)
    from .customer_review import register as register_customer_review
    register_customer_review(app, root)
    from .type_contracts import register as register_type_contracts
    register_type_contracts(app, root, service)
    from .ticket_evaluation_view import register as register_ticket_evaluation
    register_ticket_evaluation(app, root)

    @app.get('/api/runtime')
    def runtime_status():
        return jsonify(runtime)

    @app.get("/")
    @app.get("/library")
    def index():
        return send_file(root / "web/index.html")

    @app.get('/service')
    def customer_service():
        return send_file(root / 'web/service.html')

    @app.get('/api/service/examples')
    def customer_examples():
        from .customer_view import order_examples
        return jsonify(order_examples(root))

    @app.get("/api/catalog/meta")
    def catalog_meta():
        from .catalog import metadata
        try:
            return jsonify(metadata(root))
        except sqlite3.OperationalError:
            return jsonify({"error": "本机原始资料浏览索引尚未建立。"}), 503

    @app.get("/api/catalog/<kind>")
    def catalog_list(kind):
        from .catalog import list_records
        try:
            return jsonify(list_records(kind, root, query=request.args.get("q", ""), pn=request.args.get("pn", ""), scene=request.args.get("scene", ""), visibility=request.args.get("visibility", "all"), sheet=request.args.get("sheet", ""), page=int(request.args.get("page", "1")), page_size=int(request.args.get("page_size", "20"))))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except sqlite3.OperationalError:
            return jsonify({"error": "本机原始资料浏览索引尚未建立。"}), 503

    @app.get("/api/catalog/<kind>/<identifier>")
    def catalog_detail(kind, identifier):
        from .catalog import get_record
        try:
            record = get_record(kind, identifier, root)
        except ValueError:
            return jsonify({"error": "unknown_kind"}), 400
        except sqlite3.OperationalError:
            return jsonify({"error": "本机原始资料浏览索引尚未建立。"}), 503
        if record is None:
            return jsonify({"error": "not_found"}), 404
        if kind == "media":
            response = send_file(root / "local/catalog-media" / record["file_name"], mimetype=record["mime_type"])
        else:
            response = jsonify(record)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.get("/api/status")
    def status():
        from .provider import Provider
        versions = sorted(p.name for p in (workspace(root) / "versions").iterdir() if p.is_dir())
        return jsonify({"active": active(root), "versions": versions, "data": load_json(root / "data/import-audit.json"), "vector": load_json(root / "data/vector-manifest.json") if (root / "data/vector-manifest.json").exists() else {"status": "not_built", "fallback": "BM25 only"}, "model": Provider().public_status(), "judge": Provider(judge=True).public_status(), "scope": "local text/mail demo; no email sending or real refund"})

    def run_mail_or_chat(mail=False, stream=False):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("message"), str) or not payload["message"].strip() or len(payload["message"]) > 16000:
            return jsonify({"error": "message must be a nonempty string, <=16000 characters"}), 400
        if not isinstance(payload.get("mode", "offline"), str) or payload.get("mode", "offline") not in {"offline", "live"}:
            return jsonify({"error": "unknown mode"}), 400
        if not isinstance(payload.get("variant", "full"), str):
            return jsonify({"error": "invalid variant"}), 400
        if not isinstance(payload.get('response_language', 'zh'), str) or payload.get('response_language', 'zh') not in {'zh', 'en'}:
            return jsonify({'error': 'unknown response language'}), 400
        from .customer_workflow import validate as validate_workflow
        try:
            validate_workflow(payload.get('workflow', {}))
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        payload.pop('_workflow_skill', None)
        context = payload.get("context", {})
        if not isinstance(context, dict) or set(context) - {"sku", "order_number", "country", "seller"} or any(not isinstance(v, str) or len(v) > 100 for v in context.values()):
            return jsonify({"error": "context accepts string sku/order_number/country/seller only"}), 400
        for key in ["session_id", "version"]:
            if key in payload and (not isinstance(payload[key], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", payload[key])):
                return jsonify({"error": "invalid " + key}), 400
        if stream:
            from .customer_stream import stream_reply
            return stream_reply(service, payload, runtime)
        try:
            result = service.run(payload)
        except (ValueError, FileNotFoundError) as exc:
            return jsonify({"error": str(exc)[:180]}), 400
        if mail:
            result["draft"] = {"subject_zh": "关于您的产品咨询", "subject_en": "Regarding your product inquiry", "body_zh": result["zh"], "body_en": result["en"], "sent": False}
        result['runtime'] = runtime
        return jsonify(result)

    app.add_url_rule("/api/chat/stream", "chat_stream", lambda: run_mail_or_chat(stream=True), methods=["POST"])
    app.add_url_rule("/api/chat", "chat", run_mail_or_chat, methods=["POST"])
    app.add_url_rule("/api/mail/draft", "mail", lambda: run_mail_or_chat(True), methods=["POST"])

    @app.get("/api/trace/<trace_id>")
    def trace(trace_id):
        with connect(root) as conn:
            item = conn.execute("SELECT payload FROM traces WHERE id=?", (trace_id,)).fetchone()
        return (jsonify(json.loads(item[0])), 200) if item else (jsonify({"error": "not_found"}), 404)

    @app.get("/api/ontology")
    def ontology():
        version = request.args.get("version") or active(root)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", version):
            return jsonify({"error": "invalid_version"}), 400
        try:
            semantic = layer(version, root)
            if semantic.version == "uninitialized":
                return jsonify({"error": "not_found"}), 404
            return jsonify({"bundle": bundle(version, root), "manifest": semantic.manifest(), "browse": semantic.browse(request.args.get("query", "T2353"), limit=6)})
        except FileNotFoundError:
            return jsonify({"error": "not_found"}), 404

    @app.get("/ontology/native")
    def native():
        from .explorer import selection
        try:
            info = selection(request.args.get("pn", "T2353"), int(request.args.get("page", "1")), request.args.get("qa"), root)
            audit = load_json(root / "data/import-audit.json")
            counts = {"tickets": len(load_json(root / "data/regression-manifest.json")), "qa": audit["qa_total"], "media": len(audit["attachment_audit"]["media"]), "hidden": audit["qa_total"] - audit["qa_customer_visible"]}
            return render_template("ontology.html", info=info, counts=counts, frame_url=url_for("native_view", pn=info["pn"], page=info["page"], qa=info["qa_id"], lang="zh"), previous_url=url_for("native", pn=info["pn"], page=info["page"] - 1, qa=info["qa_id"]), next_url=url_for("native", pn=info["pn"], page=info["page"] + 1, qa=info["qa_id"]))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/ontology/native/view")
    def native_view():
        from .explorer import render
        try:
            return send_file(render(request.args.get("pn", "T2353"), root, int(request.args.get("page", "1")), request.args.get("qa")))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/report")
    def report():
        path = root / "reports/summary.json"
        return jsonify(load_json(path) if path.exists() else {"status": "not_run"})

    @app.get("/reports/<name>")
    def reports(name):
        if name not in {"curve.svg", "curve.png", "report.html", "report.md", "summary.json", "manual-review.json"}:
            return jsonify({"error": "not_found"}), 404
        path = root / "reports" / name
        return send_file(path) if path.is_file() else (jsonify({"error": "not_run"}), 404)

    return app


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5112)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, threaded=True)
