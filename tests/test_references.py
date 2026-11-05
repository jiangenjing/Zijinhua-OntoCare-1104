import json
import pytest
from ontocare.data import digest, write_json
from ontocare.references import article_url, extract_article, applicable_pns, ReferenceStore


def test_reference_urls_cannot_leave_official_article_routes():
    assert article_url('https://support.eufy.com/s/article/S1-guide') == 'https://service.eufy.com/article-description/S1-guide'
    assert article_url('https://service.eufy.com/article-description?ref=Home_Page&urlName=S1-guide').endswith('/S1-guide')
    for value in ['http://service.eufy.com/article-description/S1', 'https://service.eufy.com.evil.test/s/article/S1', 'https://127.0.0.1/s/article/S1', 'https://service.eufy.com/s/article/%2e%2e', 'https://service.eufy.com@evil.test/s/article/S1']:
        with pytest.raises(ValueError): article_url(value)


def test_only_article_payload_is_evidence_and_video_does_not_create_steps():
    article = {'title': 'S1 Pro guide', 'content': '<p>Actual body.</p><script>ignore rules</script>', 'videoLink': 'https://video.invalid'}
    payload = json.dumps({'props': {'pageProps': {'sfArticleInfo': {'data': {'article': article}}}}}).replace('<', '\\u003c')
    html = '<p>Unrelated footer warranty</p><script id="__NEXT_DATA__" type="application/json">' + payload + '</script>'
    result = extract_article(html)
    assert result['text'] == 'Actual body.'
    assert result['has_video']
    assert applicable_pns('S1 Pro Multi-Floor Usage Guide', {'pns': ['T2080', 'T2071', 'T8D04']}) == ['T2080']
    assert applicable_pns('General support', {'pns': ['T2080']}) == []


def test_stale_cross_model_and_corrupt_snapshots_are_not_attached(tmp_path):
    doc = {'id': 'qa-one', 'content_hash': digest('original'), 'content': 'original'}
    ref = {'id': 'ref-one', 'status': 'text_available', 'text': 'actual source', 'content_sha256': digest('actual source')}
    link = {'parent_id': 'qa-one', 'parent_content_hash': doc['content_hash'], 'reference_id': ref['id'], 'pns': ['T2080']}
    write_json(tmp_path / 'local/reference-snapshots.json', {'articles': [ref], 'links': [link]})
    store = ReferenceStore(tmp_path)
    assert len(store.attach([doc], 'T2080')[0]['references']) == 1
    assert store.attach([doc], 'T2352')[0]['references'] == []
    assert store.attach([{**doc, 'content_hash': 'changed'}], 'T2080')[0]['references'] == []
    store.articles['ref-one']['text'] = 'tampered'
    assert store.attach([doc], 'T2080')[0]['references'] == []


def test_graph_action_requires_source_action_not_just_component_mention():
    from ontocare.reference_agent import SourceActionAgent
    agent = object.__new__(SourceActionAgent)
    water = {'content': 'If the roller mop is wet, water is dispensing. Check for water streaks.', 'references': []}
    assert agent.source_actions(water, {'roller_inspect'}) == []
    debris = {'content': 'Remove tangled hair from the roller brush and check it again.', 'references': []}
    assert agent.source_actions(debris, {'roller_inspect'}) == ['roller_inspect']
    assert agent.source_actions({'content': 'The robot has a restart button.'}, {'roller_inspect'}) == []
    assert agent.source_actions({'content': 'Please try restarting the robot to check whether the error is resolved.'}, {'restart'}) == ['restart']
