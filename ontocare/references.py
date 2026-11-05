"""Versioned official article snapshots; original Q&A cells are never rewritten."""
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener, Request

from .data import digest, load_json

HOSTS = {'support.eufy.com', 'service.eufy.com'}


def article_url(value):
    parts = urlsplit(value.strip().rstrip(').,;'))
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.port not in {None, 443} or parts.username or parts.password:
        raise ValueError('unapproved_reference_url')
    if parts.path.startswith('/s/article/'):
        slug = parts.path.removeprefix('/s/article/')
    elif parts.path.startswith('/article-description/'):
        slug = parts.path.removeprefix('/article-description/')
    elif parts.path == '/article-description':
        slug = parse_qs(parts.query).get('urlName', [''])[0]
    else:
        raise ValueError('not_an_article')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', unquote(slug)):
        raise ValueError('invalid_article_slug')
    return 'https://service.eufy.com/article-description/' + slug


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        article_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}: self.skip += 1
        if tag in {'p', 'br', 'li', 'tr', 'h1', 'h2', 'h3'}: self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}: self.skip = max(0, self.skip - 1)
        if tag in {'p', 'li', 'tr'}: self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def extract_article(html):
    match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match: raise ValueError('missing_article_payload')
    payload = json.loads(match[1])
    article = payload['props']['pageProps']['sfArticleInfo']['data']['article']
    parser = ArticleText(); parser.feed(article.get('content') or '')
    text = '\n'.join(re.sub(r'\s+', ' ', line).strip() for line in ''.join(parser.parts).splitlines() if line.strip())
    return {'title': article['title'], 'text': text, 'published_at': article.get('LastPublishedDate'),
            'publisher_id': article.get('id'), 'has_video': bool(article.get('videoLink'))}


def fetch_article(url):
    url = article_url(url)
    with build_opener(OfficialRedirects()).open(Request(url, headers={'User-Agent': 'OntoCare-reference-audit/1.0'}), timeout=30) as response:
        article_url(response.url)
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000: raise ValueError('article_too_large')
        if 'text/html' not in response.headers.get('Content-Type', ''): raise ValueError('not_html')
        result = extract_article(raw.decode('utf-8'))
    return {**result, 'url': url, 'raw_sha256': digest(raw), 'content_sha256': digest(result['text']),
            'status': 'text_available' if len(result['text'].split()) >= 25 else 'video_only' if result['has_video'] else 'missing_text'}


def applicable_pns(title, parent):
    """Intersect explicit article labels with the parent FAQ scope; never widen it."""
    found = set(re.findall(r'\bT[0-9][A-Z0-9]{3}\b', title.upper()))
    labels = {'T2353': r'\bE25\b', 'T2352': r'\bE28\b', 'T2351': r'\bX10 Pro\b',
              'T2280': r'\bC20\b', 'T2292': r'\bC10\b', 'T8170': r'\bSoloCam S340\b'}
    if not re.search(r'breast|pump', title, re.I):
        labels.update({'T2080': r'\bS1 Pro\b', 'T2071': r'\bS1(?! Pro)\b'})
    else: labels['T8D04'] = r'\bS1 Pro\b'
    found.update(pn for pn, pattern in labels.items() if re.search(pattern, title, re.I))
    return sorted(found.intersection(parent['pns']))


class ReferenceStore:
    def __init__(self, root):
        path = root / 'local/reference-snapshots.json'
        self.snapshot = load_json(path) if path.exists() else {'articles': [], 'links': []}
        self.articles = {a['id']: a for a in self.snapshot['articles']}
        self.links = self.snapshot['links']
        self.sha256 = digest(self.snapshot)

    def attach(self, documents, pn):
        attached = []
        for document in documents:
            references = []
            for link in self.links:
                if link['parent_id'] != document['id'] or link['parent_content_hash'] != document['content_hash'] or pn not in link['pns']:
                    continue
                article = self.articles.get(link['reference_id'])
                if article and article['status'] == 'text_available' and digest(article['text']) == article['content_sha256']:
                    references.append({**article, 'pns': link['pns'], 'parent_id': document['id']})
            attached.append({**document, 'references': references})
        return attached
