# Heatwave Trend Analyzer

Select a region and a period, and see how heatwave **frequency, duration and intensity** have changed, with honest statistics about whether the change is real.

Hazards: **heatwave** (default), **heavy rainfall**, **drought**.

**Stack:** React + Vite + Chart.js + Leaflet · FastAPI (Python) · MongoDB · Open-Meteo (ERA5 reanalysis)

---

## Quick start (5 minutes)

**Prerequisites:** Python **3.11+** and Node **20+**. No MongoDB needed locally — the app falls back to an in-memory store and no API keys or signup are required.

```bash
# 1. Backend (a virtualenv is recommended; see the PowerShell tab for Windows)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. Frontend
cd ../frontend
npm ci
npm run build

# 3. Serve API + UI from one process
cd ../backend
FRONTEND_DIST=../frontend/dist uvicorn app.main:app_factory --factory --reload --port 8000
```

Open **http://localhost:8000** — that is the whole app.

If `uvicorn` is "not recognized", either the venv is not activated or the dependencies were never
installed into it. Use `python -m uvicorn ...` instead: it resolves uvicorn through the active
interpreter rather than your PATH, so it works in either case.

<details>
<summary>Windows PowerShell</summary>

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # PowerShell may block this: see Troubleshooting
pip install -r requirements-dev.txt

cd ../frontend
npm ci
npm run build

cd ../backend
$env:FRONTEND_DIST = "../frontend/dist"     # PowerShell has no VAR=value syntax


```
</details>

You can skip step 2 and step 3's `FRONTEND_DIST` if you use the [dev server](#b-two-processes-with-hot-reload) instead.

---

## Running the tests

```bash
cd backend  && python -m pytest      # 59 tests, no network needed
cd frontend && npm test              # 6 tests
```

Run pytest **from inside `backend/`**. The repository root has no pytest config, so the
`filterwarnings = ignore::DeprecationWarning` in `backend/pytest.ini` is not picked up and you
see ~700 third-party DeprecationWarnings from starlette/fastapi/asyncio. The tests still pass;
the warnings are just noise.

---

## Development setup in detail

### A. One process (API + built UI)

Best for a quick look or for verifying a change end to end. The backend serves the built UI from
the same origin, so there is no CORS setup and no proxy.

```bash
cd backend
pip install -r requirements-dev.txt

cd ../frontend && npm ci && npm run build && cd ..

FRONTEND_DIST=../frontend/dist uvicorn app.main:app_factory --factory --reload --port 8000
```

Rebuild the UI (`npm run build`) after each frontend change; the backend picks up Python changes
by itself thanks to `--reload`.

### B. Two processes (with hot reload)

Best while working on the frontend. Vite serves the UI on 5173 and proxies `/api` to the backend
on 8000.

```bash
# terminal 1 - API only, no FRONTEND_DIST needed
cd backend && uvicorn app.main:app_factory --factory --reload --port 8000

