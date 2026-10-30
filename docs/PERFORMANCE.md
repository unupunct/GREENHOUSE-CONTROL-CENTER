# Performance

## Measured (development PC, not a Raspberry Pi)

`scripts/benchmark.py` builds a temporary database with 15 sensors sampled once a minute for 90 days (1.94 million rows) and times the operations below. Result on the development machine (Windows 11, 8 CPUs, Python 3.13, SSD):

| Operation | Time |
|---|---|
| history, 24 h, one sensor | 16 ms |
| history, 60 days, 300 points | 75 ms |
| history older than the raw data (hourly roll-ups) | 65 ms |
| VPD history, 7 days | 177 ms |
| DLI over 30 days | 340 ms |
| monthly report (JSON / PDF) | 1.15 s / 1.54 s |
| seasonal comparison | 302 ms |
| mean of 2 sensors over all data: Python (before) → SQL (now) | 759 ms → 405 ms |
| roll-up + prune of 647,000 old raw samples (one-off) | 5.9 s |
| backup of the 148 MB database | 4.0 s |
| backup + restore verification | 10.1 s |
| one poll cycle of 15 simulated sensors / one flush | 2.8 ms / 5.7 ms |
| both engines' tick, gate evaluated every tick (before) → memoised (now) | 9.5 ms → 6.6 ms |
| database size, 90 days raw, 15 sensors | 145 MB |

**A Raspberry Pi will be slower**, and its storage much slower than this SSD: expect reports several times slower and backups far slower on a microSD card. Run the benchmark on your Pi (`python scripts/benchmark.py 90`); no Pi numbers exist yet.

## What was optimised

- **History charts:** bucket averaging in SQLite instead of loading every row into Python; memory is bounded however long the range.
- **Mean across sensors** (VPD, DLI, reports) computed by SQLite (about 1.9× faster in the benchmark).
- **Hourly roll-ups:** raw samples are summarised per sensor-hour before being pruned, so history charts and the seasonal comparison reach back years (default 3 years) at a few percent of the storage. Raw retention (default 90 days) is cut at whole hours and never deletes samples that are not summarised.
- **Commissioning gate** (several queries) is evaluated at most every 2 s per engine instead of every second, and immediately after any checklist action or configuration change.
- **Writes to flash:** samples are averaged in memory and written once per minute (15 rows per minute for 15 sensors); sessions touch the database at most once a minute; WAL mode with `synchronous=NORMAL`.
- **Network:** responses over 1 KB are gzip-compressed; hashed asset files are cached for a year, `index.html` never.

## Known costs and limits

- Raw data grows about 48 MB per month for 15 sensors at one sample a minute. SQLite does not shrink the file after pruning (space is reused); run `VACUUM` manually during a quiet period if you need the space back.
- Reports read raw samples for the period; periods older than the raw retention fall back to hourly data only in the history chart and seasonal comparison, not in reports (a report for an old month will be empty).
- The Mermaid diagram library is a large lazily-loaded download (about 0.5-1.4 MB per chunk) on the first Wiring page visit.
- A very large number of sensors, or a slow bus with many dead Modbus devices, lengthens the poll cycle (each silent device costs its timeout).
