"""Article scope rules, independent of a publisher's text/image permissions."""
import re
import unicodedata
from urllib.parse import unquote, urlsplit


def excluded(source_id, title, url):
    if source_id != 'nasa':
        return False
    title = unicodedata.normalize('NFKC', str(title or '')).strip().casefold()
    if re.match(r'^(?:apod\b|astronomy\s+picture\s+of\s+the\s+day\b)', title):
        return True
    try:
        parsed = urlsplit(str(url or ''))
        host = (parsed.hostname or '').lower().rstrip('.')
        if host != 'nasa.gov' and not host.endswith('.nasa.gov'):
            return False
        return (host == 'apod.nasa.gov' or host.endswith('.apod.nasa.gov')
                or bool(re.search(r'(?:^|/)apod(?:/|-|$)', unquote(parsed.path).casefold())))
    except ValueError:
        return False


def excluded_item(item):
    item = dict(item)
    return excluded(item.get('source_id'), item.get('title'), item.get('original_url'))
