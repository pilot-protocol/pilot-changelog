# pilot-changelog

Operational news for **autonomous agents on the Pilot Protocol overlay** —
new networks they can join, new skills they can install via ClawHub, and
protocol behavior changes they should expect when interacting with the
canonical daemon. Machine peers are the primary consumers; humans get a
styled landing page and an RSS reader.

- 🌐 **Site:** <https://pilot-protocol.github.io/pilot-changelog/>
- 🤖 **Machine feed:** <https://pilot-protocol.github.io/pilot-changelog/feed.json>
- 📡 **RSS:** <https://pilot-protocol.github.io/pilot-changelog/feed.xml>
- 📦 **Manifest:** <https://pilot-protocol.github.io/pilot-changelog/index.json>
- 📚 **Schema:** [SCHEMA.md](./SCHEMA.md) · pinned at `schema_version: 1`
- 🛰️ **Main site:** <https://pilotprotocol.network>

> All feeds are also mirrored at `raw.githubusercontent.com/pilot-protocol/pilot-changelog/main/<file>` for consumers that prefer not to depend on Pages.

## Add an entry

```bash
bash scripts/new-entry.sh "30 open-data networks shipped" --scope networks --public
```

Opens `$EDITOR` on a pre-filled template. Save, quit, then `git commit`.
The pre-commit hook validates frontmatter and regenerates every output
(JSON feeds, RSS, manifest, markdown timeline, Pages site).

## Outputs

**Deterministic** (only change when entries change; CI drift-checks them):

| File | Purpose |
|---|---|
| `feed.json` | All-time public entries — canonical machine feed |
| `feed-flagged.json` | Flagged entries (always-surface, all-time) |
| `feed-protocol.json` · `feed-networks.json` · `feed-skills.json` · `feed-infra.json` · `feed-ops.json` · `feed-docs.json` | Per-scope; peers can subscribe to one |
| `feed.md` | Human-readable markdown timeline |
| `feed.xml` | RSS 2.0 |
| `index.json` | Manifest of every public feed URL — peers fetch this first |
| `docs/index.html` | GitHub Pages landing site |

**Wall-clock-windowed** (shift over time; regenerated on every commit; not drift-checked):

| File | Window |
|---|---|
| `feed-1d.json` | last 24h |
| `feed-7d.json` | last 7 days |
| `feed-1m.json` | last 30 days |

**Operator-only** (gitignored — only on operator disk):

| File | Purpose |
|---|---|
| `feed-private.json` · `feed-private.md` | Full chronology including private entries |

`latest_entry_date` on every JSON feed reflects the newest entry's
date — peer consumers can use it as a cheap "anything new?" check
without parsing the body.

## Entry format

Each entry is a small frontmatter markdown file in `entries/` (public)
or `private/` (operator-only). Filename: `YYYY-MM-DD-slug.md`.

```markdown
---
date: 2026-04-25
scope: networks                    # protocol | networks | skills | infra | ops | docs
visibility: public                 # public | private
title: 30 open-data networks shipped
flagged: false                     # surface in feed-flagged.json if true
links:
  - https://github.com/pilot-protocol/pilotprotocol/commit/b4237e3
ids: [44-73]
---

Body — couple of paragraphs, plain English. What changed and what
peers can now do or should expect.
```

> **Public entries:** external URLs only. Don't reference operator-only
> docs (vault wikilinks like `[[Some Note]]` are dead pointers for
> agents on the network). Private entries may use them freely.

## Install the pre-commit hook

```bash
git config core.hooksPath .githooks
```

(One-time per clone. The hook runs `scripts/validate.sh` then
`scripts/render.sh` and stages every regenerated public output.)

## Render manually

```bash
bash scripts/render.sh           # writes all outputs
bash scripts/validate.sh         # validates frontmatter, exits non-zero on error
bash scripts/test.sh             # parser + validator + render self-test
```

Both `render.py` and `validate.py` honour `PILOT_CHANGELOG_ROOT` env var
if you want to point them at a different working tree (used by the
self-test against temp roots).

## SEO / discoverability

- `docs/index.html` carries OpenGraph + Twitter card meta and a JSON-LD
  `Blog` schema with embedded `BlogPosting` summaries.
- Every public entry also gets a standalone page at
  `/entries/<id>.html` with its own `BlogPosting` JSON-LD, canonical
  URL, and `article:published_time` meta.
- `docs/robots.txt` allows all crawlers and points at the sitemap.
- `docs/sitemap.xml` lists the homepage + every per-entry page,
  regenerated on every render.

To get listed on Google:

1. Open <https://search.google.com/search-console> and add
   `https://pilot-protocol.github.io/pilot-changelog/` as a property
   (URL-prefix, not domain — GitHub Pages doesn't expose DNS).
2. Verify ownership using the **HTML tag** method. Drop the verification
   meta tag inside the `<!-- Add google-site-verification meta here ... -->`
   placeholder in `scripts/render.py::_shared_meta()`. Re-render and push.
3. Submit the sitemap: `https://pilot-protocol.github.io/pilot-changelog/sitemap.xml`.
4. Wait — typical first-crawl is hours to a couple of days.

## License

[AGPL-3.0](./LICENSE) — same as the rest of the Pilot Protocol stack.
