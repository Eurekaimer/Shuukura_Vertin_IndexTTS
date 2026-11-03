import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from books import load_book  # noqa: E402
from segmentation import split_for_reading  # noqa: E402


class TextBookTest(unittest.TestCase):
    def test_parts_are_polished_and_keep_their_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            book = Path(directory)
            (book / "parts").mkdir()
            (book / "parts" / "0001-p1.txt").write_text(
                "— Hello – world.\n\ndocument.getElementById('x')", encoding="utf-8")
            (book / "parts" / "0002-p2.txt").write_text("Second part.", encoding="utf-8")
            (book / "book.json").write_text(json.dumps({
                "slug": "test-en", "title": "Test", "lang": "en", "clean": "en",
                "source": {"type": "text", "index": "unused"},
                "segmentation": {"sent_end": ".!?;…", "clause_end": ",;:",
                                 "join_lines": " ", "sent_pause": 0.45,
                                 "clause_pause": 0.22, "paragraph_pause": 0.75,
                                 "part_pause": 1.2},
                "unit_chars": 140,
                "chapters": [{
                    "no": 1, "title": "Test", "pov": "Miyagi",
                    "header": "Chapter One. Test.",
                    "parts": [{"part": 1, "url": "", "file": "parts/0001-p1.txt"},
                              {"part": 2, "url": "", "file": "parts/0002-p2.txt"}],
                }],
            }), encoding="utf-8")

            spec, chapters = load_book(book)
            chapter = chapters[0]
            self.assertEqual(chapter.parts[0], "Chapter One. Test.")
            self.assertEqual(len(chapter.parts), 3)
            self.assertEqual(chapter.parts[1], "Hello, world.")
            self.assertNotIn("document", chapter.text)
            self.assertEqual(chapter.text, "\n\n".join(chapter.parts))

            seg = {k: v for k, v in spec["segmentation"].items() if k != "part_pause"}
            units = split_for_reading(chapter.text, max_chars=spec["unit_chars"], **seg)
            self.assertEqual(units, [
                ("Chapter One. Test.", 0.75),
                ("Hello, world.", 0.75),
                ("Second part.", 0.0),
            ])


if __name__ == "__main__":
    unittest.main()
