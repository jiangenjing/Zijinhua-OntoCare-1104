"""Read-only Excel ingestion; raw tickets and orders never leave local/."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
FILES = ["黑客松智能服务赛题资料.xlsx", "客诉工单信息.xlsx", "eufy Robovacs Q&A.xlsx", "eufy Breast Pump Q&A.xlsx"]
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def load_json(path):
    return json.loads(Path(path).read_text())


def redact(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", str(text))
    return re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)", "[NUMBER]", text)


def read_tables(path):
    """Repair incorrect dimensions and only fill cells in actual merge ranges."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    merges, media = {}, []
    with zipfile.ZipFile(path) as archive:
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {x.attrib["Id"]: x.attrib["Target"] for x in rels}
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        for sheet in book.find("s:sheets", NS):
            rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = targets[rel_id]
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            merges[sheet.attrib["name"]] = [m.attrib["ref"] for m in ET.fromstring(archive.read(target)).findall("s:mergeCells/s:mergeCell", NS)]
        for name in archive.namelist():
            if name.startswith("xl/media/"):
                media.append({"member": name, "sha256": digest(archive.read(name)), "bytes": archive.getinfo(name).file_size, "interpretation": "not_processed"})
        anchors = []
        for name in archive.namelist():
            if name.startswith("xl/drawings/") and name.endswith(".xml"):
                tree = ET.fromstring(archive.read(name))
                for anchor in tree:
                    start = anchor.find("{*}from")
                    if start is not None:
                        anchors.append({"drawing": name, "row": int(start.find("{*}row").text) + 1, "column": int(start.find("{*}col").text) + 1})
    tables = {}
    for sheet in wb:
        sheet.reset_dimensions()
        values = {i: list(row) for i, row in enumerate(sheet.values, 1) if any(v is not None for v in row)}
        for span in merges[sheet.title]:
            min_c, min_r, max_c, max_r = openpyxl.utils.range_boundaries(span)
            top = values.get(min_r, [])
            value = top[min_c - 1] if len(top) >= min_c else None
            for row in range(min_r, max_r + 1):
                if row not in values:
                    continue
                values[row] += [None] * max(0, max_c - len(values[row]))
                for col in range(min_c - 1, max_c):
                    values[row][col] = value
        headers = values.pop(1)
        tables[sheet.title] = [(n, {str(k): (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in zip(headers, row) if k is not None}) for n, row in values.items()]
    wb.close()
    return tables, {"merge_ranges": merges, "media": media, "drawing_anchors": anchors}


def connect(root=ROOT):
    conn = sqlite3.connect(Path(root) / "local/service.sqlite")
    conn.row_factory = sqlite3.Row
    return conn


def ingest(source_dir, root=ROOT):
    root, source_dir = Path(root), Path(source_dir)
    tables, workbook_audit = read_tables(source_dir / FILES[0])
    hashes = {name: digest((source_dir / name).read_bytes()) for name in FILES}
    mirrors = []
    for name, sheet in [(FILES[1], "客诉工单信息"), (FILES[2], "eufy Robovacs Q&A"), (FILES[3], "eufy Breast Pump Q&A")]:
        other, _ = read_tables(source_dir / name)
        mirror_rows = next(iter(other.values()))
        original = [row for _, row in tables[sheet]]
        keys = list(original[0])
        matched = [{k: r.get(k) for k in keys} for _, r in mirror_rows] == original
        if not matched:
            raise ValueError(f"Mirror workbook differs: {name}; resolve before ingest")
        mirrors.append({"file": name, "canonical_sheet": sheet, "rows": len(original), "identical_business_fields": True})
    docs, products = [], {}
    for sheet in ["eufy Robovacs Q&A", "eufy Breast Pump Q&A"]:
        for number, row in tables[sheet]:
            pns = [x.strip().upper() for x in str(row["PN"]).split(";") if x.strip()]
            record_id = "qa-" + digest([sheet, number])[:12]
            doc = {"id": record_id, "title": row["Title"], "content": row["Content"], "pns": pns, "pdt": row["PDT"], "visible": row["Status"] == "Published" and row["Consumer Visible"] == "Visible", "source": {"file": FILES[0], "sha256": hashes[FILES[0]], "sheet": sheet, "row": number}, "content_hash": digest(row["Content"])}
            docs.append(doc)
            for pn in pns:
                products.setdefault(pn, {"pn": pn, "pdt": set(), "aliases": set(), "evidence": []})
                products[pn]["pdt"].add(row["PDT"])
                products[pn]["evidence"].append(record_id)
    tickets, unknown_skus = [], []
    for number, row in tables["客诉工单信息"]:
        sku = str(row.get("SKU") or "").strip()
        candidates = [pn for pn in products if sku.upper().startswith(pn)]
        pn = candidates[0] if len(candidates) == 1 else None
        if not pn:
            unknown_skus.append({"source_row": number, "sku": sku, "reason": "no_unique_source_PN_prefix"})
        else:
            products[pn]["aliases"].add(sku.upper())
        tickets.append({"id": f"ticket-{number:03}", "pn": pn, "sku": sku, "text": row["客户首封邮件内容"], "order_number": str(row.get("订单号") or ""), "scene": row["咨询场景"], "source_row": number})
    orders, items = {}, []
    for number, row in tables["订单信息"]:
        order_id = str(row["订单号"] or "")
        if not order_id:
            raise ValueError(f"Unresolved order id at row {number}")
        item = {"source_row": number, "order_number": order_id, "sku": row["SKU"], "description": row["Product Description"], "quantity": row["QTY"], "purchase_date": row["购买日期"], "warranty_end": row["质保结束日期"], "carrier": row["物流承运商"], "tracking": row["物流单号"], "shipping_status": row["物流状态"], "ship_date": row["发货日期"]}
        items.append(item)
        orders.setdefault(order_id, {"order_number": order_id, "status": row["订单状态"], "address": row["订单地址"], "source_rows": []})["source_rows"].append(number)
        candidates = [pn for pn in products if str(row["SKU"]).upper().startswith(pn)]
        # A prefix suggests a candidate, corroboration comes from ticket SKU or PN in description.
        for pn in candidates:
            if str(row["SKU"]).upper() in products[pn]["aliases"] or pn.lower() in str(row["Product Description"]).lower():
                products[pn]["aliases"].add(str(row["SKU"]).upper())
    dealers = sorted({(str(r["country"] or "").strip(), str(r["seller"] or "").strip()) for _, r in tables["经销商信息"]})
    for product in products.values():
        product["aliases"] = sorted(product["aliases"])
        product["pdt"] = sorted(product["pdt"])
    (root / "local").mkdir(exist_ok=True)
    with connect(root) as conn:
        for name in ["documents", "products", "tickets", "orders", "order_items", "dealers"]:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {name} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            conn.execute(f"DELETE FROM {name}")
        datasets = {"documents": [(d["id"], d) for d in docs], "products": list(products.items()), "tickets": [(t["id"], t) for t in tickets], "orders": list(orders.items()), "order_items": [(f"item-{i['source_row']}", i) for i in items], "dealers": [(str(i), {"country": c, "seller": s}) for i, (c, s) in enumerate(dealers)]}
        for name, records in datasets.items():
            conn.executemany(f"INSERT INTO {name} VALUES (?,?)", [(key, json.dumps(record, ensure_ascii=False)) for key, record in records])
    audit = {"schema": 1, "files": hashes, "canonical": FILES[0], "mirror_checks": mirrors, "raw_counts": {name: len(rows) for name, rows in tables.items()}, "qa_total": len(docs), "qa_customer_visible": sum(d["visible"] for d in docs), "orders": len(orders), "order_items": len(items), "dealers_unique": len(dealers), "duplicate_dealers_removed": len(tables["经销商信息"]) - len(dealers), "same_text_qa_extra_records_preserved": len(docs) - len({d["content_hash"] for d in docs}), "unresolved_skus": unknown_skus, "attachment_audit": workbook_audit, "policy": {"raw_private_data": "local/service.sqlite only; ignored by Git", "evaluation_as_of": "2026-10-28", "ticket_outcomes": "unknown; first emails only"}}
    write_json(root / "data/import-audit.json", audit)
    write_json(root / "data/knowledge.json", docs)
    write_json(root / "data/products.json", list(products.values()))
    write_json(root / "data/regression-manifest.json", [{k: t[k] for k in ["id", "pn", "scene", "source_row"]} for t in tickets])
    from .catalog import index_tables
    index_tables(tables, hashes[FILES[0]], source_dir / FILES[0], root)
    return audit


def rows(table, root=ROOT):
    if table not in {"documents", "products", "tickets", "orders", "order_items", "dealers"}:
        raise ValueError("Unknown table")
    with connect(root) as conn:
        return [json.loads(r[0]) for r in conn.execute(f"SELECT payload FROM {table} ORDER BY id")]
