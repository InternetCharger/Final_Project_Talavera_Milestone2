#!/usr/bin/env python3
"""
AI Network Troubleshooting Agent  (CIS 2347 Final Project - Milestone 2)

Collects evidence layer by layer, then reasons about the most likely fault.
Python standard library only. Runs in the VS Code terminal on Windows
(PowerShell); also works on macOS/Linux.

Tools the agent uses
  1. DNS   : system resolver (same one your browser uses) + nslookup for raw evidence
  2. PING  : ping -n (Windows) / ping -c (macOS/Linux)
  3. TCP   : one socket connect to the chosen port (open / refused / timeout)
  4. HTTP  : one HEAD request (status code, server header, response time)
  5. TRACE : tracert -d (Windows) / traceroute -n, bounded hop count
  6. LATENCY SERIES : N repeated HTTP probes -> loss %, median, p95, jitter
  7. ROUTER STATS   : reads a router's stats page (SNMP-style counters)

Examples
  python network_diagnostics.py example.com
  python network_diagnostics.py no-such-host.invalid --known-ip 104.20.23.154 --no-http
  python network_diagnostics.py localhost --port 8080 --scheme http
  python network_diagnostics.py localhost --port 8081 --scheme http --samples 20 ^
         --bypass localhost:8080 --router-stats http://127.0.0.1:8082/stats
"""

import argparse
import http.client
import ipaddress
import json
import platform
import re
import shutil
import socket
import ssl
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

IS_WINDOWS = platform.system() == "Windows"

# Thresholds used by the overload / congestion check (see router-overload-detection skill)
LOSS_FLAG_PCT = 5.0          # >= 5 % failed probes is abnormal
EXTRA_DELAY_FLAG_MS = 100.0  # p95 more than 100 ms above the bypass path is abnormal
ABS_P95_FLAG_MS = 250.0      # used only when no bypass path is given
ROUTER_CPU_FLAG_PCT = 85.0


