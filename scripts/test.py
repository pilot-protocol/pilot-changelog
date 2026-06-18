#!/usr/bin/env python3
"""Self-test for the pilot-changelog pipeline.

Two tiers:
  - Unit tests for the frontmatter parser, excerpt extractor, and date
    window filter — fast, no I/O.
  - Integration tests that spin up a temp repo root via the
    PILOT_CHANGELOG_ROOT env var, run validate.py / render.py via
    subprocess, and assert on exit codes and JSON output.

Run with: bash scripts/test.sh  (or python3 scripts/test.py)
Exits 0 on all-pass, 1 if anything fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import render  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []
TESTS: list = []


def case(fn):
    """Decorator that registers a test for later execution."""
    TESTS.append(fn)
    return fn


# -------- unit: frontmatter parser --------

@case
def test_parser_basic_scalars():
    fm, body = render.parse_frontmatter(
        "---\ndate: 2026-04-25\nscope: protocol\nflagged: true\n---\nbody line\n"
    )
    assert fm == {"date": "2026-04-25", "scope": "protocol", "flagged": True}, fm
    assert body == "body line\n", body


@case
def test_parser_inline_list():
    fm, _ = render.parse_frontmatter("---\nids: [1, 2, 3]\n---\nbody\n")
    assert fm == {"ids": ["1", "2", "3"]}, fm


@case
def test_parser_inline_list_quoted():
    fm, _ = render.parse_frontmatter('---\nids: ["a", "b"]\n---\nx\n')
    assert fm == {"ids": ["a", "b"]}, fm


@case
def test_parser_block_list():
    fm, _ = render.parse_frontmatter(
        '---\nlinks:\n  - "foo"\n  - https://x\n---\nbody\n'
    )
    assert fm == {"links": ["foo", "https://x"]}, fm


@case
def test_parser_booleans():
    fm, _ = render.parse_frontmatter("---\nflagged: false\nactive: true\n---\nx\n")
    assert fm == {"flagged": False, "active": True}, fm


@case
def test_parser_no_frontmatter():
    fm, body = render.parse_frontmatter("just a body, no frontmatter\n")
    assert fm == {}, fm
    assert body == "just a body, no frontmatter\n", body


@case
def test_parser_quoted_string_strips_quotes():
    fm, _ = render.parse_frontmatter('---\ntitle: "hello: world"\n---\nx\n')
    assert fm == {"title": "hello: world"}, fm


# -------- unit: excerpt --------

@case
def test_excerpt_skips_html_comment():
    body = "<!-- skip me -->\n\nFirst paragraph.\n\nSecond.\n"
    assert render.first_paragraph(body) == "First paragraph."


@case
def test_excerpt_skips_heading():
    body = "## Heading\n\nReal body.\n"
    assert render.first_paragraph(body) == "Real body."


@case
def test_excerpt_collapses_lines_in_paragraph():
    body = "line one\nline two\nline three\n\nnext paragraph\n"
    assert render.first_paragraph(body) == "line one line two line three"


# -------- unit: window filter --------

@case
def test_filter_window_24h():
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    entries = [
        render.Entry(id="a", date="2026-04-27", scope="ops", visibility="public", title="today"),
        render.Entry(id="b", date="2026-04-26", scope="ops", visibility="public", title="yesterday"),
        render.Entry(id="c", date="2026-04-20", scope="ops", visibility="public", title="week ago"),
    ]
    out = render.filter_window(entries, 1, now)
    assert [e.id for e in out] == ["a"], [e.id for e in out]


@case
def test_filter_window_7d():
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    entries = [
        render.Entry(id="a", date="2026-04-27", scope="ops", visibility="public", title="today"),
        render.Entry(id="b", date="2026-04-21", scope="ops", visibility="public", title="6 days ago"),
        render.Entry(id="c", date="2026-04-19", scope="ops", visibility="public", title="8 days ago"),
    ]
    out = render.filter_window(entries, 7, now)
    assert sorted(e.id for e in out) == ["a", "b"], sorted(e.id for e in out)


# -------- integration: validate + render against a temp root --------

VALID_PUBLIC = textwrap.dedent("""\
    ---
    date: 2026-04-25
    scope: networks
    visibility: public
    title: a public entry
    flagged: true
    links:
      - "https://example.com"
    ids: []
    ---

    Body of the public entry.
    """)

VALID_PRIVATE = textwrap.dedent("""\
    ---
    date: 2026-04-24
    scope: ops
    visibility: private
    title: a private entry
    flagged: false
    ---

    Operator-only.
    """)


def make_temp_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="pcl-test-"))
    (root / "entries").mkdir()
    (root / "private").mkdir()
    return root


def run_script(script: str, root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PILOT_CHANGELOG_ROOT": str(root)}
    return subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script)],
        env=env,
        capture_output=True,
        text=True,
    )


@case
def test_integration_valid_repo_passes():
    root = make_temp_root()
    try:
        (root / "entries" / "2026-04-25-a-public-entry.md").write_text(VALID_PUBLIC)
        (root / "private" / "2026-04-24-a-private-entry.md").write_text(VALID_PRIVATE)

        v = run_script("validate.py", root)
        assert v.returncode == 0, f"validate failed: {v.stderr}"

        r = run_script("render.py", root)
        assert r.returncode == 0, f"render failed: {r.stderr}"

        feed = json.loads((root / "feed.json").read_text())
        assert feed["count"] == 1, feed
        assert feed["entries"][0]["title"] == "a public entry"

        priv = json.loads((root / "feed-private.json").read_text())
        assert priv["count"] == 2, priv

        flagged = json.loads((root / "feed-flagged.json").read_text())
        assert flagged["count"] == 1, flagged
    finally:
        shutil.rmtree(root)


@case
def test_integration_filename_date_mismatch_fails():
    root = make_temp_root()
    try:
        (root / "entries" / "2026-04-26-mismatch.md").write_text(VALID_PUBLIC)
        v = run_script("validate.py", root)
        assert v.returncode != 0, "expected validate to fail on date mismatch"
        assert "filename date" in v.stderr, v.stderr
    finally:
        shutil.rmtree(root)


@case
def test_integration_visibility_in_wrong_dir_fails():
    root = make_temp_root()
    try:
        # public entry placed in private/
        (root / "private" / "2026-04-25-a-public-entry.md").write_text(VALID_PUBLIC)
        v = run_script("validate.py", root)
        assert v.returncode != 0, "expected validate to fail on dir mismatch"
        assert "must live under entries/" in v.stderr, v.stderr
    finally:
        shutil.rmtree(root)


@case
def test_integration_invalid_scope_fails():
    root = make_temp_root()
    try:
        bad = VALID_PUBLIC.replace("scope: networks", "scope: bogus")
        (root / "entries" / "2026-04-25-a-public-entry.md").write_text(bad)
        v = run_script("validate.py", root)
        assert v.returncode != 0, "expected validate to fail on bad scope"
        assert "scope" in v.stderr, v.stderr
    finally:
        shutil.rmtree(root)


@case
def test_integration_missing_required_field_fails():
    root = make_temp_root()
    try:
        bad = VALID_PUBLIC.replace("title: a public entry\n", "")
        (root / "entries" / "2026-04-25-a-public-entry.md").write_text(bad)
        v = run_script("validate.py", root)
        assert v.returncode != 0, "expected validate to fail on missing title"
        assert "title" in v.stderr, v.stderr
    finally:
        shutil.rmtree(root)


@case
def test_integration_render_schema_keys_stable():
    """Lock the JSON shape so peer consumers don't break silently."""
    root = make_temp_root()
    try:
        (root / "entries" / "2026-04-25-a-public-entry.md").write_text(VALID_PUBLIC)
        run_script("render.py", root)
        feed = json.loads((root / "feed.json").read_text())
        expected_top = {"schema_version", "latest_entry_date", "window", "include_private", "count", "entries"}
        assert set(feed.keys()) == expected_top, feed.keys()
        assert feed["schema_version"] == 1, feed["schema_version"]
        entry_keys = set(feed["entries"][0].keys())
        expected = {"id", "date", "scope", "visibility", "title", "flagged", "links", "ids", "body", "excerpt"}
        assert entry_keys == expected, entry_keys ^ expected
    finally:
        shutil.rmtree(root)


