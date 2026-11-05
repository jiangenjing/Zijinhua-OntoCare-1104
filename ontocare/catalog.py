"""Complete local source browser, kept separate from customer retrieval/evaluation."""
import collections
import json
import mimetypes
from pathlib import Path
import posixpath
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

from .data import FILES, NS, ROOT, connect, digest, load_json, read_tables, rows, write_json

KINDS = {"tickets", "qa", "media"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def part(source, target):
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(source), target))


def relationships(archive, source):
    path = posixpath.join(posixpath.dirname(source), "_rels", posixpath.basename(source) + ".rels")
    if path not in archive.namelist():
        return {}
    return {r.attrib["Id"]: part(source, r.attrib["Target"]) for r in ET.fromstring(archive.read(path)) if r.attrib.get("TargetMode") != "External"}


def extract_media(path, root):
    assets, anchors = [], collections.defaultdict(list)
    directory = Path(root) / "local/catalog-media"
    directory.mkdir(exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = relationships(archive, "xl/workbook.xml")
        for sheet in book.find("s:sheets", NS):
            source = sheets[sheet.attrib[REL + "id"]]
            worksheet = ET.fromstring(archive.read(source))
            links = relationships(archive, source)
            for drawing in worksheet.findall("s:drawing", NS):
                drawing_path = links.get(drawing.attrib[REL + "id"])
                if not drawing_path:
                    continue
                images = relationships(archive, drawing_path)
                for anchor in ET.fromstring(archive.read(drawing_path)):
                    start = anchor.find("{*}from")
                    if start is None:
                        continue
                    for blip in anchor.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
                        member = images.get(blip.attrib.get(REL + "embed"))
                        if member:
                            anchors[member].append({"sheet": sheet.attrib["name"], "row": int(start.find("{*}row").text) + 1, "column": int(start.find("{*}col").text) + 1, "association": "Excel image anchor, not an independently verified business relationship"})
        for name in archive.namelist():
            if not name.startswith("xl/media/"):
                continue
            content = archive.read(name)
            identifier = "media-" + digest([name, digest(content)])[:12]
            suffix = Path(name).suffix.lower()
            if suffix not in {".png", ".jpeg", ".jpg", ".gif", ".webp", ".bmp"}:
                continue
            file_name = identifier + suffix
            (directory / file_name).write_bytes(content)
            assets.append({"id": identifier, "kind": "media", "title": Path(name).name, "file_name": file_name, "mime_type": mimetypes.guess_type(file_name)[0], "bytes": len(content), "sha256": digest(content), "anchors": anchors[name], "source_member": name, "source_file": FILES[0], "pns": [], "visible": None, "fields": {}, "interpretation": "original file display only; not visual understanding"})
    return assets


def index_tables(tables, source_hash, source_path, root=ROOT):
    root = Path(root)
    tickets = {t["source_row"]: t for t in rows("tickets", root)}
    docs = {(d["source"]["sheet"], d["source"]["row"]): d for d in load_json(root / "data/knowledge.json")}
    records = []
    assets = extract_media(source_path, root)
    for sheet in ["客诉工单信息", "eufy Robovacs Q&A", "eufy Breast Pump Q&A"]:
        for number, fields in tables[sheet]:
            is_ticket = sheet == "客诉工单信息"
            existing = tickets[number] if is_ticket else docs[sheet, number]
            record = {"id": existing["id"], "kind": "tickets" if is_ticket else "qa", "title": str(fields.get("产品名") or fields.get("Title") or existing["id"]), "content": str(fields["客户首封邮件内容"] if is_ticket else fields["Content"]), "pns": [existing["pn"]] if is_ticket and existing["pn"] else ([] if is_ticket else existing["pns"]), "visible": None if is_ticket else existing["visible"], "scene": str(fields.get("咨询场景") or ""), "fields": fields, "source": {"file": FILES[0], "sha256": source_hash, "sheet": sheet, "row": number}, "media_ids": [a["id"] for a in assets if any(p["sheet"] == sheet and p["row"] == number for p in a["anchors"])]}
            records.append(record)
    records += assets
    counts = dict(collections.Counter(r["kind"] for r in records))
    pns = sorted({p for r in records for p in r["pns"]})
    metadata = {"counts": counts, "qa_visible": sum(r["kind"] == "qa" and r["visible"] for r in records), "qa_hidden": sum(r["kind"] == "qa" and not r["visible"] for r in records), "source_sha256": source_hash, "canonical_file": FILES[0], "all_original_fields_preserved": True, "pns": pns, "scenes": sorted({r["scene"] for r in records if r["kind"] == "tickets"}), "qa_sheets": ["eufy Robovacs Q&A", "eufy Breast Pump Q&A"], "raw_data_location": "local/service.sqlite and local/catalog-media only; excluded from Git", "media_note": "All embedded media displayed in original form; anchor locations are source coordinates, not model-verified associations."}
    with connect(root) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS source_records (kind TEXT, id TEXT, sort_index INTEGER, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")
        conn.execute("CREATE TABLE IF NOT EXISTS source_catalog_meta (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("DELETE FROM source_records")
        conn.executemany("INSERT INTO source_records VALUES (?,?,?,?)", [(r["kind"], r["id"], i, json.dumps(r, ensure_ascii=False)) for i, r in enumerate(records)])
        conn.execute("INSERT OR REPLACE INTO source_catalog_meta VALUES (1,?)", (json.dumps(metadata, ensure_ascii=False),))
    write_json(root / "data/source-catalog-manifest.json", metadata)
    return metadata


def build(source_dir, root=ROOT):
    root = Path(root)
    source = Path(source_dir) / FILES[0]
    expected = load_json(root / "data/import-audit.json")["files"][FILES[0]]
    actual = digest(source.read_bytes())
    if actual != expected:
        raise ValueError("Source differs from the imported snapshot; import and version it before browsing")
    tables, _ = read_tables(source)
    return index_tables(tables, actual, source, root)


def metadata(root=ROOT):
    with connect(root) as conn:
        row = conn.execute("SELECT payload FROM source_catalog_meta WHERE id=1").fetchone()
    if row is None:
        raise sqlite3.OperationalError("Source catalog not initialized")
    return json.loads(row[0])


def list_records(kind, root=ROOT, *, query="", pn="", scene="", visibility="all", sheet="", page=1, page_size=20):
    if kind not in KINDS or not 1 <= page_size <= 100 or page < 1 or visibility not in {"all", "visible", "hidden"}:
        raise ValueError("Invalid catalog filter or pagination")
    with connect(root) as conn:
        records = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM source_records WHERE kind=? ORDER BY sort_index", (kind,))]
    matched = []
    for record in records:
        if pn and (pn not in record["pns"] if pn != "unresolved" else bool(record["pns"])):
            continue
        if scene and record.get("scene") != scene:
            continue
        if sheet and record.get("source", {}).get("sheet") != sheet:
            continue
        if visibility != "all" and record["visible"] is not (visibility == "visible"):
            continue
        if query and query.casefold() not in json.dumps(record, ensure_ascii=False).casefold():
            continue
        matched.append(record)
    count = len(matched)
    return {"kind": kind, "total": count, "unfiltered_total": len(records), "page": page, "page_size": page_size, "pages": max(1, (count + page_size - 1) // page_size), "items": matched[(page - 1) * page_size:page * page_size]}


def get_record(kind, identifier, root=ROOT):
    if kind not in KINDS:
        raise ValueError("Unknown source kind")
    with connect(root) as conn:
        result = conn.execute("SELECT payload FROM source_records WHERE kind=? AND id=?", (kind, identifier)).fetchone()
    return json.loads(result[0]) if result else None
