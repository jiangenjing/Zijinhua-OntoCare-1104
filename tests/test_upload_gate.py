import pytest
from ontocare.upload_gate import threshold_passes,recount,assess
from ontocare.data import write_json,digest


def test_exactly_ninety_or_only_hit_above_ninety_cannot_authorize_upload():
    assert not threshold_passes({'hit_at_1':.9,'recall_at_1':.9})
    assert not threshold_passes({'hit_at_1':.98,'recall_at_1':.89})
    assert not threshold_passes({'hit_at_1':float('nan'),'recall_at_1':.99})
    assert threshold_passes({'hit_at_1':.91,'recall_at_1':.905})


def test_recount_ignores_claimed_scores_and_preserves_multiple_gold_denominator():
    data={'cases':[{'id':'case','questions':{'zh':'问题','en':'question'},'pn':'T2353','gold_ids':['a','b']}]}
    rows=[{'id':'case:'+lang,'original_query':q,'pn':'T2353','gold_ids':['a','b'],'ranked_ids':['a'],'scores':{'hit_at_1':1,'recall_at_1':1}} for lang,q in data['cases'][0]['questions'].items()]
    assert recount(data,rows)=={'samples':2,'hit_at_1':1.,'recall_at_1':.5}
    with pytest.raises(ValueError,match='Missing'):recount(data,rows[:1])
    with pytest.raises(ValueError,match='Missing'):recount(data,rows+[rows[0]])
    changed=[{**r,'gold_ids':['a']} for r in rows]
    with pytest.raises(ValueError,match='gold changed'):recount(data,changed)


def make_frozen_gate(root):
    runtime=root/'ontocare/runtime.py';runtime.parent.mkdir();runtime.write_text('frozen runtime')
    hashes={}
    for name,namespace,n in [('legacy','grounded-reserve-v2',150),('confirmation','confirmation-v3',300)]:
        data={'cases':[{'id':str(i),'pn':'T2353','questions':{'zh':f'问题{i}','en':f'question {i}'},'gold_ids':['a']} for i in range(n)]}
        manifest={'split_sha256':{'final':digest(data)}}
        write_json(root/'evaluation'/namespace/'final.json',data)
        write_json(root/'evaluation'/namespace/'manifest.json',manifest);hashes[name]=digest(manifest)
        rows=[{'id':c['id']+':'+lang,'original_query':q,'pn':c['pn'],'gold_ids':c['gold_ids'],'ranked_ids':['a']} for c in data['cases'] for lang,q in c['questions'].items()]
        write_json(root/'reports/reranker-v3'/(name+'-result.json'),{'cases':rows})
    ids=[str(i) for i in range(60)]
    inputs={'cases':[{'id':i+':'+arm,'case_id':i,'arm':arm,'model_status':'completed'} for i in ids for arm in ['parent','candidate']]}
    records=[{'id':r['id'],'metrics':{'faithfulness':.9},'model_calls':[{'status':'completed'}]} for r in inputs['cases']]
    write_json(root/'local/confirmation-faithfulness-input.json',inputs)
    write_json(root/'reports/reranker-v3/confirmation-faithfulness-raw.json',{'cases':records})
    write_json(root/'reports/reranker-v3/release-freeze.json',{'runtime_files':{'ontocare/runtime.py':digest(runtime.read_bytes())},'dataset_manifest_sha256':hashes,'faithfulness_input_sha256':digest(inputs),'faithfulness_case_ids':ids})


def test_gate_requires_both_complete_sets_and_unchanged_runtime(tmp_path):
    make_frozen_gate(tmp_path)
    assert assess(tmp_path)['allowed']
    (tmp_path/'ontocare/runtime.py').write_text('changed after confirmation')
    with pytest.raises(ValueError,match='Runtime changed'):assess(tmp_path)


def test_ninety_percent_on_one_set_blocks_even_if_other_is_perfect(tmp_path):
    from ontocare.data import load_json
    make_frozen_gate(tmp_path);path=tmp_path/'reports/reranker-v3/legacy-result.json'
    data=load_json(path)
    for row in data['cases'][:30]:row['ranked_ids']=['wrong']
    data['metrics']={'hit_at_1':1,'recall_at_1':1}  # Claimed summary cannot override evidence.
    write_json(path,data)
    assert not assess(tmp_path)['allowed']


def test_faithfulness_drop_blocks_even_perfect_recall(tmp_path):
    from ontocare.data import load_json
    make_frozen_gate(tmp_path); path=tmp_path/'reports/reranker-v3/confirmation-faithfulness-raw.json'
    data=load_json(path)
    for row in data['cases']:
        if row['id'].endswith(':candidate'):row['metrics']['faithfulness']=.89
    write_json(path,data)
    assert not assess(tmp_path)['allowed']
    path.unlink()
    with pytest.raises(FileNotFoundError):assess(tmp_path)
