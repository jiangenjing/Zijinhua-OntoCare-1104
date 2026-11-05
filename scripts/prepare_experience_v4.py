"""Fix source-grounded identifier roles, retaining the original experience wording."""
import sys,shutil,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from ontocare.data import write_json,digest
BASE=ROOT/'local/customer-service-v2/experience548';src=BASE/'v1';dst=BASE/'v4';assert not dst.exists();dst.mkdir()
for folder in ['ontocare','prompts','data','ontology']:shutil.copytree(src/folder,dst/folder,ignore=shutil.ignore_patterns('__pycache__'))
for folder in ['web','actions','skills','evaluation','reports','docs']:(dst/folder).symlink_to(ROOT/folder,target_is_directory=True)
(dst/'local').mkdir()
for p in (src/'local').iterdir():
 if p.is_file() and p.suffix=='.sqlite':
  with sqlite3.connect(p) as source,sqlite3.connect(dst/'local'/p.name) as target:source.backup(target)
 elif p.is_file() and not p.name.endswith(('-wal','-shm')):(dst/'local'/p.name).symlink_to(p.resolve())
(dst/'local/customer-service-v2').symlink_to(ROOT/'local/customer-service-v2',target_is_directory=True)
p=dst/'ontocare/agent.py';s=p.read_text();s=s.replace("dealer_only = skill == 'aftersales' and bool(re.search(","dealer_only = skill == 'aftersales' and bool(business_context.get('dealer_check') or re.search(")
needle='    def identify(self, text):\n'
insert=r'''        # A source-documented accessory SKU must not become a second host model
        # merely because its prefix matches a main-device SKU alias.
        known_models = {p['pn'] for p in self.products}
        explicit_models = set(re.findall(r"(?<![A-Z0-9])T[0-9][A-Z0-9]{3}(?![A-Z0-9])", text.upper())) & known_models
        if len(explicit_models) == 1:
            host = next(iter(explicit_models))
            for accessory in re.findall(r"(?<![A-Z0-9])T[0-9][A-Z0-9]{4,}(?:-[A-Z0-9]+)*(?![A-Z0-9])", text.upper()):
                if any(host in d['pns'] and accessory in (d['title'] + ' ' + d['content']).upper()
                       and re.search(r'flange|insert|accessor|attachment|法兰|配件', d['title'] + ' ' + d['content'], re.I)
                       for d in self.retriever.docs):
                    text = re.sub(re.escape(accessory), '', text, flags=re.I)
'''
assert needle in s;s=s.replace(needle,needle+insert);p.write_text(s)
p=dst/'ontocare/prompting.py';s=p.read_text().replace('"customer-experience-v1" if customer_experience','"customer-experience-v4-roles" if customer_experience');p.write_text(s)
write_json(BASE/'v4-changes.json',{'baseline':'v1','changes':['Retain v1 customer Prompt and Skill unchanged','Use already-returned dealer object in purchase-evidence routing','Separate source-documented accessory SKU role from explicitly identified host model; keep original query and evidence unchanged'],'identifier_policy':'Only suppress an accessory alias when exactly one explicit known host PN exists, and a source scoped to it contains the full accessory code and an accessory role word. Unknown codes and actual multiple host PNs stay ambiguous.','unchanged':['source records and Gold','primary Judge','retrieval and reranker','product-scope and safety validators'],'code_sha256':digest((dst/'ontocare/agent.py').read_bytes())})
print('V4 FROZEN',flush=True)
