"""把 EPUB 按章节批量转成有声书（IndexTTS-2.5，Vertin 参考音频）。

用法：
    cd ~/Documents/GitHub/Shuukura_Vertin_IndexTTS
    ./bin/vertin-read

行为：
  * 按 EPUB spine 顺序取章节，跳过目录页；
  * 每 ~per-file 章合并成一个音频文件，章间插入 --chapter-pause 秒静音；
  * 长文本按 --unit-chars 切分；已完成章节以校验过的检查点保存；
  * 仅跳过校验通过且配置一致的输出，Ctrl-C 或重启后可继续。

文本会做朗读向的清洗：去掉章节标题行里的英文 "episode N"、译者注、多余空白。
"""

import argparse
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from vertin_ref import REF_7S  # noqa: E402
from audio_clean import durable_replace, smooth_file  # noqa: E402
from segmentation import split_for_reading  # noqa: E402
from text_prep import clean_chapter  # noqa: E402


def _checkpoint_namespace(args, model_dir, epub_path):
    """Identify settings that affect individual generated chapters."""
    digest = hashlib.sha256()
    for path in (epub_path, args.ref, __file__, os.path.join(HERE, "text_prep.py"),
                 os.path.join(HERE, "segmentation.py"),
                 os.path.join(model_dir, "config.yaml"),
                 os.path.join(REPO, "index-tts", "indextts", "infer_v2_5.py")):
        with open(path, "rb") as f:
            digest.update(f.read())
    for name in ("gpt.pth", "s2mel.pth", "codec.pth",
                 "hf_cache/campplus_cn_common.bin",
                 "hf_cache/bigvgan/bigvgan_generator.pt",
                 "hf_cache/semantic_codec/model.safetensors",
                 "hf_cache/w2v-bert-2.0/model.safetensors"):
        path = os.path.join(model_dir, name)
        stat = os.stat(path) if os.path.isfile(path) else None
        digest.update(f"{name}:{stat.st_size if stat else None}:{stat.st_mtime_ns if stat else None}".encode())
    digest.update(json.dumps([args.lang, args.unit_chars, args.interval_silence,
                              args.duration_factor, args.device]).encode())
    return digest.hexdigest()[:20]


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path, signature, audio_path):
    data = {"signature": signature, "size": os.path.getsize(audio_path),
            "sha256": _file_hash(audio_path)}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True)
    durable_replace(tmp, path)


