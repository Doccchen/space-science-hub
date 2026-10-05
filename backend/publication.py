"""Explicit publication metadata. No event dates, location-to-timezone guessing."""
import re
from datetime import datetime, timezone


def publication_fields(raw, *, date_order='dmy', origin='detail'):
    value = str(raw or '').strip()
    result = dict(published_at=None, date_status='missing', published_raw=value or None,
                  published_precision='missing', published_origin=origin if value else 'missing',
                  published_calendar_date=None, published_timezone=None, published_time_status='missing')
    if not value:
        return result
    parsed = None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?', value):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            pass
        if parsed:
            aware = parsed.tzinfo is not None
            result.update(published_at=(parsed if aware else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec='seconds'),
                          date_status='provided', published_precision='second' if re.search(r'[T ]\d{2}:\d{2}:\d{2}', value) else 'minute',
                          published_calendar_date=parsed.date().isoformat(),
                          published_timezone=parsed.strftime('%z') if aware else None,
                          published_time_status='provided' if aware else 'timezone_missing')
            return result
    # Source-specific month/day ordering is part of the inspected adapter.
    formats = ['%Y-%m-%d', '%Y/%m/%d', '%Y年%m月%d日', '%B %d, %Y', '%b %d, %Y', '%B %d %Y', '%b %d %Y']
    formats += ['%m.%d.%Y', '%m/%d/%Y'] if date_order == 'mdy' else ['%d.%m.%Y', '%d/%m/%Y']
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    if parsed:
        # UTC midnight is a sorting convention only; the public calendar date
        # is authoritative. Never render this convention as a precise instant.
        result.update(published_at=parsed.replace(tzinfo=timezone.utc).isoformat(timespec='seconds'),
                      date_status='provided', published_precision='day',
                      published_calendar_date=parsed.date().isoformat(), published_time_status='date_only')
    else:
        result['date_status'] = 'invalid'
    return result
