#!/usr/bin/env python3
"""Render changelog entries to feed.json (+ windowed variants) and feed.md.

Zero deps — uses a minimal frontmatter parser that handles the bounded
schema we actually use (scalars, booleans, inline lists, block lists).

Outputs (relative to repo root):
  feed.json            all-time, public
  feed-1d.json         last 24h, public
  feed-7d.json         last 7 days, public
  feed-1m.json         last 30 days, public
  feed-flagged.json    flagged: true, public, all-time
  feed.md              human-readable timeline, public
  feed-private.json    all-time, all visibilities (gitignored)
  feed-private.md      same, markdown (gitignored)
"""

from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

REPO_ROOT = Path(os.environ.get("PILOT_CHANGELOG_ROOT") or Path(__file__).resolve().parent.parent)
ENTRIES_DIRS = [REPO_ROOT / "entries", REPO_ROOT / "private"]
# Scopes that make up the human-facing changelog (feed.json, RSS, the site).
CHANGELOG_SCOPES = {"protocol", "networks", "skills", "infra", "ops", "docs"}
# "motd" is a special scope: a message-of-the-day banner consumed only by the
# pilot-daemon via feed-motd.json. For a motd entry the `date` is the UTC day
# the banner is active (not a publish date), and the `title` is the banner
# text. motd entries are deliberately kept OUT of the general changelog feeds
# (feed.json, windowed, flagged, RSS, site) — they ride the same pipeline but
# are not changelog news. ALLOWED_SCOPES is the frontmatter-validation set.
MOTD_SCOPE = "motd"
ALLOWED_SCOPES = CHANGELOG_SCOPES | {MOTD_SCOPE}
ALLOWED_VISIBILITY = {"public", "private"}
SCHEMA_VERSION = 1

PAGES_BASE_URL = "https://teoslayer.github.io/pilot-changelog"
PAGES_PATH = "/pilot-changelog"  # absolute path prefix for in-site links
MAIN_SITE_URL = "https://pilotprotocol.network"
REPO_URL = "https://github.com/TeoSlayer/pilot-changelog"

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Entry:
    id: str
    date: str
    scope: str
    visibility: str
    title: str
    flagged: bool = False
    links: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    body: str = ""
    excerpt: str = ""
    source_path: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("source_path", None)
        return d


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a leading `---\\n…\\n---\\n` YAML-ish block.

    Returns ({}, text) when no frontmatter is present.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        end = text.find("\n---", 4)
        if end == -1:
            return {}, text
        body = text[end + 4:]
    else:
        body = text[end + 5:]
    fm_text = text[4:end]

    fm: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw in fm_text.split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("  - ") or raw.startswith("- "):
            if current_list_key is None:
                continue
            val = raw.split("-", 1)[1].strip()
            val = _unquote(val)
            fm[current_list_key].append(val)
            continue
        if ":" not in raw:
            continue
        key, _, val = raw.partition(":")
        key = key.strip()
        val = val.strip()
        if not val:
            fm[key] = []
            current_list_key = key
            continue
        current_list_key = None
        fm[key] = _coerce_scalar(val)
    return fm, body


def _unquote(val: str) -> str:
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    return val


def _coerce_scalar(val: str) -> Any:
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_unquote(x.strip()) for x in inner.split(",") if x.strip()]
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    return _unquote(val)


def first_paragraph(body: str) -> str:
    body = body.lstrip()
    # Skip HTML comments at the top of the body.
    while body.startswith("<!--"):
        end = body.find("-->")
        if end == -1:
            break
        body = body[end + 3:].lstrip()
    para: list[str] = []
    for line in body.split("\n"):
        if not line.strip():
            if para:
                break
            continue
        if line.startswith("#"):
            continue
        para.append(line.strip())
    return " ".join(para)


def load_entries() -> list[Entry]:
    entries: list[Entry] = []
    for d in ENTRIES_DIRS:
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(text)
            if not fm:
                print(f"skip (no frontmatter): {path}", file=sys.stderr)
                continue
            entries.append(
                Entry(
                    id=path.stem,
                    date=str(fm.get("date", "")),
                    scope=str(fm.get("scope", "")),
                    visibility=str(fm.get("visibility", "")),
                    title=str(fm.get("title", "")),
                    flagged=bool(fm.get("flagged", False)),
                    links=[str(x) for x in fm.get("links", []) if x],
                    ids=[str(x) for x in fm.get("ids", [])],
                    body=body.strip(),
                    excerpt=first_paragraph(body),
                    source_path=str(path.relative_to(REPO_ROOT)),
                )
            )
    # Sort newest first by (date, id).
    entries.sort(key=lambda e: (e.date, e.id), reverse=True)
    return entries


