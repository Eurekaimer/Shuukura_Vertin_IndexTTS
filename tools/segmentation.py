"""朗读向断句：把章节正文切成适合 TTS 的朗读单元，并给出每段之后的停顿时长。

EPUB 里每个 <p> 往往只有一句话，靠换行判断段落会把每句都当段末（停顿过长、
单元过碎）。所以这里**只按标点断句**，行结构只用于合并：

  1. 先把换行并成空白，按句末标点（。！？…!?）切句。
  2. 相邻短句贪心合并到 unit_chars 上限，让一次推理覆盖 1–3 句，减少接缝。
  3. 单句超过上限时，再按逗号/顿号/分号/冒号在小句边界切开。
  4. 仍然过短的碎片并回相邻单元，避免「对。」单独成段。
  5. 尽量不在引号/括号内切分；超长时优先在内部标点切分。

停顿：句末 0.35 s，小句末 0.18 s。正常人朗读的节奏主要由标点决定，
段末额外停顿在小说里只会让节奏变拖。
"""

import re

SENT_END = "。！？…!?;"
CLAUSE_END = "，、；：,:;"
OPEN_Q = "「『“‘（("
CLOSE_Q = "」』”’）)"

PAUSE_SENT = 0.35
PAUSE_CLAUSE = 0.18


def _split_sentences(text, sent_end=SENT_END):
    out, cur, depth = [], "", 0
    for ch in text:
        if ch in OPEN_Q:
            depth += 1
        elif ch in CLOSE_Q and depth > 0:
            depth -= 1
        cur += ch
        if depth == 0 and ch in sent_end:
            out.append(cur.strip())
            cur = ""
    if cur.strip():
        out.append(cur.strip())
    return [s for s in out if s]


def _split_at_clauses(sent, max_chars, sent_end=SENT_END, clause_end=CLAUSE_END,
                      prefer_word_boundary=False):
    """单句过长时按小句标点切，再合并到 <= max_chars。"""
    parts, cur, depth = [], "", 0
    for ch in sent:
        if ch in OPEN_Q:
            depth += 1
        elif ch in CLOSE_Q and depth > 0:
            depth -= 1
        cur += ch
        if depth == 0 and ch in clause_end:
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    merged, buf = [], ""
    for p in parts:
        if buf and len(buf) + len(p) > max_chars:
            merged.append(buf)
            buf = p
        else:
            buf += p
    if buf:
        merged.append(buf)
    # 对话过长时先在标点处分段，避免直接把词语从中间切开。
    out = []
    for m in merged or [sent]:
        while len(m) > max_chars:
            cut = max((m.rfind(ch, 0, max_chars) for ch in sent_end + clause_end), default=-1) + 1
            if cut <= 0 and prefer_word_boundary:
                cut = m.rfind(" ", 0, max_chars + 1)
            if cut <= 0:
                cut = max_chars
            while cut < len(m) and m[cut] in CLOSE_Q:
                cut += 1
            out.append(m[:cut])
            m = m[cut:]
        if m:
            out.append(m)
    return out


def _pause_of(unit, clause_end=CLAUSE_END, sent_pause=PAUSE_SENT,
              clause_pause=PAUSE_CLAUSE):
    return clause_pause if unit and unit[-1] in clause_end else sent_pause


def _join(head, tail, sep):
    if not head or not sep or head[-1].isspace() or tail[:1].isspace():
        return head + tail
    return head + sep + tail


def _split_flat(text, max_chars, min_chars, sent_end, clause_end, join_lines,
                sent_pause, clause_pause):
    flat = re.sub(r"\s*\n\s*", join_lines, text)

    phrases, buf = [], ""
    for sent in _split_sentences(flat, sent_end):
        pieces = (_split_at_clauses(sent, max_chars, sent_end, clause_end, bool(join_lines))
                  if len(sent) > max_chars else [sent])
        for piece in pieces:
            if buf and len(buf) + len(piece) > max_chars:
                phrases.append(buf)
                buf = piece
            else:
                buf = _join(buf, piece, join_lines)
    if buf:
        phrases.append(buf)

    merged = []
    for ph in phrases:
        if merged and (len(ph) < min_chars or len(merged[-1]) < min_chars):
            merged[-1] = _join(merged[-1], ph, join_lines)
        else:
            merged.append(ph)

    units = [(u, _pause_of(u, clause_end, sent_pause, clause_pause)) for u in merged]
    if units:
        units[-1] = (units[-1][0], 0.0)
    return units


def split_for_reading(text, max_chars=55, min_chars=12, sent_end=SENT_END,
                      clause_end=CLAUSE_END, join_lines="",
                      sent_pause=PAUSE_SENT, clause_pause=PAUSE_CLAUSE,
                      paragraph_pause=0.0):
    """返回 [(unit, pause_after_seconds), ...]。"""
    if paragraph_pause <= 0:
        return _split_flat(text, max_chars, min_chars, sent_end, clause_end,
                           join_lines, sent_pause, clause_pause)

    units = []
    for para in re.split(r"\n\s*\n", text.strip()):
        chunk = _split_flat(para, max_chars, min_chars, sent_end, clause_end,
                            join_lines, sent_pause, clause_pause)
        if not chunk:
            continue
        units.extend(chunk[:-1])
        units.append((chunk[-1][0], paragraph_pause))
    if units:
        units[-1] = (units[-1][0], 0.0)
    return units
