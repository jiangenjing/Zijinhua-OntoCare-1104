"""Candidate only: the parent service remains unchanged until evaluation passes."""
from .agent import Agent
from .grounded_retrieval_v2 import Retriever as ParentRetriever
from .references import ReferenceStore
import re


class ReferenceRetriever(ParentRetriever):
    def __init__(self, root):
        super().__init__(root); self.references = ReferenceStore(root)

    def search(self, query, pn=None, error_code=None, limit=6, use_scope=True,
               allow_rewrite=False, ranking_profile=None):
        result = super().search(query, pn, error_code, limit, use_scope, allow_rewrite, ranking_profile)
        # Source-cell content and ranking IDs stay intact. Supplementary article text is separate.
        return {**result, 'documents': self.references.attach(result['documents'], pn),
                'reference_snapshot_sha256': self.references.sha256}


class ReferenceAgent(Agent):
    def __init__(self, root, retriever=None):
        super().__init__(root, retriever or ReferenceRetriever(root))


class SourceActionAgent(ReferenceAgent):
    def source_actions(self, document, relation_actions=None):
        proposed = super().source_actions(document, relation_actions)
        body = document['content'] + '\n' + '\n'.join(r['text'] for r in document.get('references', []))
        # A roller mentioned in water-flow diagnostics does not authorize generic hair-removal steps.
        roller = bool(re.search(r'(?:roller|rolling brush|滚刷|滚筒|滚轮|滚拖)[^.!?。\n]{0,100}(?:tangl|hair|debris|obstruct|foreign object|缠绕|毛发|异物|卡住)|(?:tangl|hair|debris|obstruct|foreign object|缠绕|毛发|异物|卡住)[^.!?。\n]{0,100}(?:roller|rolling brush|滚刷|滚筒|滚轮|滚拖)', body, re.I))
        restart = bool(re.search(r'\brestart(?:ing|ed)?\b|\breboot(?:ing|ed)?\b|重启', body, re.I))
        return [a for a in proposed if (a == 'roller_inspect' and roller) or (a == 'restart' and restart)]


class VerifiedReferenceAgent(SourceActionAgent):
    def model_provider(self):
        from .grounded_provider import GroundedProvider
        return GroundedProvider(config_path=self.root / 'local/deepseek-config.json')
