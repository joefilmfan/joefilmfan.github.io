#!/usr/bin/env python3
"""Rebuild the josephkahn.com project search index.

Crawls the public category pages and writes projects.json next to this script.
Usage:
    python3 rebuild.py
    python3 rebuild.py --out /path/to/projects.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

BASE = "https://www.josephkahn.com"
UA = "JosephKahnSearchIndexer/1.0 (+https://joefilmfan.github.io/search/)"
TIMEOUT = 30
PAUSE = 0.25

# Work-filter pages linked from the site header. Press/bio/contact are
# checked too, but they are not project grids.
DEFAULT_CATEGORIES = [
    ("featured", "Featured"),
    ("commercials", "Commercials"),
    ("music-videos", "Music Videos"),
    ("films", "Films"),
    ("short-films", "Short Films"),
    ("tv", "TV"),
]
INFO_PAGES = [("press", "Press"), ("bio", "Bio"), ("contact", "Contact")]

CELL_RE = re.compile(
    r'<a\s+href="(/project/(\d+)/([^"]+))"\s+class="cell">(.*?)</a>',
    re.I | re.S,
)
NAV_FILTER_RE = re.compile(
    r'<figure class="filter.*?</figure>',
    re.I | re.S,
)
NAV_LINK_RE = re.compile(
    r'<a\s+href="(/[^"]+)"[^>]*>\s*([^<]+?)\s*</a>',
    re.I,
)
IMG_RE = re.compile(r"<img\b([^>]*)>", re.I | re.S)
ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*"([^"]*)"')
H1_RE = re.compile(r"<h1>(.*?)</h1>", re.I | re.S)
H2_RE = re.compile(r"<h2>(.*?)</h2>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    with urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def fetch_retry(url: str, attempts: int = 3) -> str:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fetch(url)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last}")


def textify(html: str) -> str:
    return unescape(TAG_RE.sub("", html or "")).strip()


FILENAME_PREFIX_RE = re.compile(r"^\d+_[A-Za-z0-9]+_(.+)$")
TRAILING_PNG_RE = re.compile(r"png$", re.I)
TRAILING_DURATION_RE = re.compile(r"[-_ ]?\d{2,3}$")
SCREENSHOT_RE = re.compile(r"^screenshot\b", re.I)


def title_from_filename(filename: str) -> str:
    """Best-effort label for CMS tiles that have a thumbnail but no caption."""
    name = Path((filename or "").split("?")[0]).stem
    name = unescape(name)
    m = FILENAME_PREFIX_RE.match(name)
    if m:
        name = m.group(1)
    name = TRAILING_PNG_RE.sub("", name)
    name = name.replace("_", "-").strip("- ")
    # "blank-30", "lwymmd-15", "out-of-the-woods-30"
    name = TRAILING_DURATION_RE.sub("", name).strip("- ")
    if not name or SCREENSHOT_RE.match(name):
        return ""
    words = [w for w in re.split(r"[-]+", name) if w]
    if not words:
        return ""
    pretty = []
    for w in words:
        letters = "".join(c for c in w if c.isalpha())
        if len(letters) >= 4 and not any(c in "aeiouAEIOU" for c in letters):
            pretty.append(w.upper())
        else:
            pretty.append(w[:1].upper() + w[1:].lower())
    return " ".join(pretty)


def parse_attrs(attr_html: str) -> dict[str, str]:
    return {k.lower(): v for k, v in ATTR_RE.findall(attr_html or "")}


def thumb_url(filename: str, size: str | None = "500") -> str:
    name = (filename or "").strip()
    if not name:
        return ""
    # data-src is a bare filename; src may already be a path.
    if name.startswith("http://") or name.startswith("https://"):
        return name
    if name.startswith("/"):
        # Prefer the color file (data-src) when we get a bare name.
        # If a full path including siteGray is all we have, keep it.
        return urljoin(BASE, name)
    encoded = quote(name, safe="._-")
    if size:
        return f"{BASE}/images/pics/{size}/{encoded}"
    return f"{BASE}/images/pics/{encoded}"


def parse_cells(html: str) -> list[dict]:
    items = []
    for match in CELL_RE.finditer(html):
        path, pid, slug, body = match.groups()
        img_m = IMG_RE.search(body)
        attrs = parse_attrs(img_m.group(1) if img_m else "")
        data_src = attrs.get("data-src") or ""
        src = attrs.get("src") or ""
        filename = data_src or Path(urlparse(src).path).name
        # If we only have the gray placeholder path, still record it.
        if data_src:
            thumbnail = thumb_url(data_src, "500")
            thumbnail_full = thumb_url(data_src, None)
        elif src:
            thumbnail = urljoin(BASE, src)
            thumbnail_full = thumbnail
        else:
            thumbnail = thumbnail_full = ""
        h1 = textify(H1_RE.search(body).group(1) if H1_RE.search(body) else "")
        h2 = textify(H2_RE.search(body).group(1) if H2_RE.search(body) else "")
        if h1 and h2:
            artist, title = h1, h2
        else:
            artist, title = "", h1 or h2
        inferred = False
        if not title:
            fallback = title_from_filename(data_src or filename)
            if fallback:
                title = fallback
                inferred = True
        try:
            width = int(attrs.get("data-width") or 0) or None
        except ValueError:
            width = None
        try:
            height = int(attrs.get("data-height") or 0) or None
        except ValueError:
            height = None
        items.append(
            {
                "id": pid,
                "slug": slug,
                "url": urljoin(BASE, path),
                "title": title,
                "artist": artist,
                "thumbnail": thumbnail,
                "thumbnail_full": thumbnail_full,
                "width": width,
                "height": height,
                "title_inferred": inferred,
            }
        )
    return items


def discover_categories(home_html: str) -> list[tuple[str, str]]:
    """Read FILTER links from the homepage header; fall back to known slugs."""
    block = NAV_FILTER_RE.search(home_html)
    found: list[tuple[str, str]] = []
    if block:
        for href, label in NAV_LINK_RE.findall(block.group(0)):
            path = href.strip().strip("/")
            if not path or path.startswith("http") or path.startswith("project/"):
                continue
            # Skip overlay-only pages if they ever appear here
            if path in {"press", "bio", "contact", "shop"}:
                continue
            found.append((path, unescape(label).strip().title() if label.isupper() else unescape(label).strip()))
    # Keep canonical labels when we know them
    label_map = dict(DEFAULT_CATEGORIES)
    cleaned = []
    seen = set()
    for slug, label in found or DEFAULT_CATEGORIES:
        if slug in seen:
            continue
        seen.add(slug)
        pretty = label_map.get(slug, label)
        if slug == "tv":
            pretty = "TV"
        cleaned.append((slug, pretty))
    # Ensure defaults still get crawled even if nav markup changes
    for slug, label in DEFAULT_CATEGORIES:
        if slug not in seen:
            cleaned.append((slug, label))
    return cleaned


def merge_project(existing: dict, incoming: dict, category_slug: str, category_label: str) -> None:
    if category_slug not in existing["category_slugs"]:
        existing["category_slugs"].append(category_slug)
        existing["categories"].append(category_label)
    # Prefer a color thumbnail if we somehow got a gray-only first
    if "siteGray" in (existing.get("thumbnail") or "") and "siteGray" not in (incoming.get("thumbnail") or ""):
        existing["thumbnail"] = incoming["thumbnail"]
        existing["thumbnail_full"] = incoming["thumbnail_full"]
    if not existing.get("artist") and incoming.get("artist"):
        existing["artist"] = incoming["artist"]
    if not existing.get("title") and incoming.get("title"):
        existing["title"] = incoming["title"]
    if not existing.get("width") and incoming.get("width"):
        existing["width"] = incoming["width"]
        existing["height"] = incoming["height"]


def crawl(verbose: bool = True) -> dict:
    log = (lambda *a: print(*a, file=sys.stderr)) if verbose else (lambda *a: None)
    log(f"Fetching {BASE}/")
    home = fetch_retry(f"{BASE}/")
    categories = discover_categories(home)
    log("Categories:", ", ".join(f"{label} (/{slug})" for slug, label in categories))

    by_url: dict[str, dict] = {}
    order: list[str] = []
    per_category: dict[str, int] = {}
    skipped: dict[str, str] = {}

    def ingest(slug: str, label: str, html: str, is_info: bool = False) -> int:
        items = parse_cells(html)
        # Also count bare /project/ links in case markup changes
        bare = re.findall(r'href="(/project/\d+/[^"]+)"', html)
        per_category[slug] = len(items)
        if is_info and not items:
            if bare:
                skipped[slug] = f"{len(set(bare))} project link(s) but no thumbnail cells"
            else:
                skipped[slug] = "no project cells"
            return 0
        for item in items:
            item["category_slugs"] = [slug]
            item["categories"] = [label]
            url = item["url"]
            if url in by_url:
                merge_project(by_url[url], item, slug, label)
            else:
                by_url[url] = item
                order.append(url)
        return len(items)

    for slug, label in categories:
        url = f"{BASE}/{slug}"
        log(f"Crawling {url}")
        try:
            html = fetch_retry(url)
        except Exception as exc:
            skipped[slug] = f"fetch failed: {exc}"
            log(f"  ERROR {exc}")
            continue
        n = ingest(slug, label, html)
        log(f"  {n} projects")
        time.sleep(PAUSE)

    for slug, label in INFO_PAGES:
        url = f"{BASE}/{slug}"
        log(f"Checking {url}")
        try:
            html = fetch_retry(url)
        except Exception as exc:
            skipped[slug] = f"fetch failed: {exc}"
            log(f"  ERROR {exc}")
            continue
        n = ingest(slug, label, html, is_info=True)
        log(f"  {n} projects" + (f" ({skipped[slug]})" if slug in skipped else ""))
        time.sleep(PAUSE)

    projects = [by_url[u] for u in order]
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    counts = {}
    for slug, label in categories:
        counts[label] = sum(1 for p in projects if slug in p["category_slugs"])
    inferred = [p for p in projects if p.get("title_inferred")]
    payload = {
        "meta": {
            "site": BASE,
            "generated_at": now,
            "project_count": len(projects),
            "per_category": counts,
            "title_inferred_count": len(inferred),
            "category_pages": [f"{BASE}/{slug}" for slug, _ in categories],
            "pages_without_projects": skipped,
        },
        "projects": projects,
    }
    return payload


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild josephkahn.com search index")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "projects.json",
        help="Output JSON path (default: ./projects.json)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = crawl(verbose=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    meta = payload["meta"]
    print(f"Wrote {meta['project_count']} projects to {args.out}", file=sys.stderr)
    for label, n in meta["per_category"].items():
        print(f"  {label}: {n}", file=sys.stderr)
    if meta["pages_without_projects"]:
        print("Pages without project grids:", file=sys.stderr)
        for slug, reason in meta["pages_without_projects"].items():
            print(f"  /{slug}: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
