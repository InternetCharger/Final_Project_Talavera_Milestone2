# AI Network Troubleshooting Agent - How to run (VS Code, Windows)

Needs Python 3.10+ only (no installs, no admin, no Linux).

1. Open the `Final Project` folder in VS Code.
2. Open a terminal: **Terminal > New Terminal** (PowerShell).
3. Run:

```powershell
python run_scenarios.py          # shows the menu
python run_scenarios.py 1        # Normal - example.com
python run_scenarios.py 2        # DNS failure
python run_scenarios.py 3        # Service fault (HTTP 503)
python run_scenarios.py 4        # Port blocked (before/after)
python run_scenarios.py 5        # FAA-RTR-01 router overload (before/after, ~15 s)
python run_scenarios.py all      # everything
```

Every run is saved to `evidence/scenario_N_*.txt`. Take a screenshot of the terminal for the report.

## Files

| File | What it is |
|---|---|
| `network_diagnostics.py` | The agent: runs the tools and writes the conclusion |
| `run_scenarios.py` | Starts the lab, runs a scenario, saves the evidence |
| `lab/lab_web_server.py` | Fake company web app (200 OK or 503 error) on 127.0.0.1:8080 |
| `lab/faa_router_sim.py` | FAA-RTR-01 router simulator on 127.0.0.1:8081, stats on :8082 |
| `lab/traffic_flood.py` | Overloads FAA-RTR-01 (only allowed to target 127.0.0.1) |
| `.github/skills/*/SKILL.md` | Agent skills (loaded by Copilot agent mode) |
| `Milestone 2 Report.md` | The Milestone 2 write-up |

## Using it with the AI agent (Copilot Chat, agent mode)

Ask, for example:

> Use the ai-network-troubleshooting skill to diagnose localhost port 8080 over http.

> The network through FAA-RTR-01 feels slow. Use the router-overload-detection skill.

The agent runs `network_diagnostics.py`, reads the evidence, and explains the verdict.

**Troubleshooting:** if the scenario says a port is busy, close other terminals that are still running a lab server, or restart VS Code.
