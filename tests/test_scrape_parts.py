import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from scrape_parts import parse_part  # noqa: E402
from scrape_extras import parse_extra_toc  # noqa: E402


class PartScrapingTest(unittest.TestCase):
    def test_navigation_ends_story_before_comments(self):
        for kind in ("Part", "Post"):
            with self.subTest(kind=kind):
                page = (f'<div class="entry-content"><p>The story ends here.</p>'
                        f'<p>&lt; Previous {kind} | Next {kind} &gt;</p>'
                        '<p>Comment that must not be read.</p></div>')
                self.assertEqual(parse_part(page), ["The story ends here."])

    def test_paragraphs_after_entry_content_are_not_story(self):
        page = ('<div class="entry-content"><p>Actual story.</p>'
                '<div><p>Nested paragraph.</p></div></div>'
                '<p>angela</p><p>This is a comment, not the story.</p>')
        self.assertEqual(parse_part(page), ["Actual story.", "Nested paragraph."])

    def test_toc_collects_extra_inside_chapter_paragraph(self):
        page = ('<div class="entry-content"><p><strong>Chapter Fifty-eight – Title</strong>'
                '<br><a href="/part">Part 171</a><br><br>'
                '<strong>Volume Six Extra (Chapter 58.5) – Bonus</strong><br>'
                '<a href="/extra">Extra</a></p></div>')
        extras = parse_extra_toc(page)
        self.assertEqual(len(extras), 1)
        self.assertEqual(extras[0]["after_chapter"], 58)
        self.assertTrue(extras[0]["url"].endswith("/extra"))


if __name__ == "__main__":
    unittest.main()
