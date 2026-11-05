"""Read-only row/field comparison against all supplied canonical workbooks."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ontocare.data import read_tables
from ontocare.business import coverage


def audit():
    parent=ROOT.parent
    canonical=parent/'黑客松智能服务赛题资料.xlsx'
    tables,_=read_tables(canonical)
    results=[]
    with sqlite3.connect((ROOT/'local/business.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as conn:
        for sheet,rows in tables.items():
            stored={n:json.loads(payload) for n,payload in conn.execute('SELECT rownum,payload FROM raw_rows WHERE sheet=?',(sheet,))}
            mismatched=[n for n,r in rows if stored.get(n)!=r]
            results.append({'sheet':sheet,'source_rows':len(rows),'stored_rows':len(stored),'field_count':len(rows[0][1]),'mismatched_rows':mismatched,'exact_match':len(rows)==len(stored) and not mismatched})
    mirrors=[]
    for name,sheet in [('客诉工单信息.xlsx','客诉工单信息'),('eufy Robovacs Q&A.xlsx','eufy Robovacs Q&A'),('eufy Breast Pump Q&A.xlsx','eufy Breast Pump Q&A')]:
        records,_=read_tables(parent/name)
        rows=records.get(sheet,next(iter(records.values())))
        mirrors.append({'file':name,'sha256':sha256((parent/name).read_bytes()).hexdigest(),'rows':len(rows),'matches_master':rows==tables[sheet]})
    brief=next(parent.glob('*智能客服赛题*.docx'))
    with ZipFile(brief) as z:
        root=ET.fromstring(z.read('word/document.xml'));ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs=[''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in root.findall('.//w:p',ns)]
        media=[n for n in z.namelist() if n.startswith('word/media/')]
    return {'scope':'用户提供的本地正式工作簿、拆分镜像与赛题 Word；不是远程飞书资料的完整性认证',
            'master':{'file':canonical.name,'sha256':sha256(canonical.read_bytes()).hexdigest(),'sheets':results},'mirror_files':mirrors,
            'brief':{'file':brief.name,'sha256':sha256(brief.read_bytes()).hexdigest(),'nonempty_paragraphs':sum(bool(p) for p in paragraphs),'embedded_images':media,'business_sop_image':'image1.jpeg，已按原图核对转录4条 SOP 建议规则，尚待业务人员确认；另1条销售方规则来自正文','decorative_image':'image2.png，色块与水印，不作为业务事实'},
            'business_counts':coverage(ROOT)['node_counts'],
            'gaps':['飞书远程资料和百炼教程未验证，不宣称全部远程材料已读','工单嵌入图与外部附件已定位，内容未自动核验','满意度调查、正式寄修、补发、退款与换货系统未接通','统一退款/换货申请对象尚未落地，现有 Action 是本地通用复核任务'],
            'source_rows_passed':all(r['exact_match'] for r in results),'mirrors_passed':all(r['matches_master'] for r in mirrors)}


if __name__=='__main__':
    result=audit();out=ROOT/'reports/final-source-audit.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
