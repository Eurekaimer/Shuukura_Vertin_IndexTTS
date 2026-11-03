"""导出全书朗读计划：清洗后正文 + 断句单元，供检查与后续推理复用。

用法：
    index-tts/.venv/bin/python example/make_plan.py \
        --epub "buying-a-classmate-once-a-week/*.epub" --out-dir audiobook/plans

只读：不改 EPUB、不改生成代码。plan.json 记录每个单元的文字与停顿；
plan.txt 每行 `章号 [单元号] 文本`，方便逐章核对。
"""

import argparse
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from segmentation import CLAUSE_END, SENT_END, split_for_reading  # noqa: E402
from text_prep import clean_chapter  # noqa: E402
from tts_book import load_chapters  # noqa: E402

ENDINGS = SENT_END + CLAUSE_END + "”』」）)"


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epub", required=True)
    ap.add_argument("--out-dir", default=os.path.join(REPO, "audiobook", "plans"))
    ap.add_argument("--unit-chars", type=int, default=70)
    args = ap.parse_args()

    paths = glob.glob(args.epub)
    if len(paths) != 1:
        sys.exit(f"expected exactly one EPUB for {args.epub}, found {len(paths)}")
    chapters = load_chapters(paths[0])
    os.makedirs(args.out_dir, exist_ok=True)

    plan = {
        "source": {
            "epub": os.path.basename(paths[0]),
            "epub_sha256": _file_hash(paths[0]),
            "text_prep_sha256": _file_hash(os.path.join(HERE, "text_prep.py")),
            "segmentation_sha256": _file_hash(os.path.join(HERE, "segmentation.py")),
            "unit_chars": args.unit_chars,
        },
        "chapters": [],
    }
    lines = []
    total_units = total_chars = hard_cuts = 0
    for number, (_, raw) in enumerate(chapters, 1):
        text, stats = clean_chapter(raw, number)
        if stats["missing"]:
            plan["chapters"].append({"no": number, "skipped": "no readable body",
                                     "chars": stats["chars"]})
            lines.append(f"{number:04d} [skipped] 无正文（占位/密码页），不推理")
            continue
        units = split_for_reading(text, max_chars=args.unit_chars)
        entries = []
        for index, (unit, pause) in enumerate(units):
            cut = not unit.endswith(tuple(ENDINGS))
            hard_cuts += cut
            total_units += 1
            entries.append({"i": index, "text": unit, "pause": pause, "cut": cut})
            lines.append(f"{number:04d} [{index:03d}] {unit}")
        total_chars += len(text)
        plan["chapters"].append({
            "no": number, "title": stats["title"], "chars": len(text),
            "units": entries,
        })

    with open(os.path.join(args.out_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out_dir, "plan.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    readable = sum(1 for c in plan["chapters"] if "units" in c)
    print(f"chapters={len(chapters)} readable={readable} chars={total_chars} "
          f"units={total_units} avg_unit_chars={total_chars / max(total_units, 1):.1f} "
          f"hard_cuts={hard_cuts}")
    print(f"written {os.path.join(args.out_dir, 'plan.json')} and plan.txt")


if __name__ == "__main__":
    main()
