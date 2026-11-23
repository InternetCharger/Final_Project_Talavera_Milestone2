# AI Network Troubleshooting Agent — Milestone 1

## Project and team

**Project title:** AI Network Troubleshooting Agent

| Team member | Contribution to this milestone |
|---|---|
| Eeshaan Momin | Researched the diagnostic workflow, configured the workspace Skill, and ran the initial DNS/TCP/HTTP demonstration. |

## Initial Skill

The project Skill is [`.github/skills/ai-network-troubleshooting/SKILL.md`](./.github/skills/ai-network-troubleshooting/SKILL.md). It directs the agent to clarify authorization and target, then gather DNS, ICMP, TCP, HTTP, and (when needed) route evidence in a graduated order. It also requires separating measurements from hypotheses and cautions against concluding that a host is down based only on ping.

## Networking knowledge translated into the workflow

The workflow follows the layered nature of network troubleshooting. DNS resolution checks whether a hostname maps to an address. ICMP echo tests provide a basic reachability/latency signal, but firewalls may block ICMP even while a service works. A TCP connection test checks whether a particular transport-layer port completes its handshake. An HTTP request then checks application-layer behavior and status. Comparing these results helps narrow a symptom to name resolution, reachability/path, transport/service, or application behavior rather than treating every failure as “the network is down.”

The chosen tools are native PowerShell/Windows utilities available in this environment: `Resolve-DnsName`, `Test-Connection`, `Test-NetConnection`, `Invoke-WebRequest`, and `tracert`. They are targeted and read-only for the checks used here, and provide evidence at distinct layers. Route tracing is conditional because missing hop responses can reflect filtering. Packet capture with Wireshark/`tshark` is reserved for an authorized, narrowly scoped follow-up when command outputs cannot distinguish protocol-level causes.

## Working demonstration

The Skill is saved in the project workspace in the VS Code-discoverable `.github/skills/<skill-name>/SKILL.md` format, with valid frontmatter and a matching folder/name. The agent loaded the Skill and ran its DNS → TCP → HTTP workflow using `example.com` as a benign public test endpoint. These point-in-time results can vary by network.

**DNS — `Resolve-DnsName -Name example.com -Type A`**

```text
Name        Type TTL IPAddress
----        ---- --- ---------
example.com   A 297 172.66.147.243
example.com   A 297 104.20.23.154
```

**TCP — `Test-NetConnection -ComputerName example.com -Port 443 -InformationLevel Detailed`**

```text
ComputerName          : example.com
RemoteAddress         : 2606:4700:10::ac42:93f3
RemotePort            : 443
NameResolutionResults :
TcpTestSucceeded      : True
```

**HTTP — `Invoke-WebRequest -Uri https://example.com/ -Method Head -TimeoutSec 15`**

```text
StatusCode        : 200
StatusDescription : OK
Server            : cloudflare
```

**Agent interpretation:** DNS returned two IPv4 A records; the TCP probe selected an IPv6 address and completed the connection to port 443; the HTTP HEAD request returned 200 OK. Together these observations verify name resolution and successful TCP/HTTPS service response at test time. They do not prove ICMP reachability, validate every address or network path, or guarantee future availability.

## Progress summary

Completed: created and loaded the initial workspace Skill, documented the layered decision workflow and tool-selection rationale, and verified the normal-state DNS/TCP/HTTP workflow with live command output. Problems: none encountered in the normal-state run; network policy, DNS answers, and remote service behavior may vary between runs. Next: run the proposal's DNS-failure, service-fault, routing, and blocked-port scenarios in a controlled/authorized lab, compare agent conclusions with raw evidence, and add narrowly scoped packet-capture verification if needed. It reports DNS results, tests one resolved address on the specified TCP port, and optionally sends an HTTP HEAD request without following redirects. The example.com demo succeeded: TCP connected and HTTPS returned 200. I also verified syntax and that URL and out-of-range port inputs are rejected.