@case
def test_integration_per_scope_feeds_emitted():
    """Every allowed scope gets a feed file, even if empty (stable URLs)."""
    root = make_temp_root()
    try:
        # VALID_PUBLIC has scope: networks
        (root / "entries" / "2026-04-25-a-public-entry.md").write_text(VALID_PUBLIC)
        run_script("render.py", root)
        scopes = ["protocol", "networks", "skills", "infra", "ops", "docs"]
        for s in scopes:
            f = root / f"feed-{s}.json"
            assert f.exists(), f"missing feed-{s}.json"
            data = json.loads(f.read_text())
            assert data["window"] == f"scope:{s}", data["window"]
        assert json.loads((root / "feed-networks.json").read_text())["count"] == 1
        assert json.loads((root / "feed-protocol.json").read_text())["count"] == 0
    finally:
        shutil.rmtree(root)


MOTD_ENTRY = textwrap.dedent("""\
    ---
    date: 2026-04-25
    scope: motd
    visibility: public
    title: maintenance window 22:00 UTC
    flagged: false
    links: []
    ids: []
    ---

    Banner active today.
    """)


@case
def test_integration_motd_isolated_from_changelog():
    """A motd entry lands in feed-motd.json but NOT in the human changelog
    feeds (feed.json, windowed, flagged, RSS, site)."""
    root = make_temp_root()
    try:
        (root / "entries" / "2026-04-25-a-public-entry.md").write_text(VALID_PUBLIC)
        (root / "entries" / "2026-04-25-motd-maint.md").write_text(MOTD_ENTRY)
        run_script("render.py", root)

        motd = json.loads((root / "feed-motd.json").read_text())
        assert motd["count"] == 1, motd["count"]
        assert motd["entries"][0]["title"] == "maintenance window 22:00 UTC"

        # The changelog "all" feed and flagged feed must exclude motd.
        allf = json.loads((root / "feed.json").read_text())
        assert all(e["scope"] != "motd" for e in allf["entries"]), "motd leaked into feed.json"
        assert allf["count"] == 1, allf["count"]  # only the networks entry
        flagged = json.loads((root / "feed-flagged.json").read_text())
        assert all(e["scope"] != "motd" for e in flagged["entries"]), "motd leaked into feed-flagged.json"
        # RSS must not contain the motd title.
        assert "maintenance window 22:00 UTC" not in (root / "feed.xml").read_text()
    finally:
        shutil.rmtree(root)