# terminal 2 - UI with hot module replacement
cd frontend && npm run dev     # http://localhost:5173
```

### C. Docker (single container, closest to production)

```bash
docker build -t heat .
docker run -p 8000:8000 -e MONGODB_URI="mongodb+srv://..." heat
```

Omit `MONGODB_URI` to run entirely in memory. The image builds the frontend and serves it from
the API process, and `PORT` is honoured.

### Offline demo

`DEMO_SYNTHETIC=1` swaps the real weather provider for a generator so the app runs with no
network. The data is **generated, not real**, and the UI shows a red "Demo mode" banner. Good for
demos and for CI.

```bash
DEMO_SYNTHETIC=1 uvicorn app.main:app_factory --factory --port 8000
```

---

## Configuration

All settings are environment variables, read once at startup (`backend/app/config.py`).
`.env.example` lists the common ones; every value below is optional.

| Variable | Default | Purpose |
|---|---|---|
| `MONGODB_URI` | *(empty)* | MongoDB connection string. Empty = in-memory `mongomock`, so nothing persists across restarts. |
| `MONGODB_DB` | `climate_hazards` | Database name. |
| `FRONTEND_DIST` | *(empty)* | Path to the built UI. When it resolves to a directory, the backend serves it at `/`. |
| `DEMO_SYNTHETIC` | `0` | `1` uses generated data instead of Open-Meteo. |
| `CORS_ORIGINS` | *(empty)* | Comma-separated allowed origins. Only needed if you serve the UI separately. |
| `TRUST_PROXY` | `false` | `true` makes rate limiting read the real client IP from `X-Forwarded-For`. **Only enable behind a proxy you control** — otherwise clients can spoof it and bypass the limiter. |
| `CACHE_TTL_DAYS` | `30` | TTL for cached raw data and analyses. Ranges including the current year use `FRESH_DATA_TTL_HOURS` (default `24`) instead. |
| `RATE_LIMIT_HEAVY` / `RATE_LIMIT_GENERAL` | `20` / `120` | Requests per window per IP for analysis+export and everything else. |
| `PROVIDER_TIMEOUT_S` / `PROVIDER_RETRIES` | `60` / `3` | Upstream Open-Meteo timeout and retry budget. |

---

## Troubleshooting

**`.\.venv\Scripts\Activate.ps1` is blocked by PowerShell.** Windows blocks running local scripts by
default. Allow them for your user only (needs no admin rights):

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**`uvicorn` is "not recognized".** The virtualenv is not active (your prompt should start with
`(.venv)`), or you created the venv but never installed into it. Run `pip install -r
requirements-dev.txt` while the venv is active, or bypass PATH entirely with `python -m uvicorn`.
A bare `python -m venv .venv` creates an environment containing *only* pip.

**`npm ci` prints audit warnings / blocked install scripts.** npm 11 blocks dependency lifecycle
scripts by default and will warn about `esbuild`'s postinstall. The build still works, because npm
installs the platform-specific binary directly. `npm audit` also reports 6 advisories (2 critical)
in `tinypool`, a transitive dependency of **vitest** — a dev-only tool that is not part of the
production bundle. Nothing here ships to users.

**"Rate limit exceeded" while testing.** Analysis and export endpoints allow 20 requests/minute
per IP. That is easy to hit while clicking *Analyze* repeatedly; wait a few seconds.

**The first load of a place takes a while.** The very first request for a region downloads
~30 years of daily data from Open-Meteo (~1.5 s) and caches it. Later requests are served from
the database.

**Nothing renders at `/` but `/api/health` works.** `FRONTEND_DIST` is unset or does not point at
a directory that exists. Set it to the built UI (`../frontend/dist` from `backend/`) and restart.

**`docker` build fails on the frontend stage.** Make sure you build from the repository root,
not from inside `frontend/` — the Dockerfile copies `frontend/` itself.

---

## Deploying

Render free tier + MongoDB Atlas M0: create an Atlas free cluster, create a Render web service
from this repository (`render.yaml` is included), and set `MONGODB_URI`. `TRUST_PROXY=true` makes
rate limiting use the real client IP behind Render's proxy.

The README intentionally leaves the deployed URL and demo video placeholders for you to fill in.

---

## Architecture

```
React (Chart.js, Leaflet) --/api--> FastAPI --> MongoDB  (weather_raw, analyses; TTL indexes)
                                       '------> Open-Meteo archive + geocoding (only on cache miss)