def parse_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def filter_window(entries: list[Entry], days: int, now: datetime) -> list[Entry]:
    cutoff = now - timedelta(days=days)
    out = []
    for e in entries:
        d = parse_date(e.date)
        if d is None:
            continue
        if d >= cutoff:
            out.append(e)
    return out


def write_json_feed(
    path: Path,
    *,
    entries: list[Entry],
    window: str,
    include_private: bool,
) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "latest_entry_date": entries[0].date if entries else None,
        "window": window,
        "include_private": include_private,
        "count": len(entries),
        "entries": [e.to_public_dict() for e in entries],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(entries)} entries)")


def to_rfc822(date_str: str) -> str:
    """Convert YYYY-MM-DD to RFC 822 (RSS pubDate). Locale-independent."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{_DAY_NAMES[dt.weekday()]}, {dt.day:02d} {_MONTH_NAMES[dt.month-1]} {dt.year} 00:00:00 +0000"


def write_rss_feed(path: Path, entries: list[Entry], *, channel_link: str) -> None:
    """Write an RSS 2.0 feed of public entries. Deterministic given entries."""
    items = []
    for e in entries:
        guid = f"{REPO_URL}/blob/main/entries/{e.id}.md"
        # Description: excerpt is plain text; wrap categories from links/scope.
        desc = xml_escape(e.excerpt or e.title)
        items.append(
            "    <item>\n"
            f"      <title>{xml_escape(e.title)}</title>\n"
            f"      <link>{xml_escape(channel_link)}#{xml_escape(e.id)}</link>\n"
            f"      <description>{desc}</description>\n"
            f"      <category>{xml_escape(e.scope)}</category>\n"
            f"      <pubDate>{to_rfc822(e.date)}</pubDate>\n"
            f'      <guid isPermaLink="false">{xml_escape(guid)}</guid>\n'
            "    </item>"
        )
    last_build = to_rfc822(entries[0].date) if entries else to_rfc822("1970-01-01")
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>Pilot Protocol Changelog</title>\n"
        f"    <link>{xml_escape(channel_link)}</link>\n"
        f'    <atom:link href="{xml_escape(channel_link)}/feed.xml" rel="self" type="application/rss+xml" />\n'
        "    <description>Operational news for autonomous agents on the Pilot Protocol overlay — new networks, new skills, protocol behavior changes.</description>\n"
        "    <language>en-us</language>\n"
        f"    <lastBuildDate>{last_build}</lastBuildDate>\n"
        "    <generator>pilot-changelog/render.py</generator>\n"
        + ("\n".join(items) + "\n" if items else "")
        + "  </channel>\n"
        "</rss>\n"
    )
    path.write_text(rss, encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(entries)} items)")


def _scope_color_class(scope: str) -> str:
    """Stable scope → CSS class for tag styling."""
    return f"tag-{scope}"


def _shared_meta(*, title: str, description: str, canonical_url: str, og_type: str = "website", entry: Entry | None = None) -> str:
    """Open Graph + Twitter card + JSON-LD common to index and per-entry pages."""
    desc_safe = html.escape(description)
    title_safe = html.escape(title)
    article_meta = ""
    json_ld = ""
    if entry is not None:
        article_meta = (
            f'  <meta property="article:published_time" content="{html.escape(entry.date)}T00:00:00Z" />\n'
            f'  <meta property="article:section" content="{html.escape(entry.scope)}" />\n'
        )
        body_plain = (entry.body or entry.excerpt).replace("\n", " ").replace('"', '\\"')
        json_ld_data = {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": entry.title,
            "datePublished": f"{entry.date}T00:00:00Z",
            "dateModified": f"{entry.date}T00:00:00Z",
            "description": entry.excerpt or entry.title,
            "articleBody": entry.body or entry.excerpt,
            "url": canonical_url,
            "mainEntityOfPage": {"@type": "WebPage", "@id": canonical_url},
            "author": {"@type": "Organization", "name": "Pilot Protocol", "url": MAIN_SITE_URL},
            "publisher": {"@type": "Organization", "name": "Pilot Protocol", "url": MAIN_SITE_URL},
            "articleSection": entry.scope,
            "keywords": [entry.scope, "pilot-protocol", "agent-network"],
        }
        json_ld = f'  <script type="application/ld+json">{json.dumps(json_ld_data, ensure_ascii=False)}</script>\n'
    return (
        f'  <meta name="description" content="{desc_safe}" />\n'
        f'  <meta property="og:type" content="{og_type}" />\n'
        f'  <meta property="og:title" content="{title_safe}" />\n'
        f'  <meta property="og:description" content="{desc_safe}" />\n'
        f'  <meta property="og:url" content="{html.escape(canonical_url)}" />\n'
        f'  <meta property="og:site_name" content="Pilot Protocol Changelog" />\n'
        f'  <meta name="twitter:card" content="summary" />\n'
        f'  <meta name="twitter:title" content="{title_safe}" />\n'
        f'  <meta name="twitter:description" content="{desc_safe}" />\n'
        f'  <meta name="google" content="notranslate" />\n'
        '  <!-- Add google-site-verification meta here once Search Console is set up. -->\n'
        f'{article_meta}'
        f'{json_ld}'
    )


def _shared_head_links() -> str:
    return (
        f'  <link rel="alternate" type="application/rss+xml" title="Pilot Protocol Changelog (RSS)" href="{PAGES_PATH}/feed.xml" />\n'
        '  <link rel="preconnect" href="https://fonts.googleapis.com" />\n'
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n'
        '  <link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@300;400;500;600;700&amp;family=JetBrains+Mono:wght@400;500;600&amp;family=Instrument+Serif:ital@0;1&amp;display=swap" rel="stylesheet" />\n'
        f'  <link rel="stylesheet" href="{PAGES_PATH}/style.css" />\n'
    )


def _body_to_html(body: str, fallback: str) -> str:
    txt = html.escape(body or fallback)
    txt = txt.replace("\n\n", "</p><p>").replace("\n", " ")
    return f"<p>{txt}</p>" if txt else ""


def _links_html(links: list[str]) -> str:
    if not links:
        return ""
    items = " · ".join(
        f'<a href="{html.escape(u)}" target="_blank" rel="noopener">{html.escape(u)}</a>'
        for u in links
    )
    return f'<div class="card-links">{items}</div>'


def write_docs_html(path: Path, entries: list[Entry]) -> None:
    """Write the GitHub Pages landing page. Style lifted from web4. Deterministic."""
    cards = []
    for e in entries:
        body_html = _body_to_html(e.body, e.excerpt)
        flag = '<span class="badge-flag" title="Always-surface entry">⚑ flagged</span>' if e.flagged else ""
        entry_url = f"{PAGES_PATH}/entries/{html.escape(e.id)}.html"
        cards.append(
            f'    <article class="entry-card" id="{html.escape(e.id)}" data-scope="{html.escape(e.scope)}" data-flagged="{str(e.flagged).lower()}">\n'
            "      <div class=\"meta\">\n"
            f'        <span class="date">{html.escape(e.date)}</span>\n'
            f'        <span class="tag {_scope_color_class(e.scope)}">{html.escape(e.scope)}</span>\n'
            f"        {flag}\n"
            "      </div>\n"
            f'      <h3><a href="{entry_url}">{html.escape(e.title)}</a></h3>\n'
            f'      <div class="card-body">{body_html}</div>\n'
            f"      {_links_html(e.links)}\n"
            "    </article>"
        )
    cards_html = "\n".join(cards) if cards else '    <p class="empty">No public entries yet.</p>'

    # JSON-LD: Blog with embedded BlogPosting summaries (Google can crawl
    # both the embedded data and follow links to per-entry pages).
    blog_ld = {
        "@context": "https://schema.org",
        "@type": "Blog",
        "name": "Pilot Protocol Changelog",
        "url": f"{PAGES_BASE_URL}/",
        "description": "Operational news for autonomous agents on the Pilot Protocol overlay.",
        "publisher": {"@type": "Organization", "name": "Pilot Protocol", "url": MAIN_SITE_URL},
        "blogPost": [
            {
                "@type": "BlogPosting",
                "headline": e.title,
                "datePublished": f"{e.date}T00:00:00Z",
                "url": f"{PAGES_BASE_URL}/entries/{e.id}.html",
                "description": e.excerpt or e.title,
                "articleSection": e.scope,
            }
            for e in entries
        ],
    }
    blog_ld_script = f'  <script type="application/ld+json">{json.dumps(blog_ld, ensure_ascii=False)}</script>\n'

    scopes_sorted = sorted(CHANGELOG_SCOPES)
    filter_buttons = '\n'.join(
        f'      <button class="filter-tab" data-filter="{s}">{s}</button>'
        for s in scopes_sorted
    )
    latest = entries[0].date if entries else "—"

    index_meta = _shared_meta(
        title="Pilot Protocol Changelog",
        description="Operational news for autonomous agents on the Pilot Protocol overlay — new networks, new skills, protocol behavior changes.",
        canonical_url=f"{PAGES_BASE_URL}/",
        og_type="website",
    )
    html_doc = f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Pilot Protocol Changelog</title>
  <link rel="canonical" href="{PAGES_BASE_URL}/" />
{index_meta}{_shared_head_links()}{blog_ld_script}</head>
<body>
  <nav class="nav-top">
    <div class="wrap">
      <div class="nav-row">
        <a href="{MAIN_SITE_URL}" class="brand" aria-label="Pilot Protocol — main site">
          <span class="brand-text">Pilot / Protocol<small class="brand-tag">Changelog</small></span>
        </a>
        <div class="nav-links">
          <a class="nav-link" href="{MAIN_SITE_URL}">Main site</a>
          <a class="nav-link" href="{MAIN_SITE_URL}/docs/">Docs</a>
          <a class="nav-link" href="{REPO_URL}">GitHub</a>
        </div>
        <div class="nav-right">
          <a class="bots-link" href="{PAGES_PATH}/feed.json" aria-label="Machine-readable feed for agents">
            <span class="bots-label">feed.json</span>
          </a>
        </div>
      </div>
    </div>
  </nav>

  <main class="blog-list">
    <div class="eyebrow">Pilot · Changelog</div>
    <h1>News from the <em>overlay</em>.</h1>
    <p class="subtitle">Operational news for autonomous agents on the Pilot Protocol network. New networks become joinable, new skills land on ClawHub, and protocol behavior changes — they show up here first.</p>

    <div class="rss-group">
      <a class="rss-btn" href="{PAGES_PATH}/feed.xml" target="_blank" rel="noopener" title="Open RSS Feed">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><circle cx="6.18" cy="17.82" r="2.18"/><path d="M4 4.44v2.83c7.03 0 12.73 5.7 12.73 12.73h2.83c0-8.59-6.97-15.56-15.56-15.56z"/><path d="M4 10.1v2.83c3.9 0 7.07 3.17 7.07 7.07h2.83c0-5.47-4.43-9.9-9.9-9.9z"/></svg>
        RSS
      </a>
      <span class="rss-divider"></span>
      <a class="rss-btn" href="{PAGES_PATH}/feed.json" target="_blank" rel="noopener" title="JSON feed (all-time)">JSON</a>
      <span class="rss-divider"></span>
      <a class="rss-btn" href="{PAGES_PATH}/index.json" target="_blank" rel="noopener" title="Manifest of all feeds">Manifest</a>
    </div>

    <div class="status-row">
      <span class="status-pill">Latest entry · <strong>{latest}</strong></span>
      <span class="status-pill">{len(entries)} public entries</span>
    </div>

    <div class="blog-filters">
      <button class="filter-tab active" data-filter="all">all</button>
      <button class="filter-tab" data-filter="flagged">flagged</button>
{filter_buttons}
    </div>

    <div id="entry-cards">
{cards_html}
    </div>
  </main>

  <footer class="site-footer">
    <div class="wrap">
      <div class="foot-grid">
        <div class="foot-about">
          <h4>Pilot / Protocol — Changelog</h4>
          <p>Built for agents, by humans. <a href="{MAIN_SITE_URL}">{MAIN_SITE_URL.replace('https://', '')}</a></p>
        </div>
        <div>
          <h4>Feeds</h4>
          <a href="{PAGES_PATH}/feed.json">feed.json</a>
          <a href="{PAGES_PATH}/feed.xml">feed.xml (RSS)</a>
          <a href="{PAGES_PATH}/feed-flagged.json">feed-flagged.json</a>
          <a href="{PAGES_PATH}/index.json">index.json</a>
        </div>
        <div>
          <h4>Source</h4>
          <a href="{REPO_URL}">GitHub repo</a>
          <a href="{REPO_URL}/blob/main/SCHEMA.md">Schema</a>
          <a href="{REPO_URL}/blob/main/README.md">Readme</a>
        </div>
        <div>
          <h4>Network</h4>
          <a href="{MAIN_SITE_URL}">{MAIN_SITE_URL.replace('https://', '')}</a>
          <a href="{MAIN_SITE_URL}/docs/">Docs</a>
          <a href="https://polo.pilotprotocol.network">Polo (live)</a>
        </div>
      </div>
      <div class="foot-bottom">
        <div>© Pilot Protocol · Built for agents</div>
        <div><a class="foot-status" href="https://polo.pilotprotocol.network">pilot://0x00000000 · backbone · up</a></div>
      </div>
    </div>
  </footer>

  <script>
    // Filter cards by scope or flagged.
    document.querySelectorAll('.filter-tab').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const f = btn.dataset.filter;
        document.querySelectorAll('.entry-card').forEach(card => {{
          let show;
          if (f === 'all') show = true;
          else if (f === 'flagged') show = card.dataset.flagged === 'true';
          else show = card.dataset.scope === f;
          card.style.display = show ? '' : 'none';
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(entries)} cards)")


def write_entry_html(path: Path, entry: Entry, *, all_entries: list[Entry]) -> None:
    """One HTML page per public entry — separately indexable URL with focused content."""
    entry_url = f"{PAGES_BASE_URL}/entries/{entry.id}.html"
    title = f"{entry.title} — Pilot Protocol Changelog"
    description = entry.excerpt or entry.title
    body_html = _body_to_html(entry.body, entry.excerpt)
    flag = '<span class="badge-flag" title="Always-surface entry">⚑ flagged</span>' if entry.flagged else ""

    # Sibling entries: prev/next by date, for in-page navigation.
    idx = next((i for i, x in enumerate(all_entries) if x.id == entry.id), -1)
    newer = all_entries[idx - 1] if idx > 0 else None
    older = all_entries[idx + 1] if 0 <= idx < len(all_entries) - 1 else None
    nav_links = []
    if newer:
        nav_links.append(f'<a class="entry-nav-link" href="{PAGES_PATH}/entries/{newer.id}.html" rel="prev">← {html.escape(newer.title)}</a>')
    nav_links.append(f'<a class="entry-nav-link" href="{PAGES_PATH}/">All entries</a>')
    if older:
        nav_links.append(f'<a class="entry-nav-link" href="{PAGES_PATH}/entries/{older.id}.html" rel="next">{html.escape(older.title)} →</a>')
    nav_html = '<nav class="entry-nav">' + " · ".join(nav_links) + '</nav>'

    meta = _shared_meta(
        title=title,
        description=description,
        canonical_url=entry_url,
        og_type="article",
        entry=entry,
    )
    doc = f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <link rel="canonical" href="{entry_url}" />
{meta}{_shared_head_links()}</head>
<body>
  <nav class="nav-top">
    <div class="wrap">
      <div class="nav-row">
        <a href="{MAIN_SITE_URL}" class="brand" aria-label="Pilot Protocol — main site">
          <span class="brand-text">Pilot / Protocol<small class="brand-tag">Changelog</small></span>
        </a>
        <div class="nav-links">
          <a class="nav-link" href="{PAGES_PATH}/">All entries</a>
          <a class="nav-link" href="{MAIN_SITE_URL}">Main site</a>
          <a class="nav-link" href="{REPO_URL}">GitHub</a>
        </div>
        <div class="nav-right">
          <a class="bots-link" href="{PAGES_PATH}/feed.json" aria-label="Machine-readable feed for agents">
            <span class="bots-label">feed.json</span>
          </a>
        </div>
      </div>
    </div>
  </nav>

  <main class="blog-list entry-page">
    <div class="eyebrow">Pilot · Changelog · {html.escape(entry.scope)}</div>
    <article class="entry-card single" id="{html.escape(entry.id)}" data-scope="{html.escape(entry.scope)}" data-flagged="{str(entry.flagged).lower()}">
      <div class="meta">
        <span class="date">{html.escape(entry.date)}</span>
        <span class="tag {_scope_color_class(entry.scope)}">{html.escape(entry.scope)}</span>
        {flag}
      </div>
      <h1>{html.escape(entry.title)}</h1>
      <div class="card-body">{body_html}</div>
      {_links_html(entry.links)}
    </article>

    {nav_html}
  </main>

  <footer class="site-footer">
    <div class="wrap">
      <div class="foot-grid">
        <div class="foot-about">
          <h4>Pilot / Protocol — Changelog</h4>
          <p>Built for agents, by humans. <a href="{MAIN_SITE_URL}">{MAIN_SITE_URL.replace('https://', '')}</a></p>
        </div>
        <div>
          <h4>Feeds</h4>
          <a href="{PAGES_PATH}/feed.json">feed.json</a>
          <a href="{PAGES_PATH}/feed.xml">feed.xml (RSS)</a>
          <a href="{PAGES_PATH}/index.json">index.json</a>
        </div>
        <div>
          <h4>Source</h4>
          <a href="{REPO_URL}">GitHub repo</a>
          <a href="{REPO_URL}/blob/main/SCHEMA.md">Schema</a>
        </div>
        <div>
          <h4>Network</h4>
          <a href="{MAIN_SITE_URL}">{MAIN_SITE_URL.replace('https://', '')}</a>
          <a href="{MAIN_SITE_URL}/docs/">Docs</a>
        </div>
      </div>
      <div class="foot-bottom">
        <div>© Pilot Protocol · Built for agents</div>
        <div><a class="foot-status" href="https://polo.pilotprotocol.network">pilot://0x00000000 · backbone · up</a></div>
      </div>
    </div>
  </footer>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")


def write_robots_txt(path: Path) -> None:
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {PAGES_BASE_URL}/sitemap.xml\n"
    )
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def write_sitemap_xml(path: Path, entries: list[Entry]) -> None:
    """Sitemap with homepage + per-entry pages. Deterministic from entries."""
    urls = []
    latest = entries[0].date if entries else None
    if latest:
        urls.append(
            "  <url>\n"
            f"    <loc>{PAGES_BASE_URL}/</loc>\n"
            f"    <lastmod>{latest}</lastmod>\n"
            "    <changefreq>daily</changefreq>\n"
            "    <priority>1.0</priority>\n"
            "  </url>"
        )
    else:
        urls.append(
            "  <url>\n"
            f"    <loc>{PAGES_BASE_URL}/</loc>\n"
            "    <changefreq>daily</changefreq>\n"
            "    <priority>1.0</priority>\n"
            "  </url>"
        )
    for e in entries:
        urls.append(
            "  <url>\n"
            f"    <loc>{PAGES_BASE_URL}/entries/{xml_escape(e.id)}.html</loc>\n"
            f"    <lastmod>{e.date}</lastmod>\n"
            "    <changefreq>monthly</changefreq>\n"
            "    <priority>0.8</priority>\n"
            "  </url>"
        )
    body = "\n".join(urls)
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )
    path.write_text(sitemap, encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(entries) + 1} URLs)")


def write_index(path: Path, *, public_entries: list[Entry]) -> None:
    """Manifest of every public feed URL — peers fetch this first to discover."""
    feeds = [
        {"name": "all", "window": "all", "url": "feed.json",
         "description": "Every public entry, all-time."},
        {"name": "1d", "window": "1d", "url": "feed-1d.json",
         "description": "Public entries from the last 24 hours (wall-clock cutoff)."},
        {"name": "7d", "window": "7d", "url": "feed-7d.json",
         "description": "Public entries from the last 7 days (wall-clock cutoff)."},
        {"name": "1m", "window": "1m", "url": "feed-1m.json",
         "description": "Public entries from the last 30 days (wall-clock cutoff)."},
        {"name": "flagged", "window": "flagged", "url": "feed-flagged.json",
         "description": "Public entries marked flagged (always-surface, regardless of date)."},
    ]
    for scope in sorted(ALLOWED_SCOPES):
        if scope == MOTD_SCOPE:
            description = ("Message-of-the-day banners. Each entry's `date` is the "
                          "UTC day it is active and `title` is the banner text; "
                          "consumed by pilot-daemon, not part of the changelog.")
        else:
            description = f"All public entries scoped to {scope!r}, all-time."
        feeds.append({
            "name": f"scope:{scope}",
            "window": "all",
            "url": f"feed-{scope}.json",
            "description": description,
        })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "repo": "https://github.com/TeoSlayer/pilot-changelog",
        "latest_entry_date": public_entries[0].date if public_entries else None,
        "feeds": feeds,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(feeds)} feeds listed)")


def write_markdown_feed(path: Path, entries: list[Entry], *, title: str) -> None:
    lines = [f"# {title}", ""]
    last_month = ""
    for e in entries:
        month = e.date[:7] if len(e.date) >= 7 else "unknown"
        if month != last_month:
            lines.append(f"## {month}")
            lines.append("")
            last_month = month
        flag = " ⚑" if e.flagged else ""
        vis = "" if e.visibility == "public" else f" *(private)*"
        lines.append(f"### {e.date} — {e.title}{flag}{vis}")
        lines.append(f"_scope: `{e.scope}`_")
        lines.append("")
        if e.body:
            lines.append(e.body)
            lines.append("")
        if e.links:
            lines.append("**Links:** " + " · ".join(e.links))
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(entries)} entries)")


def main() -> int:
    now = datetime.now(timezone.utc)
    all_entries = load_entries()
    public = [e for e in all_entries if e.visibility == "public"]
    # The human changelog excludes motd banners — those ride the same pipeline
    # but are served only via feed-motd.json (see the per-scope loop below).
    changelog = [e for e in public if e.scope != MOTD_SCOPE]

    write_json_feed(REPO_ROOT / "feed.json", entries=changelog, window="all", include_private=False)
    write_json_feed(REPO_ROOT / "feed-1d.json", entries=filter_window(changelog, 1, now), window="1d", include_private=False)
    write_json_feed(REPO_ROOT / "feed-7d.json", entries=filter_window(changelog, 7, now), window="7d", include_private=False)
    write_json_feed(REPO_ROOT / "feed-1m.json", entries=filter_window(changelog, 30, now), window="1m", include_private=False)
    write_json_feed(REPO_ROOT / "feed-flagged.json", entries=[e for e in changelog if e.flagged], window="flagged", include_private=False)

    # Per-scope feeds — peers can subscribe to just protocol/networks/etc.
    # Always emit a file per allowed scope (incl. motd), even if empty, so URLs
    # are stable. The per-scope filter naturally isolates motd into
    # feed-motd.json — the daemon's message-of-the-day source.
    for scope in sorted(ALLOWED_SCOPES):
        scope_entries = [e for e in public if e.scope == scope]
        write_json_feed(REPO_ROOT / f"feed-{scope}.json", entries=scope_entries, window=f"scope:{scope}", include_private=False)

    write_markdown_feed(REPO_ROOT / "feed.md", changelog, title="Pilot Protocol Changelog")

    # RSS 2.0 for human / RSS-reader subscription.
    write_rss_feed(REPO_ROOT / "feed.xml", changelog, channel_link=PAGES_BASE_URL)

    # Manifest — single discovery URL listing every public feed.
    write_index(REPO_ROOT / "index.json", public_entries=changelog)

    # GitHub Pages landing page (dark theme, web4-styled).
    write_docs_html(REPO_ROOT / "docs" / "index.html", changelog)

    # Per-entry pages — each changelog entry gets a separately indexable URL.
    # motd banners are intentionally not given public pages.
    entries_dir = REPO_ROOT / "docs" / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    # Wipe stale entry HTML so renamed/removed entries don't linger on Pages.
    for stale in entries_dir.glob("*.html"):
        stale.unlink()
    for e in changelog:
        write_entry_html(entries_dir / f"{e.id}.html", e, all_entries=changelog)
    print(f"wrote {len(changelog)} per-entry HTML pages under docs/entries/")

    # SEO surface — robots.txt + sitemap.xml live in docs/ so they're served
    # from the Pages origin at /pilot-changelog/robots.txt and /sitemap.xml.
    write_robots_txt(REPO_ROOT / "docs" / "robots.txt")
    write_sitemap_xml(REPO_ROOT / "docs" / "sitemap.xml", changelog)

    # Private mirror outputs — gitignored, operator console only.
    write_json_feed(REPO_ROOT / "feed-private.json", entries=all_entries, window="all", include_private=True)
    write_markdown_feed(REPO_ROOT / "feed-private.md", all_entries, title="Pilot Protocol Changelog (operator)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
