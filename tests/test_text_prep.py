import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from text_prep import clean_chapter


class CleanChapterTest(unittest.TestCase):
    def test_narrative_dash_becomes_pause_in_title_and_body(self):
        sentence = "我想说的话——终于可以告诉她了，虽然我仍然有些担心。"
        text, stats = clean_chapter("Episode 1 标题——开头\n" + sentence * 5, 1)
        self.assertFalse(stats["missing"])
        self.assertIn("标题，开头", text)
        self.assertEqual(text.count("我想说的话，终于可以告诉她了"), 5)
        self.assertNotIn("—", text)

    def test_jpg_aside_removed_but_narrative_kept(self):
        raw = (
            "episode 21\nepisode 21\nepisode 21\n"
            "她停下脚步。（译者：她急了.jpg）然后她继续往前走。"
        )
        text, _ = clean_chapter(raw, 21)
        self.assertIn("她停下脚步。", text)
        self.assertIn("然后她继续往前走。", text)
        self.assertNotIn("jpg", text.lower())
        self.assertNotIn("译者", text)

    def test_nested_translator_notes_fully_removed(self):
        raw = (
            "episode 79\nepisode 79\nepisode 79\n"
            "「做啊。还有干贝片冷盘。」"
            "(译注：カルパッチョ（Carpaccio）：一种意大利菜，把肉类制成薄片后的冷盘。)\n"
            "「问我去那儿干什么。」（译注：（神轿）御神輿，差不多就是祭典上的花车吧。）我重复了一遍。\n"
            "然而，“成人礼”这个活动，又和成人日（注：日本的节日，每年一月的第二个星期一）"
            "这样的节日联系在一起。\n"
            "我看着她。（译者吐槽：这一串操作确实很有工口魔神风范）\n"
            "明天见。（译：幻想时间）"
        )
        text, _ = clean_chapter(raw, 79)
        for kept in (
            "「做啊。还有干贝片冷盘。」",
            "「问我去那儿干什么。」",
            "我重复了一遍。",
            "“成人礼”这个活动",
            "这样的节日联系在一起。",
            "我看着她。",
            "明天见。",
        ):
            self.assertIn(kept, text)
        for gone in (
            "カルパッチョ",
            "Carpaccio",
            "御神輿",
            "日本的节日",
            "工口魔神",
            "幻想时间",
            "译注",
            "译者",
            "（注",
            "(译",
        ):
            self.assertNotIn(gone, text)

    def test_line_leading_parenthetical_note_keeps_trailing_narrative(self):
        raw = (
            "episode 136\nepisode 136\nepisode 136\n"
            "（译注：日本国中相当于我们的初中）她坐在桌子对面盯着试题集。"
        )
        text, _ = clean_chapter(raw, 136)
        self.assertIn("她坐在桌子对面盯着试题集。", text)
        self.assertNotIn("日本国中", text)
        self.assertNotIn("译注", text)

    def test_unmarked_meta_parenthetical_removed_conservatively(self):
        raw = (
            "episode 14\nepisode 14\nepisode 14\n"
            "“和宇都宫？”（就是前文提到的宫城的朋友，宇都宫舞香）我说出了这个名字。\n"
            "（前文的伏笔在这里。）"
        )
        text, _ = clean_chapter(raw, 14)
        self.assertIn("“和宇都宫？”", text)
        self.assertIn("我说出了这个名字。", text)
        self.assertNotIn("宇都宫舞香", text)
        self.assertNotIn("前文提到", text)
        # 没有“提到/说过”等元叙述标记的括注仍按剧情保留
        self.assertIn("（前文的伏笔在这里。）", text)

    def test_standalone_star_translator_note_dropped(self):
        raw = (
            "episode 80\nepisode 80\nepisode 80\n"
            "第一句正文。\n"
            "※译者注：简单提一下，日本传统文化里非常讲究「义理」。\n"
            "第二句正文。"
        )
        text, _ = clean_chapter(raw, 80)
        self.assertIn("第一句正文。", text)
        self.assertIn("第二句正文。", text)
        self.assertNotIn("※", text)
        self.assertNotIn("简单提一下", text)

    def test_uploader_note_between_repeated_markers_removed(self):
        body = "不怎么说话的宫城并不稀奇。" * 40
        raw = (
            "episode 26\nepisode 26\n"
            "本来今天不准备再更了的。\n"
            "结果刷推看到羽田老师在身体抱恙的情况下，更新了178章。\n"
            "从昏迷中醒来之后决定学习羽田老师的敬业精神再小翻一章。\n"
            "------------------------------------------------------------------------------\n"
            "episode 26\n"
            + body
        )
        text, _ = clean_chapter(raw, 26)
        self.assertNotIn("羽田老师", text)
        self.assertNotIn("昏迷", text)
        self.assertIn("不怎么说话的宫城并不稀奇。", text)
        self.assertTrue(text.startswith("第26话。"))

    def test_unmarked_real_title_between_markers_preserved(self):
        raw = (
            "Episode 1\nEpisode 1\n"
            "仙台同学的价格正好五千元\n"
            "Episode 1\n"
            "其实并没有非仙台同学不可的理由。"
        )
        text, _ = clean_chapter(raw, 1)
        self.assertTrue(text.startswith("第1话。仙台同学的价格正好五千元。"))
        self.assertEqual(text.count("仙台同学的价格正好五千元"), 1)
        self.assertIn("其实并没有非仙台同学不可的理由。", text)

    def test_markdown_episode_heading_normalized(self):
        raw = (
            "### episode 315 在我身边的仙台同学\n"
            "### episode 315 在我身边的仙台同学\n"
            "### episode 315 在我身边的仙台同学\n"
            "好的事情和坏的事情并没有明确的分界线。"
        )
        text, _ = clean_chapter(raw, 315)
        self.assertTrue(text.startswith("第315话。在我身边的仙台同学。"))
        self.assertEqual(text.count("在我身边的仙台同学"), 1)
        self.assertNotIn("###", text)
        self.assertNotIn("episode", text.lower())

    def test_pisode_heading_typo_normalized(self):
        raw = (
            "episode 84 宫城不会说的话\n"
            "episode 84 宫城不会说的话\n"
            "pisode 84 宫城不会说的话\n"
            "宫城来探望我了。"
        )
        text, _ = clean_chapter(raw, 84)
        self.assertTrue(text.startswith("第84话。宫城不会说的话。"))
        self.assertEqual(text.count("宫城不会说的话"), 1)
        self.assertNotIn("pisode", text.lower())
        self.assertIn("宫城来探望我了。", text)

    def test_variant_repeated_headings_not_narrated(self):
        raw = (
            "episode 208 宫城\n"
            "episode 208 宫城\n"
            "episode 208 宫城的痕迹\n"
            "我脱掉衣服。"
        )
        text, _ = clean_chapter(raw, 208)
        self.assertTrue(text.startswith("第208话。宫城的痕迹。"))
        self.assertEqual(text.count("宫城的痕迹"), 1)
        self.assertIn("我脱掉衣服。", text)

        raw = (
            "episode 399 昨天的仙台同学和今天的仙台同学\n"
            "episode 399 昨天的仙台同学和今天的仙台同学\n"
            "昨天的仙台同学与今天的仙台同学\n"
            "吃早饭吧。"
        )
        text, _ = clean_chapter(raw, 399)
        self.assertTrue(text.startswith("第399话。昨天的仙台同学和今天的仙台同学。"))
        self.assertNotIn("与今天", text)
        self.assertIn("吃早饭吧。", text)

    def test_single_period_after_closing_quote_kept(self):
        raw = "episode 2\nepisode 2\nepisode 2\n她故意重复了两遍“好”。然后她笑了。"
        text, _ = clean_chapter(raw, 2)
        self.assertIn("“好”。然后", text)
        self.assertNotIn("“好”然后", text)

    def test_only_duplicate_period_after_closing_quote_collapsed(self):
        raw = "他说：“好。”。然后走了。" * 3
        text, _ = clean_chapter(raw, 2)
        self.assertIn("“好。”然后走了。", text)
        self.assertNotIn("。”。", text)

    def test_short_body_still_marks_missing(self):
        raw = "episode 142\nepisode 142\nepisode 142\n正文太短。"
        _, stats = clean_chapter(raw, 142)
        self.assertTrue(stats["missing"])


if __name__ == "__main__":
    unittest.main()
