#!/usr/bin/env python3
"""Render only versioned Study article JSON into static public pages."""
import argparse
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import UUID

PALETTES = {'Dark': ('#101820', '#e8edf2', '#9ecaff'),
            'Light': ('#ffffff', '#17212b', '#1456a0'),
            'Paper': ('#f4efdf', '#29281f', '#214e81')}
TAGS = {'p', 'h2', 'ul', 'li', 'strong', 'em', 'u', 'a', 'section', 'ol'}


def escape(value):
    return html.escape(value, quote=True).replace('&#x27;', '&#39;')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


class ArticleFragment(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []
        self.markers = set()
        self.references = []

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else None
        if tag not in TAGS or (
                (tag in {'p', 'ul', 'section'} and parent is not None) or
                (tag == 'h2' and parent not in {None, 'section'}) or
                (tag == 'ol' and parent != 'section') or
                (tag == 'li' and parent not in {'ul', 'ol'}) or
                (tag in {'a', 'em', 'strong', 'u'} and parent not in {'p', 'h2', 'li', 'a', 'em', 'strong', 'u'}) or
                (tag == 'a' and 'a' in self.stack)):
            raise ValueError('Unsupported article markup')
        if len({name for name, _ in attrs}) != len(attrs):
            raise ValueError('Duplicate HTML attribute')
        fields = dict(attrs)
        if tag == 'section':
            if fields != {'aria-label': 'References'} or self.stack:
                raise ValueError('Invalid References section')
        elif tag == 'li' and fields:
            if parent != 'ol' or set(fields) != {'id'} or not re.fullmatch(r'reference-[1-9][0-9]*', fields['id']):
                raise ValueError('Invalid reference entry')
            number = int(fields['id'].split('-')[1])
            if number in self.references:
                raise ValueError('Duplicate reference entry')
            self.references.append(number)
        elif tag == 'li' and parent == 'ol':
            raise ValueError('Missing reference ID')
        elif tag == 'a':
            href = fields.get('href')
            if href is None or set(fields) - {'href', 'aria-label'}:
                raise ValueError('Invalid article link')
            if href.startswith('#'):
                if not re.fullmatch(r'#reference-[1-9][0-9]*', href) or fields.get('aria-label') != 'Reference ' + href.split('-')[1]:
                    raise ValueError('Invalid citation marker')
                self.markers.add(int(href.split('-')[1]))
            else:
                address = urlsplit(href)
                if (address.scheme != 'https' or not address.hostname or address.username or address.password
                        or re.search(r'[\x00-\x20\x7f]', href) or 'aria-label' in fields):
                    raise ValueError('Unsafe article link')
        elif fields:
            raise ValueError('Unsupported HTML attribute')
        self.stack.append(tag)
        self.parts.append('<' + tag + ''.join(f' {name}="{escape(value)}"' for name, value in attrs) + '>')

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            raise ValueError('Unbalanced article markup')
        self.stack.pop()
        self.parts.append(f'</{tag}>')

    def handle_data(self, value):
        if not self.stack and value.strip():
            raise ValueError('Text outside article block')
        self.parts.append(escape(value))

    def handle_startendtag(self, tag, attrs):
        raise ValueError('Unsupported empty tag')

    def handle_comment(self, data):
        raise ValueError('Comments are not article content')

    def handle_decl(self, decl):
        raise ValueError('Declarations are not article content')

    def handle_pi(self, data):
        raise ValueError('Processing instructions are not article content')

    def validated(self, source):
        if not isinstance(source, str) or not source or len(source) > 200_000 or 'study://' in source.lower():
            raise ValueError('Invalid article body')
        self.feed(source)
        self.close()
        if self.stack or ''.join(self.parts) != source:
            raise ValueError('Noncanonical article markup')
        if self.references != list(range(1, len(self.references) + 1)) or self.markers != set(self.references):
            raise ValueError('Unmatched article citation')
        return source


def validate(article):
    required = {'schemaVersion', 'id', 'slug', 'title', 'appearance', 'bodyHTML'}
    if not isinstance(article, dict) or not required <= set(article) or set(article) - required - {'author'}:
        raise ValueError('Unsupported article fields')
    if type(article['schemaVersion']) is not int or article['schemaVersion'] != 1:
        raise ValueError('Unsupported article schema')
    if not isinstance(article['id'], str) or str(UUID(article['id'])) != article['id']:
        raise ValueError('Invalid article ID')
    if article['slug'] != 'article-' + article['id']:
        raise ValueError('Invalid article path')
    if (not isinstance(article['title'], str) or not article['title'].strip() or len(article['title']) > 200
            or any(ord(char) < 32 or ord(char) == 127 for char in article['title'])):
        raise ValueError('Invalid article title')
    if article['appearance'] not in PALETTES:
        raise ValueError('Invalid appearance')
    if 'author' in article and article['author'] is not None and (
            not isinstance(article['author'], str) or not article['author'].strip() or len(article['author']) > 120
            or any(ord(char) < 32 or ord(char) == 127 for char in article['author'])):
        raise ValueError('Invalid author')
    ArticleFragment().validated(article['bodyHTML'])


def render(article):
    validate(article)
    background, foreground, accent = PALETTES[article['appearance']]
    mode = 'dark' if article['appearance'] == 'Dark' else 'light'
    byline = f'<p class="byline">By {escape(article["author"])}</p>' if article.get('author') else ''
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="{mode}"><meta name="referrer" content="no-referrer">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            f'<title>{escape(article["title"])}</title><style>:root{{color-scheme:{mode}}}'
            f'body{{background:{background};color:{foreground};font:18px/1.7 Georgia,serif;margin:0}}'
            f'a{{color:{accent}}}main{{max-width:760px;margin:auto;padding:48px 24px}}'
            'article{border:1px solid #647180;border-radius:18px;padding:28px}'
            'h1,h2{line-height:1.25}p,li{overflow-wrap:anywhere}.byline{font:15px system-ui;opacity:.85}'
            ':focus-visible{outline:3px solid currentColor;outline-offset:4px}</style></head><body><main><article>'
            f'<h1>{escape(article["title"])}</h1>{byline}{article["bodyHTML"]}</article></main></body></html>')


