# Schema

Stable contracts for peer consumers of `pilot-changelog`. The current
`schema_version` is **`1`** on every JSON output. Breaking changes will
bump this number; additive changes (new optional fields) keep it.

## Discovery

Start at `index.json`. It enumerates every published feed, their windows,
their URLs (relative to the manifest), and their descriptions. A peer
that fetches `index.json` once knows everything it can subscribe to.

```json
{
  "schema_version": 1,
  "repo": "https://github.com/TeoSlayer/pilot-changelog",
  "latest_entry_date": "2026-04-26",
  "feeds": [
    {"name": "all", "window": "all", "url": "feed.json", "description": "..."},
    {"name": "1d", "window": "1d", "url": "feed-1d.json", "description": "..."},
    {"name": "scope:protocol", "window": "all", "url": "feed-protocol.json", "description": "..."}
  ]
}
```

## JSON feed shape

Every `feed*.json` (including per-scope and `feed-private.json`) follows:

```json
{
  "schema_version": 1,
  "latest_entry_date": "2026-04-26",
  "window": "all",
  "include_private": false,
  "count": 7,
  "entries": [ ...Entry... ]
}
```

| Field | Type | Notes |
|---|---|---|
| `schema_version` | integer | `1` today. Bumps on breaking changes. |
| `latest_entry_date` | string \| null | Newest entry's `date`. `null` if `count == 0`. |
| `window` | string | `"all"`, `"1d"`, `"7d"`, `"1m"`, `"flagged"`, or `"scope:<scope>"`. |
| `include_private` | boolean | `true` only on `feed-private.*` (operator-only, gitignored). |
| `count` | integer | `entries.length`. |
| `entries` | Entry[] | Newest first. |

### Entry shape

```json
{
  "id": "2026-04-26-30-open-data-networks",
  "date": "2026-04-26",
  "scope": "networks",
  "visibility": "public",
  "title": "30 open-data networks shipped...",
  "flagged": true,
  "links": ["https://github.com/.../commit/b4237e3"],
  "ids": ["44-73", "b4237e3"],
  "body": "...full body markdown...",
  "excerpt": "First paragraph of body, plain text."
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | Filename stem; stable per entry. |
| `date` | string | `YYYY-MM-DD`, UTC. |
| `scope` | string | One of: `protocol`, `networks`, `skills`, `infra`, `ops`, `docs`. The special `motd` scope is consumed only by `feed-motd.json` — see below. |
| `visibility` | string | `public` (always for public feeds). `private` only appears in operator-only outputs. |
| `title` | string | Plain text. |
| `flagged` | boolean | `true` → also surfaces in `feed-flagged.json` regardless of date window. |
| `links` | string[] | External URLs only on public entries. May be empty. |
| `ids` | string[] | Free-form correlation IDs (commits, ticket IDs, etc.). May be empty. |
| `body` | string | Entry body, raw markdown. May contain headings/lists/code. |
| `excerpt` | string | First paragraph of body, plain text — convenient for listings. |

## Message of the day (`motd` scope)

The `motd` scope is a special-cased feed for the **message-of-the-day banner**
that `pilot-daemon` shows ahead of every `pilotctl` command. It rides the same
entry/render pipeline as the changelog but is **kept out of the human-facing
feeds** (`feed.json`, the windowed feeds, `feed-flagged.json`, `feed.xml`,
`feed.md`, and the Pages site) — it is published **only** to
`feed-motd.json`.

For a `motd` entry the standard fields are re-purposed:

| Field | Meaning for `motd` |
|---|---|
| `date` | The **UTC day the banner is active** (not a publish date). The daemon shows the entry whose `date` equals the current UTC day. |
| `title` | The **banner text**, shown verbatim by `pilotctl`. Keep it short and plain. |
| `body` / `excerpt` / `links` / `ids` / `flagged` | Ignored by the daemon. |

Conventions: keep **at most one** `motd` entry per `date`. A withdrawn banner
(no entry for today) self-clears in the daemon within one poll interval.
Tooling: `scripts/set-motd.sh "text" [YYYY-MM-DD]` and
`scripts/clear-motd.sh [YYYY-MM-DD|--all]` author/remove a banner and
re-render. `feed-motd.json` follows the same JSON feed shape as every other
feed (`window` is `"scope:motd"`).

## Determinism

- `feed.json`, `feed-flagged.json`, per-scope feeds, `index.json`,
  `feed.xml`, `feed.md`, and `docs/index.html` are **deterministic**
  given entries — they only change when entries change.
- `feed-1d.json`, `feed-7d.json`, `feed-1m.json` are wall-clock-windowed
  and shift over time. The pre-commit hook keeps them fresh on each
  commit, but they may be stale by N days if no commits land. Peers
  needing a precise window should filter `feed.json` by `date` themselves.

CI enforces a drift check on the deterministic outputs only.

## RSS

`feed.xml` is RSS 2.0. Channel `<title>` is `Pilot Protocol Changelog`,
`<link>` points to the GitHub Pages site, items use the entry's `id` as
GUID and the entry's `date` (UTC midnight) as `<pubDate>` in RFC 822.

## Feed URLs

Every public feed is served from two origins:

**Primary — GitHub Pages** (single origin, RSS auto-discovery, faster):

- `https://teoslayer.github.io/pilot-changelog/` — human site
- `https://teoslayer.github.io/pilot-changelog/index.json` — manifest
- `https://teoslayer.github.io/pilot-changelog/feed.json` — canonical machine feed
- `https://teoslayer.github.io/pilot-changelog/feed.xml` — RSS
- `https://teoslayer.github.io/pilot-changelog/feed-<scope>.json` — per scope
- `https://teoslayer.github.io/pilot-changelog/feed-flagged.json` — flagged

**Alternate — `raw.githubusercontent.com`** (no Pages dep, ~5 min cache):

- `https://raw.githubusercontent.com/TeoSlayer/pilot-changelog/main/feed.json`
- `https://raw.githubusercontent.com/TeoSlayer/pilot-changelog/main/feed.xml`
- `https://raw.githubusercontent.com/TeoSlayer/pilot-changelog/main/index.json`
- (etc. — same filenames at the repo root)

## Polling

Peers should poll the manifest or `feed.json` on a cadence that suits
them. `latest_entry_date` lets a consumer skip parsing when nothing has
changed since their last successful fetch. There is no rate limit on
raw.githubusercontent.com beyond GitHub's standard caching (~5 min).

## Versioning

If `schema_version` ever needs to change in a breaking way, the new
version will ship alongside the old at a versioned URL (e.g.
`feed.v2.json`) for a deprecation period. Peer consumers should pin to
`schema_version: 1` and gracefully ignore feeds with a higher version.
