"""把 EPUB 按章节批量转成有声书（IndexTTS-2.5，Vertin 参考音频）。

用法：
    cd ~/Documents/GitHub/Vertin
    index-tts/.venv/bin/python example/tts_book.py \
        --epub "buying-a-classmate-once-a-week/*.epub" \
        --out-dir audiobook --per-file 20 --device cuda:0

行为：
  * 按 EPUB spine 顺序取章节，跳过目录页；
  * 每 ~per-file 章合并成一个 wav，章间插入 --chapter-pause 秒静音；
  * 单章过长时按句子边界切成 --max-chars 字的小段分别推理，避免显存峰值；
  * 已存在的输出文件直接跳过，可中断后续跑。

文本会做朗读向的清洗：去掉章节标题行里的英文 "episode N"、译者注、多余空白。
"""

import argparse
import glob
import os
import re
import sys
import time
import zipfile
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from vertin_ref import REF_7S  # noqa: E402
from audio_clean import clean as clean_audio  # noqa: E402
from segmentation import split_for_reading  # noqa: E402
from text_prep import clean_chapter  # noqa: E402


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


def polish(text, chapter_no):
    """朗读向清洗：去掉英文集数标题、译者注、残留标记。"""
    lines = [ln.strip() for ln in text.split("\n")]
    out = []
    for i, ln in enumerate(lines):
        if not ln:
            continue
        # 首行若是 "episode 12" / "Chapter 12" 之类标题，丢掉（改用中文报章号）
        if i == 0 and re.match(r"^(episode|chapter|part)\s*\d+", ln, re.I):
            continue
        if re.match(r"^[（(]?\s*(译注|译者注|作者注|注)[:：]", ln):
            continue
        ln = re.sub(r"[（(]\s*(译注|译者注)[^）)]*[）)]", "", ln)
        ln = re.sub(r"[ \t]+", " ", ln)
        if ln:
            out.append(ln)
    body = "\n".join(out)
    return f"第{chapter_no}话。\n{body}"


