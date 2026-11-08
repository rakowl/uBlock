# iPhone Duo stock checker (Austin Apple Stores)

Checks Apple's in-store pickup availability for every iPhone Duo configuration
at **Austin, TX Apple Stores only** (Barton Creek, The Domain, etc. — any store
Apple reports with city = Austin).

- Runs **8:00–11:00 AM Austin time (America/Chicago)**, daily
- Checks **every 10 seconds** inside the window, sleeps outside it
- Python 3.9+, no dependencies

## Run

```bash
python3 check_stock.py
```

Options:

| Flag | Purpose |
|---|---|
| `--ntfy-topic NAME` | Push alert to your phone. Install the **ntfy** app, subscribe to the same topic name (pick something unique). |
| `--match "512GB"` | Only alert for matching configs (capacity, `Night Sky`, `Star White`). |
| `--parts MXXX3LL/A ...` | Check specific part numbers instead of auto-discovering all. |
| `--once` | Single check right now (test). |
| `--ignore-window` | Check every 10 s around the clock. |

Alerts: terminal bell + desktop notification + spoken alert (macOS). Re-alerts
every 5 minutes per store/config while it stays in stock.

## Keep it running

Leave it open in a terminal, or on macOS/Linux:

```bash
nohup python3 check_stock.py --ntfy-topic my-duo-alerts > duo.log 2>&1 &
```

Your computer must be awake 8–11 AM for checks to run.
