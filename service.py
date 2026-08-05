"""HTTP front end for the solver. POST /solve {sitekey, siteurl} -> {token}."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from solver import solve, start_display

PORT = int(os.environ.get("PORT", 8191))
# Each worker is a whole Chrome, roughly 500MB resident.
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", 2))
DEFAULT_TIMEOUT = int(os.environ.get("SOLVE_TIMEOUT", 45))

_worker_sem = threading.Semaphore(MAX_WORKERS)
_counts = {"active": 0, "queued": 0}
_counts_lock = threading.Lock()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[service] {self.address_string()} - {fmt % args}", flush=True)

    def send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_json(404, {"error": "use POST /solve"})
            return
        with _counts_lock:
            self.send_json(200, {"status": "ok", "workers": MAX_WORKERS, **_counts})

    def do_POST(self) -> None:
        if self.path != "/solve":
            self.send_json(404, {"error": "use POST /solve"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid JSON"})
            return

        sitekey = str(payload.get("sitekey", "")).strip()
        siteurl = str(payload.get("siteurl", "")).strip()
        timeout = int(payload.get("timeout", DEFAULT_TIMEOUT))
        if not sitekey or not siteurl:
            self.send_json(400, {"error": "sitekey and siteurl are required"})
            return

        with _counts_lock:
            _counts["queued"] += 1
        _worker_sem.acquire()
        with _counts_lock:
            _counts["queued"] -= 1
            _counts["active"] += 1

        started = time.time()
        try:
            try:
                token = solve(sitekey, siteurl, timeout=timeout)
            except TimeoutError:
                # The failed attempt binned its profile, so this starts from a clean
                # one. Without the retry a single poisoned profile fails the caller's
                # whole job even though the very next request would have succeeded.
                print(f"[service] retrying {sitekey} on a fresh profile", flush=True)
                token = solve(sitekey, siteurl, timeout=timeout)
            elapsed = round(time.time() - started, 2)
            print(f"[service] solved {sitekey} in {elapsed}s", flush=True)
            self.send_json(200, {"token": token, "elapsed": elapsed})
        except (TimeoutError, FileNotFoundError, OSError) as exc:
            elapsed = round(time.time() - started, 2)
            print(f"[service] failed {sitekey} after {elapsed}s: {exc}", flush=True)
            self.send_json(500, {"error": str(exc), "elapsed": elapsed})
        finally:
            with _counts_lock:
                _counts["active"] -= 1
            _worker_sem.release()


if __name__ == "__main__":
    xvfb = start_display()
    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[service] listening on 0.0.0.0:{PORT} with {MAX_WORKERS} workers", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        if xvfb:
            xvfb.terminate()
