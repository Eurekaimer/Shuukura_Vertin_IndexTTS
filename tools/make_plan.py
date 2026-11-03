"""导出全书朗读计划：正文 + 断句单元，供检查与后续推理复用。

用法：
    index-tts/.venv/bin/python tools/make_plan.py \
        --book books/shuukura-zh --out-dir audiobook/shuukura-zh/plans

只读：不改书籍来源、不改生成代码。plan.json 记录每个单元的文字与停顿；
plan.txt 每行 `章号 [单元号] 文本`，方便逐章核对。
"""

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from books import load_book  # noqa: E402
from segmentation import split_for_reading  # noqa: E402


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--out-dir", help="默认 audiobook/<slug>/plans")
    ap.add_argument("--unit-chars", type=int)
    args = ap.parse_args()

    book_dir = os.path.abspath(args.book)
    spec, chapters = load_book(book_dir)
    args.unit_chars = args.unit_chars or spec["unit_chars"]
    out_dir = args.out_dir or os.path.join(REPO, "audiobook", spec["slug"], "plans")
    os.makedirs(out_dir, exist_ok=True)

    endings = spec["segmentation"]["sent_end"] + spec["segmentation"]["clause_end"] + "”』」）)"
    plan = {
        "source": {
            "book": spec["slug"],
            "book_json_sha256": _file_hash(os.path.join(book_dir, "book.json")),
            "text_prep_sha256": _file_hash(os.path.join(HERE, "text_prep.py")),
            "segmentation_sha256": _file_hash(os.path.join(HERE, "segmentation.py")),
            "unit_chars": args.unit_chars,
        },
        "chapters": [],
    }
    lines = []
    total_units = total_chars = hard_cuts = 0
    for chapter in chapters:
        if chapter.missing:
            plan["chapters"].append({"no": chapter.no, "skipped": "no readable body",
                                     "chars": len(chapter.text)})
            lines.append(f"{chapter.no:04d} [skipped] 无正文（占位/密码页），不推理")
            continue
        seg = {k: v for k, v in spec["segmentation"].items() if k != "part_pause"}
        units = split_for_reading(chapter.text, max_chars=args.unit_chars, **seg)
        entries = []
        for index, (unit, pause) in enumerate(units):
            cut = not unit.endswith(tuple(endings))
            hard_cuts += cut
            total_units += 1
            entries.append({"i": index, "text": unit, "pause": pause, "cut": cut})
            lines.append(f"{chapter.no:04d} [{index:03d}] {unit}")
        total_chars += len(chapter.text)
        plan["chapters"].append({
            "no": chapter.no, "title": chapter.title, "chars": len(chapter.text),
            "units": entries,
        })

    with open(os.path.join(out_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "plan.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    readable = sum(1 for c in plan["chapters"] if "units" in c)
    print(f"chapters={len(chapters)} readable={readable} chars={total_chars} "
          f"units={total_units} avg_unit_chars={total_chars / max(total_units, 1):.1f} "
          f"hard_cuts={hard_cuts}")
    print(f"written {os.path.join(out_dir, 'plan.json')} and plan.txt")


if __name__ == "__main__":
    main()
