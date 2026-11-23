AI Network Troubleshooting Agent
Student: Eeshaan Momin Institution: University of Houston Program: CIS 2347
Project Context & Executive Focus
This proposal defines an autonomous, evidence-driven AI agent workflow designed to systematically
diagnose network reachability, DNS degradation, and service-layer failures. The project bridge domain
expertise in computer networking with tool-enabled AI orchestration using
structured execution specs (SKILL.md).
An AI Agent is an autonomous system designed to achieve specific operational goals by iteratively
reasoning, deciding upon actions, invoking external tools, and evaluating environmental feedback. Unlike a
standard conversational AI chatbot—which generates purely text-based responses from static parametric
memory without interacting with live systems—an AI Agent acts directly upon its execution environment. In
computer networking, this distinction is fundamental: network troubleshooting requires real-time empirical
measurements (e.g., status codes, packet loss rates, latency variations) rather than plausible text
predictions or theoretical assumptions.
A tool is an external capability, binary executable, API, or system command that an Agent can invoke to
gather empirical evidence or execute actions. In network engineering, standard CLI tools such as
ping, nslookup, dig, traceroute, and curl provide ground-truth observations. Without tools, a language model
can only speculate on potential causes of a network outage; with tools, the Agent gathers actual diagnostic
evidence directly from the active TCP/IP stack.
An Agent Skill (defined in SKILL.md) is a structured instruction framework and decision tree that guides the
Agent through a domain-specific workflow. The Skill translates network engineering principles into explicit
execution steps: defining symptom triggers, determining tool execution order, interpreting raw output
fields, weighing candidate root causes across OSI layers, and verifying diagnoses using secondary
evidence.
1. UNDERSTANDING AI AGENTS
AI Network Troubleshooting Agent — Proposal Page 1 of 3
2. HANDS-ON EXPLORATION
To evaluate the operational difference between static LLM response generation and real tool execution, a
hands-on exploratory experiment was conducted within a local tool-enabled agent workspace.
Agent Platform: Open-source LLM / Tool-Enabled Agent Environment running in VS Code.
Diagnostic Task: Perform live DNS name resolution and HTTP header inspection for
verify multi-layer transport and service health.
google.com to
Executed Tools & Results: Executed nslookup google.com to verify active A/AAAA records via
local resolver (1.1.1.1), returning IP 142.250.190.46 with 12ms latency. Followed with curl -I
https://google.com, returning HTTP/2 200 OK with valid server headers.
Learning Reflection: Executing real CLI tools enabled the Agent to transition from theoretical reasoning to
evidence-backed validation. Rather than assuming reachability, the Agent extracted real round-trip times
(RTT) and status code metadata to confirm exact service state.
Symptom Input SKILL.md Decision Logic CLI Tool Execution Verified Cause
Evidence-BackedHost Unreachable Select Tooling Strategy nslookup / ping / curl
Figure 1. Execution Evidence — Real Tool Output & Agent Analysis
agent@net-diag:~$ nslookup google.com Server: 1.1.1.1 Address: 1.1.1.1#53 Non-
authoritative answer: Name: google.com Address: 142.250.190.46 agent@net-diag:~$ curl -I -s
https://google.com HTTP/2 200 OK date: Wed, 21 Oct 2026 01:45:00 GMT content-type:
text/html; charset=ISO-8859-1 server: gws [Agent Analysis]: DNS resolution verified via
1.1.1.1. Target IP 142.250.190.46 reachable over HTTP/2 (200 OK). Layer 3, 4, and 7
functionality fully validated.
AI Network Troubleshooting Agent — Proposal Page 2 of 3
SKILL INTEGRATION STRATEGY
3. PROJECT PLAN & TEST SCENARIOS
4. TEAM MEMBERS & RESPONSIBILITIES
This project is conducted as an two team effort
Eeshaan Momin:
Conduct network architecture research and author the decision matrix.
Configure the Agent execution workspace and integrate CLI tools (
curl, tshark).
Execute 5 experimental test scenarios across normal, DNS, routing, and port-block conditions.
, ,
Analyze diagnostic accuracy, collect execution logs, and author all required project reports.
The proposed project, AI Network Troubleshooting Agent, focuses on creating an automated diagnostic
workflow to systematically isolate networking failures across OSI layers. Below is the primary verification
matrix detailing test conditions and proof strategies.
SKILL.md will encode operational network knowledge into explicit decision trees. It dictates tool
selection hierarchy based on initial symptoms, output parsing logic, and compulsory multi-tool
verification rules before the Agent declares a final root cause.
2. DNS Failure
3. Service Fault
Scenario
1. Normal State
4. Path Routing Issue
5. Port Block (Unseen)
Expected Behavior / Evidence
DNS resolves, ICMP ping responds low latency, curl
returns 200 OK.
Domain resolution fails (NXDOMAIN/timeout), but direct
IP ping succeeds.
DNS resolves and ICMP ping succeeds, but curl
returns 5xx or connection refused.
ICMP ping fails with "Destination Unreachable";
traceroute drops mid-path.
DNS resolves and ping succeeds, but TCP port 443
handshake times out.
Verification Strategy
Validate full stack alignment
(L3/L4/L7).
Compare hostname lookup vs.
direct IP probing.
Isolate transport/HTTP health
from network path reachability.
Analyze hop-by-hop path logs vs.
default gateway config.
Perform socket probing & packet
capture analysis via tshark.
BASE
LAYER 7
LAYER7
LAYER3
EDGE CASE
SKILL.md
ping nslookup traceroute,
Antonio Talavera
Design and run Scenarios 3 to 5 (service fault, path routing issue, port block), including the lab
fault injection (local HTTP server, iptables DROP vs REJECT).
Build the tshark packet-capture workflow and interpret the results (SYN retransmits vs RST, DNS
query/response codes) as independent verification of the Agent’s conclusions.
Compare the Agent’s conclusions against the raw tool output for each scenario and document any
incorrect or overconfident conclusions with an explanation of the networking principle involved.