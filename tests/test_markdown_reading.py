"""Markdown editions must share the existing permission and version boundaries."""
import unittest

from backend import reading
import test_reading


edition = test_reading.edition


class MarkdownReadingTests(unittest.TestCase):
    setUp = test_reading.ReadingTests.setUp
    tearDown = test_reading.ReadingTests.tearDown
    content = test_reading.ReadingTests.content
    def test_markdown_round_trip_withdrawal_and_republish(self):
        document = edition()
        document['blocks'] = [{'type': 'markdown', 'text': '## Flight\n\n**Pending**, not completed.\n\n![test](https://example.com/test.png)'}]
        first = reading.publish(document)
        content = self.content()
        self.assertEqual(content['read_scope'], 'full_text')
        self.assertEqual(content['blocks'][0]['type'], 'markdown')
        self.assertEqual(content['blocks'][0]['block_id'], 'b001')
        self.assertEqual(content['blocks'][0]['text'], document['blocks'][0]['text'])
        self.assertEqual(content['assets'], [])
        reading.withdraw(1, 'test', 'withdraw Markdown')
        self.assertEqual(self.content()['blocks'], [])
        self.assertNotEqual(content['content_version'], self.content()['content_version'])
        reading.publish(document, republish=True)
        self.assertEqual(self.content()['blocks'], content['blocks'])
        self.assertTrue(first['version'])

    def test_markdown_pending_permission_does_not_expose_text(self):
        document = edition()
        document['blocks'] = [{'type': 'markdown', 'text': '# Private until permitted'}]
        document['permissions']['text'] = {'status': 'pending'}
        reading.publish(document)
        self.assertEqual(self.content()['blocks'], [])

    def test_markdown_validation_keeps_limits_and_rejects_embedded_metadata(self):
        for block in ({'type': 'markdown', 'text': ''},
                      {'type': 'markdown', 'text': 'x' * 12001},
                      {'type': 'markdown', 'text': 'text', 'allow_html': True}):
            document = edition(); document['blocks'] = [block]
            with self.assertRaises(ValueError):
                reading.validate(document)


if __name__ == '__main__':
    unittest.main()
