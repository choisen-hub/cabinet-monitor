# cabinet-monitor

A small Flask application that keeps track of who sits in the cabinet of the Republic of Korea (State Council members: the Prime Minister and the ministers). It scrapes a current list on a weekly schedule, records appointments, replacements and departures as a change history, stores dated snapshots, and serves a one-page dashboard with search, a "time machine" slider for browsing past cabinets, and Wikipedia-backed profile popups. A companion script backfills roughly three years of weekly snapshots from Wikipedia tenure tables. It is intended for anyone following Korean government personnel changes who wants a local, self-updating reference rather than a news feed.

## Features

From `app.py`, `backfill.py`, `templates/index.html` and `static/app.js`:

- Scraping with fallbacks: tries korea.net, then the Office for Government Policy Coordination (opm.go.kr), then the Korean Wikipedia page for the current administration. The first source returning at least 5 entries wins.
- Change detection keyed by post title: new post, replacement (with previous holder) and removal, each stamped with a timestamp and kept in a history of up to 100 entries.
- Weekly snapshots of the full list (up to 52 kept by the live refresher), plus a backfill script that reconstructs weekly cabinets for the past three years from Wikipedia tenure data for the two most recent administrations.
- Dashboard: minister cards with photo or initial placeholder, title, appointment date and source; stat tiles (total members, change count, data source, countdown to the next refresh); search by name or title; a change-history sidebar; a manual refresh button.
- Time machine: a range slider over all snapshots that loads the cabinet as it stood on a given date.
- Profile modal: clicking a card fetches a summary, thumbnail and link from the Korean Wikipedia REST API, retrying without and with spaces in the name.
- JSON API: `/api/ministers`, `/api/snapshots`, `/api/snapshot/<idx>`, `/api/profile?name=...`, `POST /api/refresh`.
- CORS enabled on all routes (flask-cors).

## How it works

- `app.py` starts an APScheduler `BackgroundScheduler` that calls `refresh_data()` once a week. On first launch, if `ministers_cache.json` is missing or empty, it refreshes immediately.
- `refresh_data()` runs the scrapers in order, diffs the result against the cached list with `detect_changes()`, prepends new changes to `history`, writes `ministers_cache.json` and appends a snapshot to `snapshots.json`.
- Scrapers use `requests` with a desktop User-Agent and `BeautifulSoup` with the `lxml` parser. The korea.net and opm.go.kr scrapers rely on a list of CSS selectors that may or may not match the live markup; the Wikipedia scraper reads the first `wikitable` on the administration page, where each row holds two ministers in groups of four cells (title, name, photo, tenure).
- `backfill.py` fetches the Wikipedia pages for the previous and current administrations, expands rowspan/colspan tables into a grid, parses Korean date ranges such as `2022년 5월 10일~2023년 12월 28일`, filters to State Council posts using `INCLUDE_TITLES`/`EXCLUDE_TITLES`, then generates one snapshot per week by asking "who held each post on this date". Existing snapshots with a non-midnight timestamp (live refreshes) are preserved when merging.
- The frontend is vanilla JavaScript. It polls `/api/ministers` on load and once a week, keeps a one-week countdown, and switches between live and snapshot views without reloading.

## Requirements

- Python 3.9 or later (uses `list[dict]` style annotations)
- Packages pinned in `requirements.txt`: flask 3.1.0, requests 2.32.3, beautifulsoup4 4.12.3, lxml 5.3.0, apscheduler 3.10.4, flask-cors 5.0.0
- Network access to korea.net, opm.go.kr and ko.wikipedia.org

## Installation and running

```bash
git clone https://github.com/choisen-hub/cabinet-monitor.git
cd cabinet-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the server (first run scrapes immediately, then weekly):

```bash
python app.py
```

Open `http://localhost:8080`.

Optional: backfill three years of weekly snapshots before or after starting the server.

```bash
python backfill.py
```

The server runs with `debug=True` and `use_reloader=False` (the reloader is off so the scheduler is not started twice). For anything beyond local use, run it under a WSGI server and turn debug off.

## Configuration

