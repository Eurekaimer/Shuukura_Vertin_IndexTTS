"""章节正文清洗：只保留要朗读的叙事文本。

EPUB 抓下来的原始文本混着目录行、集数标记（`Episode 1`）、标题重复、译者注、
上传者的更后记、密码页、图片占位等。规则按子 agent 的抽样审查结果逐条落实：

  * 纯标记行、导航/声明/水印行整行丢弃
  * `Episode N 标题` 行：抽出标题后**整行丢弃**（原文里标题常重复 3–4 次并粘进正文）
  * 开头剩余的标题副本、`大更特更！` 之类更数行，一并丢弃
  * 括号内含假名的注释、`（译者注：…）`、`（译注：…）`、`（注：…）`、`（译者吐槽：…）`
    等译注（含嵌套括号）整段删除，但保留同一行的叙事；行内 `.jpg` 梗注只删括号本身
  * 章首重复的 `episode N` 标记（含 `### episode`、`pisode` 笔误）与标记之间的
    上传者碎碎念整段丢弃；标记之间的真实标题保留
  * 章尾 `------------` 之后的更后记：仅当尾部很短（≤400 字或 ≤20% 行数）才截断
  * 引号配对修正、`。”。` → `。”`
  * 密码页（142/169/229/270/320/381 章正文缺失）：标记为 missing，不合成
"""

import re
from difflib import SequenceMatcher

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

DROP_MARKER = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:e?pisode|chapter|part|ch\.?)\s*\d+\s*$", re.I
)
UPDATE_LINE = re.compile(r"^\s*(?:大更特更|加更|爆更|二更|三更)[！!。．]?\s*$")

INLINE_MARKER = re.compile(r"(?:e?pisode|chapter|part)\s*\d+\s*", re.I)
INLINE_NOISE = re.compile(r"(?:\[\s*(?:图片|插图|图)\s*\]|【\s*(?:图片|插图)\s*】|\(\s*图\s*\))")
URL = re.compile(r"(?:https?://\S+|www\.\S+)")

# 译注（含嵌套括号）：用括号配对扫描，不再用会截断内层括号的正则
NOTE_START = re.compile(
    r"^[（(]\s*(?:※\s*)?(?:译者吐槽|译者注|译者的话|译注|译者|作者的话|作者注|译|注)\s*[:：]"
)
# 独占一行的译注/译者说明（含 `※译者注：…`）
NOTE_LINE = re.compile(
    r"^\s*[（(]?\s*(?:※\s*)?(?:译者吐槽|译者注|译者的话|译者|译注|作者注|作者的话)\s*[:：]"
)

# 无译者标记、但明确在指涉前文/上文的译注括注（保守：需同时出现指涉词与“提到/说过”等）
META_PAREN = re.compile(
    r"(?:前文|上文|后文|下文)\s*(?:中)?\s*(?:提到|提过|说过|讲到|讲过|所述|所说)"
    r"|(?:如前所述|如前文所述|见前文|见上文)"
)

# 括号里夹着日文假名的注释（译者原文／吐槽）
KANA_PAREN = re.compile(rf"[（(][^）)]*[{KANA}][^）)]*[）)]")

# 更后记分隔线
SEP = re.compile(r"^-{10,}\s*$")

TITLE_PAT = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:e?pisode|chapter|part)\s*(\d+)\s*[、.．:：\-—]?\s*(.*)$", re.I
)
TITLE_PAT_CN = re.compile(r"^\s*第\s*(\d+)\s*[话話章][、.．:：\-—]?\s*(.*)$")

PASSWORD_PAT = re.compile(r"(?:password|密码|提取码)\s*[:：]", re.I)

# 章首标记之间疑似上传者碎碎念的词，用来避免把吐槽当成标题
NOTE_HINT = re.compile(
    r"更新|更了|加更|爆更|双更|日更|码字|翻译|译者|排版|手机版|电脑版|随缘|发文|大佬|攒点|rp|cp",
    re.I,
)


