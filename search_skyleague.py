#!/usr/bin/env python3
"""Search Skyleague draws using exact, cyclic, then shared-item similarity.

Standard library only; Python 3.9+. The default archive is beside this script.
Letters and block numbers are atomic items, not expanded scoring points.
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

TOKEN = re.compile(r'(?:[A-Q]|[1-9]|1[0-9]|2[0-2])\Z')


def parse_dive(value):
    """Accept commas, hyphens, or whitespace; reject ambiguous/malformed input."""
    parts = tuple(re.split(r'[\s,\-–—]+', value.strip().upper()))
    if not parts or any(not TOKEN.fullmatch(p) for p in parts):
        raise ValueError('Use separated formation letters A–Q or block numbers 1–22, e.g. A-B-12-D.')
    return parts


def rotations(items):
    return (items[i:] + items[:i] for i in range(len(items)))


def edges(items):
    """Directed adjacent pairs, including the end-to-start transition."""
    if len(items) < 2:
        return Counter()
    return Counter(zip(items, items[1:] + items[:1]))


def similarity(query, candidate):
    """Return a tiered score, or None for an unhelpful (<3 item) overlap.

    Repeated items count only as often as they occur in both dives.
    Exact and rotation matches remain eligible for one- or two-item queries.
    """
    shared = sum((Counter(query) & Counter(candidate)).values())
    qe, ce = edges(query), edges(candidate)
    shared_pairs = sum((qe & ce).values())
    pair_dice = 2 * shared_pairs / (sum(qe.values()) + sum(ce.values())) if qe or ce else 0
    item_dice = 2 * shared / (len(query) + len(candidate))
    shift = next((i for i, r in enumerate(rotations(candidate)) if r == query), None)
    if query == candidate:
        kind, score = 'exact', 100.0
    elif shift is not None:
        kind, score = 'rotation', 95.0
    elif shared < 3:
        return None
    elif Counter(query) == Counter(candidate):
        kind, score = 'permutation', 80 + 9 * pair_dice
    else:
        kind, score = 'partial', 30 + 49 * (0.75 * item_dice + 0.25 * pair_dice)
    return dict(match_type=kind, score=score, shared_items=shared,
                query_items=len(query), candidate_items=len(candidate),
                shared_cyclic_pairs=shared_pairs, rotation_offset=shift)


def search(archive, query, limit=5, disciplines=('FS4', 'IFS4'), classes=None,
           distinct_events=True, before=None):
    matches = []
    skipped_invalid = 0
    considered = 0
    with Path(archive).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        required = {'event_id', 'event_url', 'event_name', 'start_date', 'end_date',
                    'discipline', 'class', 'round', 'draw', 'draw_status'}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError('Archive missing columns: ' + ', '.join(sorted(missing)))
        for row in reader:
            if row['draw_status'] != 'published':
                continue
            if disciplines and row['discipline'] not in disciplines:
                continue
            if classes and row['class'].upper() not in classes:
                continue
            if before and row['end_date'] >= before.isoformat():
                continue
            try:
                candidate = parse_dive(row['draw'])
            except ValueError:
                skipped_invalid += 1
                continue
            considered += 1
            result = similarity(query, candidate)
            if result is not None:
                matches.append(dict(row, **result))
    # Use full precision for ordering; round only for presentation.
    matches.sort(key=lambda r: (r['score'], r['shared_items'],
                               r['shared_cyclic_pairs'], r['start_date'],
                               r['event_id'], r['class'], r['round']), reverse=True)
    selected, seen = [], set()
    for match in matches:
        if distinct_events and match['event_id'] in seen:
            continue
        seen.add(match['event_id'])
        match['score'] = round(match['score'], 2)
        selected.append(match)
        if len(selected) == limit:
            break
    return {'query': ','.join(query), 'rounds_considered': considered,
            'invalid_published_rows_skipped': skipped_invalid,
            'matching_rounds': len(matches), 'results': selected}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dive', nargs='?', help='Quote the dive, e.g. "A-B-12-D"; omitted: prompt interactively')
    p.add_argument('--archive', type=Path, default=Path(__file__).resolve().with_name('skyleague_draws.csv'))
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--disciplines', default='FS4,IFS4', help='Comma-separated discipline codes (default: FS4,IFS4)')
    p.add_argument('--classes', help='Optional classes, e.g. AAA,AA')
    p.add_argument('--before', type=date.fromisoformat, default=date.today(), help='Exclusive event end-date cutoff, YYYY-MM-DD')
    p.add_argument('--all-rounds', action='store_true', help='Allow several results from the same event')
    p.add_argument('--json', action='store_true', help='Print structured results')
    args = p.parse_args()
    if args.limit < 1:
        p.error('--limit must be positive')
    try:
        query = parse_dive(args.dive if args.dive is not None else input('Dive (e.g. A-B-12-D): '))
        result = search(args.archive, query, args.limit,
                        tuple(x.strip().upper() for x in args.disciplines.split(',') if x.strip()),
                        {x.strip().upper() for x in args.classes.split(',')} if args.classes else None,
                        not args.all_rounds, args.before)
    except (OSError, ValueError, EOFError) as exc:
        p.exit(2, f'Error: {exc}\n')
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"Dive: {result['query']} | Searched {result['rounds_considered']:,} published rounds")
    if not result['results']:
        print('No matches: no exact/rotation match or candidate sharing at least 3 items.')
    for i, row in enumerate(result['results'], 1):
        print(f"\n{i}. {row['score']:.2f}/100 — {row['match_type']} — {row['draw']}")
        print(f"   {row['event_name']} | {row['start_date']} | {row['discipline']} | {row['class']} | Round {row['round']}")
        print(f"   Shared items: {row['shared_items']}/{row['query_items']} query, "
              f"{row['shared_items']}/{row['candidate_items']} candidate; "
              f"shared cyclic adjacent pairs: {row['shared_cyclic_pairs']}")
        if row['match_type'] == 'rotation':
            print(f"   Start the archived dive at item {row['rotation_offset'] + 1} to match your input.")
        print(f"   {row['event_url']}")
    if result['invalid_published_rows_skipped']:
        print(f"\nSkipped {result['invalid_published_rows_skipped']} malformed published sequences.", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
