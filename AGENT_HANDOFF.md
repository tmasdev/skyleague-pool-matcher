# Skyleague draw archive and similarity search — agent handoff

Last updated: 19 October 2026. This document describes the completed project and its current limitations; it is not a request to perform the suggested future work automatically.

## Purpose and user requirements

The user wants to enter a formation-skydiving dive and find previous competitions with similar rounds, with a direct Skyleague event link for every result.

Completed requests:

1. Investigate whether https://www.skyleague.com/ has a draw-search endpoint. No public sequence-search endpoint was found. Public pages expose year/league filters and HTML scoreboards; absence of an undocumented API was not proven.
2. Create and run a Python scraper for past competition draws into CSV.
3. Preserve an event-page link on every draw row.
4. Create a search script returning the top five most similar historical dives and their event links, prioritizing:
   - Exact ordered matches.
   - Cyclic rotations, e.g. A-B-C-D matches B-C-D-A.
   - Other permutations and partial matches sharing at least three items. Two-item partial overlaps are too common to be useful.
5. Write this handoff.

No UI, hosted service, scheduled refresh, or database has been requested or built. Both scripts are local command-line programs. The full scrape and recovery have finished; no scrape is intentionally left running.

## Location and files

Workspace root:

```text
/Users/thomasgale/Documents/Codex/2026-10-19/for-tyh
```

Paths below are relative to that root. Preserve `outputs/` for user-facing deliverables and `work/` for intermediate files.

| File | Purpose |
| --- | --- |
| `outputs/scrape_skyleague.py` | Scraper, including fixes discovered during the full run |
| `outputs/skyleague_draws.csv` | Final, recovered draw archive |
| `outputs/skyleague_draws.coverage.csv` | One coverage row per checked event |
| `outputs/search_skyleague.py` | Search CLI and importable parsing/scoring/search functions |
| `outputs/search_skyleague_README.md` | User-facing usage and scoring explanation |
| `outputs/AGENT_HANDOFF.md` | This document |
| `work/cache/` | Downloaded HTML; filenames are SHA-256 hashes of full request URLs |
| `work/test_search_skyleague.py` | Four unittest cases for search behavior; run from workspace root |
| `work/final-summary.json` | Statistics from final archive reconciliation |
| `work/recover.py` | One-off recovery helper; not a supported general-purpose resume command |
| `work/recovered.csv`, `work/recovered-coverage.csv` | Recovery intermediates already merged into the final files |
| Other `work/` CSVs and JSON | Small tests and example search output, not the complete archive |

The scripts and CSV must remain available together for the searcher's default archive path. Search uses the CSV beside its own script, independent of the working directory. Scraper output/cache defaults are relative to the working directory.

## Running the project

Python 3.9+ is the intended baseline. Search uses only the standard library; scraping requires `requests` and `beautifulsoup4`.

From the workspace root:

```bash
python3 -m pip install requests beautifulsoup4
python3 outputs/search_skyleague.py "A-B-C-D"
python3 outputs/search_skyleague.py "P,7,9" --classes AAA --json
python3 work/test_search_skyleague.py
```

Search options:

- Omit the positional dive to enter it interactively.
- `--limit 5` is the default.
- `--disciplines FS4,IFS4` is the default; Cloud League can be included with `FS4,IFS4,FS4X6,IFS4X6`.
- `--classes AAA,AA` restricts classes; all classes are included by default.
- `--all-rounds` permits multiple results from one event. Otherwise the best matching row per event is returned.
- `--before YYYY-MM-DD` excludes events whose end date is on or after the cutoff. CLI default is the machine's current date.
- `--archive PATH` selects another archive; `--json` emits structured results.

For a small scraper test, write into `work/`, not over the final archive:

```bash
python3 outputs/scrape_skyleague.py --start-year 2026 --end-year 2026 --before 2026-10-19 --max-events 3 --cache-dir work/cache --output work/smoke.csv
```

To rebuild the historical snapshot using cached HTML, also use a separate output first:

```bash
python3 outputs/scrape_skyleague.py --start-year 1900 --end-year 2026 --before 2026-10-19 --cache-dir work/cache --output work/rebuilt.csv
```

For fresh network data use `--refresh`. It redownloads everything selected, including historical pages. Without it, cache entries never expire, so current-year listings can remain stale. The scraper opens its output files in write mode at startup: do not test or run a partial refresh against the delivered filenames. Validate and merge/replace intentionally afterward. HTML caching saves network work; it is not an incremental CSV checkpoint system.