@case
def test_integration_index_manifest():
    """index.json lists every public feed URL with stable schema."""
    root = make_temp_root()
    try:
        (root / "entries" / "2026-04-25-a-public-entry.md").write_text(VALID_PUBLIC)
        run_script("render.py", root)
        idx = json.loads((root / "index.json").read_text())
        assert idx["schema_version"] == 1
        assert idx["latest_entry_date"] == "2026-04-25"
        names = {f["name"] for f in idx["feeds"]}
        # The 5 windowed/flagged + 6 changelog per-scope feeds + the special
        # motd feed (consumed by pilot-daemon, isolated from the changelog).
        expected_names = {"all", "1d", "7d", "1m", "flagged"} | {f"scope:{s}" for s in ["protocol", "networks", "skills", "infra", "ops", "docs", "motd"]}
        assert names == expected_names, names ^ expected_names
        # Every feed entry must have name/window/url/description.
        for f in idx["feeds"]:
            assert set(f.keys()) == {"name", "window", "url", "description"}, f.keys()
    finally:
        shutil.rmtree(root)


@case
def test_integration_latest_entry_date_is_deterministic():
    """latest_entry_date must equal the newest entry's date (not wall-clock)."""
    root = make_temp_root()
    try:
        (root / "entries" / "2026-04-25-a-public-entry.md").write_text(VALID_PUBLIC)
        (root / "private" / "2026-04-24-a-private-entry.md").write_text(VALID_PRIVATE)
        run_script("render.py", root)
        feed = json.loads((root / "feed.json").read_text())
        assert feed["latest_entry_date"] == "2026-04-25", feed["latest_entry_date"]
        priv = json.loads((root / "feed-private.json").read_text())
        assert priv["latest_entry_date"] == "2026-04-25", priv["latest_entry_date"]
    finally:
        shutil.rmtree(root)


@case
def test_integration_empty_window_has_null_latest():
    """An empty windowed feed should report latest_entry_date: null, not crash."""
    root = make_temp_root()
    try:
        # No entries at all → all feeds empty
        run_script("render.py", root)
        feed = json.loads((root / "feed.json").read_text())
        assert feed["count"] == 0
        assert feed["latest_entry_date"] is None, feed["latest_entry_date"]
    finally:
        shutil.rmtree(root)


def main() -> int:
    print(f"Running {len(TESTS)} tests...")
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
        except AssertionError as e:
            FAILED.append((name, str(e) or "assertion failed"))
            print(f"FAIL {name}: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            FAILED.append((name, f"{type(e).__name__}: {e}"))
            print(f"ERROR {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            continue
        PASSED.append(name)
        print(f"PASS {name}")
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("\nFailures:")
        for name, msg in FAILED:
            print(f"  - {name}: {msg}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
