import pytest
from ontocare.decisions import evaluate


def test_unknown_facts_are_not_denial_and_never_execute():
    r=evaluate({'intent':'fault'},as_of='2026-11-03')
    assert r['outcome']=='NEED_INFORMATION' and not r['can_execute']
    assert all(c['state']=='UNKNOWN' for c in r['checks'])


def test_delivered_is_review_not_automatic_reship():
    r=evaluate({'intent':'shipping','delivery_status':'DELIVERED','customer_received':False})
    assert r['outcome']=='DELIVERED_REQUIRES_REVIEW' and r['proposed_action'] is None


def test_replacement_requires_all_materials_and_does_not_execute():
    facts={'intent':'fault','troubleshooting_completed':True,'issue_persists':True,'warranty_end':'2026-12-31'}
    r=evaluate(facts,as_of='2026-11-03')
    assert r['proposed_action']=='replacement_request'
    assert set(r['missing_facts'])=={'purchase_proof_verified','shipping_address_verified','media_verified','serial_number_verified'}
    facts.update({k:True for k in r['missing_facts']})
    result=evaluate(facts,as_of='2026-11-03')
    assert result['missing_facts']==[] and result['can_execute'] is False
    assert result['evaluation_basis']=='SUPPLIED_FACTS_NOT_INDEPENDENTLY_VERIFIED'


def test_expiry_is_evaluated_on_date_and_unknown_materials_are_not_pass():
    r=evaluate({'intent':'fault','warranty_end':'2026-11-02'},as_of='2026-11-03')
    assert r['outcome']=='OUT_OF_WARRANTY_REVIEW'
    with pytest.raises(ValueError):evaluate({'intent':'fault','warranty_end':'yesterday'})
    with pytest.raises(ValueError):evaluate({'intent':'fault','issue_persists':'false'})


def test_shipping_rule_has_actual_brief_source():
    r=evaluate({'intent':'shipping','delivery_status':'IN_TRANSIT','customer_received':False})
    assert r['outcome']=='CONSIDER_RESHIP' and not r['can_execute']
    assert r['source_rules'][0]['source']['location']=='word/media/image1.jpeg'
