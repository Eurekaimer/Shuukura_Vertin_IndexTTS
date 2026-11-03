import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def make_epub(path):
    body = "今天天气很好，我们走过街边的公园，呼吸新鲜的空气。" * 6
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("chapter.xhtml", f"<html><body><p>{body}</p></body></html>")


class ReadingPlanTest(unittest.TestCase):
    def test_plan_splits_every_chapter_without_losing_text(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            epub = directory / "book.epub"
            make_epub(epub)
            subprocess.run(
                [sys.executable, str(ROOT / "example" / "make_plan.py"),
                 "--epub", str(epub), "--out-dir", str(directory / "plans"),
                 "--unit-chars", "40"],
                check=True, capture_output=True,
            )
            plan = json.loads((directory / "plans" / "plan.json").read_text(encoding="utf-8"))
            chapter = plan["chapters"][0]
            units = [unit["text"] for unit in chapter["units"]]
            self.assertEqual(chapter["no"], 1)
            self.assertGreater(len(units), 2)
            self.assertTrue(all(len(unit) <= 40 for unit in units))
            self.assertEqual("".join(units).count("今天天气很好"), 6)
            self.assertTrue(all(isinstance(unit["pause"], float) for unit in chapter["units"]))
            first_line = (directory / "plans" / "plan.txt").read_text(encoding="utf-8").splitlines()[0]
            self.assertTrue(first_line.startswith("0001 [000] "), first_line)


if __name__ == "__main__":
    unittest.main()
