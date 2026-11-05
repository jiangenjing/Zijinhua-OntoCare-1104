"""SSE delivery of validated answers; never expose raw model tokens before checks."""
import json
import logging
from queue import Queue, Empty
from threading import Thread
import time

from flask import Response, stream_with_context
from .customer_view import conversation_graph, business_snapshot


def stream_reply(service, payload, runtime):
    events = Queue()
    snapshot = None
    root = getattr(service, 'root', None)
    def graph(result, preview=False):
        nonlocal snapshot
        if result.get('business_context', {}).get('order') and snapshot is None:
            snapshot = business_snapshot(root)
        return conversation_graph(result, root, snapshot, preview=preview)

    def progress(kind, data):
        if kind == 'identified':
            message = '已确认本轮型号：' + data['pn'] if data.get('pn') and not data.get('ambiguous') else '已读取会话信息，正在确认处理对象。'
            events.put(('status', {'stage': 'identify', 'message': message}))
        elif kind == 'tool_completed':
            labels = {'resolve_semantics': '已定位适用的本体记录。', 'skill_state': '已匹配处理步骤与历史状态。',
                      'search_evidence': '已完成适用资料检索。', 'lookup_order': '已完成本地订单快照查询。',
                      'check_dealer': '已完成销售方名录查询。', 'evaluate_service_decision': '已核对服务条件与待补信息。',
                      'graph_search': '已读取本轮关联图谱。','advance_service_workflow':'已保存本轮案件状态与本地流程回执。'}
            events.put(('status', {'stage': data['name'], 'message': labels.get(data['name'], '已完成资料查询。')}))
        elif kind == 'context_ready':
            events.put(('graph', {'graph': graph(data, preview=True), 'trace_id': data['trace_id'], 'phase': 'retrieved'}))
            events.put(('status', {'stage': 'generate', 'message': '正在依据已找到的资料生成答复。'}))
    def run():
        try:
            result = service.run({**payload, '_customer_experience': True}, on_event=progress)
            result['runtime'] = runtime
            result['conversation_graph'] = graph(result)
            events.put(('result', result))
        except (ValueError, FileNotFoundError):
            events.put(('error', {'error': '资料或会话无法读取，请核对输入后重试。'}))
        except Exception as error:
            logging.getLogger(__name__).error('Customer stream failed (%s)', type(error).__name__)
            events.put(('error', {'error': '本次服务暂不可用，请稍后重试。'}))

    def frame(event, data):
        return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'

    @stream_with_context
    def generate():
        yield frame('status', {'stage': 'received', 'message': '已收到问题，正在核对资料与适用条件。', 'delivery': 'validated_answer_chunks'})
        Thread(target=run, daemon=True).start()
        while True:
            try:
                kind, result = events.get(timeout=5)
                if kind in {'status', 'graph'}:
                    yield frame(kind, result)
                    continue
                break
            except Empty:
                yield frame('status', {'stage': 'waiting', 'message': '仍在处理；答复完成校验后将逐段显示。'})
        if kind == 'error':
            yield frame('error', result)
            return
        yield frame('status', {'stage': 'checked', 'message': '答复已返回并完成边界检查。'})
        yield frame('evidence', result)
        answer = result[payload.get('response_language', 'zh')]
        for offset in range(0, len(answer), 24):
            yield frame('delta', {'text': answer[offset:offset + 24]})
            time.sleep(.018)
        yield frame('done', {'session_id': result['session_id'], 'trace_id': result['trace_id']})

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no'})
