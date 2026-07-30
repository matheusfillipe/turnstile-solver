# turnstile-solver

HTTP service that mints Cloudflare Turnstile tokens using stock Chrome driven by nodriver.
Fork of [EzSolver](https://github.com/ismoiloffS/EzSolver).

A token is single-use and valid for about 300 seconds, so request one per submission.
The sitekey is hostname-restricted, so `siteurl` must be a page on the sitekey's own domain.

## Run

```bash
pip install -r requirements.txt
python service.py                                    # serves :8191
python solver.py <sitekey> <siteurl>                 # one-shot, prints a token
```

Linux needs `Xvfb` installed; macOS and Windows use the real display.

## API

```bash
curl -X POST localhost:8191/solve \
  -H 'content-type: application/json' \
  -d '{"sitekey": "0x4AAAAAAA...", "siteurl": "https://example.com/"}'
# {"token": "0.abc...", "elapsed": 8.1}

curl localhost:8191/health
# {"status": "ok", "workers": 2, "active": 0, "queued": 0}
```

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8191` | listen port |
| `MAX_WORKERS` | `2` | concurrent Chrome instances, roughly 500MB each |
| `SOLVE_TIMEOUT` | `45` | seconds before a solve gives up |
| `CHROME_PATH` | autodetected | Chrome executable |
| `TS_PROFILE_DIR` | `/tmp/ts_profile` | profile root, one directory per worker |
