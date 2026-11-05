import json
import urllib.request

import pytest

from ontocare.data import ROOT, digest, load_json, read_tables
from ontocare.explorer import PAGE_SIZE, selection
from ontocare.ontology import active, verify_bundle


def read(base, path):
    with urllib.request.urlopen(base + path, timeout=30) as response:
        return json.load(response)


def test_catalog_exact_source_counts_and_hidden_states(base):
    meta = read(base, "/api/catalog/meta")
    assert meta["counts"] == {"tickets": 63, "qa": 875, "media": 11}
    assert (meta["qa_visible"], meta["qa_hidden"]) == (872, 3)
    for state, expected in [("visible", 872), ("hidden", 3), ("all", 875)]:
        result = read(base, "/api/catalog/qa?visibility=" + state)
        assert result["total"] == expected


def test_every_qa_reachable_once_and_untruncated_over_http(base):
    expected = {d["id"]: d for d in load_json(ROOT / "data/knowledge.json")}
    found = {}
    first = read(base, "/api/catalog/qa?page_size=100")
    for page in range(1, first["pages"] + 1):
        result = read(base, f"/api/catalog/qa?page_size=100&page={page}")
        for record in result["items"]:
            assert record["id"] not in found
            assert record["content"] == expected[record["id"]]["content"]
            assert record["fields"]["Content"] == expected[record["id"]]["content"]
            assert len(record["fields"]) == 10
            found[record["id"]] = record
    assert set(found) == set(expected)


def test_every_ticket_original_field_and_source_coordinate_preserved(base):
    source, _ = read_tables(ROOT.parent / "黑客松智能服务赛题资料.xlsx")
    expected = dict(source["客诉工单信息"])
    result = read(base, "/api/catalog/tickets?page_size=100")
    assert result["total"] == len(result["items"]) == 63
    for record in result["items"]:
        assert record["fields"] == expected[record["source"]["row"]]
        assert record["content"] == expected[record["source"]["row"]]["客户首封邮件内容"]
        assert len(record["fields"]) == 7


def test_filters_search_later_records_and_full_detail(base):
    from urllib.parse import urlencode
    q = read(base, "/api/catalog/qa?" + urlencode({"pn": "T2352", "q": "3212"}))
    assert q["total"] >= 1 and all("T2352" in r["pns"] and "3212" in json.dumps(r) for r in q["items"])
    tickets = read(base, "/api/catalog/tickets?q=Anker001&page_size=100")
    assert tickets["total"] >= 1
    last = read(base, "/api/catalog/tickets?page_size=20&page=4")
    assert len(last["items"]) == 3
    detail = read(base, "/api/catalog/tickets/" + last["items"][-1]["id"])
    assert detail == last["items"][-1]
    for name, total in [("eufy Robovacs Q&A", 593), ("eufy Breast Pump Q&A", 282)]:
        assert read(base, "/api/catalog/qa?" + urlencode({"sheet": name}))["total"] == total


def test_all_embedded_media_original_bytes_and_anchors(base):
    originals = load_json(ROOT / "data/import-audit.json")["attachment_audit"]["media"]
    expected = {a["member"]: a for a in originals}
    result = read(base, "/api/catalog/media")
    assert len(result["items"]) == 11
    for image in result["items"]:
        with urllib.request.urlopen(base + "/api/catalog/media/" + image["id"], timeout=20) as response:
            content = response.read()
            assert response.headers["Content-Type"].startswith("image/")
            assert "no-store" in response.headers["Cache-Control"]
        assert digest(content) == expected[image["source_member"]]["sha256"]
    # Original drawing anchor at complaint row 15 must be navigable without inventing image meaning.
    ticket = read(base, "/api/catalog/tickets/ticket-015")
    assert ticket["media_ids"]


@pytest.mark.parametrize("path", ["/api/catalog/unknown", "/api/catalog/qa?page=0", "/api/catalog/qa?page=-1", "/api/catalog/qa?page=oops", "/api/catalog/qa?page_size=1000", "/api/catalog/qa?visibility=invalid", "/ontology/native?pn=all&page=999999"])
def test_invalid_catalog_queries(app, path):
    assert app.test_client().get(path).status_code == 400


def test_missing_record_and_media_paths_do_not_leak_files(app):
    assert app.test_client().get("/api/catalog/tickets/missing").status_code == 404
    assert app.test_client().get("/api/catalog/media/missing").status_code == 404


def test_graph_pagination_covers_all_visible_knowledge_without_publication(test_root):
    before = active(test_root)
    first = selection("all", root=test_root)
    all_ids = []
    for page in range(1, first["pages"] + 1):
        info = selection("all", page, root=test_root)
        assert len(info["ids"]) <= PAGE_SIZE
        all_ids.extend(info["ids"])
    expected = {"knowledge:" + d["id"] for d in load_json(ROOT / "data/knowledge.json") if d["visible"]}
    assert len(all_ids) == len(set(all_ids)) == 872
    assert set(all_ids) == expected
    assert active(test_root) == before and verify_bundle(before, test_root)


def test_specific_source_opens_exact_graph_and_hidden_stays_out():
    docs = load_json(ROOT / "data/knowledge.json")
    known = next(d for d in docs if d["visible"] and "T2352" in d["pns"] and "3212" in d["title"])
    assert selection("T2352", qa_id=known["id"])["ids"] == ["knowledge:" + known["id"]]
    hidden = next(d for d in docs if not d["visible"])
    with pytest.raises(ValueError):
        selection("all", qa_id=hidden["id"])