## Archive snapshot and schema

The full scrape scanned annual event listings for 1900–2026, accepting events with an end date strictly before 2026-10-19. This is coverage of the site's discoverable annual listings, not a guarantee that the site contains every historical competition or every draw.

Final reconciled counts:

| Metric | Count |
| --- | ---: |
| Events checked | 2,867 |
| Events with round rows | 2,805 |
| Total round rows | 44,921 |
| Rows marked published | 43,886 |
| Rows marked unresolved | 663 |
| Rows marked missing | 372 |
| Events with complete published draws (`ok`) | 2,611 |
| Events with partial draws | 194 |
| Events with no published draw | 62 |
| Remaining fetch/parser errors after recovery | 0 |

Event listing dates range from 1977-07-17 to 2026-10-01. The earliest events do not necessarily have draw rows. These counts describe the snapshot, not a live service.

Draw CSV columns, in order:

```text
event_id,event_name,start_date,end_date,league,discipline,venue,class,round,draw,draw_raw,draw_status,scoreboard_number,event_url
```

- Grain: one event × scoreboard × class × round.
- Verified unique key: `(event_id, scoreboard_number, class, round)`.
- `event_url` is `https://www.skyleague.com/events/{event_id}/` on every row.
- `draw` is an uppercase, whitespace-stripped, comma-separated sequence when classified published; otherwise blank.
- `draw_raw` retains the extracted display text (HTML whitespace is normalized).
- `draw_status` is `published`, `missing`, or `unresolved`. The scraper's syntactic definition of published is deliberately broader than the search parser's valid FS4 tokens.
- `scoreboard_number` counts original scoreboard elements, including ones later skipped; it need not start at 1 in the exported rows.
- Dates use ISO strings. Files are UTF-8 with BOM and standard CSV quoting; use a CSV reader, not comma splitting.
- The archive includes FS4, IFS4, FS8, IFS8, VFS4, IVFS4, FS4X6, IFS4X6, and IDYN4. Do not mix these pools indiscriminately when searching.

Coverage columns are the event metadata (`event_id`, name, dates, league, discipline, venue, URL), plus `status`, `rows`, `error`. Scraper errors can be `archive_error`, `date_error`, or `event_error`. Missing draws are not fetch failures. Counts of coverage `rows` were reconciled against the final CSV per event.

## Scraper implementation and recovery history

- Listing URL: `https://www.skyleague.com/events/?startdate=YYYY-01-01`.
- Event URL: `https://www.skyleague.com/events/{id}/`.
- `events_from_page()` reads `table.eventboard`, metadata cells, and event links.
- `draw_rows()` reads `table.scoreboard`, `th.roundlabel`, and `tr.scoreboard_class_header`.
- For conventional scoreboards, labels are round numbers and class names are in the second header cell.
- Cloud League labels are classes rather than round numbers; each class sequence becomes round `1`.
- Requests are serial, paced at one second between request starts by default. Timeout is 45 seconds; up to four attempts with exponential backoff. The cache is written atomically. The CSV is flushed per event but is not atomically finalized by the scraper itself.
- The process exits nonzero for fetch/parsing errors, but not for missing/partial draws. A `--max-events` test can exit zero without being a full archive scrape.

Issues found and fixed during the run:

1. Thirty-eight event downloads in 2015 encountered temporary name-resolution failures. All were recovered.
2. Event `150230` (2017 Shamrock Showdown) uses scoreboard CSS for its schedule table. The parser now only treats header rows beginning with `Rank` as draw headers. Twenty actual draw rows were recovered.
3. Event `5044` (2005 Carolina Meet 1) lists teams and totals but has no rounds. The parser now treats this as no published draw rather than an error.

The original running process predated these fixes. Its 40 reported errors were resolved in a separate recovery pass. Final merging removed any existing rows for recovered event IDs before adding recovered rows, replaced the corresponding coverage entries, sorted the outputs, and validated counts/keys/URLs. **Do not append `work/recovered.csv` again: those rows are already present.** The one-off merge was executed inline and is not a reusable project command.

## Search model and assumptions

Explicit user priorities are exact > cyclic rotation > other permutations/partial overlap, with a three-item minimum for partial matches. The following implementation choices were communicated to the user but were not separately specified by them:

- Each formation letter or block number is one atomic item. Block `12` does not count as two scoring points, and blocks are not expanded into formations.
- Default search scope is FS4/IFS4.
- Default results are five distinct events, not five rows potentially from the same event.
- More recent event dates break otherwise equal similarity ties.
- The scoring weights and numerical bands are heuristic, not empirically calibrated probabilities.

`parse_dive()` accepts separated A–Q letters and integers 1–22, case-insensitively. Commas, whitespace, hyphens, and en/em dashes are separators. Compact `ABCD`, leading-zero numbers, TBD, and out-of-range tokens are rejected. Repeated items are supported as multisets.

Let:

- `shared_items = sum(Counter(query) & Counter(candidate))`.
- `item_similarity = 2 × shared_items / (query_length + candidate_length)`.
- Directed cyclic pairs include the final-to-first transition, because dives repeat.
- `pair_similarity` is the equivalent multiset Dice overlap for those directed pairs.

Ranking:

| Tier | Score |
| --- | --- |
| Exact ordered match | 100 |
| Cyclic rotation | 95 |
| Other full multiset permutation | `80 + 9 × pair_similarity` |
| Partial, at least three shared occurrences | `30 + 49 × (0.75 × item_similarity + 0.25 × pair_similarity)` |
| Fewer than three shared occurrences | Excluded, except exact/rotation matches of short inputs |

The bands cannot overlap. Reversals are not rotations. Three non-sequential shared items qualify, but preserved adjacency earns a bonus. Partial ranking balances proportional overlap and adjacency; it does **not** guarantee that a candidate sharing four items always outranks one sharing three if lengths differ. If the user wants strict shared-count precedence, change this deliberately and update tests/docs.

Sorting uses unrounded scores, then shared-item count, shared-pair count, event start date, event ID, class, and round (descending). The last three are string tie-breakers, not numeric ordering. Scores are rounded to two decimals only for presentation. `rotation_offset` is zero-based; the CLI prints the corresponding one-based starting item.

`search()` returns query, rounds considered, invalid published rows skipped, matching-round count before event deduplication, and selected result dictionaries including event metadata and similarity details. Its programmatic default `before=None` differs from the CLI's date cutoff. CLI validates a positive limit; direct callers should supply a positive limit and a parsed nonempty query.

## Validation already performed

- Live small scraper tests covered conventional and Cloud League scoreboards, 2000-era events, and an empty 1900 listing.
- Full run plus recovery: no unresolved download/parser errors remained.
- Final assertions checked unique round keys, one coverage row per event, row totals per event, and exact event URL format on every row.
- Four search unittest cases passed: tier scores, rotations/block tokens/input rejection, repeated-item counting, and archive filtering/ranking/event deduplication.
- Search was exercised against the real archive with `A-B-C-D` and `P,7,9`.
- The default FS4/IFS4 sample considered 39,681 valid published rounds and skipped 34 malformed entries marked published by the scraper. Do not silently reinterpret malformed sequences.
- `A-B-C-D` returned an exact match at event `151689`, Brazil Tunnel League Meet 2, 2025-08-02, AA, round 9. This is a useful snapshot regression example, not a future-data invariant.

There is no comprehensive automated scraper fixture suite yet. Some scraper checks and the final reconciliation were inline commands; the persistent automated tests currently cover search only. No tests need a network connection.

## Limitations and useful future work

Only implement these if they fit a subsequent request:

1. Package scripts/tests into a conventional project structure and add dependency metadata.
2. Add saved HTML fixtures for conventional, Cloud League, schedule-style, no-round, and historical layouts. Preserve the two parser fixes above.
3. Add cache expiry/selective refresh and resumable incremental export. Currently `--refresh` is all-or-nothing and a scraper run truncates its target CSV immediately.
4. Add automated reconciliation and atomic final output replacement instead of relying on the one-off recovery procedure.
5. Examine the 34 malformed FS4/IFS4 sequences with source provenance; retain raw values and avoid guessing corrections.
6. If repeated queries become expensive, index by token multiset and canonical cyclic sequence; preserve ranking behavior and source links.
7. Ask about domain semantics before changing block expansion, three-distinct-items versus three-occurrences, pool versions, rotation equivalence, or cross-discipline matches. The current token grammar is FS4-oriented even when another discipline is explicitly selected.
8. Consider stronger validation for direct Python API calls and imported CSV dates if the scripts become a library/service.

Keep the full recovered archive intact while developing. Use temporary outputs and compare counts/statuses before replacing it. Published draws do not prove that every round was actually flown; missing data is a source limitation, not a score of zero.
