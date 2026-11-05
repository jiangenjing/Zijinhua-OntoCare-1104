import pytest
from ontocare.grounded_provider import GroundedProvider
from ontocare.provider import Provider, ModelUnavailable


@pytest.mark.parametrize('supported', [True, False])
def test_support_guard_rejects_unsupported_answer_without_relabeling(monkeypatch, supported):
    answer = {'zh': '答复', 'en': 'reply', 'citation_ids': ['qa-one']}
    monkeypatch.setattr(Provider, 'generate', lambda *args: answer)
    def chat(self, *args):
        import json
        self.calls.append({'status': 'completed'})
        return {'content': json.dumps({'supported': supported, 'violations': [] if supported else ['Conditional diagnosis was asserted as an established cause.']})}
    monkeypatch.setattr(Provider, 'chat', chat)
    provider = GroundedProvider()
    context = {'user_message': 'question', 'state': {'pn': 'T2080'}, 'evidence': [{'id': 'qa-one', 'content': 'actual source'}]}
    if supported: assert provider.generate(context, None, 0) is answer
    else:
        with pytest.raises(ModelUnavailable, match='unsupported_answer'): provider.generate(context, None, 0)
    assert provider.grounding_reviews[-1]['supported'] == supported
    assert provider.calls[-1]['phase'] == 'answer_support_check'