# --------------------------------------------------------------------------- helpers
def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_cmd(cmd, timeout):
    """Run an OS tool and return (exit_code, combined_output). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return None, f"tool not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return None, f"tool timed out after {timeout}s"
    except Exception as e:  # pragma: no cover
        return None, str(e)


def is_ip(text):
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def ms(seconds):
    return round(seconds * 1000.0, 1)


# --------------------------------------------------------------------------- tool 1: DNS
def check_dns(host):
    if is_ip(host):
        return {"executed": False, "success": True, "addresses": [host],
                "note": "target is an IP address - DNS not needed"}

    t0 = time.perf_counter()
    result = {"executed": True}
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addrs = []
        for info in infos:
            ip = info[4][0]
            if ip not in addrs:
                addrs.append(ip)
        # IPv4 first so results are easy to read and match the lab servers
        addrs.sort(key=lambda a: (":" in a))
        result.update(success=True, addresses=addrs, time_ms=ms(time.perf_counter() - t0))
    except socket.gaierror as e:
        code = e.errno
        if code in (11001, getattr(socket, "EAI_NONAME", -2)):
            kind = "NXDOMAIN - the name does not exist"
        elif code in (11002, getattr(socket, "EAI_AGAIN", -3)):
            kind = "resolver timeout / temporary failure"
        else:
            kind = "resolution error"
        result.update(success=False, addresses=[], error=str(e), error_kind=kind,
                      time_ms=ms(time.perf_counter() - t0))

    # nslookup = raw evidence straight from the DNS server (skips the hosts file)
    if host.lower() != "localhost" and shutil.which("nslookup"):
        _, out = run_cmd(["nslookup", host], timeout=8)
        result["nslookup_raw"] = out
        if not result["success"] and re.search(r"non-existent domain|NXDOMAIN", out, re.I):
            result["error_kind"] = "NXDOMAIN - the name does not exist"
    return result


# --------------------------------------------------------------------------- tool 2: PING
def check_ping(ip, count=2):
    if IS_WINDOWS:
        cmd = ["ping", "-n", str(count), "-w", "1000", ip]   # -n = count on Windows
    else:
        cmd = ["ping", "-c", str(count), "-W", "1", ip]
    code, out = run_cmd(cmd, timeout=count * 3 + 5)
    if code is None:
        return {"executed": False, "target": ip, "success": False, "error": out,
                "command": " ".join(cmd), "replies": 0, "sent": count, "loss_pct": None}

    # Count only REAL echo replies (they contain TTL=). On Windows a router's
    # "Destination host unreachable" message is counted as "Received" - a classic trap.
    replies = len(re.findall(r"ttl[=:]\s*\d+", out, re.I))
    rtts = [float(x) for x in re.findall(r"time[=<]\s*([\d.]+)\s*ms", out, re.I)]
    loss = round(100.0 * (count - min(replies, count)) / count, 1)
    return {
        "executed": True, "command": " ".join(cmd), "target": ip, "sent": count,
        "replies": replies, "loss_pct": loss, "success": replies > 0,
        "avg_ms": round(statistics.mean(rtts), 1) if rtts and replies else None,
        "unreachable_msg": "unreachable" in out.lower(),
        "raw": out,
    }


# --------------------------------------------------------------------------- tool 3: TCP
def tcp_probe(ip, port, timeout=3.0):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.perf_counter()
    try:
        s.connect((ip, port))
        return {"ip": ip, "port": port, "state": "open", "time_ms": ms(time.perf_counter() - t0),
                "meaning": "3-way handshake completed (SYN -> SYN/ACK -> ACK)"}
    except ConnectionRefusedError as e:
        return {"ip": ip, "port": port, "state": "refused", "time_ms": ms(time.perf_counter() - t0),
                "error": str(e), "meaning": "host answered with TCP RST - nothing listening or firewall REJECT"}
    except (socket.timeout, TimeoutError) as e:
        return {"ip": ip, "port": port, "state": "timeout", "time_ms": ms(time.perf_counter() - t0),
                "error": str(e) or "timed out", "meaning": "no reply to SYN - silent DROP, black hole, or host down"}
    except OSError as e:
        winerr = getattr(e, "winerror", None)
        unreachable = e.errno in (113, 101, 65, 51) or winerr in (10065, 10051)
        return {"ip": ip, "port": port, "state": "unreachable" if unreachable else "error",
                "time_ms": ms(time.perf_counter() - t0), "error": str(e),
                "meaning": "a router reported no route (ICMP unreachable)" if unreachable else "socket error"}
    finally:
        s.close()


def check_tcp(addresses, port, timeout):
    return [tcp_probe(ip, port, timeout) for ip in addresses[:4]]


# --------------------------------------------------------------------------- tool 4: HTTP
class _PinnedHTTP(http.client.HTTPConnection):
    """HTTP connection to a specific IP while keeping the real Host header."""
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a specific IP; SNI + certificate check still use the hostname."""
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        raw = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def http_probe(host, ip, port, scheme, timeout=5.0, path="/"):
    cls = _PinnedHTTPS if scheme == "https" else _PinnedHTTP
    conn = cls(host, ip, port, timeout)
    t0 = time.perf_counter()
    try:
        conn.request("HEAD", path, headers={"User-Agent": "cis2347-net-agent/2.0"})
        r = conn.getresponse()
        return {"ok": True, "status": r.status, "reason": r.reason,
                "server": r.getheader("Server"), "time_ms": ms(time.perf_counter() - t0)}
    except (socket.timeout, TimeoutError):
        kind = "timeout"
    except (ConnectionResetError, http.client.RemoteDisconnected, BrokenPipeError,
            ConnectionAbortedError):
        kind = "reset (connection dropped mid-request)"
    except ConnectionRefusedError:
        kind = "refused"
    except ssl.SSLError as e:
        kind = f"tls error: {e.reason}"
    except OSError as e:
        kind = f"error: {e}"
    finally:
        conn.close()
    return {"ok": False, "error": kind, "time_ms": ms(time.perf_counter() - t0)}


# --------------------------------------------------------------------------- tool 5: TRACE
def check_trace(ip, max_hops=8):
    if IS_WINDOWS:
        cmd = ["tracert", "-d", "-h", str(max_hops), "-w", "1000", ip]
    elif shutil.which("traceroute"):
        cmd = ["traceroute", "-n", "-m", str(max_hops), "-w", "1", "-q", "2", ip]
    elif shutil.which("tracepath"):
        cmd = ["tracepath", "-n", "-m", str(max_hops), ip]
    else:
        return {"executed": False, "error": "no traceroute tool available"}
    code, out = run_cmd(cmd, timeout=max_hops * 4 + 15)
    if code is None:
        return {"executed": False, "command": " ".join(cmd), "error": out}

    hops, last_ok = [], None
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)[\s:]", line)
        if not m:
            continue
        n = int(m.group(1))
        ips = [x for x in re.findall(r"(\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f:]*:[0-9a-f:]+)", line[m.end():], re.I)
               if is_ip(x)]
        hop_ip = ips[0] if ips else None
        hops.append({"hop": n, "ip": hop_ip})
        if hop_ip and hop_ip != ip:
            last_ok = {"hop": n, "ip": hop_ip}
    reached = any(h["ip"] == ip for h in hops)
    return {"executed": True, "command": " ".join(cmd), "hops": hops, "reached_target": reached,
            "last_responding_hop": last_ok, "raw": out}


