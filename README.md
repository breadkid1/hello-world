# hello-world

hello men

currently one of data analyst in educational institution and hoping could learn comething from github
and, I am very tall, probably :)

## Flight price monitor

This repository now includes a small flight price monitor for a 9-day summer trip from Nanjing or Shanghai to Urumqi. It is configured for 2 adult passengers, Saturday morning departures to Urumqi, and a return landing in Nanjing on the following Sunday.

### Routes and dates being watched

The default configuration watches these outbound origins:

- NKG → URC
- PVG → URC
- SHA → URC

For each outbound date, the script checks a return from URC → NKG 8 days later:

| Outbound date | Return date | Vacation shape |
| --- | --- | --- |
| 2026-07-04 | 2026-07-12 | Saturday to next Sunday |
| 2026-07-11 | 2026-07-19 | Saturday to next Sunday |
| 2026-07-18 | 2026-07-26 | Saturday to next Sunday |
| 2026-07-25 | 2026-08-02 | Saturday to next Sunday |
| 2026-08-01 | 2026-08-09 | Saturday to next Sunday |
| 2026-08-08 | 2026-08-16 | Saturday to next Sunday |

The script prefers outbound flights that depart at or before 12:00, so the report focuses on morning flights when any are available.

### How to run locally

Generate a sample report without API credentials:

```bash
python scripts/flight_monitor.py --dry-run
```

Run a live search with the Amadeus production API:

```bash
export AMADEUS_CLIENT_ID="your-client-id"
export AMADEUS_CLIENT_SECRET="your-client-secret"
python scripts/flight_monitor.py --production
```

The latest report is written to `reports/flight-monitor-latest.md`, and historical results are appended to `reports/flight-monitor-history.csv`.

### Daily automation

The GitHub Actions workflow in `.github/workflows/flight-monitor.yml` runs every day at 01:30 UTC, which is 09:30 China Standard Time. To enable it:

1. Create an Amadeus for Developers app.
2. Add repository secrets named `AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET`.
3. Enable GitHub Actions for this repository.
4. Use the workflow's manual `workflow_dispatch` button if you want to check prices immediately.

The workflow commits updated report files back to the current branch after each successful run.
