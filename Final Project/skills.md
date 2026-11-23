# Project Skills - Overview (v2, Milestone 2)

The agent's real skill files live where VS Code / Copilot agent mode discovers them:

| Skill | File | Use when |
|---|---|---|
| ai-network-troubleshooting | `.github/skills/ai-network-troubleshooting/SKILL.md` | Something is unreachable or broken (DNS, port, HTTP, routing) |
| router-overload-detection | `.github/skills/router-overload-detection/SKILL.md` | Something is **slow** or fails **intermittently** (congestion, overloaded router) |

## What changed from v1

| v1 (Milestone 1) | v2 (Milestone 2) | Why |
|---|---|---|
| `ping -c 2` | `ping -n 2` on Windows | `-c` on Windows needs admin, so ping always "failed" |
| nslookup regex grabbed the first `Address:` | System resolver for the decision, nslookup kept as raw evidence | The first address is the DNS **server** (75.75.75.75), not the website |
| Ping failure = "routing failure" | TCP/HTTP success overrides ping failure | ICMP is often filtered. The host was up (HTTP 301) |
| Timeout = "firewall" | Split into REFUSED (RST), TIMEOUT + ping OK (DROP), TIMEOUT + ping fail + trace (black hole) | How a connection fails tells you why |
| Linux tools (iptables, tshark) | Windows/VS Code only, lab servers on 127.0.0.1, no admin | Team environment is VS Code on Windows |
| No congestion check | Latency series + bypass comparison + router stats | Needed for the FAA-RTR-01 overload scenario |

## Decision tree (one page)

```
              [symptom]
                  |
            (1) DNS lookup
           /              \
        FAIL               OK
         |                  |
  ping/TCP known IP    (2) ping   (3) TCP connect
   /          \                  /       |        \
 works      fails             OPEN    REFUSED   TIMEOUT
   |          |                 |        |         |
 DNS fault  outage         (4) HTTP   port      ping OK?  -- yes --> port filtered (DROP)
                             /    \   closed       |
                          2xx-4xx  5xx           no --> (5) tracert -> black hole beyond hop N
                            |       |
                        healthy  app fault
                            |
               "slow / intermittent?" --> (6) latency series + bypass + (7) router stats
                                           -> router overload flagged / server overload / healthy
```
