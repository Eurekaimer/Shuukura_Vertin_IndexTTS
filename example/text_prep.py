"""章节正文清洗：只保留要朗读的叙事文本。

EPUB 抓下来的原始文本混着目录行、集数标记（`Episode 1`）、标题重复、译者注、
上传者的更后记、密码页、图片占位等。规则按子 agent 的抽样审查结果逐条落实：

  * 纯标记行、导航/声明/水印行整行丢弃
  * `Episode N 标题` 行：抽出标题后**整行丢弃**（原文里标题常重复 3–4 次并粘进正文）
  * 开头剩余的标题副本、`大更特更！` 之类更数行，一并丢弃
  * 括号内含假名的注释（译者夹带的日文原文）、`（译者：…）`、`（译者注：…）`、
    `NNN读后吐槽：…`、`.jpg` 梗注一律删除
  * 章尾 `------------` 之后的更后记：仅当尾部很短（≤400 字或 ≤20% 行数）才截断
  * 引号配对修正、`。”。` → `。”`
  * 密码页（142/169/229/270/320/381 章正文缺失）：标记为 missing，不合成
"""

import re

KANA = "\u3040-\u30ff"

DROP_LINE = re.compile(
    r"^\s*(?:"
    r"目录|目錄|上一章|下一章|返回目录|章节目录|"
    r"作品名[:：].*|作者[:：].*|译者[:：].*|来源[:：].*|"
    r".*禁止转载.*|.*禁止在外网.*|.*仅供日语学习.*|.*不得用于任何商业用途.*|"
    r".*侵删.*|.*请勿.*|.*转载请.*|.*首发.*|"
    r"(?:地址|password|密码|提取码)\s*[:：].*|"
    r"\d+\s*读后吐槽\s*[:：].*|"
    r".*https?://.*|.*www\..*|.*\.jpg.*|"
    r"[\s\-—=*#~·]*"
    r")\s*$",
    re.I,
)

DROP_MARKER = re.compile(r"^\s*(?:episode|chapter|part|ch\.?)\s*\d+\s*$", re.I)
UPDATE_LINE = re.compile(r"^\s*(?:大更特更|加更|爆更|二更|三更)[！!。．]?\s*$")

INLINE_MARKER = re.compile(r"(?:episode|chapter|part)\s*\d+\s*", re.I)
INLINE_NOISE = re.compile(r"(?:\[\s*(?:图片|插图|图)\s*\]|【\s*(?:图片|插图)\s*】|\(\s*图\s*\))")
URL = re.compile(r"(?:https?://\S+|www\.\S+)")

# 译者注：不再限制长度（原规则 80 字上限漏掉了 75 处）
NOTE_INLINE = re.compile(
    r"[（(]\s*(?:译者注|译者|译注|作者注|作者的话)\s*[:：][^）)]*[）)]"
)
NOTE_LINE = re.compile(r"^\s*[（(]?\s*(?:译注|译者注|译者|作者注)\s*[:：]")

# 括号里夹着日文假名的注释（译者原文／吐槽）
KANA_PAREN = re.compile(rf"[（(][^）)]*[{KANA}][^）)]*[）)]")

# 更后记分隔线
SEP = re.compile(r"^-{10,}\s*$")

TITLE_PAT = re.compile(r"^\s*(?:episode|chapter|part)\s*(\d+)\s*[、.．:：\-—]?\s*(.*)$", re.I)
TITLE_PAT_CN = re.compile(r"^\s*第\s*(\d+)\s*[话話章][、.．:：\-—]?\s*(.*)$")

PASSWORD_PAT = re.compile(r"(?:password|密码|提取码)\s*[:：]", re.I)


def fix_quotes(text):
    """译文里左右引号常被打成同一个字符，按出现顺序配对修正。"""
    out, opened = [], False
    for ch in text:
        if ch == "\u201c":
            out.append("\u201d" if opened else "\u201c")
            opened = not opened
        elif ch == "\u201d":
            out.append("\u201d")
            opened = False
        else:
            out.append(ch)
    return "".join(out)


def _norm_ws(s):
    s = s.replace("\u3000", " ")
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _cut_afterword(raw):
    """章尾 `-----` 之后若只是简短更后记，截断。"""
    lines = raw.split("\n")
    total = max(len(lines), 1)
    cut = None
    for i, ln in enumerate(lines):
        if SEP.match(ln.strip()):
            tail = lines[i + 1:]
            tail_lines = [x for x in tail if x.strip()]
            if len(tail_lines) * 5 <= total or sum(len(x) for x in tail) <= 400:
                cut = i
    if cut is None:
        return raw
    return "\n".join(lines[:cut])


def clean_chapter(raw, chapter_no):
    """返回 (readable_text, stats)。stats 含 missing 标记，调用方应跳过 missing。"""
    raw = _cut_afterword(raw)
    lines = [_norm_ws(x) for x in raw.split("\n")]
    kept, dropped = [], 0
    title = None

    for ln in lines:
        if not ln:
            continue
        if DROP_LINE.match(ln) or DROP_MARKER.match(ln) or UPDATE_LINE.match(ln):
            dropped += 1
            continue
        if NOTE_LINE.match(ln):
            dropped += 1
            continue

        # 标题行：抽走标题后整行丢弃，避免重复副本粘进正文
        if not title:
            m = TITLE_PAT.match(ln) or TITLE_PAT_CN.match(ln)
            if m:
                rest = _norm_ws(m.group(2))
                if len(rest) >= 2:
                    title = rest
                    dropped += 1
                    continue

        ln = URL.sub("", ln)
        ln = INLINE_NOISE.sub("", ln)
        ln = NOTE_INLINE.sub("", ln)
        ln = KANA_PAREN.sub("", ln)
        ln = _norm_ws(INLINE_MARKER.sub("", ln))
        if len(ln) < 2:
            dropped += 1
            continue
        kept.append(ln)

    # 开头残留的标题副本 / 更数行
    def is_copy(line):
        if not title:
            return False
        if line == title:
            return True
        if re.fullmatch(rf"第{chapter_no}话[。．]?\s*{re.escape(title)}[。！？…]?", line):
            return True
        return bool(UPDATE_LINE.match(line))

    while kept and is_copy(kept[0]):
        kept.pop(0)
        dropped += 1

    if not title and kept:
        first = kept[0]
        if len(first) <= 30 and not re.search(r"[。！？…!?]$", first):
            title = first
            kept = kept[1:]
            dropped += 1

    body = fix_quotes("".join(kept))
    body = body.replace("。”。", "。”")

    head = f"第{chapter_no}话。"
    if title:
        head += re.sub(r"[。！？…\s]+$", "", title) + "。"
    out = head + body
    out = re.sub(r"([。”』」])\。", r"\1", out)

    missing = len(body) < 100 or bool(PASSWORD_PAT.search(body))
    return out, {
        "dropped_lines": dropped,
        "title": title,
        "chars": len(out),
        "missing": missing,
    }
