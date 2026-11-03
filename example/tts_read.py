"""纯文本 → 音频，逐句合成 + 显式静音停顿（IndexTTS-2.5）。

用法：
    cd ~/Documents/GitHub/Shuukura_Vertin_IndexTTS
    index-tts/.venv/bin/python example/tts_read.py \
        --text-file example/texts/read_zh.txt --lang zh \
        --out example/04_indextts_read_zh.wav

逐句合成的好处：每句都从同一段参考音频重新起跑，长文本不会语义漂移；
句间/段间停顿由 --pause / --para-pause 精确控制（IndexTTS 整段推理只在
segment 边界插固定 200 ms，无法调）。

整本 EPUB 请用 tts_book.py（按章批量、20 章合并一个文件）。
"""

import argparse
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ORIG_CWD = os.getcwd()

sys.path.insert(0, HERE)
from vertin_ref import REF_7S  # noqa: E402
from audio_clean import clean as clean_audio  # noqa: E402

SENT_END = "。！？；…!?;."
LANG_CODE = {"zh": "ZH", "en": "EN", "ja": "JA"}


def split_paragraphs(text):
    """按空行切段落，再按句末标点切句子。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    out = []
    for para in paras:
        flat = re.sub(r"\s*\n\s*", " ", para)
        buf, cur = [], ""
        for ch in flat:
            cur += ch
            if ch in SENT_END:
                buf.append(cur.strip())
                cur = ""
        if cur.strip():
            buf.append(cur.strip())
        out.append([s for s in buf if s])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--lang", default="zh", choices=["zh", "en", "ja"])
    ap.add_argument("--ref", default=REF_7S)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pause", type=float, default=0.35, help="句间静音秒数")
    ap.add_argument("--para-pause", type=float, default=0.9, help="段落间静音秒数")
    ap.add_argument("--device", default="cuda:0", help="cuda:0 / cpu")
    ap.add_argument("--pitch", type=float, default=0.0, help="音高偏移（半音）")
    ap.add_argument("--denoise", type=float, default=0.0)
    ap.add_argument("--interval-silence", type=int, default=350,
                    help="IndexTTS 段内句间静音毫秒")
    args = ap.parse_args()

    # 脚本可能 chdir，相对路径按调用者的 cwd 还原
    for attr in ("text_file", "out", "ref"):
        val = getattr(args, attr)
        if val and not os.path.isabs(val):
            setattr(args, attr, os.path.join(ORIG_CWD, val))
    if not os.path.exists(args.ref):
        sys.exit(f"reference not found: {args.ref}")

    paras = split_paragraphs(open(args.text_file, encoding="utf-8").read())
    if not any(paras):
        sys.exit("no text")

    import numpy as np
    import soundfile as sf

    sys.path.insert(0, os.path.join(REPO, "index-tts"))
    from indextts.infer_v2_5 import IndexTTS2

    ckpt = os.path.join(REPO, "index-tts/checkpoints")
    tts = IndexTTS2(cfg_path=os.path.join(ckpt, "config.yaml"), model_dir=ckpt,
                    use_bf16=(args.device != "cpu"), use_cuda_kernel=False,
                    device=args.device)
    # 低显存模式会把 >40 字的文本再切成 40 字一段，而我们的朗读单元已经 ≤ unit-chars，
    # 再切会打碎节奏并增加调用次数（实测 RTF 0.68 → 0.52）。关掉它。
    tts.low_vram = False

    tmpdir = tempfile.mkdtemp(prefix="idx_read_")
    chunks, sr_out = [], None
    try:
        for pi, para in enumerate(paras):
            for si, sent in enumerate(para):
                path = os.path.join(tmpdir, f"{pi}_{si}.wav")
                tts.infer(spk_audio_prompt=args.ref, text=sent,
                          lang=LANG_CODE[args.lang], output_path=path,
                          interval_silence=args.interval_silence, verbose=False)
                audio, sr = sf.read(path)
                sr_out = sr
                chunks.append(audio)
                print(f"[p{pi} s{si}] {len(audio) / sr:.2f}s  {sent[:40]}")
                last = pi == len(paras) - 1 and si == len(para) - 1
                if not last:
                    gap = args.para_pause if si == len(para) - 1 else args.pause
                    chunks.append(np.zeros(int(sr * gap), dtype=chunks[-1].dtype))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    out_audio = np.concatenate(chunks)
    out_audio, st = clean_audio(out_audio, sr_out, denoise_prop=args.denoise, pitch=args.pitch)
    n_jumps = st.get("pops", 0)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    sf.write(args.out, out_audio, sr_out)
    print(f"WRITTEN {args.out} sr={sr_out} dur={len(out_audio) / sr_out:.2f}s declick={n_jumps}")


if __name__ == "__main__":
    main()
