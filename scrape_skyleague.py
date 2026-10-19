#!/usr/bin/env python3
"""Export published Skyleague event draws. Requires requests and beautifulsoup4.

python3 -m pip install requests beautifulsoup4
python3 scrape_skyleague.py --output skyleague_draws.csv

Defaults to 1900 through today (completed events only). Use --disciplines
FS4,IFS4 for conventional outdoor/indoor 4-way, or omit for all disciplines.
An accompanying .coverage.csv records events without draws and failed pages.
HTML is cached so interrupted runs can restart without downloading it again.
This exports published draws, not proof that every drawn round was flown.
"""

import argparse
import csv
import hashlib
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = 'https://www.skyleague.com'
FIELDS = ['event_id', 'event_name', 'start_date', 'end_date', 'league',
          'discipline', 'venue', 'class', 'round', 'draw', 'draw_raw',
          'draw_status', 'scoreboard_number', 'event_url']
META = ['event_id', 'event_name', 'start_date', 'end_date', 'league',
        'discipline', 'venue', 'event_url']
DATE_RE = re.compile(r'([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})')


def text(node):
    return node.get_text(' ', strip=True).replace('\xa0', ' ')


def dates(value):
    result = []
    for month, day, year in DATE_RE.findall(value):
        result.append(datetime.strptime(f'{month[:3]} {day} {year}', '%b %d %Y').date())
    return result


class Fetcher:
    def __init__(self, cache, delay, refresh):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.delay, self.refresh, self.last = delay, refresh, 0.0
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'SkyleagueDrawArchive/1.0 (personal research scraper)'

    def get(self, url):
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + '.html')
        if path.exists() and not self.refresh:
            return BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
        for attempt in range(4):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
            try:
                self.last = time.monotonic()
                response = self.session.get(url, timeout=45)
                response.raise_for_status()
                html = response.content.decode(response.apparent_encoding or 'utf-8', errors='replace')
                soup = BeautifulSoup(html, 'html.parser')
                if not soup.select_one('#content_container'):
                    raise ValueError('Unexpected page (missing content container)')
                temp = path.with_suffix('.tmp')
                temp.write_text(html, encoding='utf-8')
                temp.replace(path)
                return soup
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))


