"""Fixed publisher scopes, public DNS pinned before connect, bounded responses.

No proxy, credentials, browser impersonation or visitor-supplied fetch endpoint.
"""
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser

HOSTS = {'nasa': {'www.nasa.gov', 'science.nasa.gov'},
         'cnsa': {'www.cnsa.gov.cn', 'cnsa.gov.cn'},
         'cmse': {'www.cmse.gov.cn', 'cmse.gov.cn'}}


def checked_url(source, url, *, image=False, robots=False):
    parsed = urlsplit(url)
    if parsed.hostname not in HOSTS.get(source, set()) or parsed.scheme not in {'https', 'http'}:
        raise ValueError('Unreviewed publisher host')
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443} or any(ord(c) < 32 for c in url):
        raise ValueError('Invalid publisher URL')
    if len(url) > 2048 or '\\' in url or '%' in parsed.path or '..' in parsed.path:
        raise ValueError('Unreviewed publisher path')
    if source == 'nasa' and not robots:
        prefixes = ('/wp-content/uploads/', '/system/resources/', '/content/dam/') if image else ('/news-release/', '/image-article/', '/missions/', '/centers-and-facilities/', '/blog/', '/science-research/')
        if not parsed.path.startswith(prefixes):
            raise ValueError('Unreviewed NASA path')
    return parsed


def public_addresses(host, port):
    addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError('Publisher resolved to non-public address')
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, port):
        super().__init__(host, port=port, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, address, port):
        super().__init__(host, port=port, timeout=15)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class Publisher:
    def __init__(self, source):
        self.source, self.robots, self.requests = source, {}, 0
        self.deadline = time.monotonic()+120

    def get(self, url, *, image=False, robots=False, limit=2*1024*1024):
        for _ in range(4):
            parsed = checked_url(self.source, url, image=image, robots=robots)
            if not robots and parsed.netloc not in self.robots:
                rp = RobotFileParser()
                raw, _ = self.get(f'{parsed.scheme}://{parsed.netloc}/robots.txt', robots=True)
                rp.parse(raw.decode('utf-8', errors='replace').splitlines())
                self.robots[parsed.netloc] = rp
            if not robots and not self.robots[parsed.netloc].can_fetch('SpaceNewsReview', url):
                raise ValueError('robots.txt disallows this material')
            if self.requests >= 12 or time.monotonic() > self.deadline:
                raise ValueError('Publisher request budget reached')
            address = public_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))[0]
            if self.requests:
                time.sleep(1)
            conn = (PinnedHTTPS if parsed.scheme == 'https' else PinnedHTTP)(parsed.hostname, address, parsed.port or (443 if parsed.scheme == 'https' else 80))
            self.requests += 1
            try:
                conn.request('GET', parsed.path + ('?'+parsed.query if parsed.query else ''), headers={'User-Agent': 'SpaceNewsReview/1.0', 'Accept-Encoding': 'identity'})
                response = conn.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.getheader('Location', ''))
                    continue
                if response.status == 404 and robots:
                    return b'', 'text/plain'
                if response.status != 200:
                    raise ValueError(f'Publisher HTTP {response.status}; no bypass attempted')
                if response.getheader('Content-Encoding', 'identity') != 'identity':
                    raise ValueError('Unexpected compression')
                data = bytearray()
                while True:
                    chunk = response.read(64*1024)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > limit or time.monotonic() > self.deadline:
                        raise ValueError('Publisher response budget reached')
                if robots and bytes(data).lstrip().startswith(b'<'):
                    raise ValueError('robots.txt returned HTML; review required')
                return bytes(data), response.getheader('Content-Type', '').split(';')[0].lower()
            finally:
                conn.close()
        raise ValueError('Too many publisher redirects')
