#!/usr/bin/env python3
"""
FAA-RTR-01 : simulated edge router (runs on this computer, no admin needed).

    client --> [ FAA-RTR-01 :8081 ] --> lab web server :8080
                    |
                    +-- stats page  http://127.0.0.1:8082/stats  (like SNMP counters)

How it behaves like a real router
  * Limited forwarding capacity: WORKERS x (1000 / PROC_MS) connections per second
    (default 1 x 100 = 100 conn/s).
  * Packets that arrive faster than that wait in an input QUEUE  -> queuing delay.
  * When the queue is full, new arrivals are TAIL-DROPPED (reset)  -> loss.
  * Every second it writes a log line: CPU %, queue depth, drops, top talker.

Nothing here is faked with sleep() on the probe path: delay and drops only
appear when real traffic (traffic_flood.py) exceeds the router's capacity.

  python lab/faa_router_sim.py
"""
import argparse
import collections
import json
import os
import queue
import socket
import struct
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_METHODS = (b"GET ", b"HEAD", b"POST", b"PUT ", b"DELE", b"OPTI")


class Router:
    def __init__(self, a):
        self.a = a
        self.q = queue.Queue(maxsize=a.queue)
        self.lock = threading.Lock()
        self.start = time.time()
        self.drops_total = 0
        self.forwarded_total = 0
        self.events = collections.deque()   # (time, kind, src, busy_seconds)

    # ---------------- bookkeeping
    def record(self, kind, src, busy=0.0):
        with self.lock:
            self.events.append((time.time(), kind, src, busy))
            if kind == "drop":
                self.drops_total += 1
            if kind == "done":
                self.forwarded_total += 1

    def stats(self):
        w = self.a.window
        cutoff = time.time() - w
        with self.lock:
            while self.events and self.events[0][0] < cutoff:
                self.events.popleft()
            ev = list(self.events)
            drops_total, fwd_total = self.drops_total, self.forwarded_total
        arrivals = [e for e in ev if e[1] in ("arrive",)]
        busy = sum(e[3] for e in ev if e[1] == "done")
        capacity = self.a.workers * (1000.0 / self.a.proc_ms)      # conn per second
        talkers = collections.Counter(e[2] for e in arrivals)
        total = sum(talkers.values()) or 1
        return {
            "name": self.a.name,
            "interface": f"Gi0/0 (listen :{self.a.listen}) -> backend {self.a.backend}",
            "uptime_s": int(time.time() - self.start),
            "window_s": w,
            "capacity_conn_per_s": round(capacity, 1),
            "arrivals_per_s": round(len(arrivals) / w, 1),
            "offered_load_pct": round(100.0 * len(arrivals) / w / capacity, 1),
            "cpu_util_pct": round(min(100.0, 100.0 * busy / (w * self.a.workers)), 1),
            "queue_depth": self.q.qsize(),
            "queue_max": self.a.queue,
            "drops_window": sum(1 for e in ev if e[1] == "drop"),
            "drops_total": drops_total,
            "forwarded_total": fwd_total,
            "top_talkers": [{"src": s, "pct": round(100.0 * c / total, 1)}
                            for s, c in talkers.most_common(3)],
        }

    # ---------------- data plane
    @staticmethod
    def hard_close(sock):
        """Close with RST (like a router discarding the flow)."""
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def accept_loop(self):
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("127.0.0.1", self.a.listen))
        ls.listen(512)
        while True:
            conn, addr = ls.accept()
            src = addr[0]
            self.record("arrive", src)
            try:
                self.q.put_nowait((conn, src, time.time()))
            except queue.Full:
                self.record("drop", src)          # tail drop: queue is full
                self.hard_close(conn)

    def worker(self):
        bh, bp = self.a.backend.split(":")
        while True:
            conn, src, _queued_at = self.q.get()
            t0 = time.perf_counter()
            # forwarding cost: route lookup / ACL / NAT processing for this flow
            time.sleep(self.a.proc_ms / 1000.0)
            try:
                conn.settimeout(2.0)
                first = conn.recv(4096)
                if first[:4] in HTTP_METHODS:
                    self.forward(conn, first, bh, int(bp))
            except OSError:
                pass
            finally:
                self.hard_close(conn)   # no-op if forward() already closed it cleanly
                self.record("done", src, time.perf_counter() - t0)

    @staticmethod
    def forward(conn, first, bh, bp):
        with socket.create_connection((bh, bp), timeout=3) as up:
            up.sendall(first)
            while True:
                data = up.recv(65536)
                if not data:
                    break
                conn.sendall(data)
        try:
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        conn.close()

    # ---------------- logging
    def log_loop(self):
        while True:
            time.sleep(1)
            s = self.stats()
            top = s["top_talkers"][0] if s["top_talkers"] else {"src": "-", "pct": 0}
            line = (f"{datetime.now().strftime('%H:%M:%S')} {s['name']} cpu={s['cpu_util_pct']:5.1f}% "
                    f"load={s['offered_load_pct']:6.1f}% queue={s['queue_depth']:>2}/{s['queue_max']} "
                    f"drops({s['window_s']}s)={s['drops_window']:>4} top_talker={top['src']}({top['pct']}%)")
            status = "  <-- OVERLOAD" if s["cpu_util_pct"] >= 85 or s["drops_window"] > 0 else ""
            if self.a.log:
                with open(self.a.log, "a", encoding="utf-8") as f:
                    f.write(line + status + "\n")
            if not self.a.quiet:
                print(line + status, flush=True)


def stats_server(router, port):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(router.stats(), indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="FAA-RTR-01")
    ap.add_argument("--listen", type=int, default=8081)
    ap.add_argument("--backend", default="127.0.0.1:8080")
    ap.add_argument("--stats-port", type=int, default=8082)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--proc-ms", type=float, default=10.0, help="forwarding cost per connection")
    ap.add_argument("--queue", type=int, default=30, help="input queue size before tail drop")
    ap.add_argument("--window", type=int, default=5, help="seconds used for stats")
    ap.add_argument("--log", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.log:
        os.makedirs(os.path.dirname(a.log) or ".", exist_ok=True)

    r = Router(a)
    for _ in range(a.workers):
        threading.Thread(target=r.worker, daemon=True).start()
    threading.Thread(target=r.log_loop, daemon=True).start()
    threading.Thread(target=stats_server, args=(r, a.stats_port), daemon=True).start()
    cap = a.workers * 1000.0 / a.proc_ms
    print(f"{a.name} up: listen 127.0.0.1:{a.listen} -> {a.backend} | capacity {cap:.0f} conn/s | "
          f"queue {a.queue} | stats http://127.0.0.1:{a.stats_port}/stats", flush=True)
    try:
        r.accept_loop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
