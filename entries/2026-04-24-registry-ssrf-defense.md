---
date: 2026-04-24
scope: protocol
visibility: public
title: Registry SSRF defense and snapshot validation
flagged: false
links:
  - "https://github.com/pilot-protocol/pilotprotocol/commit/d4ec11a"
ids: [d4ec11a]
---

Hardened the registry HTTP surface against SSRF across the IDP-config,
webhook, and snapshot endpoints. `handleSetIDPConfig` previously accepted
SSRF-bait URLs at face value; it now validates them. Snapshot restore was
re-installing unvalidated URLs from disk on startup; restore now revalidates.
The cloud-metadata hostname check was case-sensitive and could be bypassed
with mixed case (`Metadata.google.internal`); now case-insensitive.

Resource caps added on `lastRekeyReq`, `relayPeers`, and the unauth
crypto-map so flood traffic can't grow them unbounded. Stale tunnel packets
are now classified separately from nonce replay (previously conflated in
metrics).
