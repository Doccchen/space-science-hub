"""Publisher links survive capture and edition validation without source HTML."""
import copy
import json
import unittest

from backend import reading, review_capture
from test_reading import edition


class NewsLinkTests(unittest.TestCase):
    def capture(self, body):
        html = '<article><div class="entry-content">' + body + '</div></article>'
        document, _ = review_capture.parse('nasa', 'https://www.nasa.gov/news-release/test/', html.encode(), 'test', strict=True)
        reading.validate(document)
        return document['blocks']

    def test_capture_preserves_labels_offsets_and_relative_destinations(self):
        blocks = self.capture('<p> 🚀 Visit <a href="/marshall?x=1&amp;y=2#about">NASA <b>Marshall</b></a>, then <a href="../more/">more</a>. </p>')
        block = blocks[0]
        self.assertEqual(block['text'], '🚀 Visit NASA Marshall, then more.')
        self.assertEqual([block['text'][link['start']:link['end']] for link in block['links']], ['NASA Marshall', 'more'])
        self.assertEqual([link['url'] for link in block['links']], ['https://www.nasa.gov/marshall?x=1&y=2#about', 'https://www.nasa.gov/news-release/more/'])

    def test_lists_tables_and_repeated_labels_keep_individual_targets(self):
        blocks = self.capture('<ul><li><a href="/a">source</a> <a href="/b">source</a></li></ul><table><tr><td>See <a href="/c">NASA <b>data</b></a></td></tr></table>')
        self.assertEqual([link['url'] for link in blocks[0]['links']], ['https://www.nasa.gov/a', 'https://www.nasa.gov/b'])
        self.assertEqual([link['item'] for link in blocks[0]['links']], [0, 0])
        cell = blocks[1]['rows'][0][0]
        link = blocks[1]['links'][0]
        self.assertEqual(cell[link['start']:link['end']], 'NASA data')
        self.assertEqual((link['row'], link['column']), (0, 0))

    def test_unsafe_anchors_stay_plain_text(self):
        blocks = self.capture('<p><a href="javascript:alert(1)">unsafe</a> <a href="https://user:password@example.com/">credentials</a> <a href="data:text/html,test">data</a></p>')
        self.assertEqual(blocks[0]['text'], 'unsafe credentials data')
        self.assertNotIn('links', blocks[0])

    def test_edition_rejects_invalid_url_ranges_and_indices(self):
        for change in ({'url': 'javascript:alert(1)'}, {'start': -1}, {'end': 10000}, {'start': True}):
            document = edition()
            document['blocks'] = [{'type': 'paragraph', 'text': 'source', 'links': [{'start': 0, 'end': 6, 'url': 'https://example.com/', **change}]}]
            with self.assertRaises(ValueError):
                reading.validate(document)
        document = edition()
        document['blocks'] = [{'type': 'list', 'items': ['source'], 'links': [{'item': 2, 'start': 0, 'end': 6, 'url': 'https://example.com/'}]}]
        with self.assertRaises(ValueError):
            reading.validate(document)

    def test_links_round_trip_and_legacy_blocks_remain_valid(self):
        document = edition()
        reading.validate(document)
        document['blocks'] = self.capture('<h2><a href="/mission">Mission</a></h2><p>Read <a href="/source">source</a>.</p>')
        before = copy.deepcopy(document)
        reading.validate(document)
        self.assertEqual(document, before)
        item = {'id': 1, 'source_id': 'nasa', 'original_url': document['original_url'], 'lang': 'en'}
        stored = {'document': json.dumps(document), 'version': 'test', 'revision': 1, 'withdrawn': 0}
        public = reading.public_content(item, stored)
        self.assertEqual(public['blocks'][1]['links'], document['blocks'][1]['links'])
        stored['withdrawn'] = 1
        self.assertEqual(reading.public_content(item, stored)['blocks'], [])


if __name__ == '__main__':
    unittest.main()
