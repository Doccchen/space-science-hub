import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class Settings:
    data: Path = field(default_factory=lambda: Path(os.getenv('READER_DATA_DIR', 'data/temporary-reader')).resolve())
    session_seconds: int = field(default_factory=lambda: int(os.getenv('READER_SESSION_HOURS','24'))*3600)
    ip_calls: int = field(default_factory=lambda: int(os.getenv('READER_IP_DAILY_CALLS','40')))
    public_origin: str = field(default_factory=lambda: os.getenv('READER_PUBLIC_ORIGIN','').rstrip('/'))
    trusted_proxies: str = field(default_factory=lambda: os.getenv('READER_TRUSTED_PROXIES','127.0.0.1,::1'))
    site_storage_bytes: int = field(default_factory=lambda: int(os.getenv('READER_SITE_STORAGE_MB','500'))*1024*1024)
    max_bytes: int = field(default_factory=lambda: int(os.getenv('READER_MAX_UPLOAD_MB', '20')) * 1024 * 1024)
    max_pages: int = field(default_factory=lambda: int(os.getenv('READER_MAX_PAGES', '200')))
    owner_bytes: int = field(default_factory=lambda: int(os.getenv('READER_OWNER_STORAGE_MB', '100')) * 1024 * 1024)
    parse_timeout: int = field(default_factory=lambda: int(os.getenv('READER_PARSE_TIMEOUT', '60')))
    daily_calls: int = field(default_factory=lambda: int(os.getenv('READER_DAILY_CALLS', '20')))
    site_calls: int = field(default_factory=lambda: int(os.getenv('READER_SITE_DAILY_CALLS', '100')))
    site_tokens: int = field(default_factory=lambda: int(os.getenv('READER_SITE_DAILY_TOKENS', '200000')))
    access_code: str = field(default_factory=lambda: os.getenv('READER_ACCESS_CODE', ''))
    secure_cookie: bool = field(default_factory=lambda: os.getenv('READER_COOKIE_SECURE', '0') == '1')
    model_url: str = field(default_factory=lambda: os.getenv('READER_MODEL_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'))
    model_key: str = field(default_factory=lambda: os.getenv('READER_MODEL_KEY', ''))
    model: str = field(default_factory=lambda: os.getenv('READER_MODEL', 'qwen-plus'))
    wanfang_key: str = field(default_factory=lambda: os.getenv('READER_WANFANG_API_KEY', ''))
    verify_answers: bool = field(default_factory=lambda: os.getenv('READER_VERIFY_ANSWERS','1')=='1')
    legacy_url: str = field(default_factory=lambda: os.getenv('READER_LEGACY_URL', 'http://127.0.0.1:8080'))

    def __post_init__(self):
        if not (1 <= self.max_pages <= 500 and 1 <= self.parse_timeout <= 180):
            raise ValueError('Invalid parser limits')
        if min(self.max_bytes, self.owner_bytes, self.daily_calls, self.site_calls, self.site_tokens) < 1:
            raise ValueError('Storage and usage limits must be positive')
        if self.session_seconds<1 or self.ip_calls<1 or self.site_storage_bytes<1:
            raise ValueError('Temporary limits must be positive')
        if self.public_origin:
            origin=urlsplit(self.public_origin)
            if origin.scheme not in ('http','https') or not origin.netloc or origin.path or origin.query or origin.fragment or origin.username:
                raise ValueError('READER_PUBLIC_ORIGIN must be an exact scheme and host, including port')
        if self.model_key and not self.model_url.startswith('https://'):
            raise ValueError('External model endpoint must use HTTPS')