def _verified_file(path, signature):
    path = os.fspath(path)
    try:
        with open(path + ".manifest.json", encoding="utf-8") as f:
            data = json.load(f)
        return (data["signature"] == signature and data["size"] == os.path.getsize(path)
                and data["sha256"] == _file_hash(path))
    except (OSError, ValueError, KeyError, TypeError):
        return False


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
    ap.add_argument("--smooth", action="store_true", help="apply mild declick and treble reduction")
    ap.add_argument("--checkpoint-dir", help="directory for resumable chapter audio")
    ap.add_argument("--keep-checkpoints", action="store_true", help="retain chapter checkpoints after output")
    args = ap.parse_args()

    paths = glob.glob(args.epub)
    if len(paths) != 1:
        sys.exit(f"expected exactly one EPUB for {args.epub}, found {len(paths)}")
    chapters = load_chapters(paths[0])
    end = args.end or len(chapters)
    sel = chapters[args.start - 1:end]
    print(f"epub={os.path.basename(paths[0])} chapters={len(chapters)} selected={len(sel)} "
          f"chars={sum(len(c[1]) for c in sel)}")

    os.makedirs(args.out_dir, exist_ok=True)
    ckpt = os.path.join(REPO, "index-tts/checkpoints")
    checkpoint_root = args.checkpoint_dir or os.path.join(args.out_dir, ".checkpoints")
    os.makedirs(checkpoint_root, exist_ok=True)
    lock = open(os.path.join(checkpoint_root, ".lock"), "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f"another audiobook process is using {checkpoint_root}")
    output_lock = open(os.path.join(args.out_dir, ".vertin.lock"), "a")
    try:
        fcntl.flock(output_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f"another audiobook process is using {args.out_dir}")
    namespace = _checkpoint_namespace(args, ckpt, paths[0])
    checkpoint_dir = os.path.join(checkpoint_root, namespace)
    os.makedirs(checkpoint_dir, exist_ok=True)
    print(f"chapter checkpoints: {checkpoint_dir}")

    import numpy as np
    import soundfile as sf
    sys.path.insert(0, os.path.join(REPO, "index-tts"))
    from indextts.infer_v2_5 import IndexTTS2

    t0 = time.time()
    tts = IndexTTS2(cfg_path=os.path.join(ckpt, "config.yaml"), model_dir=ckpt,
                    use_bf16=(args.device != "cpu"), use_cuda_kernel=False, device=args.device)
    # 低显存模式会把 >40 字的文本再切成 40 字一段，而我们的朗读单元已经 ≤ unit-chars，
    # 再切会打碎节奏并增加调用次数（实测 RTF 0.68 → 0.52）。关掉它。
    tts.low_vram = False
    print(f"model loaded in {time.time() - t0:.1f}s on {args.device}")

    for entry in os.scandir(args.out_dir):
        if entry.name.startswith(".vertin-tmp-") and entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path)
    tmp = tempfile.mkdtemp(prefix=".vertin-tmp-", dir=args.out_dir)
    filter_hash = _file_hash(os.path.join(HERE, "audio_clean.py")) if args.smooth else ""
    lang = "ZH" if args.lang == "zh" else "EN"

    spent_audio = 0.0
    spent_wall = 0.0
    for g0 in range(0, len(sel), args.per_file):
        group = sel[g0:g0 + args.per_file]
        first_no = args.start + g0
        last_no = first_no + len(group) - 1
        out_name = f"{first_no:04d}-{last_no:04d}.{args.format}"
        out_path = os.path.join(args.out_dir, out_name)
        output_signature = hashlib.sha256(json.dumps(
            [namespace, first_no, last_no, args.format, args.chapter_pause, args.smooth, filter_hash]
        ).encode()).hexdigest()
        if os.path.exists(out_path):
            if not _verified_file(out_path, output_signature):
                sys.exit(f"existing output is damaged or uses different settings: {out_path}; "
                         "choose another output directory rather than overwriting it")
            print(f"skip verified {out_name}")
            continue

        pieces = []
        group_checkpoints = []
        for k, (name, raw) in enumerate(group):
            ch_no = first_no + k
            text, prep_stats = clean_chapter(raw, ch_no)
            if prep_stats["missing"]:
                print(f"  ch{ch_no:04d} SKIP (no readable body: {prep_stats['chars']} chars)")
                continue
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            chapter_file = os.path.join(checkpoint_dir, f"{ch_no:04d}-{text_hash}.flac")
            if os.path.isfile(chapter_file):
                if _verified_file(chapter_file, text_hash):
                    ch_audio, sr = sf.read(chapter_file, dtype="float32")
                    pieces.append(ch_audio)
                    group_checkpoints.append(chapter_file)
                    print(f"  ch{ch_no:04d} RESTORED {len(ch_audio) / sr:.1f}s [{k + 1}/{len(group)}]")
                    continue
                print(f"  ch{ch_no:04d} invalid checkpoint; regenerating")
                os.remove(chapter_file)
            units = split_for_reading(text, max_chars=args.unit_chars)
            audio_parts = []
            for ci, (chunk, pause) in enumerate(units):
                seg_path = os.path.join(tmp, f"{ch_no:04d}_{ci:03d}.wav")
                t1 = time.time()
                tts.infer(spk_audio_prompt=args.ref, text=chunk, lang=lang,
                          output_path=seg_path, interval_silence=args.interval_silence,
                          duration_factor=args.duration_factor, verbose=False)
                a, sr = sf.read(seg_path, dtype="float32")
                os.remove(seg_path)
                audio_parts.append(a)
                if pause > 0:
                    audio_parts.append(np.zeros(int(sr * pause), dtype=a.dtype))
                spent_wall += time.time() - t1
                spent_audio += len(a) / sr
            ch_audio = np.concatenate(audio_parts)
            chapter_tmp = chapter_file + ".tmp.flac"
            sf.write(chapter_tmp, ch_audio, sr, subtype="PCM_16")
            _write_manifest(chapter_file + ".manifest.json", text_hash, chapter_tmp)
            durable_replace(chapter_tmp, chapter_file)
            group_checkpoints.append(chapter_file)
            print(f"  ch{ch_no:04d} CHECKPOINT saved")
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
        raw_path = os.path.join(tmp, out_name)
        sf.write(raw_path, final, sr, subtype="PCM_16")
        prepared_path = raw_path
        if args.smooth:
            prepared_path = os.path.join(tmp, "smooth-" + out_name)
            smooth_file(raw_path, prepared_path)
            os.remove(raw_path)
        _write_manifest(out_path + ".manifest.json", output_signature, prepared_path)
        durable_replace(prepared_path, out_path)
        if not args.keep_checkpoints:
            for chapter_file in group_checkpoints:
                os.remove(chapter_file)
                os.remove(chapter_file + ".manifest.json")
        print(f"WRITTEN {out_name} dur={len(final) / sr / 60:.1f} min "
              f"size={os.path.getsize(out_path) / 1e6:.0f} MB")

    shutil.rmtree(tmp)
    if spent_audio:
        print(f"DONE audio={spent_audio / 60:.1f} min wall={spent_wall / 60:.1f} min "
              f"rtf={spent_wall / spent_audio:.2f}")


if __name__ == "__main__":
    main()
