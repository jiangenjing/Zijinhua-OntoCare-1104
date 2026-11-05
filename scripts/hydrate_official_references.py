"""Fetch only official article URLs already present in visible source Q&A."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from ontocare.data import load_json, write_json, digest
from ontocare.references import article_url, fetch_article, applicable_pns


def main():
    docs = [d for d in load_json(ROOT / 'data/knowledge.json') if d['visible']]
    links = []; urls = set(); pending = []
    for d in docs:
        for value in set(re.findall(r'https?://[^\s<>"\[\]]+', d['content'])):
            try: url = article_url(value)
            except ValueError:
                pending.append({'parent_id': d['id'], 'url': value, 'status': 'not_approved_article_or_media_unparsed'}); continue
            urls.add(url); links.append((d, url))
    folder = ROOT / 'local/source-hydration'; folder.mkdir(exist_ok=True)
    def one(url):
        path = folder / (digest(url) + '.json')
        if path.exists(): return load_json(path)
        try: result = fetch_article(url)
        except Exception as error: result = {'url': url, 'status': 'fetch_failed', 'error': type(error).__name__}
        result.update({'id': 'reference-' + digest(url)[:16], 'retrieved_at': datetime.now(timezone.utc).isoformat()})
        write_json(path, result); return result
    articles = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(one, url) for url in sorted(urls)]):
            articles.append(future.result())
            if len(articles) % 20 == 0: print('official references', len(articles), '/', len(urls), flush=True)
    by_url = {a['url']: a for a in articles}; mappings = []
    for parent, url in links:
        article = by_url[url]
        pns = applicable_pns(article.get('title', ''), parent)
        status = 'scoped_text' if article['status'] == 'text_available' and pns else 'scope_pending' if article['status'] == 'text_available' else article['status']
        mappings.append({'parent_id': parent['id'], 'parent_content_hash': parent['content_hash'], 'reference_id': article['id'],
                         'pns': pns if status == 'scoped_text' else [], 'status': status})
    snapshot = {'schema_version': 1, 'articles': sorted(articles, key=lambda a: a['id']),
                'links': sorted(mappings, key=lambda a: (a['parent_id'], a['reference_id']))}
    write_json(ROOT / 'local/reference-snapshots.json', snapshot)
    public = {'snapshot_sha256': digest(snapshot), 'articles': len(articles), 'article_status': dict(Counter(a['status'] for a in articles)),
              'links': len(mappings), 'link_status': dict(Counter(a['status'] for a in mappings)), 'media_or_unapproved': len(pending),
              'source_cells_rewritten': False, 'evaluations_read': False, 'pending': pending,
              'references': [{k: v for k, v in a.items() if k != 'text'} for a in snapshot['articles']], 'mappings': snapshot['links']}
    write_json(ROOT / 'reports/workbench-v5/reference-audit.json', public)
    print({k: v for k, v in public.items() if k not in {'references', 'mappings', 'pending'}}, flush=True)


if __name__ == '__main__': main()
