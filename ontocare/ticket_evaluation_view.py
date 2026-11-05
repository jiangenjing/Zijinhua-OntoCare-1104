"""Local read-only view of the explicitly seen-ticket evaluation run."""
from pathlib import Path
import json
from flask import jsonify, request, send_file


def register(app, root):
    root=Path(root);folder=root/'local/ticket-evaluation-v1'
    def local():return request.remote_addr in {'127.0.0.1','::1'}
    @app.get('/ticket-evaluation')
    def ticket_evaluation_page():
        if not local():return jsonify(error='仅供本机查看'),403
        return send_file(root/'web/ticket-evaluation.html')
    @app.get('/api/ticket-evaluation')
    def ticket_evaluation_data():
        if not local():return jsonify(error='仅供本机查看'),403
        path=folder/'export.json'
        response=jsonify(json.loads(path.read_text()) if path.exists() else {'status':'preparing','cases':[],'planned':63})
        response.headers['Cache-Control']='no-store';return response
    @app.get('/api/ticket-evaluation/download/<kind>')
    def ticket_evaluation_download(kind):
        if not local():return jsonify(error='仅供本机查看'),403
        names={'csv':folder/'逐条问答与评分.csv','xlsx':root/'outputs/ticket-evaluation-v1/工单问答与LLM裁判评分.xlsx','json':folder/'export.json','report':folder/'逐条问答报告.html'}
        path=names.get(kind)
        if path is None or not path.exists():return jsonify(error='文件尚未生成'),404
        response=send_file(path,as_attachment=True);response.headers['Cache-Control']='no-store';return response
