"""抓取 Ave Lilium 的英文版章节，写入书籍目录（逐 part 可续跑）。

用法：
    uv run python tools/scrape_parts.py --chapters 1-2
    uv run python tools/scrape_parts.py --dry-run

每个 part 单独存成 parts/NNNN-pN.txt；章节文件 chapters/NNNN.txt 由已下载的
part 重新拼出。book.json 记录章节/part 映射与来源，供渲染器读取。
"""

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TOC = "https://avelilium.com/story-about-buying-my-classmate-once-a-week/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124 Safari/537.36")
STOP = re.compile(r"^\s*(?:Credits?\b|If you enjoyed|Next part|Previous part|Share this)")
HEAD_RE = re.compile(r"^Chapter\s+(.+?)\s+[–—-]\s+(.+)$")
POV_RE = re.compile(r"\s*\(([^)]*?)\s+PoV\)$")
NUMBER_RE = re.compile(r"^(?:[A-Za-z]+(?:[\s-][A-Za-z]+)*|\d+)$")
LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>\s*Part\s+(\d+)\s*</a>')

UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate(
    "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split())}


def session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    retry = Retry(total=6, backoff_factor=1.5, connect=6, read=6, status=6,
                  status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def chapter_no(token):
    if token.isdigit():
        return int(token)
    total = 0
    for word in token.lower().replace("-", " ").split():
        if word in TENS:
            total += TENS[word]
        elif word in UNITS:
            total += UNITS[word]
        else:
            raise ValueError(f"unknown chapter word: {token}")
    return total


def fetch(s, url, delay):
    r = s.get(url, timeout=(10, 40))
    r.raise_for_status()
    time.sleep(delay)
    return r.text


def parse_toc(page):
    body = page[page.index('class="entry-content'):]
    chapters = []
    for block in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S):
        head = re.split(r"<br\s*/?>", block, maxsplit=1)[0]
        text = re.sub(r"<[^>]+>", "", html.unescape(head))
        text = re.sub(r"\s+", " ", text).strip()
        m = HEAD_RE.match(text)
        if not m or not NUMBER_RE.match(m.group(1)):
            continue
        title = m.group(2).strip()
        pov = ""
        pm = POV_RE.search(title)
        if pm:
            pov = pm.group(1).strip()
            title = title[:pm.start()].strip()
        parts = [(int(n), u) for u, n in LINK_RE.findall(block)]
        if parts:
            chapters.append({"no": chapter_no(m.group(1)), "word": m.group(1).lower(),
                             "title": title, "pov": pov,
                             "parts": parts})
    return chapters


def parse_part(page):
    body = page[page.index('class="entry-content'):]
    out = []
    for block in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S):
        text = re.sub(r"<br\s*/?>", "\n", block)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        text = text.replace("\u00a0", "")
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            continue
        if STOP.match(text):
            break
        out.append(text.replace("「", "“").replace("」", "”")
                    .replace("『", "‘").replace("』", "’"))
        out[-1] = re.sub(r"――+", "—", out[-1])
    return out


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected(chapters, spec):
    if spec == "all":
        return chapters
    wanted = set()
    for item in spec.split(","):
        if "-" in item:
            a, b = item.split("-", 1)
            wanted.update(range(int(a), int(b) + 1))
        else:
            wanted.add(int(item))
    return [c for c in chapters if c["no"] in wanted]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-dir", default="books/shuukura-en")
    ap.add_argument("--chapters", default="all", help="1-2, 1,2, 5；默认 all")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    s = session()
    try:
        page = fetch(s, TOC, 0)
    except requests.RequestException as e:
        sys.exit(f"cannot fetch {TOC}: {e}")
    chapters = parse_toc(page)
    if not chapters:
        sys.exit(f"no chapters parsed from {TOC}")
    picked = selected(chapters, args.chapters)
    if not picked:
        sys.exit(f"no chapters match {args.chapters}")
    print(f"toc chapters={len(chapters)} selected={len(picked)} "
          f"parts={sum(len(c['parts']) for c in picked)}")
    for c in picked:
        print(f"  chapter {c['no']:03d} ({c['word']}) {c['title']} [{c['pov'] or '?'} PoV]")
        for part, url in c["parts"]:
            print(f"    part {part:03d} {url}")
    if args.dry_run:
        return

    parts_dir = os.path.join(args.book_dir, "parts")
    chapters_dir = os.path.join(args.book_dir, "chapters")
    os.makedirs(parts_dir, exist_ok=True)
    os.makedirs(chapters_dir, exist_ok=True)

    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for c in picked:
        written = []
        for part, url in c["parts"]:
            path = os.path.join(parts_dir, f"{part:04d}-p{part}.txt")
            if os.path.exists(path) and not args.force:
                written.append((part, path, url))
                continue
            try:
                paras = parse_part(fetch(s, url, args.delay))
            except requests.RequestException as e:
                sys.exit(f"failed {url}: {e}")
            if not paras:
                sys.exit(f"no prose found at {url}")
            write_atomic(path, "\n\n".join(paras) + "\n")
            print(f"  fetched part {part:03d} ({len(paras)} paragraphs) {url}")
            written.append((part, path, url))
        written = [(part, path, url) for part, path, url in written if os.path.exists(path)]
        if written:
            c["files"] = written
            text = "\n\n".join(open(p, encoding="utf-8").read().strip() for _, p, _ in written)
            header = f"Chapter {c['word'].capitalize()}. {c['title']}.\n\n"
            write_atomic(os.path.join(chapters_dir, f"{c['no']:04d}.txt"), header + text + "\n")

    book = {
        "slug": "shuukura-en",
        "title": "Story About Buying My Classmate Once A Week",
        "lang": "en",
        "clean": "none",
        "source": {"type": "text", "index": TOC, "fetched_at": fetched_at},
        "segmentation": {"sent_end": ".!?;…", "clause_end": ",;:",
                         "join_lines": " "},
        "unit_chars": 140,
        "chapters": [],
    }
    for c in chapters:
        files = c.get("files")
        if not files:
            continue
        book["chapters"].append({
            "no": c["no"], "title": c["title"], "pov": c["pov"],
            "parts": [{"part": part, "url": url, "file": os.path.relpath(path, args.book_dir),
                       "sha256": sha256_file(path)} for part, path, url in files],
        })
    write_atomic(os.path.join(args.book_dir, "book.json"),
                 json.dumps(book, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {os.path.join(args.book_dir, 'book.json')} "
          f"chapters={len(book['chapters'])}")


if __name__ == "__main__":
    main()
