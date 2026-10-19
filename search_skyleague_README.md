# Search the Skyleague draw archive

Place `search_skyleague.py` beside `skyleague_draws.csv`. Requires Python 3.9+; no packages to install.

```bash
python3 search_skyleague.py "A-B-C-D"
python3 search_skyleague.py "11,16,10"
python3 search_skyleague.py "A B 12 D" --classes AAA
python3 search_skyleague.py "A-B-C-D" --json
```

Run without a dive to enter it at a prompt. Defaults to the top five distinct events in FS4 and IFS4, with event links. Exact ties use the more recent event first. `--all-rounds` allows multiple rounds/classes from one event. `--limit 10` returns more matches. `--archive PATH` selects another CSV. `--before 2025-01-01` restricts results to events ending before that date.

To include the 4-way Cloud League sequences too:

```bash
python3 search_skyleague.py "A-B-C-D" --disciplines FS4,IFS4,FS4X6,IFS4X6
```

## Similarity scores

These are ranking scores, not probabilities. A formation letter or block number is one atomic item: block 12 does not count as two items. Order matters; rotations preserve order and do not reverse it. Repeated items are matched by occurrence count.

| Match | Score | Meaning |
| --- | --- | --- |
| Exact | 100 | Identical items in identical order |
| Rotation | 95 | Identical cyclic order with a different starting item |
| Other full permutation | 80–89 | Same items and counts, in another order |
| Partial overlap | 30–79 (exclusive upper bound) | At least three shared items, with missing or additional items |
| Fewer than three shared items | Excluded | Except an exact or rotation match to a shorter input |

Within the permutation tier, the score is `80 + 9 × pair_similarity`.

For partial matches, it is `30 + 49 × (0.75 × item_similarity + 0.25 × pair_similarity)`.

- `item_similarity = 2 × shared_item_count / (query_length + candidate_length)`.
- `pair_similarity` uses the same formula for shared **directed adjacent pairs**, including the final-to-first transition because dives repeat cyclically.
- Pair counts are multisets, so repeated items or pairs cannot inflate the overlap beyond their actual occurrences.

This guarantees exact > rotation > other full permutation > partial overlap. Within partial matches, it rewards greater overlap, penalizes extra/missing items, and gives a bonus for preserving adjacent order. Three non-sequential shared items remain eligible; two shared items never qualify as a partial match.

For `A-B-C-D`, examples are:

| Archived dive | Type | Score |
| --- | --- | --- |
| A-B-C-D | Exact | 100 |
| B-C-D-A | Rotation | 95 |
| A-C-B-D | Permutation | 82.25 |
| A-B-C-E | Partial | 63.69 |
| A-C-B-E | Partial | 57.56 |
| A-B-E-F | Excluded | — |

Only published, valid sequences are searched. Missing/TBD entries are excluded; malformed sequences marked published by the source are counted and skipped. The archive is a snapshot: rerun the scraper to obtain newer events. Some published rounds may not have been flown. Different disciplines can use different dive pools, so change `--disciplines` deliberately rather than mixing 4-way and 8-way.
