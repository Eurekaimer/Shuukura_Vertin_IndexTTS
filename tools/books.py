"""书籍目录 -> 章节列表。EPUB 走清洗，抓取的英文文本已可直接朗读。

book.json 决定来源类型（epub/text）、断句参数与每章文件；渲染器与计划导出
共用这里的加载逻辑，保证同一本书只有一种读法。
"""

import glob
import json
import os
import re
import zipfile
from collections import namedtuple
from html.parser import HTMLParser

from text_prep import clean_chapter

Chapter = namedtuple("Chapter", "no title text missing parts", defaults=[None])

NOISE_LINE = re.compile(r"(?m)^\s*(?:document\.|var\s|function\s*\(|window\.).*$")
MARKER_LINE = re.compile(r"(?m)^[ \t]*[^\w\s]{1,6}[ \t]*$")


def polish_en(text):
    """朗读向前处理：去掉网页残留与装饰行，长破折号改成停顿（逗号）。"""
    text = text.replace("\u00ad", "").replace("\u200b", "")
    text = NOISE_LINE.sub("", text)
    text = re.sub(r"(?m)^[ \t]*[–—][ \t]+", "", text)
    text = re.sub(r"[ \t]*[–—][ \t]*", ", ", text)
    text = MARKER_LINE.sub("", text)
    text = re.sub(r"[*_]{1,3}(?=\w)|(?<=\w)[*_]{1,3}", "", text)
    text = re.sub(r",\s*,+", ",", text)
    text = re.sub(r",\s*([.!?;:])", r"\1", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class TextExtract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buf = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "div", "br", "h1", "h2", "h3", "li"):
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def html_to_text(raw):
    p = TextExtract()
    p.feed(raw)
    text = "".join(p.buf)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def load_chapters(epub_path):
    z = zipfile.ZipFile(epub_path)
    names = [n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
    opfs = [n for n in z.namelist() if n.endswith(".opf")]
    order = []
    if opfs:
        opf_raw = z.read(opfs[0]).decode("utf-8", "ignore")
        ids = re.findall(r'<itemref[^>]*idref="([^"]+)"', opf_raw)
        items = dict((m[0], m[1]) for m in re.findall(r'<item[^>]*id="([^"]+)"[^>]*href="([^"]+)"', opf_raw))
        items.update(dict((m[1], m[0]) for m in re.findall(r'<item[^>]*href="([^"]+)"[^>]*id="([^"]+)"', opf_raw)))
        base = os.path.dirname(opfs[0])
        for i in ids:
            href = items.get(i)
            if href:
                order.append(os.path.normpath(os.path.join(base, href)))
    order = [n for n in order if n in names] or sorted(names)

    chapters = []
    for n in order:
        if "nav" in os.path.basename(n).lower() or "toc" in os.path.basename(n).lower():
            continue
        t = html_to_text(z.read(n).decode("utf-8", "ignore"))
        if len(t) < 50:
            continue
        # 目录页也伪装成 chapter_001.xhtml，只能靠内容特征剔除
        if t.lstrip().startswith(("目录", "Table of Contents")):
            continue
        if len(re.findall(r"episode\s+\d+", t, re.I)) > 5:
            continue
        chapters.append((n, t))
    return chapters


def _epub_chapters(book_dir, spec):
    paths = glob.glob(os.path.join(book_dir, spec["source"]["glob"]))
    if len(paths) != 1:
        raise SystemExit(f"expected exactly one EPUB for {spec['source']['glob']}, "
                         f"found {len(paths)}")
    chapters = []
    for no, (_, raw) in enumerate(load_chapters(paths[0]), 1):
        text, stats = clean_chapter(raw, no)
        chapters.append(Chapter(no, stats["title"], text, stats["missing"]))
    return paths, chapters


def _text_chapters(book_dir, spec):
    chapters = []
    for entry in spec["chapters"]:
        no = entry["no"]
        header = entry.get("header") or f"Chapter {no}. {entry['title']}."
        part_files = entry.get("parts", [])
        if part_files:
            texts = [header]
            for part in part_files:
                path = os.path.join(book_dir, part["file"])
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
                texts.append(polish_en(raw) if spec.get("clean") == "en" else raw.strip())
        else:
            path = os.path.join(book_dir, "chapters", f"{no:04d}.txt")
            if not os.path.isfile(path):
                raise SystemExit(f"missing chapter file: {path}")
            with open(path, encoding="utf-8") as f:
                texts = None
                text = f.read()
            chapters.append(Chapter(no, entry["title"], text, False, None))
            continue
        chapters.append(Chapter(no, entry["title"], "\n\n".join(texts), False, texts))
    return chapters


def load_book(book_dir):
    """返回 (book.json 内容, [Chapter])。"""
    with open(os.path.join(book_dir, "book.json"), encoding="utf-8") as f:
        spec = json.load(f)
    if spec["source"]["type"] == "epub":
        paths, chapters = _epub_chapters(book_dir, spec)
        sources = paths
    elif spec["source"]["type"] == "text":
        chapters = _text_chapters(book_dir, spec)
        sources = (sorted(glob.glob(os.path.join(book_dir, "chapters", "*.txt")))
                   + sorted(glob.glob(os.path.join(book_dir, "parts", "*.txt"))))
    else:
        raise SystemExit(f"unknown source type: {spec['source']['type']}")
    spec["_source_files"] = sources
    return spec, chapters