def build(source, output, base, commit):
    if not re.fullmatch(r'/[a-z0-9-]+', base) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid site identity')
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Missing article source directory')
    pages = []
    for path in sorted(source.glob('*.json')):
        if path.is_symlink() or path.stat().st_size > 250_000:
            raise ValueError('Unsafe article file')
        article = json.loads(path.read_text(), object_pairs_hook=unique_object)
        if path.stem != article.get('slug'):
            raise ValueError('Article path mismatch')
        pages.append((article, render(article)))
    output.mkdir(exist_ok=False)
    links = []
    for article, page in pages:
        folder = output / 'articles' / article['slug']
        folder.mkdir(parents=True)
        (folder / 'index.html').write_text(page)
        links.append(f'<li><a href="{base}/articles/{article["slug"]}/">{escape(article["title"])}</a></li>')
    shell = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta name="color-scheme" content="dark"><meta name="referrer" content="no-referrer">'
             '<style>:root{color-scheme:dark}body{background:#101820;color:#e8edf2;font:18px/1.7 Georgia,serif;margin:0}'
             'main{max-width:760px;margin:auto;padding:48px 24px}a{color:#9ecaff}:focus-visible{outline:3px solid currentColor;outline-offset:4px}'
             '</style>')
    index = '<h1>Articles</h1><ul>' + ''.join(links) + '</ul>'
    (output / 'index.html').write_text(shell + '<title>Study articles</title></head><body><main>' + index + '</main></body></html>')
    (output / '404.html').write_text(shell + '<title>Article unavailable</title></head><body><main><h1>Article unavailable</h1><p>This article is not published.</p><a href="' + base + '/">All articles</a></main></body></html>')
    (output / 'publication.json').write_text(json.dumps({'schemaVersion': 1, 'sourceCommit': commit,
        'articleIds': [article['id'] for article, _ in pages]}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--article', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--base')
    parser.add_argument('--commit')
    args = parser.parse_args()
    if args.article:
        print(render(json.loads(args.article.read_text(), object_pairs_hook=unique_object)), end='')
    else:
        if not all((args.source, args.output, args.base, args.commit)):
            parser.error('Site build requires source, output, base and commit')
        build(args.source, args.output, args.base, args.commit)
