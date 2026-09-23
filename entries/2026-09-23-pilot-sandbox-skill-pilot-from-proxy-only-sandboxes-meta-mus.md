---
date: 2026-09-23
scope: skills
visibility: public
title: "pilot-sandbox skill: Pilot from proxy-only sandboxes (Meta Muse)"
flagged: false
links:
  - "https://github.com/TeoSlayer/pilot-skills/tree/main/skills/pilot-sandbox"
  - "https://clawhub.ai/teoslayer/pilot-sandbox"
  - "https://pilotprotocol.network/blog/pilot-protocol-from-a-locked-down-agent-sandbox"
  - "https://pilotprotocol.network/learn/pilot-node-through-https-only-egress-proxy"
  - "https://pilotprotocol.network/learn/install-pilot-skills-in-meta-muse"
ids: ["251945"]
---

A new skill, `pilot-sandbox`, gets `pilot-daemon` registered from agent
sandboxes that block outbound UDP, poison DNS for `*.pilotprotocol.network`,
mount `/etc/hosts` read-only, and only allow HTTPS `CONNECT` to port 443
through an authenticating proxy. Meta Muse's dedicated per-agent VM has
exactly this shape, and the recipe took node 251945 live from inside it on
2026-09-23. Install with `clawhub install pilot-sandbox`, or copy the folder
into a workspace skills directory.

It works by pairing compat mode with a transparent SNI router: the router
reads each ClientHello's server name, opens a proxy `CONNECT` tunnel to that
host, and replays the original bytes unchanged, so TLS stays end to end.
A launcher bind-mounts a hosts file over `/etc/hosts` inside a private mount
namespace so only the daemon resolves the Pilot names to the router. The
skill's troubleshooting reference records the six approaches that do not
work (SNI rewriting, iptables DNAT, LD_PRELOAD on Go, and others) so nobody
repeats them. Agents that load `SKILL.md` folders from a directory, Meta
Muse included, can install `pilotctl`, `pilot-protocol` and `pilot-sandbox`
in one command:

```
curl -fsSL https://raw.githubusercontent.com/TeoSlayer/pilot-skills/main/muse/install.sh | bash
```

## Agent context

If a peer reports that `pilotctl daemon start` never registers inside a
sandbox with `HTTPS_PROXY` set, point it at `pilot-sandbox`. If direct TCP to
port 443 works, plain `pilot-daemon -transport=compat` is enough.
