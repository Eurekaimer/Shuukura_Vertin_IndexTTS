"""Fetch TOC interludes and side stories as a separate resumable book."""

import argparse
import datetime
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

from scrape_parts import HEAD_RE, TOC, chapter_no, fetch, parse_part, session, sha256_file, write_atomic

BONUS_HEADING = re.compile(r"^(?:Volume\s+\w+\s+(?:Interlude|Extra|Side Story)|Maika\s+Side\s+Story)\b", re.I)
BONUS_LINK = re.compile(r"\b(?:Interlude|Extra|Side Story)\b", re.I)
LINK = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
TAG = re.compile(r"<[^>]+>")


def parse_extra_toc(page):
    body = page[page.index('class="entry-content'):]
    extras, seen = [], set()
    after_chapter = 0
    for block in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S | re.I):
        title = None
        for segment in re.split(r"<br\s*/?>", block, flags=re.I):
            links = LINK.findall(segment)
            if links:
                for url, label in links:
                    label = html.unescape(TAG.sub("", label)).strip()
                    url = urljoin(TOC, html.unescape(url))
                    if title and BONUS_LINK.search(label) and url not in seen:
                        extras.append({"title": title, "url": url,
                                       "label": label, "after_chapter": after_chapter})
                        seen.add(url)
                continue
            text = re.sub(r"\s+", " ", html.unescape(TAG.sub("", segment))).strip()
            match = HEAD_RE.match(text)
            if match:
                after_chapter = chapter_no(match.group(1))
                title = None
            elif BONUS_HEADING.match(text):
                title = text
    return extras


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-dir", default="books/shuukura-en/extras")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    book_dir = Path(args.book_dir)
    s = session()
    try:
        extras = parse_extra_toc(fetch(s, TOC, 0))
    except requests.RequestException as exc:
        sys.exit(f"cannot fetch {TOC}: {exc}")
    if not extras:
        sys.exit(f"no interludes or extras parsed from {TOC}")
    print(f"extras={len(extras)}", flush=True)
    if args.dry_run:
        for extra in extras:
            print(f"after chapter {extra['after_chapter']}: {extra['title']} {extra['url']}")
        return

    base_spec = json.loads((book_dir.parent / "book.json").read_text(encoding="utf-8"))
    (book_dir / "parts").mkdir(parents=True, exist_ok=True)
    (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
    chapters = []
    for no, extra in enumerate(extras, 1):
        part_file = f"parts/{no:04d}-p{no}.txt"
        part_path = book_dir / part_file
        if not part_path.exists() or args.force:
            try:
                paragraphs = parse_part(fetch(s, extra["url"], args.delay))
            except requests.RequestException as exc:
                print(f"failed {extra['url']}: {exc}", file=sys.stderr)
                sys.exit(3)
            if not paragraphs:
                sys.exit(f"no prose found at {extra['url']}")
            write_atomic(str(part_path), "\n\n".join(paragraphs) + "\n")
            print(f"fetched {no}/{len(extras)}: {extra['title']}", flush=True)
        header = extra["title"].rstrip(".") + "."
        text = part_path.read_text(encoding="utf-8").strip()
        write_atomic(str(book_dir / "chapters" / f"{no:04d}.txt"), header + "\n\n" + text + "\n")
        chapters.append({"no": no, "title": extra["title"], "header": header,
                         "after_chapter": extra["after_chapter"], "toc_label": extra["label"],
                         "parts": [{"part": no, "url": extra["url"], "file": part_file,
                                    "sha256": sha256_file(part_path)}]})
    spec = {"slug": "shuukura-en-extras", "title": "Story About Buying My Classmate Once A Week: Extras",
            "lang": "en", "clean": "en", "source": {"type": "text", "index": TOC,
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")},
            "segmentation": base_spec["segmentation"], "unit_chars": base_spec["unit_chars"],
            "chapters": chapters}
    write_atomic(str(book_dir / "book.json"), json.dumps(spec, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {book_dir / 'book.json'}: {len(chapters)} extras", flush=True)


if __name__ == "__main__":
    main()
