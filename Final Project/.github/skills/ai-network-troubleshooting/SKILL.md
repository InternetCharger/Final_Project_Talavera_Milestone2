---
name: ai-network-troubleshooting
description: "Diagnose authorized network reachability, DNS, TCP port, HTTP service, routing and congestion symptoms with the project CLI. Use when a hostname or service appears unreachable, slow, or unhealthy."
---

# AI Network Troubleshooting (v2 - Milestone 2)

Gather evidence first, then reason. Never guess a cause from one probe.
Probe only hosts the user owns or is authorized to test, or the lab servers on 127.0.0.1.
Never scan address ranges, log in, exploit a service, or change network settings.
Environment: Windows + VS Code terminal (PowerShell). Python standard library only, no admin rights.

## 1. Run the diagnostic

```powershell
python network_diagnostics.py <hostname-or-ip> --port 443
```

The CLI runs these tools in order and stops early when a layer fails:

| Step | Tool | Layer | What it proves |
|---|---|---|---|
| 1 | System resolver + `nslookup` | 7 (DNS) | The name maps to an address |
| 1b | Ping + TCP to `--known-ip` (only if DNS failed) | 3/4 | Whether the network works without DNS |
| 2 | `ping -n 2` (Windows) | 3 | ICMP echo replies, loss, RTT |
| 3 | TCP socket connect | 4 | Port is open (handshake), refused (RST) or silent (timeout) |
| 4 | HTTP `HEAD /` | 7 | Status code, server header, response time |
| 5 | `tracert -d` (auto when ping AND TCP are both silent, or `--trace`) | 3 | Last router that answered |
| 6 | Latency series (`--samples N`) | 3-7 | Loss %, median, p95, jitter over N probes |
| 7 | Router stats page (`--router-stats URL`) | 3 | Router CPU, queue, drops, top talker |

Options: `--known-ip`, `--no-http`, `--scheme http`, `--trace`, `--no-trace`, `--max-hops`,
`--timeout`, `--samples`, `--bypass host:port`, `--router-stats URL`, `--json`.

## 2. Decision rules (how to reason)

Read the evidence top to bottom. The first rule that matches is the verdict.

| DNS | Ping | TCP | HTTP / other | Verdict | Layer |
|---|---|---|---|---|---|
| FAIL | known IP replies / TCP open | - | - | DNS fault, network OK | 7 (DNS) |
| FAIL | known IP also fails | - | - | Wider outage (link/gateway) | 1-3 |
| OK | any | OPEN | 2xx/3xx | Healthy | none |
| OK | **FAIL** | OPEN | 2xx/3xx | Healthy - ICMP is filtered, host is NOT down | none |
| OK | any | OPEN | 5xx | Application fault, network healthy | 7 |
| OK | any | REFUSED (fast RST) | - | Port closed / REJECT, host is reachable | 4 |
| OK | OK | TIMEOUT | - | Port filtered - firewall silent DROP | 4 |
| OK | FAIL | TIMEOUT | trace stops at hop N | Black-holed path beyond hop N | 3 |
| OK | any | OPEN | series slow/lossy, bypass fast | Router congestion - see `router-overload-detection` skill | 3 |

Key networking facts the agent must apply:

1. **A failed ping does not mean the host is down.** Many networks block ICMP. TCP/HTTP success overrides a ping failure.
2. **REFUSED is an answer; TIMEOUT is silence.** An RST proves the host is alive. Silence means a DROP rule, a black-hole route, or a dead host. Use ping and trace to tell them apart.
3. **A 5xx is a reply from the server.** The request and response crossed the network successfully, so do not blame DNS, routing or the router.
4. **Windows ping trap:** "Reply from <router>: Destination host unreachable" is counted as *Received* by Windows. Only lines with `TTL=` are real echo replies (the CLI counts these).
5. **Windows `ping -c` is not count.** On Windows `-c` means routing compartment and needs admin. Use `-n`. (This bug caused a wrong verdict in Milestone 1.)
6. **Missing trace hops (`*`)** can be ICMP rate limiting. Only call it a path failure when the target is never reached AND TCP also failed.

## 3. Lab scenarios (Milestone 2)

Run from the project folder. Each command saves evidence to `evidence/`.

```powershell
python run_scenarios.py all     # or 1, 2, 3, 4, 5
```

| # | Scenario | Type | Tools used | Expected verdict |
|---|---|---|---|---|
| 1 | `example.com` healthy | Normal | DNS, ping, TCP, HTTP | Healthy |
| 2 | `exampel-cis2347.invalid` + `--known-ip` | Abnormal | DNS, nslookup, ping, TCP | DNS fault, network OK |
| 3 | Lab web server returns 503 | Abnormal | DNS, ping, TCP, HTTP, server log | Application fault |
| 4 | Lab web server running, then stopped (port 8080) | Normal -> Abnormal | DNS, ping, TCP | Before: port open. After: port closed, host reachable |
| 5 | FAA-RTR-01 normal, then flooded | Normal -> Unseen | TCP, latency series, bypass, router stats, router log | Before: healthy. After: router overload flagged |

Fault injection only uses 127.0.0.1 lab servers and a reserved `.invalid` name.
It never touches real third-party systems.

## 4. Report format

For every run, report:

1. Target, time, command.
2. Raw evidence lines (copy from the output).
3. Verdict + fault layer + confidence.
4. **Why**: each reason points to a measurement.
5. **Not proven**: what this evidence cannot show.
6. Least-invasive next step.

Keep observations separate from hypotheses. If two tools disagree (for example, ping fails but HTTP works), explain the disagreement. Do not pick one result and ignore the other.
