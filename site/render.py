#!/usr/bin/env python3
"""Bounded Study article fixture renderer. Standard library only; no active markup."""
import argparse
import html
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from uuid import UUID

PALETTES = {'Dark': ('#101820', '#e8edf2', '#9ecaff'),
    'Light': ('#ffffff', '#17212b', '#1456a0'), 'Paper': ('#f4efdf', '#29281f', '#214e81')}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def page(title, content, appearance='Dark'):
    background, foreground, accent = PALETTES[appearance]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="color-scheme" content="{"dark" if appearance == "Dark" else "light"}">'
        f'<title>{html.escape(title)}</title><style>:root{{color-scheme:{"dark" if appearance == "Dark" else "light"}}}'
        f'body{{background:{background};color:{foreground};font:18px/1.7 Georgia,serif;margin:0}}'
        f'a{{color:{accent}}}main{{max-width:760px;margin:auto;padding:48px 24px}}'
        'nav,footer{font:15px/1.6 system-ui}article{border:1px solid #647180;border-radius:18px;padding:28px}'
        ':focus-visible{outline:3px solid currentColor;outline-offset:4px}</style></head>'
        f'<body><main>{content}</main></body></html>')


def render(article, base):
    if set(article) != {'schemaVersion', 'id', 'slug', 'title', 'appearance', 'paragraphs', 'references'}:
        raise ValueError('Unsupported article fields')
    if type(article['schemaVersion']) is not int or article['schemaVersion'] != 1:
        raise ValueError('Unsupported schema version')
    if str(UUID(article['id'])) != article['id']: raise ValueError('Noncanonical article ID')
    if not isinstance(article['slug'], str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', article['slug']):
        raise ValueError('Unsafe article path')
    if article['appearance'] not in PALETTES: raise ValueError('Unsupported appearance')
    if not isinstance(article['title'], str) or not article['title'].strip(): raise ValueError('Missing title')
    if not isinstance(article['paragraphs'], list) or not article['paragraphs']:
        raise ValueError('Missing paragraphs')
    if not isinstance(article['references'], list): raise ValueError('Invalid references')
    references = {}
    for position, reference in enumerate(article['references'], 1):
        if set(reference) != {'id', 'title', 'url'} or type(reference['id']) is not int or reference['id'] != position:
            raise ValueError('References must have consecutive numbered IDs')
        if not isinstance(reference['title'], str) or not reference['title'].strip(): raise ValueError('Missing reference title')
        if not isinstance(reference['url'], str) or re.search(r'[\x00-\x20]', reference['url']): raise ValueError('Unsafe reference URL')
        url = urlsplit(reference['url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password: raise ValueError('Unsafe reference URL')
        references[position] = reference

    def citation(match):
        number = int(match[1])
        if number not in references: raise ValueError('Unresolved citation')
        return f'<a href="#reference-{number}" aria-label="Reference {number}">[{number}]</a>'

    paragraphs = []
    for paragraph in article['paragraphs']:
        if not isinstance(paragraph, str) or not paragraph.strip(): raise ValueError('Invalid paragraph')
        paragraphs.append('<p>' + re.sub(r'\[(\d+)\]', citation, html.escape(paragraph)) + '</p>')
    entries = ''.join(f'<li id="reference-{number}"><a href="{html.escape(reference["url"], quote=True)}">'
        f'{html.escape(reference["title"])}</a></li>' for number, reference in references.items())
    body = f'<nav><a href="{base}/">All articles</a></nav><article><h1>{html.escape(article["title"])}</h1>'
    body += ''.join(paragraphs)
    if entries: body += '<section aria-label="References"><h2>References</h2><ol>' + entries + '</ol></section>'
    return page(article['title'], body + '</article>', article['appearance'])


def build(source, output, base, commit):
    if not re.fullmatch(r'[0-9a-f]{40}', commit): raise ValueError('Invalid source commit')
    if not re.fullmatch(r'/[a-z0-9-]+', base): raise ValueError('Invalid site base path')
    pages = []
    for path in sorted(source.glob('*.json')):
        if path.is_symlink(): raise ValueError('Article symlink rejected')
        article = json.loads(path.read_text(), object_pairs_hook=unique_object)
        if path.stem != article['slug']: raise ValueError('Filename and slug mismatch')
        pages.append((article, render(article, base)))
    # Validate every article before creating any candidate output.
    output.mkdir(exist_ok=False)
    links = []
    for article, content in pages:
        folder = output / 'articles' / article['slug']; folder.mkdir(parents=True)
        (folder / 'index.html').write_text(content)
        links.append(f'<li><a href="{base}/articles/{article["slug"]}/">{html.escape(article["title"])}</a></li>')
    (output / 'index.html').write_text(page('Study qualification articles', '<h1>Study qualification articles</h1><ul>' + ''.join(links) + '</ul>'))
    (output / '404.html').write_text(page('Article unavailable', f'<h1>Article unavailable</h1><p>This article is not published.</p><a href="{base}/">All articles</a>'))
    (output / 'qualification.json').write_text(json.dumps({'templateVersion': 1, 'sourceCommit': commit,
        'articleIds': [a['id'] for a, _ in pages], 'articleSlugs': [a['slug'] for a, _ in pages]}, sort_keys=True))


def self_test():
    fixture = {'schemaVersion': 1, 'id': '5bfa0c38-d588-4bd8-b2b1-4f37bdc99b24', 'slug': 'qualification',
        'title': 'Study qualification article', 'appearance': 'Dark', 'paragraphs': ['Literal <script>alert(1)</script> & text. [1]'],
        'references': [{'id': 1, 'title': 'Example source', 'url': 'https://example.com/source'}]}
    rendered = render(fixture, '/study-publishing-qualification')
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered and '&amp;' in rendered
    assert 'href="#reference-1"' in rendered and 'id="reference-1"' in rendered
    for changed in [dict(fixture, slug='../escape'), dict(fixture, schemaVersion=True),
            dict(fixture, paragraphs=['Missing reference [2]']), dict(fixture, secret='Not allowed'),
            dict(fixture, references=[{'id': 1, 'title': 'Bad', 'url': 'javascript:alert(1)'}])]:
        try: render(changed, '/study-publishing-qualification')
        except (ValueError, TypeError): pass
        else: raise AssertionError('Unsafe fixture accepted')
    try: json.loads('{"id":1,"id":2}', object_pairs_hook=unique_object)
    except ValueError: pass
    else: raise AssertionError('Duplicate JSON keys accepted')
    with tempfile.TemporaryDirectory(prefix='study-publishing-check-') as directory:
        root = Path(directory); source = root / 'posts'; source.mkdir()
        (source / 'qualification.json').write_text(json.dumps(fixture))
        build(source, root / 'site', '/study-publishing-qualification', 'a' * 40)
        assert (root / 'site/articles/qualification/index.html').exists()
        (source / 'bad.json').write_text('{"broken":true}')
        try: build(source, root / 'failed', '/study-publishing-qualification', 'b' * 40)
        except (ValueError, KeyError): pass
        else: raise AssertionError('Malformed article accepted')
        assert not (root / 'failed').exists() and (root / 'site/articles/qualification/index.html').exists()
    print('Article escaping, citations, path/schema/link rejection, and failed-candidate preservation pass.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--source', type=Path, default=Path('content/posts'))
    parser.add_argument('--output', type=Path, default=Path('_site'))
    parser.add_argument('--base', default='/study-publishing-qualification')
    parser.add_argument('--commit')
    args = parser.parse_args()
    if args.self_test: self_test()
    else: build(args.source, args.output, args.base, args.commit)
