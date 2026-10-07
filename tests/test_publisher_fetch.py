"""Exercise robots and material status separately at the actual HTTP seam."""
import unittest
from unittest.mock import Mock, patch

from backend.publisher_fetch import Publisher


class RobotsStatus(unittest.TestCase):
    def fetch(self, robots_status, image_status=200, robots_body=b''):
        responses=[]
        for status, body, mime in ((robots_status, robots_body, 'text/plain'),
                                   (image_status, b'image-bytes', 'image/jpeg')):
            response=Mock(status=status)
            response.getheader.side_effect=lambda name, default=None, mime=mime: {'Content-Type':mime}.get(name,default)
            response.read.side_effect=[body,b'']
            responses.append(response)
        connection=Mock()
        connection.getresponse.side_effect=responses
        with patch('backend.publisher_fetch.public_addresses',return_value=['8.8.8.8']), \
             patch('backend.publisher_fetch.PinnedHTTPS',return_value=connection), \
             patch('backend.publisher_fetch.time.sleep'):
            return Publisher('nasa').get('https://images-assets.nasa.gov/image/id/id~large.jpg',image=True)

    def test_unavailable_robots_does_not_reject_public_image(self):
        for status in (403,404,410):
            with self.subTest(status=status):
                self.assertEqual(self.fetch(status),(b'image-bytes','image/jpeg'))

    def test_actual_image_403_still_fails(self):
        with self.assertRaisesRegex(ValueError,'Publisher HTTP 403'):
            self.fetch(403,403)

    def test_robots_overload_or_server_failure_still_stops(self):
        for status in (429,500,503):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError,f'Publisher HTTP {status}'):
                self.fetch(status)

    def test_explicit_disallow_still_stops(self):
        with self.assertRaisesRegex(ValueError,'robots.txt disallows'):
            self.fetch(200,robots_body=b'User-agent: *\nDisallow: /image/\n')


if __name__=='__main__':unittest.main()
