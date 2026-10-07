"""Regression cases for lossy Wikitext conversion, using preparation-only deps."""
import importlib.util
import unittest

HAS_PARSER = importlib.util.find_spec('wikitextparser') is not None
if HAS_PARSER:
    from tools.prepare_satwiki_bailian import Converter


@unittest.skipUnless(HAS_PARSER, 'Optional tools/requirements-satwiki.txt not installed')
class SatWikiConversionTests(unittest.TestCase):
    def test_nested_tex_braces_and_angle_brackets_are_preserved(self):
        source = r'公式\[\frac{{{a^3}}}{\mu}<1\]与$\Delta v$。'
        converter = Converter()
        result = converter.convert(source)
        self.assertIn(r'\frac{{{a^3}}}{\mu}<1', result)
        self.assertIn(r'$\Delta v$', result)
        self.assertEqual(len(converter.math), 2)

    def test_forward_named_references_keep_same_number(self):
        source = '前句<ref name="a" />，独立<ref>书B</ref>，后句<ref name="a">书A</ref>。'
        result = Converter().convert(source)
        self.assertEqual(result.count('〔参考1〕'), 2)
        self.assertIn('1. 书A', result)
        self.assertIn('2. 书B', result)

    def test_table_field_names_stay_with_each_value(self):
        source = '{|\n! 列 !! 说明\n|-\n| 03-07 || NORAD编号\n|-\n| 09-16 || 轨道倾角/°\n|}'
        result = Converter().convert(source)
        self.assertIn('| 03-07 | NORAD编号 |', result)
        self.assertIn('列：09-16；说明：轨道倾角/°', result)

    def test_notice_and_nested_image_caption_are_retained(self):
        result = Converter().convert('{{需要更新}}[[文件:a.png|thumb|[[紫丁香一号]]立方星]]\n==概述==\n正文')
        self.assertIn('需要更新', result)
        self.assertIn('紫丁香一号立方星', result)
        self.assertIn('## 概述', result)

    def test_unknown_template_and_missing_reference_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported content template'):
            Converter().convert('{{Infobox|mass=100}}')
        with self.assertRaisesRegex(ValueError, 'unresolved reference'):
            Converter().convert('句子<ref name="missing" />')

    def test_nowiki_links_do_not_remain_as_wiki_syntax(self):
        result = Converter().convert('<nowiki>[[真近点角]]</nowiki>')
        self.assertEqual(result, '真近点角')


if __name__ == '__main__':
    unittest.main()
