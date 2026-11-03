import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "example"))
from segmentation import split_for_reading


class ReadingSegmentationTest(unittest.TestCase):
    def test_long_dialogue_splits_at_punctuation_without_losing_text(self):
        text = "“" + "她静静地看着窗外，雨水打在玻璃上。" * 6 + "我不禁想起那天。”"
        units = [part for part, _ in split_for_reading(text, max_chars=70)]
        self.assertEqual("".join(units), text)
        self.assertGreater(len(units), 1)
        self.assertTrue(all(not unit.startswith(("。", "，")) for unit in units[1:]))
        self.assertTrue(all(unit.endswith(("。", "，", "”")) for unit in units))
        self.assertTrue(any("我不禁" in unit for unit in units))


if __name__ == "__main__":
    unittest.main()
