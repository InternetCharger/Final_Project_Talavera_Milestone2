#!/usr/bin/env python3
"""
Lab web server (stands in for a company web app).

  --mode ok     -> every request gets 200 OK
  --mode error  -> every request gets 503 Service Unavailable
                   (simulates "database connection pool exhausted")

Runs only on this computer (127.0.0.1). No admin rights needed.
  python lab/lab_web_server.py --port 8080 --mode error
"""
import argparse
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(mode, log_path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LabWebServer/1.0"

        def version_string(self):
            return self.server_version

        def _reply(self, send_body):
            if mode == "ok":
                code, body = 200, b"OK - CIS 2347 lab web app is healthy\n"
                note = "healthy"
            else:
                code, body = 503, b"Service Unavailable - database connection pool exhausted\n"
                note = "backend error: database connection pool exhausted"
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            if code == 503:
                self.send_header("Retry-After", "30")
            self.end_headers()
            if send_body:
                self.wfile.write(body)
            line = (f"{datetime.now().strftime('%H:%M:%S')} {self.client_address[0]} "
                    f"{self.command} {self.path} -> {code}  ({note})")
            print(line, flush=True)
            if log_path:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")

        def do_GET(self):
            self._reply(True)

        def do_HEAD(self):
            self._reply(False)

        def log_message(self, *args):  # silence default noisy logging
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--mode", choices=["ok", "error"], default="ok")
    ap.add_argument("--log", default=None, help="optional log file")
    a = ap.parse_args()
    if a.log:
        os.makedirs(os.path.dirname(a.log) or ".", exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.mode, a.log))
    srv.daemon_threads = True
    print(f"Lab web server on http://127.0.0.1:{a.port}  mode={a.mode}  (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
