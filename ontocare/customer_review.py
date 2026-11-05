"""Explicit local operator functions; models cannot verify files or approve external remedies."""
import json
from pathlib import Path
import uuid

from flask import jsonify, request, send_file, current_app
import jsonschema

from .customer_workflow import connect, public, stamp


def register(app, root):
    app.config.setdefault('ONTOCARE_REVIEW_ACTOR', {'id':'local-reviewer','roles':['CustomerServiceSupervisor']})
    def actor():
        if request.remote_addr not in {'127.0.0.1','::1'} or request.headers.get('Origin',request.host_url.rstrip('/')) != request.host_url.rstrip('/'):
            raise ValueError('仅允许本机同源人工操作')
        value=current_app.config['ONTOCARE_REVIEW_ACTOR']
        if 'CustomerServiceSupervisor' not in value.get('roles',[]):raise PermissionError('服务端操作员没有人工审核权限')
        return value
    def audit(c,case_id,who,kind,details):
        record={'id':'audit-'+uuid.uuid4().hex,'case_id':case_id,'actor':who['id'],'function':kind,'details':details,'at':stamp(),'scope':'LOCAL_ONLY','external_execution':False}
        c.execute('INSERT INTO events VALUES(?,?,?)',(record['id'],case_id,json.dumps(record,ensure_ascii=False)))

    @app.get('/api/workflow/material/<ident>/download')
    def download_workflow_material(ident):
        try:
            actor()
            with connect(root) as c:row=c.execute('SELECT payload FROM materials WHERE id=?',(ident,)).fetchone()
            if not row:return jsonify(error='材料不存在'),404
            material=json.loads(row[0]);name=material.get('stored_name','')
            if not name or Path(name).name!=name:return jsonify(error='材料路径无效'),400
            response=send_file(Path(root)/'local/customer-sop-materials'/name,as_attachment=True,download_name='material-'+ident,mimetype='application/octet-stream')
            response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response
        except PermissionError as e:return jsonify(error=str(e)),403
        except ValueError as e:return jsonify(error=str(e)),400

    @app.post('/api/workflow/material/<ident>/review')
    def review_workflow_material(ident):
        try:
            who=actor();body=request.get_json(silent=True)
            jsonschema.validate(body,{'type':'object','additionalProperties':False,'required':['status','note'],'properties':{
                'status':{'enum':['VERIFIED','REJECTED']},'note':{'type':'string','minLength':5,'maxLength':1000}}})
            with connect(root) as c:
                c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT payload FROM materials WHERE id=?',(ident,)).fetchone()
                if not row:raise ValueError('材料不存在')
                m=json.loads(row[0]);m.update(status=body['status'],review_note=body['note'],reviewed_by=who['id'],reviewed_at=stamp())
                c.execute('UPDATE materials SET payload=? WHERE id=?',(json.dumps(m,ensure_ascii=False),ident));audit(c,m['case_id'],who,'verifyReceivedMaterial',{'material_id':ident,'status':body['status'],'note':body['note']})
            return jsonify(id=ident,status=m['status'],reviewed_by=who['id'])
        except PermissionError as e:return jsonify(error=str(e)),403
        except (ValueError,jsonschema.ValidationError) as e:return jsonify(error=str(e)[:180] if isinstance(e,ValueError) else '材料审核参数不符合类型契约'),400

    @app.get('/api/workflow/tasks/<ident>/private')
    def private_workflow_details(ident):
        try:
            actor()
            with connect(root) as c:
                task=c.execute('SELECT case_id FROM tasks WHERE id=?',(ident,)).fetchone()
                if not task:raise ValueError('待办不存在')
                case=json.loads(c.execute('SELECT payload FROM cases WHERE id=?',(task['case_id'],)).fetchone()[0])
            response=jsonify(address=case.get('claims',{}).get('address'),serial_number=case.get('claims',{}).get('serial_number'),scope='LOCAL_OPERATOR_ONLY')
            response.headers['Cache-Control']='no-store';return response
        except PermissionError as e:return jsonify(error=str(e)),403
        except ValueError as e:return jsonify(error=str(e)),400

    @app.post('/api/workflow/tasks/<ident>/decision')
    def decide_workflow_task(ident):
        try:
            who=actor();body=request.get_json(silent=True)
            jsonschema.validate(body,{'type':'object','additionalProperties':False,'required':['decision','note'],'properties':{
                'decision':{'enum':['NEEDS_INFORMATION','ACCEPT_FOR_LOCAL_PROCESSING','DECLINED']},
                'note':{'type':'string','minLength':5,'maxLength':1000},'ownership_checked':{'type':'boolean'},'policy_checked':{'type':'boolean'}}})
            with connect(root) as c:
                c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT payload FROM tasks WHERE id=?',(ident,)).fetchone()
                if not row:raise ValueError('待办不存在')
                task=json.loads(row[0]);case=json.loads(c.execute('SELECT payload FROM cases WHERE id=?',(task['case_id'],)).fetchone()[0])
                if case['state'] not in {'HUMAN_PENDING','MATERIALS'}:raise ValueError('案件不在可审核状态')
                req=c.execute('SELECT payload FROM requests WHERE case_id=?',(case['id'],)).fetchone();application=json.loads(req[0]) if req else None
                materials=[json.loads(x[0]) for x in c.execute('SELECT payload FROM materials WHERE case_id=? ORDER BY rowid',(case['id'],))]
                if body['decision']=='ACCEPT_FOR_LOCAL_PROCESSING' and application:
                    latest={m['kind']:m for m in materials}
                    required=['purchase_proof']+(['media'] if case['requested_remedy'] in {'replacement','refund'} else [])
                    if any(latest.get(k,{}).get('status')!='VERIFIED' for k in required):raise ValueError('请先检查并核验全部所需附件')
                    if not body.get('ownership_checked') or not body.get('policy_checked'):raise ValueError('请明确核实订单归属、寄送信息和适用政策')
                    if case['issue_type']=='fault' and not case['claims'].get('serial_number'):raise ValueError('故障申请缺少产品SN')
                task.update(status=body['decision'],review_note=body['note'],reviewed_by=who['id'],reviewed_at=stamp(),approved=False,external_human_assigned=False)
                case.update(state={'NEEDS_INFORMATION':'MATERIALS','ACCEPT_FOR_LOCAL_PROCESSING':'REVIEWED','DECLINED':'DECLINED'}[body['decision']],
                            review_note=body['note'],revision=case['revision']+1,human_task=task,updated_at=stamp())
                from .customer_workflow import LABELS
                case['state_label']=LABELS[case['state']]
                if application:
                    application.update(local_review_status=body['decision'],approved=False,external_execution=False)
                    c.execute('UPDATE requests SET payload=? WHERE case_id=?',(json.dumps(application,ensure_ascii=False),case['id']));case['request']=application
                c.execute('UPDATE tasks SET payload=? WHERE id=?',(json.dumps(task,ensure_ascii=False),ident))
                c.execute('UPDATE cases SET payload=? WHERE id=?',(json.dumps(case,ensure_ascii=False),case['id']))
                from .type_contracts import sync_review
                sync_review(c,case,body['decision'],body['note'])
                audit(c,case['id'],who,'reviewLocalServiceRequest',body)
            return jsonify(task=task,case=public(case),scope='LOCAL_REVIEW_ONLY',external_execution=False)
        except PermissionError as e:return jsonify(error=str(e)),403
        except (ValueError,jsonschema.ValidationError) as e:return jsonify(error=str(e)[:180] if isinstance(e,ValueError) else '审核参数不符合类型契约'),400