def _strip_paren_groups(text, should_strip):
    """按括号配对删除整段括号内容；括号不配对时原样保留，避免误删正文。"""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] in "（(":
            depth, j = 0, i
            while j < n:
                if text[j] in "（(":
                    depth += 1
                elif text[j] in "）)":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            if depth == 0 and should_strip(text[i:j]):
                i = j
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _strip_jpg_asides(text):
    """只删括号里的 `.jpg` 梗注，保留同一行的叙事。"""
    return _strip_paren_groups(text, lambda group: ".jpg" in group.lower())


def _strip_notes(text):
    """删除行内译注（支持嵌套括号），保留前后叙事。"""
    return _strip_paren_groups(
        text, lambda group: bool(NOTE_START.match(group) or META_PAREN.search(group))
    )


def _norm_title(s):
    return re.sub(r"[\s。．，,、！!？?…：:；;“”\"'‘’「」『』（）()【】\[\]\-—~·]+", "", s)


def _is_title_like(line):
    return bool(
        2 <= len(line) <= 40
        and not re.search(r"[。！？!?…；;：:]$", line)
        and not NOTE_HINT.search(line)
        and not NOTE_LINE.match(line)
    )


def _next_line_is_heading(lines, start):
    for j in range(start, len(lines)):
        if lines[j]:
            return bool(TITLE_PAT.match(lines[j]))
    return False


def _nearest_heading(lines, start, limit=12):
    end = min(len(lines), start + limit)
    for j in range(start, end):
        if lines[j] and TITLE_PAT.match(lines[j]):
            return j
    return None


def _is_title_copy(line, title):
    if not title or not _is_title_like(line):
        return False
    a, b = _norm_title(line), _norm_title(title)
    if not a or not b:
        return False
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.8


def _scan_head(lines):
    """剥离章首重复的集数标记与上传者碎碎念，返回 (起始行, 正文行, 标题, 删除行数)。"""
    first = next((i for i, ln in enumerate(lines) if ln and TITLE_PAT.match(ln)), None)
    if first is None:
        return 0, 0, "", 0

    title, dropped, i = "", 0, first
    while i < len(lines):
        ln = lines[i]
        if not ln:
            i += 1
            continue
        m = TITLE_PAT.match(ln)
        if m:
            rest = _norm_ws(m.group(2))
            if len(rest) >= 2:
                title = rest
            dropped += 1
            i += 1
            continue
        if SEP.match(ln) or DROP_LINE.match(ln) or UPDATE_LINE.match(ln):
            dropped += 1
            i += 1
            continue
        # 标记之间紧跟下一个标记的短句 = 真实标题；其余都是上传者碎碎念
        if _next_line_is_heading(lines, i + 1) and _is_title_like(ln):
            if not title:
                title = ln
            dropped += 1
            i += 1
            continue
        if _nearest_heading(lines, i + 1) is not None:
            dropped += 1
            i += 1
            continue
        # 最后一个标记之后、正文之前重复的标题副本
        if _is_title_copy(ln, title):
            dropped += 1
            i += 1
            continue
        break
    return first, i, title, dropped


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
    lines = []
    for x in raw.split("\n"):
        ln = _norm_ws(x)
        lines.append(_strip_jpg_asides(ln) if ln else "")

    head_start, head_end, title, dropped = _scan_head(lines)
    kept = []

    for idx, ln in enumerate(lines):
        if head_start <= idx < head_end:
            continue
        if not ln:
            continue
        if DROP_LINE.match(ln) or DROP_MARKER.match(ln) or UPDATE_LINE.match(ln):
            dropped += 1
            continue
        if NOTE_LINE.match(ln) and ln.lstrip()[:1] not in ("（", "("):
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
        ln = _strip_notes(ln)
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
    out = re.sub(r"—+", "，", out)
    # 只去掉确实重复的句号（`。”。` → `。”`），保留闭引号后唯一的句末停顿
    out = re.sub(r"(?<=。)([”』」])\。", r"\1", out)

    missing = len(body) < 100 or bool(PASSWORD_PAT.search(body))
    return out, {
        "dropped_lines": dropped,
        "title": title,
        "chars": len(out),
        "missing": missing,
    }
