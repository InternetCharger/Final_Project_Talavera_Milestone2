#!/usr/bin/env python3
"""
Traffic flood generator - LAB ONLY, targets 127.0.0.1 (this computer) only.

Sends short junk connections at a fixed rate to the FAA-RTR-01 simulator so its
offered load goes above 100 % of capacity. Uses source address 127.0.0.2 when
the OS allows it, so the router's "top talker" shows who is flooding.

  python lab/traffic_flood.py --rate 160 --seconds 20
"""
import argparse
import socket
import struct
import threading
import time

ALLOWED_TARGETS = {"127.0.0.1", "localhost"}


def flood(target, port, per_thread_rate, stop_at, source, counter, lock):
    gap = 1.0 / per_thread_rate
    nxt = time.perf_counter()
    while time.time() < stop_at:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))  # no TIME_WAIT pile-up
            if source:
                try:
                    s.bind((source, 0))
                except OSError:
                    pass
            s.settimeout(1.0)
            s.connect((target, port))
            s.sendall(b"X" * 512)
            s.close()
            with lock:
                counter[0] += 1
        except OSError:
            pass
        nxt += gap
        delay = nxt - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        else:
            nxt = time.perf_counter()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--rate", type=float, default=160, help="connections per second (total)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--source", default="127.0.0.2", help="source IP to label the flood")
    a = ap.parse_args()
    if a.target not in ALLOWED_TARGETS:
        raise SystemExit("Refusing: this lab tool only targets 127.0.0.1 (your own computer).")

    # check that the chosen source address works on this OS, else fall back
    src = a.source
    try:
        t = socket.socket()
        t.bind((src, 0))
        t.close()
    except OSError:
        src = None
    stop_at = time.time() + a.seconds
    counter, lock = [0], threading.Lock()
    print(f"Flooding {a.target}:{a.port} at ~{a.rate:.0f} conn/s for {a.seconds:.0f}s "
          f"from {src or '127.0.0.1'} (Ctrl+C to stop)", flush=True)
    threads = [threading.Thread(target=flood, daemon=True,
                                args=(a.target, a.port, a.rate / a.threads, stop_at, src, counter, lock))
               for _ in range(a.threads)]
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        pass
    print(f"Flood finished: {counter[0]} connections sent", flush=True)


if __name__ == "__main__":
    main()