```

`GET /api/analysis` flow: validate, look for a stored analysis, else look for stored raw data, else fetch from Open-Meteo, clean, detect, compute trends, **store**, then **read back from the DB** and return JSON.

| Endpoint | Purpose |
|---|---|
| `GET /api/analysis` | `lat,lon` **or** `min_lat,max_lat,min_lon,max_lon`; `start_year,end_year`; optional `percentile` (80-99.5), `min_days` (2-10), `hazard=heatwave\|heavy_rainfall\|drought` |
| `GET /api/geocode?q=` | City/state search (Open-Meteo geocoding, cached) |
| `GET /api/export/csv?kind=yearly\|events`, `GET /api/export/pdf` | Bonus exports |
| `GET /api/health`, `GET /api/hazards` | Health / available hazards |

## Hazard logic

### Heatwave
1. **Threshold per calendar day:** the 95th percentile of daily maximum temperature, pooling a +/-7-day window around that day across all years (about 15 x N samples), so the threshold is seasonal ("hot *for January*"). Leap days are aligned on a 366-day calendar.
2. **Heatwave:** 3+ consecutive days above that day's threshold. Percentile and day count are adjustable.
3. **Metrics per year:** events, heatwave days, longest event, intensity (deg C above threshold), annual mean Tmax. An event counts in the year it starts.

### Heavy rainfall
A *wet day* has at least 1 mm. The threshold is the P-th percentile (default 95, adjustable) of wet-day totals over the selected period (ETCCDI R95p style, one threshold for the year because wet-day samples are sparse). A heavy-rainfall day exceeds it. Metrics: heavy days, wettest day (Rx1day), rain on heavy days, annual total.

### Drought
**SPI-3** (3-month Standardized Precipitation Index): monthly totals, rolling 3-month sums, then for each calendar month a gamma distribution (with a zero-rain probability mass) is fitted and transformed to a standard normal. A drought month has SPI-3 <= -1; a drought event is 2+ consecutive drought months. Months with <90% valid days are missing and break events. Metrics: drought months, events started, longest event, annual total.

### Trends (all hazards)
OLS linear regression (drawn on charts), **Mann-Kendall** with **Sen's slope** (used for significance, since counts are skewed and zero-inflated), a 5-year centred rolling average, and an early-vs-late comparison (first 10 vs last 10 reliable years, or halves for shorter ranges) for the "+X%" headline. A percentage is only presented as a finding if Mann-Kendall p < 0.05; otherwise the text says the change is within normal variability. If the early average is 0, no percentage is shown.

## Data handling

- Missing days (nulls or absent dates) become explicit gaps. A gap **ends** a run; we never invent exceedances.
- Values outside -90..60 deg C are removed; duplicates are dropped (first wins); unsorted input is sorted; non-numeric values and unparseable dates are discarded; F and K are converted to C; unknown units raise an error.
- Each year gets a coverage score. Years with <90% valid days (including the current, partial year) are **excluded from trends** and shown hatched/grey in the UI.
- Under 50% usable data overall gives a clear 422 error instead of a misleading result.
- The latest ~6 days are never requested (ERA5 latency).

## Security and performance

- Strict validation (ranges, NaN/inf rejection, max box 10 degrees, min 10-year span, enum for `kind`/`hazard`); user input is only sent to upstream APIs as query parameters on fixed hostnames (no SSRF).
- Per-IP sliding-window rate limits (120/min general, 20/min for analysis/export), 429 + `Retry-After`; bounded concurrent upstream fetches; retries with exponential backoff on 429/5xx/timeouts; request timeouts.
- Caching: raw data and analyses in MongoDB with TTL (30 days; 24 h when the range includes the current year); geocoding cached in memory. Changing only percentile/min-days reuses cached raw data. Per-key locks prevent duplicate fetches under concurrent requests.
- Errors never leak internals (generic 500, upstream failures 502, storage 503). Security headers incl. CSP. API docs UI disabled (`/docs` and `/redoc` return 404; the schema is still served at `/api/openapi.json`).

## Assumptions and limitations

- **A bounding box is analysed at its centre point** (one ERA5 grid cell, ~25 km), not area-averaged. Max 10 degrees per side; boxes crossing the antimeridian are not supported.
- **The baseline is the selected period itself.** About 5% of days exceed the threshold by construction, so results describe *changes within the period*, not absolute severity. A fixed reference period (e.g. 1991-2020) would be better for cross-region comparison.
- ERA5 is reanalysis, not station data; it can differ from local readings, especially in cities and mountains.
- Mann-Kendall assumes no serial correlation; this is not corrected for.
- "State" selection works via geocoding to the state's representative point, not its full area.
- Rainfall hazards use ERA5 reanalysis rainfall, which is smoother than gauges and tends to underestimate extremes; thresholds and SPI are relative to the selected period itself. SPI ignores temperature/evaporation (it is not a water-supply or agricultural drought index).
- The rate limiter is in-process; with multiple instances, move it to Redis.

## Known issues

- **The place name does not reach the headline sentence.** The backend only ever sees coordinates, so
  if you search "Delhi" the byline reads `Heatwave · Delhi, India · 1991–2020` but the headline
  sentence reads *"Heatwave days have increased in 28.61, 77.21"*. The name is held in frontend
  state only (`frontend/src/App.jsx`). Fixing it means passing the label through as an optional
  query parameter and using it in `AnalysisParams.label` (`backend/app/service.py`).
- **Deep links 404.** `StaticFiles(html=True)` does not fall back to `index.html` for unknown
  paths. Harmless today because the app has no router, but it will break as soon as routing is
  added.
- Dev-dependency advisories in `vitest`/`tinypool` are outstanding; see [Troubleshooting](#troubleshooting).

## What I'd do with more time

Area-averaged boxes (grid sampling), a fixed-baseline option, station cross-checks (NOAA), humidity-aware definitions, SPEI (temperature-aware drought), flood/runoff hazards, block-bootstrap Mann-Kendall for autocorrelation, E2E browser tests, Redis rate limiting, and a background job for slow first fetches.

## Testing status

- 59 backend tests (cleaning, detection edge cases for all three hazards, statistics, validation, caching, rate limiting, provider retries/failures, exports) and 6 frontend tests pass.
- Provider tests use a mocked HTTP transport.
- **The live Open-Meteo call has been exercised** against the real archive and geocoding APIs:
  a 30-year daily request for Paris returned 10,958 valid days with no gaps or outliers, and
  heatwave / heavy-rainfall / drought analyses all produced sensible output. Geocoding, the CSV
  and PDF exports, caching, rate limiting and validation rejections were all checked against a
  running server. Re-run this after touching `backend/app/provider.py`:
  ```bash
  curl "http://localhost:8000/api/analysis?lat=48.86&lon=2.35&start_year=1991&end_year=2020"
  ```
- Frontend components were manually rendered against real API responses to confirm the
  frontend/backend contract; this is not yet an automated test.
- **Not covered:** end-to-end browser tests, and MongoDB is only exercised through `mongomock`
  locally — run the deployment once against a real Atlas cluster before trusting it.

## AI tools used

Claude (Anthropic) was used to generate the initial code, tests and this README from the case-study brief. *Edit this section to describe what you reviewed and changed yourself; you will be asked to explain and modify the code live.*