"""Source-bound recommendations; evaluating supplied facts never executes a remedy."""
from datetime import date
from pathlib import Path
import jsonschema
from .data import ROOT, load_json

BOOL = {'type': ['boolean', 'null']}
FACT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'intent': {'enum': ['shipping', 'fault', 'refund']},
    'delivery_status': {'enum': ['DELIVERED', 'IN_TRANSIT', 'RETURN_TO_SENDER', 'UNKNOWN']},
    **{k: BOOL for k in ['customer_received', 'troubleshooting_completed', 'issue_persists', 'purchase_proof_verified', 'shipping_address_verified', 'media_verified', 'serial_number_verified']},
    'warranty_end': {'type': ['string', 'null']},
}}


def evaluate(facts, root=ROOT, as_of=None):
    try:jsonschema.validate(facts, FACT_SCHEMA)
    except jsonschema.ValidationError as exc:raise ValueError('决策事实参数无效：' + exc.message) from None
    today = date.fromisoformat(as_of) if as_of else date.today()
    source = load_json(Path(root) / 'data/competition-rules.json')
    intent = facts.get('intent', 'fault')
    missing, checks, rule_ids = [], [], []
    def need(name):
        if name not in missing:missing.append(name)
    def check(name, value):
        checks.append({'condition': name, 'state': 'UNKNOWN' if value is None else 'PASS' if value else 'FAIL'})
        if value is None:need(name)
        return value
    outcome, proposal = 'NEED_INFORMATION', None
    if intent == 'shipping':
        rule_ids = ['brief:reship', 'brief:delivered']
        delivered = None if facts.get('delivery_status', 'UNKNOWN') == 'UNKNOWN' else facts['delivery_status'] == 'DELIVERED'
        check('delivery_confirmed', delivered)
        received = check('customer_received', facts.get('customer_received'))
        if delivered is True:outcome = 'DELIVERED_REQUIRES_REVIEW'
        elif received is True:outcome = 'CONFIRM_ISSUE_RESOLVED'
        elif delivered is False and received is False:outcome, proposal = 'CONSIDER_RESHIP', 'reship_request'
    elif intent == 'fault':
        rule_ids = ['brief:fault-replacement']
        done = check('troubleshooting_completed', facts.get('troubleshooting_completed'))
        persists = check('issue_persists', facts.get('issue_persists'))
        expiry = facts.get('warranty_end')
        try:in_warranty = date.fromisoformat(expiry) >= today if expiry else None
        except (TypeError, ValueError):raise ValueError('warranty_end 必须为 ISO 日期 YYYY-MM-DD') from None
        check('within_warranty_on_as_of', in_warranty)
        if persists is False:outcome = 'CONFIRM_ISSUE_RESOLVED'
        elif in_warranty is False:outcome = 'OUT_OF_WARRANTY_REVIEW'
        elif done is False:outcome = 'CONTINUE_APPLICABLE_TROUBLESHOOTING'
        elif done is True and persists is True and in_warranty is True:outcome, proposal = 'CONSIDER_REPLACEMENT', 'replacement_request'
    else:
        rule_ids = ['brief:required-materials']
        outcome = 'REFUND_POLICY_REQUIRES_REVIEW'
    # The brief requires material collection for replacement/refund. Receipt is not verification.
    if proposal or intent == 'refund':
        rule_ids.append('brief:required-materials')
        requirements = ['purchase_proof_verified', 'shipping_address_verified', 'media_verified']
        if intent == 'fault':requirements.append('serial_number_verified')
        for key in requirements:
            if check(key, facts.get(key)) is not True:need(key)
    return {'outcome': outcome, 'proposed_action': proposal, 'missing_facts': missing, 'checks': checks,
            'can_execute': False, 'as_of': today.isoformat(), 'evaluation_basis': 'SUPPLIED_FACTS_NOT_INDEPENDENTLY_VERIFIED',
            'source_rules': [r for r in source['rules'] if r['id'] in set(rule_ids)],
            'next_step': '补充并核验缺失资料后，提交本地复核申请；当前未执行补发、换货或退款。' if missing else '由人工核对身份、来源快照与政策适用性，再决定是否提交操作申请。',
            'limitations': ['这是赛题 SOP 的本地建议，不是完整全球售后政策', '物流和订单为快照；传入事实不等于身份认证或独立核验', '已送达一般不补发不等于无例外拒绝；退款完整资格规则未提供']}
