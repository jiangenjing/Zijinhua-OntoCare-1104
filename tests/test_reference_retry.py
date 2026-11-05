from ontocare.reference_agent import VerifiedReferenceAgent
from ontocare.provider import ModelUnavailable


def test_unsupported_claim_is_rewritten_once_not_marked_completed_directly(test_root, monkeypatch):
    agent = VerifiedReferenceAgent(test_root)
    class ReviewProvider:
        key = ''; calls = []
        def __init__(self): self.grounding_reviews = []; self.attempts = 0
        def generate(self, context, invoke, budget):
            self.attempts += 1
            if self.attempts == 1:
                self.grounding_reviews.append({'supported': False, 'violations': ['A conditional diagnostic was strengthened.']})
                raise ModelUnavailable('unsupported_answer')
            assert context['validation_feedback']['unsupported_claims']
            self.grounding_reviews.append({'supported': True, 'violations': []})
            return {'zh': '请按当前资料检查。', 'en': 'Follow the applicable source check.', 'citation_ids': [context['evidence'][0]['id']]}
    provider = ReviewProvider(); monkeypatch.setattr(agent, 'model_provider', lambda: provider)
    reply = agent.run({'message': 'T2352 error3212', 'mode': 'live'})
    assert provider.attempts == 2
    assert reply['response_validation_retries'] == 1
    assert reply['model_status'] == 'completed'
    assert [r['supported'] for r in reply['grounding_reviews']] == [False, True]
