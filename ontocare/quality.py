"""Read-only evidence view for the frozen source-grounded benchmark."""
import json
from flask import jsonify,send_file,request
from .data import load_json


def register(app,root,runtime=None):
    @app.get('/quality')
    def quality_page():return send_file(root/'web/quality.html')

    @app.get('/api/quality/summary')
    def quality_summary():
        path=root/'reports/grounded-eval/summary.json'
        data=load_json(path) if path.exists() else {'status':'running'}
        data['history_available']=(root/'evaluation/customer-service-v2/cases.json').exists()
        return jsonify(data)

    @app.get('/api/quality/workbench')
    def workbench_summary():
        def optional(name):
            path=root/name
            return load_json(path) if path.exists() else None
        measured=optional('reports/workbench-v4/summary.json')
        bound=measured['protocol']['runtimes']['after']['id'] if measured else None
        return jsonify({'runtime':runtime,'live_evaluation':measured,
                        'runtime_matches_evaluation':bound==runtime['id'] if bound and runtime else None,
                        'progress':optional('reports/workbench-v4/progress.json'),
                        'retrieval_experiments':optional('reports/reranker-v3/local-status.json'),
                        'intent_development':optional('reports/reranker-v3/intent-development.json'),
                        'intent_validation':optional('reports/reranker-v3/intent-validation.json'),
                        'intent_legacy':optional('reports/reranker-v3/intent-legacy.json'),
                        'ragas':optional('reports/workbench-v4/ragas-summary.json'),
                        'source_review':optional('reports/reranker-v3/source-label-review.json')})

    @app.get('/api/quality/repairs')
    def repairs_summary():
        path=root/'reports/workbench-v5/repair-status.json'
        data=load_json(path) if path.exists() else {'status':'本轮修复尚未汇总'}
        frozen=root/'reports/workbench-v5/action-fixed-protocol.json'
        data['active_runtime_matches_replay']=(load_json(frozen)['runtimes'].get('action-fixed',{}).get('id')==runtime['id']) if frozen.exists() and runtime else False
        return jsonify(data)

    @app.get('/api/quality/cases')
    def quality_cases():
        arm=request.args.get('arm','release');allowed={'baseline','candidate','candidate-v2','release','workbench-before','workbench-after','repairs-reference','repairs-action','repairs-verified','repairs-action-fixed'}
        if arm not in allowed:return jsonify({'error':'unknown arm'}),400
        try:page=max(1,int(request.args.get('page',1)))
        except ValueError:return jsonify({'error':'invalid page'}),400
        query=request.args.get('q','').casefold();failed=request.args.get('failed')=='1';items=[]
        workbench=arm.startswith('workbench-')
        repairs=arm.startswith('repairs-')
        name=arm.removeprefix('repairs-')
        folder=root/'local/workbench-v5'/(name+'-replay')/name if repairs else root/'local/workbench-v4'/arm.removeprefix('workbench-') if workbench else root/'local/eval-v2/live'/arm
        for p in sorted(folder.glob('*/*.json') if workbench else folder.glob('*.json')):
            if p.name.endswith('-judge.json'):continue
            row=load_json(p);jp=p.with_name(p.stem+'-judge.json');judge=row.get('judge',{}) if workbench or repairs else load_json(jp) if jp.exists() else {'status':'pending'}
            if failed and judge.get('passed') is not False:continue
            item={'id':row['id'],'case':row['case'],'turns':[{'question':t['question'],'http_ms':t['http_ms'],'reply':{k:t.get('reply',{}).get(k) for k in ['zh','en','decision','model_status','checks','timings','citation_ids','trace_id','grounding_reviews']}} for t in row['turns']],'judge':{k:v for k,v in judge.items() if k!='model_calls'}}
            if workbench:item['id']+=' · 第 '+str(row['repeat'])+' 次重复'
            reply=row['turns'][-1].get('reply',{});gates=[]
            if reply.get('model_status')!='completed':gates.append('模型或输出校验未完成：'+str(reply.get('model_status','http_failure')))
            gates.extend('硬检查失败：'+str(c['name']) for c in reply.get('checks',[]) if not c['passed'])
            if row['case'].get('expected_decision') and reply.get('decision')!=row['case']['expected_decision']:gates.append('工作流决策与预期不一致')
            item['gate_reasons']=gates
            if not query or query in json.dumps(item,ensure_ascii=False).casefold():items.append(item)
        return jsonify({'total':len(items),'page':page,'items':items[(page-1)*12:page*12]})

    @app.get('/api/quality/download/<name>')
    def quality_download(name):
        files={'protocol':root/'evaluation/grounded-1200/protocol.json','dataset':root/'reports/grounded-eval/dataset-export.json','results':root/'reports/grounded-eval/summary.json','audit':root/'reports/grounded-eval/manual-audit.json','audit-csv':root/'reports/grounded-eval/manual-audit.csv','curve':root/'reports/grounded-eval/evolution.svg','guide':root/'docs/1200题评测与受控改进说明.md'}
        files.update({'candidate-comparison':root/'reports/reranker-v3/candidate-comparison.png','local-ledger':root/'reports/reranker-v3/local-status.md','source-review':root/'reports/reranker-v3/source-label-review.md','workbench-protocol':root/'reports/workbench-v4/protocol.json','workbench-results':root/'reports/workbench-v4/summary.json','workbench-guide':root/'docs/工作台评测与客服改进交付.md'})
        files.update({'repairs-guide':root/'docs/资料补全与裁判一致性修复.md','repairs-results':root/'reports/workbench-v5/repair-status.json','repairs-curve':root/'web/repair-history.svg'})
        path=files.get(name)
        if not path or not path.exists():return jsonify({'error':'not_ready'}),404
        return send_file(path,as_attachment=name not in {'curve','candidate-comparison'})
