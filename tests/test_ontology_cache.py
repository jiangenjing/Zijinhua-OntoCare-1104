import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest

from ontocare.agent import Agent
from ontocare.ontology_cache import OntologyCache
from ontocare.retrieval import Retriever


def test_followup_reuses_snapshot_relations_and_graph_without_stale_actions(test_root):
    service = Agent(test_root, Retriever(test_root))
    first = service.run({'message': 'T2353 error 3212', 'version': 'candidate-1'})
    follow = service.run({'message': 'I already checked and cleaned the roller; error 3212 persists.', 'version': 'candidate-1', 'session_id': first['session_id']})
    assert not first['ontology_cache']['snapshot_hit']
    assert follow['ontology_cache']['snapshot_hit']
    assert follow['ontology_cache']['resolve_hits'] == 2
    assert follow['ontology_cache']['graph_hits'] == 1
    assert follow['decision'] == 'manual_review' and first['decision'] == 'answer'
    assert follow['timings']['ontology_ms'] >= 0


def test_version_product_and_error_keys_cannot_reuse_wrong_graph(test_root):
    cache = OntologyCache(test_root)
    before, hit = cache.snapshot('v0')
    after, hit = cache.snapshot('candidate-1')
    assert not hit and before['bundle']['version'] != after['bundle']['version']
    service = Agent(test_root, Retriever(test_root))
    first = service.run({'message': 'T2353 error 3212'})
    switched = service.run({'message': 'T2352 error 3212', 'session_id': first['session_id']})
    assert switched['state']['pn'] == 'T2352' and switched['retrieval']['pn'] == 'T2352'
    assert switched['ontology_cache']['graph_misses'] == 1
    missing = service.run({'message': 'T2352 error 99999', 'session_id': first['session_id']})
    assert missing['decision'] == 'insufficient_evidence' and not missing['citations']


def test_cache_returns_isolated_results_and_keeps_ambiguous_context(test_root):
    cache = OntologyCache(test_root)
    snapshot, _ = cache.snapshot('candidate-1')
    a, hit = cache.resolve(snapshot, ['pn:T2353'], 'one question')
    assert not hit
    a['results'].clear()
    b, hit = cache.resolve(snapshot, ['pn:T2353'], 'different followup')
    assert hit and b['results']
    _, hit = cache.resolve(snapshot, ['unrecognized concept'], 'one')
    assert not hit
    _, hit = cache.resolve(snapshot, ['unrecognized concept'], 'two')
    assert not hit


def test_changed_source_files_invalidate_before_serving_cached_content(tmp_path, test_root):
    for directory in ['ontology', 'data']:
        shutil.copytree(test_root / directory, tmp_path / directory)
    cache = OntologyCache(tmp_path)
    cache.snapshot('candidate-1')
    path = tmp_path / 'ontology/versions/candidate-1/relations.json'
    original = path.read_text()
    path.write_text(original+'\n')
    with pytest.raises(ValueError, match='Invalid version bundle'):
        cache.snapshot('candidate-1')
    path.write_text(original)
    _, hit = cache.snapshot('candidate-1')
    assert not hit


def test_concurrent_load_uses_one_validated_snapshot(test_root):
    cache = OntologyCache(test_root)
    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots = list(pool.map(lambda _: cache.snapshot('candidate-1'), range(4)))
    assert sum(not hit for _, hit in snapshots) == 1
    assert len({id(value) for value, _ in snapshots}) == 1


def test_cached_and_uncached_agent_have_identical_evidence_decisions_and_context(test_root):
    before = Agent(test_root, Retriever(test_root), ontology_cache=False)
    after = Agent(test_root, Retriever(test_root), ontology_cache=True)
    ids = {}
    for message in ['T2353 error 3212', 'I already checked and cleaned the roller. 3212 error persists.']:
        results = {}
        for arm, service in [('before', before), ('after', after)]:
            payload = {'message': message, 'version': 'candidate-1'}
            if arm in ids:
                payload['session_id'] = ids[arm]
            results[arm] = service.run(payload)
            ids[arm] = results[arm]['session_id']
        keys = ['zh','en','state','decision','next_action','citation_ids','citations','retrieval','prompt','checks']
        assert {k: results['before'][k] for k in keys} == {k: results['after'][k] for k in keys}
        assert results['before']['ontology_cache']['snapshot_hit'] is False
