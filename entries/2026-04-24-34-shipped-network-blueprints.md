---
date: 2026-04-24
scope: networks
visibility: public
title: 34 shipped network blueprints
flagged: false
links:
  - "https://github.com/pilot-protocol/pilotprotocol/commit/df9f6b4"
ids: [df9f6b4]
---

Shipped 34 first-class network blueprints under `configs/networks/`. Each
was round-tripped through provisioning at test time and is auto-deployed
through the Apply Networks workflow whenever the file changes on `main`.

This is the first cut of "first-class networks" — opinionated policy
defaults baked into the binary so a fresh deployment can join a real
network without authoring blueprints from scratch. Includes the
data-exchange policy tightening that landed in the same commit group.

Peers without a specific custom-network requirement can join from this
shipped roster directly. The 30 open-data networks (entry dated
2026-04-26) sit on top of these.
