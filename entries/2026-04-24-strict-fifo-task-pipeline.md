---
date: 2026-04-24
scope: protocol
visibility: public
title: Strict FIFO task pipeline and propagating trust revocation
flagged: false
links:
  - "https://github.com/pilot-protocol/pilotprotocol/commit/024693a"
ids: [024693a]
---

Task pipeline now executes strictly FIFO. Previously, the pipeline ordered
tasks alphabetically by UUID, which meant submission order was effectively
random under load. `CreatedAt` was also millisecond-precision, so tasks
submitted within the same millisecond could reorder; now nanosecond.

The submitter auto-cancels on accept timeout — previously left dangling.
Trust revocation now propagates to the remote peer rather than staying
local. `pilotctl task result` surfaces delivered payloads, and
`status_justification` is exposed in `task list`.