def split_chunks(text, max_chars):
    """按句末标点把长文本切成 <= max_chars 的块。"""
    sents = re.split(r"(?<=[。！？…!?；;])", text)
    chunks, cur = [], ""
    for s in sents:
        if not s:
            continue
        if len(cur) + len(s) > max_chars and cur:
            chunks.append(cur)
            cur = s
        else:
            cur += s
    if cur:
        chunks.append(cur)
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epub", required=True, help="EPUB 路径，支持通配符")
    ap.add_argument("--out-dir", default=os.path.join(REPO, "audiobook"))
    ap.add_argument("--per-file", type=int, default=20, help="每个音频合并多少章")
    ap.add_argument("--start", type=int, default=1, help="起始章号（1-based）")
    ap.add_argument("--end", type=int, default=None, help="结束章号（含）")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--ref", default=REF_7S)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--chapter-pause", type=float, default=1.0, help="章间静音秒数")
    ap.add_argument("--unit-chars", type=int, default=70, help="单次推理的朗读单元上限（字）")
    ap.add_argument("--interval-silence", type=int, default=350, help="句间静音毫秒（IndexTTS 参数）")
    ap.add_argument("--format", default="wav", choices=["wav", "flac"])
    ap.add_argument("--duration-factor", type=float, default=1.0,
                    help="语速：>1 更慢，<1 更快（有效范围 0.5–2.0）")
    ap.add_argument("--pitch", type=float, default=0.0,
                    help="音高偏移（半音），-1 ~ -2 更低沉/御姐")
    ap.add_argument("--denoise", type=float, default=0.0,
                    help="谱门降噪强度，0=只去爆音")
    args = ap.parse_args()

    paths = glob.glob(args.epub)
    if not paths:
        sys.exit(f"epub not found: {args.epub}")
    chapters = load_chapters(paths[0])
    end = args.end or len(chapters)
    sel = chapters[args.start - 1:end]
    print(f"epub={os.path.basename(paths[0])} chapters={len(chapters)} selected={len(sel)} "
          f"chars={sum(len(c[1]) for c in sel)}")

    os.makedirs(args.out_dir, exist_ok=True)

    import numpy as np
    import soundfile as sf
    sys.path.insert(0, os.path.join(REPO, "index-tts"))
    from indextts.infer_v2_5 import IndexTTS2

    ckpt = os.path.join(REPO, "index-tts/checkpoints")
    t0 = time.time()
    tts = IndexTTS2(cfg_path=os.path.join(ckpt, "config.yaml"), model_dir=ckpt,
                    use_bf16=(args.device != "cpu"), use_cuda_kernel=False, device=args.device)
    # 低显存模式会把 >40 字的文本再切成 40 字一段，而我们的朗读单元已经 ≤ unit-chars，
    # 再切会打碎节奏并增加调用次数（实测 RTF 0.68 → 0.52）。关掉它。
    tts.low_vram = False
    print(f"model loaded in {time.time() - t0:.1f}s on {args.device}")

    tmp = os.path.join(args.out_dir, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    lang = "ZH" if args.lang == "zh" else "EN"

    spent_audio = 0.0
    spent_wall = 0.0
    for g0 in range(0, len(sel), args.per_file):
        group = sel[g0:g0 + args.per_file]
        first_no = args.start + g0
        last_no = first_no + len(group) - 1
        out_name = f"{first_no:04d}-{last_no:04d}.{args.format}"
        out_path = os.path.join(args.out_dir, out_name)
        if os.path.exists(out_path):
            print(f"skip existing {out_name}")
            continue

        pieces = []
        for k, (name, raw) in enumerate(group):
            ch_no = first_no + k
            text, prep_stats = clean_chapter(raw, ch_no)
            if prep_stats["missing"]:
                print(f"  ch{ch_no:04d} SKIP (no readable body: {prep_stats['chars']} chars)")
                continue
            units = split_for_reading(text, max_chars=args.unit_chars)
            audio_parts = []
            for ci, (chunk, pause) in enumerate(units):
                seg_path = os.path.join(tmp, f"{ch_no:04d}_{ci:03d}.wav")
                t1 = time.time()
                tts.infer(spk_audio_prompt=args.ref, text=chunk, lang=lang,
                          output_path=seg_path, interval_silence=args.interval_silence,
                          duration_factor=args.duration_factor, verbose=False)
                a, sr = sf.read(seg_path)
                os.remove(seg_path)
                audio_parts.append(a)
                if pause > 0:
                    audio_parts.append(np.zeros(int(sr * pause), dtype=a.dtype))
                spent_wall += time.time() - t1
                spent_audio += len(a) / sr
            ch_audio = np.concatenate(audio_parts)
            pieces.append(ch_audio)
            print(f"  ch{ch_no:04d} {len(ch_audio) / sr:6.1f}s units={len(units)} "
                  f"drop={prep_stats['dropped_lines']} "
                  f"rtf={spent_wall / max(spent_audio, 1e-6):.2f}  [{k + 1}/{len(group)}]")

        if not pieces:
            print(f"skip group {out_name}: no readable chapters")
            continue
        silence = np.zeros(int(sr * args.chapter_pause), dtype=pieces[0].dtype)
        merged = []
        for i, p in enumerate(pieces):
            merged.append(p)
            if i != len(pieces) - 1:
                merged.append(silence)
        final = np.concatenate(merged)
        final, st = clean_audio(final, sr, denoise_prop=args.denoise, pitch=args.pitch)
        n_jumps = st.get("pops", 0)
        sf.write(out_path, final, sr)
        print(f"WRITTEN {out_name} dur={len(final) / sr / 60:.1f} min "
              f"size={os.path.getsize(out_path) / 1e6:.0f} MB declick={n_jumps}")

    os.rmdir(tmp)
    if spent_audio:
        print(f"DONE audio={spent_audio / 60:.1f} min wall={spent_wall / 60:.1f} min "
              f"rtf={spent_wall / spent_audio:.2f}")


if __name__ == "__main__":
    main()
