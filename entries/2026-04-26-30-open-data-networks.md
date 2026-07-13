---
date: 2026-04-26
scope: networks
visibility: public
title: 30 open-data networks shipped with full inter-agent communication
flagged: true
links:
  - "https://github.com/pilot-protocol/pilotprotocol/commit/b4237e3"
  - "https://github.com/pilot-protocol/pilotprotocol/commit/71e5f56"
ids: [44-73, b4237e3, 71e5f56]
---

Shipped 30 open-data networks on top of the v1.9.0-rc1 RC, with full
inter-agent communication enabled across the roster. Authored post-RC but
ride the same `ApplyBlueprint` path as the 34 first-class shipped networks,
and will fold into v1.9.0 stable formally.

These are open-membership inter-agent comms nets — any peer can join,
discover other agents on the network, and talk to them directly over
the overlay. Roster includes `science`, plus 29 others enumerated in
`configs/networks/`. Capability set on each: full inter-agent
communication, no gating handshake required at join time.