def events_from_page(soup):
    table = soup.select_one('table.eventboard')
    if table is None:
        raise ValueError('Event archive table missing; layout may have changed')
    for row in table.select('tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) < 5:
            continue
        link = cells[2].find('a', href=re.compile(r'^/events/\d+/?$'))
        if not link:
            continue
        ds = dates(text(cells[3]))
        yield dict(event_id=re.search(r'\d+', link['href']).group(),
                   event_name=text(link), start_date=ds[0].isoformat() if ds else '',
                   end_date=ds[-1].isoformat() if ds else '', league=text(cells[0]),
                   discipline=text(cells[1]), venue=text(cells[4]),
                   event_url=urljoin(BASE, link['href']))


def draw_rows(soup, event):
    for number, table in enumerate(soup.select('table.scoreboard'), 1):
        labels = [text(c) for c in table.select('th.roundlabel')]
        headers = table.select('tr.scoreboard_class_header')
        # Some event schedules reuse scoreboard CSS classes but contain no scores.
        headers = [h for h in headers if h.find(['td', 'th'])
                   and text(h.find(['td', 'th'])).lower() == 'rank']
        if not headers:
            continue
        if not labels and all([text(c) for c in h.find_all(['td', 'th'], recursive=False)][2:]
                              in (['Total', 'Avg'], ['Total']) for h in headers):
            # A listed event may have teams but no rounds/draw published.
            continue
        if not labels and headers:
            raise ValueError('Scoreboard has draw headers but no round labels')
        cloud = bool(labels) and all(x in {'AAA', 'AA', 'A', 'RRR', 'RR', 'R'} for x in labels)
        for header in headers:
            cells = header.find_all(['td', 'th'], recursive=False)
            if len(cells) < 2 + len(labels):
                raise ValueError('Draw cells do not match scoreboard labels')
            for label, cell in zip(labels, cells[2:2 + len(labels)]):
                raw = text(cell)
                normalized = re.sub(r'\s+', '', raw.upper())
                status = ('missing' if not normalized else
                          'published' if re.fullmatch(r'[A-Z0-9]+(?:,[A-Z0-9]+)*', normalized)
                          and normalized not in {'TBD', 'NA', 'NONE'} else 'unresolved')
                yield dict(event, **{'class': label if cloud else re.sub(r'\s+Class$', '', text(cells[1])),
                                    'round': '1' if cloud else label,
                                    'draw': normalized if status == 'published' else '',
                                    'draw_raw': raw, 'draw_status': status,
                                    'scoreboard_number': number})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=Path('skyleague_draws.csv'))
    parser.add_argument('--start-year', type=int, default=1900)
    parser.add_argument('--end-year', type=int, default=date.today().year)
    parser.add_argument('--before', type=date.fromisoformat, default=date.today(), help='Exclusive end-date cutoff, YYYY-MM-DD')
    parser.add_argument('--disciplines', help='Comma-separated codes; default: all')
    parser.add_argument('--delay', type=float, default=1.0, help='Minimum seconds between requests')
    parser.add_argument('--cache-dir', type=Path, default=Path('.skyleague-cache'))
    parser.add_argument('--refresh', action='store_true', help='Download again instead of using cached pages')
    parser.add_argument('--max-events', type=int, help='Limit event downloads for a smoke test')
    args = parser.parse_args()
    if not 1 <= args.start_year <= args.end_year <= date.today().year or args.delay < 0:
        parser.error('Use a valid past/current year range and a nonnegative delay')
    if args.max_events is not None and args.max_events < 1:
        parser.error('--max-events must be positive')
    allowed = {x.strip().upper() for x in args.disciplines.split(',')} if args.disciplines else None
    fetch = Fetcher(args.cache_dir, args.delay, args.refresh)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    coverage = args.output.with_suffix('.coverage.csv')
    seen, failures, count, written, missing = set(), 0, 0, 0, 0
    with args.output.open('w', newline='', encoding='utf-8-sig') as output, coverage.open('w', newline='', encoding='utf-8-sig') as audit:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        reporter = csv.DictWriter(audit, fieldnames=META + ['status', 'rows', 'error'])
        writer.writeheader()
        reporter.writeheader()
        for year in range(args.end_year, args.start_year - 1, -1):
            url = f'{BASE}/events/?startdate={year:04d}-01-01'
            print(f'Archive {year}', file=sys.stderr, flush=True)
            try:
                events = list(events_from_page(fetch.get(url)))
            except Exception as exc:
                failures += 1
                reporter.writerow({'event_url': url, 'status': 'archive_error', 'error': str(exc)})
                audit.flush()
                continue
            for event in events:
                if event['event_id'] in seen:
                    continue
                seen.add(event['event_id'])
                if not event['end_date']:
                    failures += 1
                    reporter.writerow(dict(event, status='date_error', error='Unrecognized event date'))
                    continue
                if date.fromisoformat(event['end_date']) >= args.before:
                    continue
                if allowed and event['discipline'] not in allowed:
                    continue
                count += 1
                print(f"  {count}: {event['start_date']} {event['event_name']} ({event['event_id']})", file=sys.stderr, flush=True)
                try:
                    rows = list(draw_rows(fetch.get(event['event_url']), event))
                    writer.writerows(rows)
                    written += len(rows)
                    status = 'ok' if rows and all(r['draw_status'] == 'published' for r in rows) else 'partial_draw' if rows else 'no_published_draw'
                    missing += status != 'ok'
                    reporter.writerow(dict(event, status=status, rows=len(rows)))
                except Exception as exc:
                    failures += 1
                    reporter.writerow(dict(event, status='event_error', error=str(exc)))
                output.flush()
                audit.flush()
                if args.max_events and count >= args.max_events:
                    break
            if args.max_events and count >= args.max_events:
                break
    print(f'Wrote {written} round rows from {count} attempted events to {args.output}.\n'
          f'{failures} errors; {missing} events with missing/partial draws. Coverage: {coverage}', file=sys.stderr)
    if args.max_events:
        print('Limited test run: this is not the full archive.', file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
