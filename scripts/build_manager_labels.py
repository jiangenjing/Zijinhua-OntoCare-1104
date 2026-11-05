"""Source-checked Chinese display titles; no changes to retrieval documents."""
from pathlib import Path
import re
import sys

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ontocare.data import ROOT, digest, load_json, write_json


def main():
    source = ROOT.parent / '黑客松智能服务赛题资料_中文对照版.xlsx'
    book = openpyxl.load_workbook(source, read_only=True, data_only=True)
    documents = {(d['source']['sheet'], d['source']['row']): d for d in load_json(ROOT / 'data/knowledge.json')}
    titles = {}
    for sheet, original, chinese in [
        ('eufy Robovacs Q&A', '原文-Robovacs Q&A', '扫地机问答中文'),
        ('eufy Breast Pump Q&A', '原文-Breast Pump Q&A', '吸奶器与摄像头问答中文'),
    ]:
        for name in [original, chinese]:
            book[name].reset_dimensions()
        originals = {i: row for i, row in enumerate(book[original].values, 1) if i > 1 and len(row) > 4 and row[3]}
        translations = {i: row for i, row in enumerate(book[chinese].values, 1) if i > 1 and len(row) > 4 and row[3]}
        for number, raw in originals.items():
            doc = documents[sheet, number]
            if (raw[3], raw[4]) != (doc['title'], doc['content']):
                raise ValueError(f'Translation source differs: {sheet} row {number}')
            translated = translations[number]
            if raw[8] != translated[8] or not re.search(r'[\u4e00-\u9fff]', translated[3]):
                raise ValueError(f'Missing Chinese title or mismatched PN: {sheet} row {number}')
            titles[doc['id']] = {'title': translated[3], 'source_title_sha256': digest(doc['title'])}
    book.close()
    if len(titles) != len(documents):
        raise ValueError('Chinese title coverage differs from knowledge records')
    write_json(ROOT / 'web/manager-titles-zh.json', {'source': source.name, 'source_sha256': digest(source.read_bytes()),
               'knowledge_sha256': digest(load_json(ROOT / 'data/knowledge.json')), 'purpose': 'Existing Chinese title reference for display only; English remains authoritative', 'titles': titles})
    print(f'Validated Chinese display titles: {len(titles)}')


if __name__ == '__main__':
    main()
