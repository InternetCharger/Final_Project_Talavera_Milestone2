#!/usr/bin/env python3
"""
Milestone 2 scenario runner - run from the VS Code terminal.

    python run_scenarios.py          # list scenarios
    python run_scenarios.py 3        # run one scenario
    python run_scenarios.py all      # run all five

Each run prints to the screen AND saves a copy to evidence/scenario_N_*.txt
Lab servers are started and stopped automatically (they only listen on 127.0.0.1).
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
AGENT = os.path.join(HERE, "network_diagnostics.py")
LAB = os.path.join(HERE, "lab")
EVID = os.path.join(HERE, "evidence")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")

SCENARIOS = {
    "1": ("normal_baseline", "Normal state - healthy public website", "NORMAL"),
    "2": ("dns_failure", "DNS failure - name does not resolve, network still up", "ABNORMAL"),
    "3": ("service_fault", "Service fault - web app returns HTTP 503", "ABNORMAL"),
    "4": ("port_blocked", "Port blocked - web service stops listening on its port", "NORMAL -> ABNORMAL"),
    "5": ("faa_router_overload", "FAA-RTR-01 router overload - congestion flagged", "NORMAL -> NEW / UNSEEN"),
}


# ---------------------------------------------------------------- helpers
class Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def __call__(self, text=""):
        print(text, flush=True)
        self.f.write(text + "\n")

    def close(self):
        self.f.close()


def run_agent(say, args, title=None):
    cmd_show = "python network_diagnostics.py " + " ".join(args)
    say("")
    if title:
        say(f">>> {title}")
    say(f"PS> {cmd_show}")
    p = subprocess.run([PY, AGENT] + args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=ENV)
    for line in (p.stdout + p.stderr).rstrip().splitlines():
        say(line)


def start(script, *args):
    return subprocess.Popen([PY, os.path.join(LAB, script)] + list(args), env=ENV,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_port(port, seconds=8):
    end = time.time() + seconds
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.5):
                return True
        except OSError:
            time.sleep(0.2)
    raise SystemExit(f"Lab server on port {port} did not start")


def stop(*procs):
    for p in procs:
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


def tail(say, path, label, n=12):
    say("")
    say(f">>> {label}  ({os.path.relpath(path, HERE)}, last {n} lines)")
    if not os.path.exists(path):
        say("    (no log written)")
        return
    with open(path, encoding="utf-8") as f:
        for line in f.readlines()[-n:]:
            say("    " + line.rstrip())


def fresh_log(name):
    path = os.path.join(EVID, name)
    if os.path.exists(path):
        os.remove(path)
    return path


def port_free(port):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


# ---------------------------------------------------------------- scenarios
def s1(say):
    say("Goal: prove the agent recognises a fully healthy path (DNS -> ping -> TCP 443 -> HTTPS).")
    run_agent(say, ["example.com", "--port", "443"])


def s2(say):
    say("Goal: a mistyped / non-existent hostname. Is it DNS, or is the whole network down?")
    say("Fault injected: hostname 'exampel-cis2347.invalid' (.invalid is reserved by RFC 6761 - it can never resolve).")
    try:
        known = sorted({i[4][0] for i in socket.getaddrinfo("example.com", 443, socket.AF_INET)})[0]
        say(f"Known-good IP: {known}  (obtained by resolving example.com just before the test)")
    except OSError:
        known = "104.20.23.154"
        say(f"Known-good IP: {known}  (example.com address recorded in Milestone 1)")
    run_agent(say, ["exampel-cis2347.invalid", "--known-ip", known, "--no-http"])


def s3(say):
    say("Goal: users report 'the website is down'. Is it the network or the application?")
    say("Fault injected: lab web server on port 8080 started in --mode error (returns HTTP 503).")
    log = fresh_log("web_server_s3.log")
    web = start("lab_web_server.py", "--port", "8080", "--mode", "error", "--log", log)
    try:
        wait_port(8080)
        run_agent(say, ["localhost", "--port", "8080", "--scheme", "http"])
        time.sleep(0.5)
        tail(say, log, "Server-side log (independent verification)")
    finally:
        stop(web)


def s4(say):
    say("Goal: the web service on port 8080 stops. Can the agent tell 'port closed' from 'network down'?")
    log = fresh_log("web_server_s4.log")
    web = start("lab_web_server.py", "--port", "8080", "--mode", "ok", "--log", log)
    try:
        wait_port(8080)
        run_agent(say, ["localhost", "--port", "8080", "--no-http"], title="BEFORE - service running (normal)")
    finally:
        stop(web)
    time.sleep(1)
    say("")
    say(">>> Fault injected: web server stopped -> nothing is listening on port 8080 any more")
    run_agent(say, ["localhost", "--port", "8080", "--no-http"], title="AFTER - port blocked (abnormal)")


def s5(say):
    say("Goal: users say 'the network is slow'. Can the agent find and flag the overloaded router?")
    say("Path:  agent --> FAA-RTR-01 (:8081) --> web server (:8080)")
    wlog, rlog = fresh_log("web_server_s5.log"), fresh_log("faa_router.log")
    web = start("lab_web_server.py", "--port", "8080", "--mode", "ok", "--log", wlog)
    rtr = start("faa_router_sim.py", "--log", rlog, "--quiet")
    flood = None
    args = ["localhost", "--port", "8081", "--scheme", "http", "--samples", "10",
            "--bypass", "localhost:8080", "--router-stats", "http://127.0.0.1:8082/stats"]
    try:
        wait_port(8080)
        wait_port(8081)
        wait_port(8082)
        time.sleep(1.5)
        run_agent(say, args, title="BEFORE - FAA-RTR-01 normal (no extra traffic)")
        flood = start("traffic_flood.py", "--rate", "160", "--seconds", "30")
        say("")
        say(">>> Fault injected: flood of traffic sent into FAA-RTR-01 (more than it can handle)")
        time.sleep(6)
        run_agent(say, args, title="AFTER - FAA-RTR-01 overloaded")
        time.sleep(1.2)
        tail(say, rlog, "FAA-RTR-01 router log (verification)", n=4)
    finally:
        stop(flood, rtr, web)


RUNNERS = {"1": s1, "2": s2, "3": s3, "4": s4, "5": s5}


def main():
    os.makedirs(EVID, exist_ok=True)
    pick = sys.argv[1] if len(sys.argv) > 1 else ""
    if pick not in RUNNERS and pick != "all":
        print(__doc__)
        for k, (_, title, kind) in SCENARIOS.items():
            print(f"  {k}. [{kind:<12}] {title}")
        return
    for k in (RUNNERS if pick == "all" else [pick]):
        slug, title, kind = SCENARIOS[k]
        say = Tee(os.path.join(EVID, f"scenario_{k}_{slug}.txt"))
        say("#" * 66)
        say(f"# SCENARIO {k}: {title}")
        say(f"# Condition type: {kind}")
        say(f"# Run at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        say("#" * 66)
        try:
            RUNNERS[k](say)
        finally:
            say.close()
        print(f"\n[saved] evidence/scenario_{k}_{slug}.txt\n")


if __name__ == "__main__":
    main()
