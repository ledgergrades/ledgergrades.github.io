# Ledger Grades

A small website that logs into your school's **Home Access Center (HAC)** and
shows your grades with:

- **Color-coded averages** — green/blue/amber/orange/red bands for A/B/C/D/F
- **A shift tracker** — each class shows how much its average has moved since
  the last time you logged in
- **A what-if calculator** — add a hypothetical assignment score to any grade
  category and see the projected class average update live

Not affiliated with GradeWay, PowerSchool, or Home Access Center — a
from-scratch implementation of the same idea for personal use.

## Architecture

The project is split in two so the frontend can be hosted for free on
**GitHub Pages** (static hosting only, no Python) while the part that
actually needs to run code lives on a real Python host:

```
backend/     Flask JSON API — HAC login, scraping, what-if math
docs/         Static site (HTML/CSS/JS) — meant for GitHub Pages
```

The frontend calls the backend over `fetch()`. No server-side session is
used — the browser holds your fetched grades in `sessionStorage` for the
current tab, and grade-shift tracking lives in `localStorage`.

## Running it locally

**Backend:**
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```
This starts the API at `http://127.0.0.1:5000`.

**Frontend:** first point it at your local backend —
open `docs/config.js` and temporarily set:
```js
const API_BASE = "http://127.0.0.1:5000";
```
Then serve the folder (any static server works):
```bash
cd docs
python3 -m http.server 8080
```
Open `http://127.0.0.1:8080`. Click **"See it with sample grades"** to try
the UI without a real HAC login.

## Deploying for real

### 1. Backend → Render (or any Python host)

1. Push this repo to GitHub.
2. render.com → New → Web Service → pick the repo, set **Root Directory** to `backend`.
3. Build command: `pip install -r requirements.txt`
   Start command: `gunicorn app:app`
4. Add environment variables:
   - `LEDGERGRADES_ALLOWED_ORIGINS` = `https://ledgergrades.github.io`
5. Deploy. You'll get a URL like `https://your-app.onrender.com`.

### 2. Frontend → GitHub Pages

1. In `docs/config.js`, set `API_BASE` to your Render URL from above.
2. Commit and push.
3. On GitHub: repo **Settings → Pages** → Source: **Deploy from branch** →
   Branch: `main`, Folder: **/docs** → Save.
4. Your site is live at `https://ledgergrades.github.io/` (this only works
   if the repo itself is named exactly `ledgergrades.github.io`, under a
   GitHub account/organization named `ledgergrades`).

Render's free tier spins down when idle, so the first request after a while
takes ~30 seconds while it wakes up. During that window it can return an
HTML "waking up" page instead of JSON, or fail the request outright — the
frontend now retries automatically a few times with a short delay and shows
a "waking up the server" message rather than a raw error.

**To avoid this entirely**, set up a free uptime monitor (e.g.
[UptimeRobot](https://uptimerobot.com), no signup cost) to ping
`https://your-app.onrender.com/api/health` every 5–10 minutes. Since Render
spins a free service down after 15 minutes with no incoming traffic, a
regular ping keeps it perpetually awake — this also avoids the deeper issue
that Render's free tier has an **ephemeral filesystem**: anything the
backend writes to disk (the grade snapshots, the view-counter file) is
wiped every time the service restarts or spins down, which is what causes
the view counter to reset unexpectedly. A keep-alive ping means it restarts
far less often, so that data survives much longer between resets — though
it will still reset on every real deploy (`git push`), which is expected.

Grade-shift tracking ("change since last login") is not affected by this
at all: it lives in the browser's `localStorage` instead of a server-side
file, so it survives regardless of what the backend does.

## A note on the scraper

HAC is run separately by each school district, and while most use the same
standard theme, some customize the markup. `backend/hac_scraper.py`'s
`_parse_classes()` anchors on stable page text ("Classwork Average") and
real column headers rather than guessed CSS classes, which should hold up
across most districts' themes — but there's no way to test this against
every district's HAC in advance, so treat it as a solid starting point
rather than a guarantee.

## Security notes

- Your HAC password goes straight from the login page to the backend to your
  district's HAC site over HTTPS. It's never stored.
- CORS on the backend is restricted to `LEDGERGRADES_ALLOWED_ORIGINS` — keep
  this set to only your actual frontend URL(s) in production.
- Grade snapshots (`backend/instance/snapshots/*.json`) are keyed by a hash
  of district+username, not by anything identifying on their own, but they
  do sit on disk on whatever host runs the backend — don't deploy the
  backend somewhere with public filesystem access.

## Project structure

```
backend/
  app.py                  Flask JSON API routes
  hac_scraper.py           HAC login + grade parsing + course-name cleanup
  requirements.txt
  Procfile
  instance/snapshots/      per-user grade snapshots (gitignored)
docs/
  index.html                login page
  dashboard.html             grades ledger + what-if UI (renders client-side)
  api.js                      login/demo fetch calls + client-side shift tracking
  app.js                      dashboard rendering + what-if calculator
  stats.js                     view-counter tracking + retry-aware fetch helper
  config.js                    API_BASE — the one line to edit per deployment
  style.css                     visual design
```
