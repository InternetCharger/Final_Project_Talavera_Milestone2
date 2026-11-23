---
name: router-overload-detection
description: "Detect and locate network congestion or an overloaded router (for example FAA-RTR-01) using repeated latency probes, a bypass-path comparison and router counters. Use when users report the network is slow, laggy, or pages fail intermittently while the server seems up."
---

# Router Overload Detection

Use this skill when the symptom is **slow or intermittent**, not "completely down".
One probe cannot show congestion. You need many samples, a baseline, and a comparison path.

## Why overload looks different

An overloaded router is still up. It still completes TCP handshakes and still answers ping.
It is just too busy. Packets wait in its input queue (**queuing delay**). When the queue is full,
new packets are thrown away (**tail drop**). So the signs are:

- latency far above normal, with high p95 values
- jitter (latency that jumps around)
- some requests reset or time out (loss)
- the same server is fast when you reach it **without** going through the router

Rough rule: delay ≈ packets waiting in the queue × time to process each one.

## Procedure

1. **Baseline first.** Measure the path when it is healthy and keep the numbers.
2. **Sample through the suspect router** (10 probes):
   ```powershell
   python network_diagnostics.py localhost --port 8081 --scheme http --samples 10 `
          --bypass localhost:8080 --router-stats http://127.0.0.1:8082/stats
   ```
3. **Compare with the bypass path** (`--bypass`). It reaches the same server without the router.
4. **Read the router's own counters** (`--router-stats`). This is the lab version of SNMP:
   CPU %, queue depth, offered load vs capacity, drops, top talker.
5. **Check the router log** (`evidence/faa_router.log`) as independent verification.

## Flag rules

Flag **NETWORK OVERLOAD at <router>** when all three are true:

| Check | Threshold |
|---|---|
| Path is degraded | loss ≥ 5 % **or** p95 ≥ bypass median + 100 ms |
| Bypass is healthy | bypass loss < 5 % and p95 < bypass median + 100 ms |
| (confidence High) Router agrees | CPU ≥ 85 % **or** drops in last window > 0 |

Other outcomes:

- Path degraded **and** bypass degraded: **server overload**, not the router.
- Path degraded, no bypass or stats: **congestion, location unknown**. Ask for a bypass path.
- Nothing degraded: **healthy**. Save the result as the new baseline.

## What not to conclude

- Do not say the router is down. It is up but overloaded.
- Do not blame the web server when the bypass path is fast.
- Do not call the flood an attack without evidence. Name the top talker and recommend investigating it.

## Recommended actions (least invasive first)

1. Identify the top talker and rate-limit or block it (ACL / policer).
2. Apply QoS so critical traffic is served first.
3. Add capacity or move load to another router.
4. Re-run the same probes and confirm that p95 and loss return to baseline.

## Lab safety

`lab/traffic_flood.py` refuses any target except 127.0.0.1. Never point load generators at real networks.
