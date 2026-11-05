"""Typed intent routing. Model estimates are never eligibility or execution permission."""
import json
import re
from pathlib import Path
from typing import TypedDict

import jsonschema
from .data import digest, redact
from .provider import ModelUnavailable, Provider

INTENTS = ['shipping', 'product_inquiry', 'troubleshooting', 'warranty', 'refund',
           'replacement', 'dealer_check', 'out_of_scope', 'clarification']
SCHEMA = {'type': 'object', 'additionalProperties': False,
          'required': ['intent', 'issue_kind', 'confidence', 'reason', 'evidence'], 'properties': {
              'intent': {'enum': INTENTS}, 'issue_kind': {'enum': ['fault', 'shipping', 'product', 'unknown']},
              'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
              'reason': {'type': 'string', 'maxLength': 400}, 'evidence': {'type': 'string', 'maxLength': 400}}}


class IntentResult(TypedDict):
    intent: str
    issue_kind: str
    confidence: float
    reason: str
    evidence: str
    method: str


def classify(message: str, previous: dict | None, root: Path, live: bool = False,
             provider=None) -> dict:
    text = message.strip()
    issue = 'fault' if re.search(r'故障|报错|错误码|坏了|不工作|漏水|无法开机|不出奶|吸力|error|broken|not work|still fail', text, re.I) else 'shipping' if re.search(r'物流|包裹|运单|快递|发货|shipping|tracking|deliver', text, re.I) else 'unknown'
    # Explicit intent rules are fast and inspectable. Negative remedy wishes are controls, not requests.
    rules = [('out_of_scope', r'订.{0,5}机票|酒店预订|写.{0,5}情书|炒股|股票推荐|代写论文|彩票|book.{0,15}(?:flight|hotel)'),
             ('refund', r'退款|退货|refund|return\s+(?:it|the\s+(?:item|product))'),
             ('replacement', r'换货|换新|更换整机|replacement|replace\s+(?:it|my|the)'),
             ('dealer_check', r'授权|经销商|购买渠道|销售方|卖家|dealer|seller'),
             ('warranty', r'质保|保修|warranty'),
             ('shipping', r'物流|包裹|运单|快递|发货|订单.{0,12}(?:状态|金额|商品)|金额|多少钱|shipping|tracking|delivery|shipment|order\s+(?:status|amount)'),
             ('troubleshooting', r'故障|报错|错误码|坏了|不工作|漏水|无法开机|不出奶|吸力|error|broken|not work'),
             ('product_inquiry', r'怎么(?:使)?用|怎么清洁|如何使用|型号|参数|功能|能.{0,8}(?:水洗|清洗)|支持.{0,15}吗|how\s+(?:to|do)|can\s+I')]
    hits = [(intent, m.group()) for intent, pattern in rules if (m := re.search(pattern, text, re.I))]
    previous = previous or {}
    result = None
    if hits:
        selected, evidence = hits[0]
        if selected != 'out_of_scope' and any(i == 'out_of_scope' for i, _ in hits):
            selected = 'clarification'
        result = dict(intent=selected, issue_kind=issue if issue != 'unknown' else
                      'shipping' if selected == 'shipping' else previous.get('issue_kind', 'unknown'),
                      confidence=.95, reason='命中明确咨询意图规则；不代表售后资格已核验。', evidence=evidence,
                      method='explicit_rules', model_calls=[])
    # Mixed or implicit requests go to a structured model; obvious single-intent requests avoid an extra call.
    mixed = len({i for i, _ in hits} - {'troubleshooting', 'warranty', 'dealer_check'}) > 1
    if live and (result is None or mixed):
        config = Path(root) / 'local/deepseek-config.json'
        model = provider or Provider(config_path=config if config.exists() else None)
        prompt = (Path(root) / 'prompts/intent-router.md').read_text()
        safe_text = redact(text)
        try:
            answer = model.chat([{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps(
                {'message': safe_text, 'previous_intent': previous.get('intent'), 'schema': SCHEMA}, ensure_ascii=False)}])
            parsed = json.loads(answer.get('content', '').strip().removeprefix('```json').removesuffix('```').strip())
            jsonschema.validate(parsed, SCHEMA)
            if parsed['evidence'] and parsed['evidence'] not in safe_text:
                raise ValueError('ungrounded intent span')
            result = {**parsed, 'method': 'structured_llm', 'model_calls': model.calls, 'prompt_sha256': digest(prompt)}
            if not result['evidence'] or result['confidence'] < .75:
                result['intent'] = 'clarification'
                result['reason'] = '意图置信度不足，需要客户澄清；' + result['reason']
        except (ModelUnavailable, ValueError, jsonschema.ValidationError):
            result = result or dict(intent='clarification', issue_kind=issue, confidence=0,
                                   reason='结构化识别不可用，请澄清需要的服务。', evidence='', method='conservative_fallback')
            result['model_calls'] = model.calls
    if result is None:
        followup = previous.get('intent') in INTENTS and bool(re.search(
            r'已经|仍然|还是|刚才|下一步|这些|收到|没有收到|done|still|already|next|received', text, re.I))
        result = dict(intent=previous['intent'] if followup else 'clarification',
                      issue_kind=previous.get('issue_kind', issue) if followup else issue,
                      confidence=.8 if followup else 0, reason='沿用当前案件的连续追问。' if followup else '需要确认客户希望查询、排障还是申请售后。',
                      evidence=text[:120] if followup else '', method='conversation_state' if followup else 'clarification', model_calls=[])
    return result


def observed_claims(text: str) -> dict:
    """Capture only explicit customer statements, preserving UNKNOWN and negative evidence."""
    patterns = {
        'customer_received': ([r'已经收到', r'我收到了', r'I (?:have )?received'],
                              [r'(?:没有|没|未)收到', r'not received', r"haven.t received"]),
        'checks_completed': ([r'(?:排障|排查|检查).{0,20}(?:全部|都).{0,8}(?:完成|做完|做过)',
                              r'(?:已经|已).{0,8}完成.{0,8}(?:排障|排查|检查)', r'all.{0,20}(?:checks|steps).{0,15}(?:done|completed)'],
                             [r'(?:还没|尚未|没有).{0,10}(?:检查|排障|排查)', r'not.{0,12}(?:checked|completed)']),
        'issue_persists': ([r'(?:仍然|依然|仍|还是).{0,12}(?:报|故障|存在|不行|不工作|没好)', r'问题仍', r'仍未解决', r'still.{0,15}(?:fail|error|broken|not work)'],
                           [r'问题(?:已经|已)?解决(?:了)?', r'现在正常了', r'恢复正常', r'(?:issue|problem) (?:is |has been )?(?:resolved|fixed)']),
    }
    claims = {}
    for field, (positive, negative) in patterns.items():
        yes = next((m.group() for p in positive if (m := re.search(p, text, re.I))), None)
        no = next((m.group() for p in negative if (m := re.search(p, text, re.I))), None)
        # "未收到" and "已经收到" can be historical and current in one message; ask rather than guess.
        if yes or no:
            claims[field] = {'value': None if yes and no else bool(yes), 'evidence': redact((yes or '') + ('；' + no if no else '')),
                             'status': 'CONFLICTING_CUSTOMER_STATEMENT' if yes and no else 'CUSTOMER_REPORTED'}
    return claims
