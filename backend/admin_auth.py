"""Single administrator, hashed passwords, expiring sessions and CSRF protection."""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from . import news
from .locking import operation_lock

COOKIE = 'space_news_admin'
SESSION_SECONDS = 3600


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 200:
        raise ValueError('Use a 12–200 character password')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()
    return salt+':'+digest


def verify(password, encoded):
    if not isinstance(password, str) or len(password) > 200:
        return False
    salt, digest = encoded.split(':')
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()
    return hmac.compare_digest(candidate, digest)


def initialize_user(username, password):
    if not isinstance(username, str) or not 1 <= len(username) <= 64:
        raise ValueError('Invalid username')
    hashed = password_hash(password)
    with operation_lock(news.DB_PATH, timeout=10), news.connect() as conn:
        conn.execute('INSERT INTO admin_user(id,username,password_hash) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password_hash=excluded.password_hash,failed=0,locked_until=0', (username, hashed))
        conn.execute('DELETE FROM admin_sessions')


def origin():
    value = os.environ.get('ADMIN_ORIGIN', 'http://127.0.0.1:18080').rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Invalid ADMIN_ORIGIN')
    if parsed.scheme == 'http' and parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('HTTP admin origin must be loopback; use SSH forwarding')
    return value


def check_origin(request):
    if request.headers.get('origin') != origin():
        raise HTTPException(403, 'Invalid origin')


def login(username, password):
    with operation_lock(news.DB_PATH, timeout=10), news.connect() as conn:
        user = conn.execute('SELECT * FROM admin_user WHERE id=1').fetchone()
        if not user:
            raise HTTPException(503, 'Initialize administrator on server first')
        if user['locked_until'] > time.time():
            raise HTTPException(429, 'Try again after the login lockout expires')
        correct = verify(password, user['password_hash'])
        if not correct or not hmac.compare_digest(str(username).encode(), user['username'].encode()):
            failures = user['failed']+1
            conn.execute('UPDATE admin_user SET failed=?,locked_until=? WHERE id=1',
                         (0 if failures >= 5 else failures, time.time()+600 if failures >= 5 else 0))
            failure = True
        else:
            failure = False
            conn.execute('UPDATE admin_user SET failed=0,locked_until=0 WHERE id=1')
            conn.execute('DELETE FROM admin_sessions')
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            conn.execute('INSERT INTO admin_sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time()+SESSION_SECONDS))
    if failure:
        raise HTTPException(401, 'Invalid credentials')
    return token, csrf


def require(request: Request):
    token = request.cookies.get(COOKIE, '')
    if len(token) > 100:
        raise HTTPException(401, 'Login required')
    with news.connect() as conn:
        session = conn.execute('SELECT * FROM admin_sessions WHERE token_hash=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        user = conn.execute('SELECT username FROM admin_user WHERE id=1').fetchone()
    if not session or not user:
        raise HTTPException(401, 'Login required')
    if request.method not in {'GET', 'HEAD'}:
        check_origin(request)
        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(403, 'Invalid CSRF token')
    return {'username': user['username'], 'csrf': session['csrf']}
