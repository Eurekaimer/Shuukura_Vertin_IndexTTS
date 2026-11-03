"""把一本书（EPUB 或抓取的英文文本）按章节批量转成有声书（IndexTTS-2.5）。

用法：
    cd ~/Documents/GitHub/Shuukura_Vertin_IndexTTS
    ./bin/vertin-read
    index-tts/.venv/bin/python tools/tts_book.py \
        --book books/shuukura-en --out-dir example/en_preview --per-file 1

行为：
  * 按 book.json 的章节顺序取正文，每 ~per-file 章合并成一个音频文件；
  * 章间插入 --chapter-pause 秒静音；
  * 长文本按书里的 unit_chars 切分；已完成章节以校验过的检查点保存；
  * 仅跳过校验通过且配置一致的输出，Ctrl-C 或重启后可继续。
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from vertin_ref import REF_7S  # noqa: E402
from audio_clean import durable_replace, smooth_file  # noqa: E402
from books import load_book  # noqa: E402
from segmentation import split_for_reading  # noqa: E402

PIPELINE_REVISION = 3


def _wait_for_vram(cuda, device, min_free_mib):
    """Wait until the GPU has enough free memory for the next operation."""
    minimum = min_free_mib * 1024 * 1024
    while True:
        free, total = cuda.mem_get_info(device)
        if minimum > total:
            raise SystemExit(f"VRAM threshold {min_free_mib} MiB exceeds device capacity "
                             f"{total // (1024 * 1024)} MiB")
        if free >= minimum:
            return
        cuda.empty_cache()
        free, _ = cuda.mem_get_info(device)
        if free >= minimum:
            return
        print(f"GPU free {free // (1024 * 1024)} MiB < {min_free_mib} MiB; "
              "waiting 30s for VRAM", flush=True)
        time.sleep(30)


def _checkpoint_namespace(args, model_dir, book_dir, spec):
    """Identify settings that affect individual generated chapters."""
    digest = hashlib.sha256()
    digest.update(str(PIPELINE_REVISION).encode())
    files = [os.path.join(book_dir, "book.json"), args.ref,
             os.path.join(HERE, "books.py"), os.path.join(HERE, "text_prep.py"),
             os.path.join(HERE, "segmentation.py"),
             os.path.join(model_dir, "config.yaml")]
    files += spec["_source_files"]
    for path in files:
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
                              args.duration_factor, args.device,
                              spec["segmentation"]]).encode())
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


def _manifest_matches(path):
    """文件与现有 manifest 的 size/sha256 一致时，可以保留文件并换用新签名。"""
    try:
        with open(path + ".manifest.json", encoding="utf-8") as f:
            data = json.load(f)
        return (data["size"] == os.path.getsize(path)
                and data["sha256"] == _file_hash(path))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True, help="书籍目录（含 book.json）")
    ap.add_argument("--out-dir", help="默认 audiobook/<slug>")
    ap.add_argument("--per-file", type=int, default=20, help="每个音频合并多少章")
    ap.add_argument("--start", type=int, default=1, help="起始章号（1-based）")
    ap.add_argument("--end", type=int, default=None, help="结束章号（含）")
    ap.add_argument("--lang", choices=["zh", "en"])
    ap.add_argument("--ref", default=REF_7S)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--vram-load-min-mib", type=int, default=6000,
                    help="minimum free GPU memory before loading the model (MiB)")
    ap.add_argument("--vram-run-min-mib", type=int, default=768,
                    help="minimum free GPU memory before inference (MiB)")
    ap.add_argument("--chapter-pause", type=float, default=1.0, help="章间静音秒数")
    ap.add_argument("--unit-chars", type=int, help="单次推理的朗读单元上限（字）")
    ap.add_argument("--interval-silence", type=int, default=350, help="句间静音毫秒（IndexTTS 参数）")
    ap.add_argument("--format", default="wav", choices=["wav", "flac"])
    ap.add_argument("--duration-factor", type=float, default=1.0,
                    help="语速：>1 更慢，<1 更快（有效范围 0.5–2.0）")
    ap.add_argument("--smooth", action="store_true", help="apply mild declick and treble reduction")
    ap.add_argument("--checkpoint-dir", help="directory for resumable chapter audio")
    ap.add_argument("--keep-checkpoints", action="store_true", help="retain chapter checkpoints after output")
    ap.add_argument("--adopt-existing", action="store_true",
                    help="keep an existing output whose manifest checksum still matches")
    ap.add_argument("--show-namespace", action="store_true",
                    help="print the checkpoint namespace digest and exit")
    args = ap.parse_args()
    if args.vram_load_min_mib < 0 or args.vram_run_min_mib < 0:
        ap.error("VRAM thresholds must not be negative")

    book_dir = os.path.abspath(args.book)
    spec, chapters = load_book(book_dir)
    args.lang = args.lang or spec["lang"]
    args.unit_chars = args.unit_chars or spec["unit_chars"]
    args.out_dir = args.out_dir or os.path.join(REPO, "audiobook", spec["slug"])
    end = args.end or len(chapters)
    sel = chapters[args.start - 1:end]
    print(f"book={spec['slug']} chapters={len(chapters)} selected={len(sel)} "
          f"chars={sum(len(c.text) for c in sel)}")

    ckpt = os.path.join(REPO, "index-tts/checkpoints")
    namespace = _checkpoint_namespace(args, ckpt, book_dir, spec)
    if args.show_namespace:
        print(namespace)
        return

    os.makedirs(args.out_dir, exist_ok=True)
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
    checkpoint_dir = os.path.join(checkpoint_root, namespace)
    os.makedirs(checkpoint_dir, exist_ok=True)
    print(f"chapter checkpoints: {checkpoint_dir}")

    import numpy as np
    import soundfile as sf
    import torch
    sys.path.insert(0, os.path.join(REPO, "index-tts"))
    from indextts.infer_v2_5 import IndexTTS2

    is_cuda = args.device.startswith("cuda")
    if is_cuda:
        _wait_for_vram(torch.cuda, args.device, args.vram_load_min_mib)

    t0 = time.time()
    tts = IndexTTS2(cfg_path=os.path.join(ckpt, "config.yaml"), model_dir=ckpt,
                    use_bf16=(args.device != "cpu"), use_cuda_kernel=False, device=args.device)
    # Conservative inference limits peak VRAM even if it adds segment boundaries.
    tts.low_vram = is_cuda
    reference_offloaded = False
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
        out_name = (f"ch{first_no:04d}.{args.format}" if first_no == last_no
                    else f"ch{first_no:04d}-{last_no:04d}.{args.format}")
        out_path = os.path.join(args.out_dir, out_name)
        output_signature = hashlib.sha256(json.dumps(
            [namespace, first_no, last_no, args.format, args.chapter_pause, args.smooth, filter_hash]
        ).encode()).hexdigest()
        if os.path.exists(out_path):
            if not _verified_file(out_path, output_signature):
                if not (args.adopt_existing and _manifest_matches(out_path)):
                    sys.exit(f"existing output is damaged or uses different settings: {out_path}; "
                             "choose another output directory rather than overwriting it")
                _write_manifest(out_path + ".manifest.json", output_signature, out_path)
                print(f"adopted {out_name} (sha256 verified)")
            if _verified_file(out_path, output_signature):
                print(f"skip verified {out_name}")
                continue

        pieces = []
        group_checkpoints = []
        for k, chapter in enumerate(group):
            ch_no = first_no + k
            text = chapter.text
            if chapter.missing:
                print(f"  ch{ch_no:04d} SKIP (no readable body: {len(text)} chars)")
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
            seg = spec["segmentation"]
            part_pause = seg.get("part_pause", 0.0)
            seg_kwargs = {k: v for k, v in seg.items() if k != "part_pause"}
            parts = chapter.parts or [text]
            audio_parts = []
            total_units = 0
            for pi, part in enumerate(parts):
                units = split_for_reading(part, max_chars=args.unit_chars, **seg_kwargs)
                total_units += len(units)
                for ci, (chunk, pause) in enumerate(units):
                    seg_path = os.path.join(tmp, f"{ch_no:04d}_{pi:02d}_{ci:03d}.wav")
                    t1 = time.time()
                    if is_cuda:
                        _wait_for_vram(torch.cuda, args.device, args.vram_run_min_mib)
                    tts.infer(spk_audio_prompt=args.ref, text=chunk, lang=lang,
                              output_path=seg_path, interval_silence=args.interval_silence,
                              duration_factor=args.duration_factor, verbose=False)
                    if is_cuda and not reference_offloaded:
                        if tts.cache_spk_cond is None or tts.cache_emo_cond is None:
                            raise RuntimeError("reference embeddings were not cached; cannot offload encoders")
                        tts.semantic_model.to("cpu")
                        tts.campplus_model.to("cpu")
                        torch.cuda.empty_cache()
                        reference_offloaded = True
                        free, _ = torch.cuda.mem_get_info(args.device)
                        print(f"reference encoders offloaded; GPU free {free // (1024 * 1024)} MiB",
                              flush=True)
                    a, sr = sf.read(seg_path, dtype="float32")
                    os.remove(seg_path)
                    audio_parts.append(a)
                    if pause > 0:
                        audio_parts.append(np.zeros(int(sr * pause), dtype=a.dtype))
                    spent_wall += time.time() - t1
                    spent_audio += len(a) / sr
                    if ci and ci % 20 == 0:
                        print(f"  ch{ch_no:04d} part {pi + 1}/{len(parts)} "
                              f"{ci}/{len(units)} ({ci / len(units):.0%})")
                if part_pause > 0 and pi != len(parts) - 1 and units:
                    audio_parts.append(np.zeros(int(sr * part_pause),
                                                dtype=audio_parts[-1].dtype))
            ch_audio = np.concatenate(audio_parts)
            chapter_tmp = chapter_file + ".tmp.flac"
            sf.write(chapter_tmp, ch_audio, sr, subtype="PCM_16")
            _write_manifest(chapter_file + ".manifest.json", text_hash, chapter_tmp)
            durable_replace(chapter_tmp, chapter_file)
            group_checkpoints.append(chapter_file)
            print(f"  ch{ch_no:04d} CHECKPOINT saved")
            pieces.append(ch_audio)
            print(f"  ch{ch_no:04d} {len(ch_audio) / sr:6.1f}s units={total_units} "
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