There are no environment variables or config files. Tunables are constants in the source:

| Where | Name | Meaning |
| --- | --- | --- |
| `app.py` | `HEADERS` | User-Agent and Accept-Language sent to all sites |
| `app.py` | `DATA_FILE`, `SNAPSHOTS_FILE` | `ministers_cache.json`, `snapshots.json` next to the script |
| `app.py` | `scheduler.add_job(..., weeks=1)` | Refresh interval |
| `app.py` | `save_snapshot`: `snapshots[-52:]` | Number of live snapshots kept |
| `app.py` | `cache["history"] = history[:100]` | Number of history entries kept |
| `app.py` | `app.run(port=8080)` | Port |
| `app.py` | `scrape_wikipedia`: `url` | Wikipedia page of the current administration |
| `backfill.py` | `INCLUDE_TITLES`, `EXCLUDE_TITLES` | Which posts count as State Council members |
| `backfill.py` | the two `scrape_gov_page(...)` calls in `main()` | Administration pages to backfill from |
| `backfill.py` | `three_years_ago` | Backfill horizon |

Generated data files (`ministers_cache.json`, `snapshots.json`, `*.log`) are listed in `.gitignore`. A sample `ministers_cache.json` and `snapshots.json` may be present in the working copy; delete them to force a clean first scrape.

## Project structure

```
cabinet-monitor/
  app.py                 Flask app, scrapers, cache/snapshot helpers, change detection, scheduler, API routes
  backfill.py            One-off script: weekly snapshots for the past 3 years from Wikipedia tenure tables
  requirements.txt       Pinned dependencies
  templates/index.html   Dashboard page (Korean UI)
  static/app.js          Frontend: data loading, cards, history, search, time machine, profile modal, toasts
  static/style.css       Dark theme styles
  ministers_cache.json   Generated: current list, last_updated, history (gitignored)
  snapshots.json         Generated: list of {timestamp, ministers} (gitignored)
  LICENSE                MIT
```

## Usage examples

Current list and change history:

```bash
curl http://localhost:8080/api/ministers
```

Snapshot index, then one snapshot:

```bash
curl http://localhost:8080/api/snapshots
curl http://localhost:8080/api/snapshot/0
```

Force a refresh:

```bash
curl -X POST http://localhost:8080/api/refresh
```

Wikipedia summary for a name:

```bash
curl "http://localhost:8080/api/profile?name=김민석"
```

Record shape in `ministers_cache.json`:

```json
{
  "ministers": [
    {"name": "...", "title": "국무총리", "photo": "", "appointed": "2025년 7월 3일~", "source": "위키피디아"}
  ],
  "last_updated": "2026-03-29 01:44:33",
  "history": [
    {"type": "교체", "title": "...", "name": "...", "prev_name": "...", "timestamp": "..."}
  ]
}
```

## Data sources, licensing and attribution

- korea.net (Korean Culture and Information Service), opm.go.kr (Office for Government Policy Coordination) and the Korean Wikipedia articles for the current and previous administrations. Wikipedia text is CC BY-SA 4.0; the dashboard links back to the source page in the profile modal.
- Profile summaries and thumbnails come from the Wikimedia REST API (`/api/rest_v1/page/summary/`).
- Scraping third-party sites is subject to their terms; keep the refresh interval modest (the default is weekly).
- The footer directs users to korea.kr for official appointment notices.

## Known limitations

- The korea.net and opm.go.kr selectors are speculative and in practice the Wikipedia scraper has been the working source (the sample cache lists `위키피디아` as source for all entries). Any change to the Wikipedia table layout breaks parsing.
- The Wikipedia scraper and `backfill.py` hard-code the current and previous administration pages; a new administration requires editing the URLs and, in `backfill.py`, possibly the table-layout branch.
- Change detection keys on the exact title string, so a renamed ministry appears as a removal plus a new post.
- No authentication on `POST /api/refresh`; anyone who can reach the server can trigger scraping.
- Snapshots are stored as one JSON file that is rewritten on every refresh; it grows with the number of ministers times snapshots.
- The UI is Korean only.

## License

MIT. See `LICENSE`.