# --------------------------------------------------------------------------- tools 6+7: LATENCY + ROUTER STATS
def latency_series(host, ip, port, scheme, samples, timeout=2.0, gap=0.1):
    results = []
    for _ in range(samples):
        results.append(http_probe(host, ip, port, scheme, timeout))
        time.sleep(gap)
    good = [r["time_ms"] for r in results if r["ok"] and r["status"] < 500]
    failed = len(results) - len(good)
    stats = {"samples": samples, "ok": len(good), "failed": failed,
             "loss_pct": round(100.0 * failed / samples, 1),
             "errors": sorted({r.get("error", f"HTTP {r.get('status')}") for r in results
                               if not (r["ok"] and r["status"] < 500)})}
    if good:
        s = sorted(good)
        stats.update(min_ms=s[0], median_ms=round(statistics.median(s), 1),
                     p95_ms=s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], max_ms=s[-1],
                     jitter_ms=round(statistics.mean(abs(a - b) for a, b in zip(good, good[1:])), 1)
                     if len(good) > 1 else 0.0)
    return stats


def read_router_stats(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never use a proxy for this
    try:
        with opener.open(url, timeout=3) as r:
            return {"ok": True, **json.loads(r.read().decode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}


# --------------------------------------------------------------------------- reasoning
def first(results, state):
    return next((r for r in results if r["state"] == state), None)


def assess(ev):
    """Turn evidence into a verdict. Every reason points at a measurement."""
    dns, ping, tcp, http_r, trace = ev["dns"], ev.get("ping"), ev.get("tcp") or [], ev.get("http"), ev.get("trace")
    port = ev["port"]
    why, not_proven = [], []

    def out(verdict, layer, confidence, next_step):
        return {"verdict": verdict, "layer": layer, "confidence": confidence,
                "why": why, "not_proven": not_proven, "next_step": next_step}

    # ---------------- DNS failed
    if not dns["success"]:
        why.append(f"DNS lookup failed: {dns.get('error_kind')} ({dns.get('error')})")
        kp = ev.get("known_ip_ping")
        kt = ev.get("known_ip_tcp")
        if kp or kt:
            kip = ev["known_ip"]
            reach = (kp and kp["success"]) or (kt and kt["state"] == "open")
            if kp and kp.get("executed"):
                why.append(f"Ping to known IP {kip}: {kp['replies']}/{kp['sent']} replies")
            elif kp:
                why.append(f"Ping to known IP could not run: {kp.get('error')}")
            if kt:
                why.append(f"TCP {kip}:{port} -> {kt['state']} ({kt['time_ms']} ms)")
            if reach:
                why.append("So packets DO reach the internet - only the name -> address step is broken")
                not_proven.append("That the known IP is the correct address for this name")
                return out("DNS resolution fault - the network path itself is working",
                           "Layer 7 (DNS / name resolution)", "High",
                           "Check the spelling of the hostname, then the DNS server setting "
                           "(ipconfig /all) or try another resolver (nslookup <name> 1.1.1.1).")
            return out("Wider connectivity outage - DNS AND the direct IP both fail",
                       "Layer 1-3 (link / gateway)", "Medium",
                       "Check Wi-Fi/cable, default gateway (ipconfig), then ping the gateway.")
        not_proven.append("Whether the rest of the network works (no --known-ip given)")
        return out("DNS resolution failure", "Layer 7 (DNS)", "Medium",
                   "Re-run with --known-ip <address> to separate a DNS fault from a network fault.")

    why.append(f"DNS OK: {ev['target']} -> {', '.join(dns['addresses'][:3])}"
               if dns["executed"] else "Target is an IP address (DNS step not needed)")
    if ping and ping.get("executed"):
        why.append(f"Ping: {ping['replies']}/{ping['sent']} replies, {ping['loss_pct']}% loss"
                   + (f", avg {ping['avg_ms']} ms" if ping.get("avg_ms") is not None else ""))
    elif ping:
        why.append(f"Ping could not run: {ping.get('error')}")
    ping_ok = bool(ping and ping.get("success"))

    opened, refused = first(tcp, "open"), first(tcp, "refused")
    timed_out, unreach = first(tcp, "timeout"), first(tcp, "unreachable")

    # ---------------- Overload / congestion check (latency series)
    if ev.get("series") and opened:
        return assess_overload(ev, why, not_proven, out)

    # ---------------- TCP connected
    if opened:
        why.append(f"TCP {opened['ip']}:{port} OPEN in {opened['time_ms']} ms (handshake completed)")
        if not ping_ok and ping and ping.get("executed"):
            why.append("Ping failed BUT TCP connected -> ICMP is being filtered; the host is NOT down")
        if http_r is None:
            return out(f"Port {port} is reachable - transport layer healthy",
                       "Layer 4 (Transport) OK", "High", "No action needed for connectivity.")
        if not http_r["ok"]:
            why.append(f"HTTP request failed after TCP connected: {http_r['error']}")
            return out("Service accepted the connection but did not answer correctly (hung app or TLS problem)",
                       "Layer 7 (Application / TLS)", "Medium",
                       "Check the service process and its logs; test again with --scheme http if TLS is suspect.")
        st = http_r["status"]
        why.append(f"HTTP {st} {http_r['reason']} in {http_r['time_ms']} ms"
                   + (f" (Server: {http_r['server']})" if http_r.get("server") else ""))
        if st >= 500:
            why.append("A 5xx is an answer FROM the server -> the network delivered the request and the reply")
            not_proven.append("Which internal component failed (database, code, upstream) - check server logs")
            return out(f"Application/server fault (HTTP {st}) - the network is healthy",
                       "Layer 7 (Application)", "High",
                       "Check the web server / application logs. Do NOT restart routers or change DNS.")
        not_proven.append("Future availability, or the health of every resolved address")
        verdict = "Healthy - DNS, transport and HTTP all working"
        if st >= 400:
            verdict = f"Network healthy - server replied HTTP {st} (request rejected, not a network fault)"
        if not ping_ok and ping and ping.get("executed"):
            verdict += " (ICMP filtered)"
        return out(verdict, "None (all layers verified)" if st < 400 else "Layer 7 (request/URL)",
                   "High", "No action required.")

    # ---------------- TCP refused (RST)
    if refused:
        why.append(f"TCP {refused['ip']}:{port} REFUSED in {refused['time_ms']} ms -> host sent RST immediately")
        why.append("An RST proves the host is alive and reachable; it is the PORT that is closed")
        not_proven.append("Whether nothing is listening or a firewall REJECT rule sent the RST")
        return out(f"Port {port} closed / rejected - host reachable, service not listening",
                   "Layer 4 (Transport)", "High",
                   f"Start the service or check that it listens on port {port} (netstat -ano | findstr :{port}).")

    # ---------------- ICMP unreachable from a router
    if unreach:
        why.append(f"TCP {unreach['ip']}:{port} -> {unreach['error']}")
        return out("Routing failure - a router reported the destination is unreachable",
                   "Layer 3 (Network / routing)", "High",
                   "Check the route / default gateway; review the trace for the failing hop.")

    # ---------------- TCP timeout (silence)
    if timed_out:
        why.append(f"TCP {timed_out['ip']}:{port} TIMED OUT after {timed_out['time_ms']} ms -> SYN got no reply at all")
        if ping_ok:
            why.append("Host answers ping, so it is up - only this port is silently dropped")
            not_proven.append("Which device (host firewall vs network firewall) is dropping")
            return out(f"Port {port} filtered - firewall silently DROPs the connection",
                       "Layer 4 (Transport / firewall)", "High",
                       "Review firewall rules for this port (Windows Defender Firewall / cloud security group).")
        if trace and trace.get("executed"):
            lh = trace.get("last_responding_hop")
            if lh:
                why.append(f"Trace: last router that answered = hop {lh['hop']} ({lh['ip']}); "
                           f"no replies after that, target never reached")
            else:
                why.append("Trace: no router answered at all")
            not_proven.append("Firewall DROP vs. black-holed route (both look like silence) - needs packet capture")
            where = f"beyond hop {lh['hop']} ({lh['ip']})" if lh else "at or before the first hop"
            return out(f"No path to destination - traffic is black-holed {where}",
                       "Layer 3 (Network / routing)", "Medium",
                       "Confirm the IP is correct/routable; check routes or ask the upstream provider.")
        not_proven.append("Where along the path packets stop (run with --trace)")
        return out("Destination not responding (ping and TCP both silent)", "Layer 3 or 4", "Low",
                   "Run again with --trace to find where packets stop.")

    return out("Inconclusive - see raw evidence", "Unknown", "Low", "Collect more evidence.")


def assess_overload(ev, why, not_proven, out):
    s, b, rs = ev["series"], ev.get("bypass_series"), ev.get("router_stats")
    port = ev["port"]

    def line(label, x):
        if x.get("ok"):
            return (f"{label}: {x['ok']}/{x['samples']} OK, loss {x['loss_pct']}%, median {x['median_ms']} ms, "
                    f"p95 {x['p95_ms']} ms, jitter {x['jitter_ms']} ms")
        return f"{label}: 0/{x['samples']} OK, loss {x['loss_pct']}%"

    why.append(line(f"Through router (port {port})", s))
    if s["errors"]:
        why.append(f"Failure types seen: {', '.join(s['errors'])}")
    if b:
        why.append(line(f"Bypass path ({ev['bypass']})", b))

    base = b.get("median_ms", 0.0) if b and b.get("ok") else None
    p95 = s.get("p95_ms")
    slow = (p95 is not None and base is not None and p95 >= base + EXTRA_DELAY_FLAG_MS) or \
           (p95 is not None and base is None and p95 >= ABS_P95_FLAG_MS) or p95 is None
    lossy = s["loss_pct"] >= LOSS_FLAG_PCT
    bypass_ok = bool(b and b.get("ok") and b["loss_pct"] < LOSS_FLAG_PCT
                     and b.get("p95_ms", 9e9) < (base or 0) + EXTRA_DELAY_FLAG_MS)

    router_hot, name = False, "the intermediate router"
    if rs and rs.get("ok"):
        name = rs.get("name", name)
        why.append(f"Router stats ({name}): CPU {rs['cpu_util_pct']}%, queue {rs['queue_depth']}/{rs['queue_max']}, "
                   f"offered load {rs['offered_load_pct']}% of capacity, drops last {rs['window_s']}s = {rs['drops_window']}")
        if rs.get("top_talkers"):
            t = rs["top_talkers"][0]
            why.append(f"Top talker on {name}: {t['src']} = {t['pct']}% of connections")
        router_hot = rs["cpu_util_pct"] >= ROUTER_CPU_FLAG_PCT or rs["drops_window"] > 0
    elif rs:
        why.append(f"Router stats unavailable: {rs.get('error')}")

    if not (slow or lossy):
        why.append(f"Delay and loss are inside normal limits (loss < {LOSS_FLAG_PCT}%, "
                   f"p95 < bypass + {EXTRA_DELAY_FLAG_MS:.0f} ms)")
        not_proven.append("Behaviour under heavier load (this is a point-in-time baseline)")
        return out(f"Path through {name} is healthy - no congestion detected",
                   "None", "High", "Keep this as the baseline for later comparison.")

    if slow:
        why.append("Queuing delay detected: p95 far above the bypass path" if base is not None
                   else "Queuing delay detected: p95 above absolute limit")
    if lossy:
        why.append(f"Packet/connection loss {s['loss_pct']}% >= {LOSS_FLAG_PCT}% limit")
    why.append("TCP handshake to the router still succeeds -> the router is up but cannot keep up")

    if bypass_ok:
        why.append("Same server is fast and loss-free when the router is bypassed -> server is NOT the bottleneck")
        if router_hot:
            why.append(f"{name} confirms overload from its own counters (CPU / queue / drops)")
        not_proven.append("Whether the flood is malicious (DoS) or a misconfiguration - inspect the top talker")
        return out(f"NETWORK OVERLOAD FLAGGED at {name} - congestion is causing delay and drops",
                   "Layer 3 (router congestion / queuing)", "High" if router_hot else "Medium",
                   f"Rate-limit or block the top talker, apply QoS, or add capacity on {name}. "
                   "Do not restart the web server - it is healthy.")
    if b:
        why.append("Bypass path is ALSO slow/lossy -> the server itself is overloaded, not the router")
        return out("Server overload - the slowdown follows the server, not the router",
                   "Layer 7 (Application capacity)", "Medium", "Check server CPU / connection limits.")
    not_proven.append("Which hop is congested (no bypass path or router stats supplied)")
    return out("Congestion detected on the path (location unknown)", "Layer 3", "Low",
               "Re-run with --bypass host:port and --router-stats to locate the bottleneck.")


# --------------------------------------------------------------------------- report printing
def print_report(ev, verdict):
    w = 66
    print("=" * w)
    print(" AI NETWORK TROUBLESHOOTING AGENT  (skill: ai-network-troubleshooting)")
    print(f" Target : {ev['target']}   Port: {ev['port']}/{ev['scheme'] if ev['http_enabled'] else 'tcp'}")
    print(f" Time   : {ev['timestamp']}   OS: {platform.system()}")
    print("=" * w)

    d = ev["dns"]
    print("[1] DNS   tool: system resolver + nslookup")
    if not d["executed"]:
        print("    SKIP  " + d["note"])
    elif d["success"]:
        print(f"    PASS  {ev['target']} -> {', '.join(d['addresses'][:4])}  ({d['time_ms']} ms)")
    else:
        print(f"    FAIL  {d['error_kind']}  [{d['error']}]")
    if d.get("nslookup_raw"):
        lines = [l for l in d["nslookup_raw"].splitlines() if l.strip()][:6]
        print("          nslookup says: " + " | ".join(l.strip() for l in lines))

    if ev.get("known_ip"):
        print(f"[1b] KNOWN-IP CHECK   comparing against operator-supplied IP {ev['known_ip']}")
        kp, kt = ev.get("known_ip_ping"), ev.get("known_ip_tcp")
        if kp:
            print(f"    PING  {kp.get('replies', 0)}/{kp.get('sent', '?')} replies" if kp.get("executed")
                  else f"    PING  could not run: {kp.get('error')}")
        if kt:
            print(f"    TCP   {kt['ip']}:{kt['port']} {kt['state'].upper()} ({kt['time_ms']} ms)")

    p = ev.get("ping")
    if p is not None:
        print(f"[2] PING  tool: {p.get('command', 'ping')}")
        if p.get("executed"):
            tag = "PASS" if p["success"] else "FAIL"
            avg = f", avg {p['avg_ms']} ms" if p.get("avg_ms") is not None else ""
            extra = "  (router said 'unreachable')" if p.get("unreachable_msg") else ""
            print(f"    {tag}  {p['replies']}/{p['sent']} replies, {p['loss_pct']}% loss{avg}{extra}")
        else:
            print(f"    N/A   {p.get('error')}")

    if ev.get("tcp"):
        print(f"[3] TCP   tool: socket connect to port {ev['port']}")
        for t in ev["tcp"]:
            print(f"    {t['state'].upper():<8}{t['ip']}:{t['port']}  {t['time_ms']} ms  - {t['meaning']}")

    h = ev.get("http")
    if h is not None:
        print(f"[4] HTTP  tool: {ev['scheme'].upper()} HEAD /")
        if h["ok"]:
            srv = f"  Server: {h['server']}" if h.get("server") else ""
            print(f"    {h['status']} {h['reason']}  in {h['time_ms']} ms{srv}")
        else:
            print(f"    FAIL  {h['error']}  after {h['time_ms']} ms")

    tr = ev.get("trace")
    if tr is not None:
        print(f"[5] TRACE tool: {tr.get('command', 'traceroute')}")
        if tr.get("executed"):
            for hop in tr["hops"]:
                print(f"    hop {hop['hop']:>2}: {hop['ip'] or '*  (no reply)'}")
            print(f"    target reached: {tr['reached_target']}")
        else:
            print(f"    N/A   {tr.get('error')}")

    for key, label in (("series", "through router"), ("bypass_series", "bypass path")):
        s = ev.get(key)
        if s:
            num = "6" if key == "series" else "6b"
            print(f"[{num}] LATENCY SERIES ({label})  tool: {s['samples']} x HTTP HEAD")
            if s["ok"]:
                print(f"    ok {s['ok']}/{s['samples']}  loss {s['loss_pct']}%  min {s['min_ms']}  median {s['median_ms']}"
                      f"  p95 {s['p95_ms']}  max {s['max_ms']}  jitter {s['jitter_ms']} (ms)")
            else:
                print(f"    ok 0/{s['samples']}  loss {s['loss_pct']}%")
            if s["errors"]:
                print(f"    failures: {', '.join(s['errors'])}")

    rs = ev.get("router_stats")
    if rs is not None:
        print("[7] ROUTER STATS  tool: router stats page (SNMP-style counters)")
        if rs.get("ok"):
            print(f"    {rs['name']}: CPU {rs['cpu_util_pct']}%  queue {rs['queue_depth']}/{rs['queue_max']}  "
                  f"offered load {rs['offered_load_pct']}%  drops(last {rs['window_s']}s) {rs['drops_window']}  "
                  f"drops(total) {rs['drops_total']}")
            for t in rs.get("top_talkers", [])[:3]:
                print(f"    top talker: {t['src']:<12} {t['pct']}% of connections")
        else:
            print(f"    N/A   {rs.get('error')}")

    print("-" * w)
    print(" AGENT CONCLUSION")
    print(f"   Verdict    : {verdict['verdict']}")
    print(f"   Fault layer: {verdict['layer']}")
    print(f"   Confidence : {verdict['confidence']}")
    print("   Why (evidence):")
    for r in verdict["why"]:
        print(f"     - {r}")
    if verdict["not_proven"]:
        print("   Not proven by this evidence:")
        for r in verdict["not_proven"]:
            print(f"     - {r}")
    print(f"   Next step  : {verdict['next_step']}")
    print("=" * w)


# --------------------------------------------------------------------------- main workflow
def parse_hostport(text):
    host, _, port = text.rpartition(":")
    return host, int(port)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evidence-based network troubleshooting agent")
    ap.add_argument("target", help="hostname or IP address you are authorized to test")
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--scheme", choices=["http", "https"], default="https")
    ap.add_argument("--no-http", action="store_true", help="skip the HTTP check (non-web service)")
    ap.add_argument("--known-ip", help="IP to compare against when DNS fails")
    ap.add_argument("--trace", action="store_true", help="always run a route trace")
    ap.add_argument("--no-trace", action="store_true", help="never run a route trace")
    ap.add_argument("--max-hops", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=3.0, help="TCP timeout seconds")
    ap.add_argument("--samples", type=int, default=0, help="repeated HTTP probes for congestion check")
    ap.add_argument("--bypass", help="host:port of the same service reached WITHOUT the suspect router")
    ap.add_argument("--router-stats", help="URL of the router stats page (JSON)")
    ap.add_argument("--json", action="store_true", help="also print the JSON evidence ledger")
    a = ap.parse_args(argv)

    if not 1 <= a.port <= 65535:
        ap.error("port must be 1-65535")
    if "/" in a.target:
        ap.error("give a hostname or IP, not a URL")

    ev = {"timestamp": now_utc(), "target": a.target, "port": a.port, "scheme": a.scheme,
          "http_enabled": not a.no_http}

    ev["dns"] = check_dns(a.target)
    if not ev["dns"]["success"]:
        if a.known_ip:
            ev["known_ip"] = a.known_ip
            ev["known_ip_ping"] = check_ping(a.known_ip)
            ev["known_ip_tcp"] = tcp_probe(a.known_ip, a.port, a.timeout)
    else:
        addrs = ev["dns"]["addresses"]
        ev["ping"] = check_ping(addrs[0])
        ev["tcp"] = check_tcp(addrs, a.port, a.timeout)
        opened = first(ev["tcp"], "open")
        if opened and not a.no_http and not a.samples:
            ev["http"] = http_probe(a.target, opened["ip"], a.port, a.scheme)
        if opened and a.samples:
            ev["series"] = latency_series(a.target, opened["ip"], a.port, a.scheme, a.samples)
            if a.bypass:
                bh, bp = parse_hostport(a.bypass)
                bip = check_dns(bh)["addresses"][0]
                ev["bypass"] = a.bypass
                ev["bypass_series"] = latency_series(bh, bip, bp, a.scheme, a.samples)
            if a.router_stats:
                ev["router_stats"] = read_router_stats(a.router_stats)
        answered = opened or first(ev["tcp"], "refused")   # an RST means the host answered
        auto_trace = (not answered and not ev["ping"]["success"])
        if (a.trace or auto_trace) and not a.no_trace:
            ev["trace"] = check_trace(addrs[0], a.max_hops)

    verdict = assess(ev)
    print_report(ev, verdict)
    if a.json:
        print(json.dumps({"evidence": ev, "root_cause": verdict}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
