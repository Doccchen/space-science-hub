"""Server-only encrypted credentials and bounded MCP preflight scopes. No model calls."""
import argparse
import hashlib
import json
import os
import secrets
import time
import uuid
from pathlib import Path

from backend import ai_config, management_store, news, news_agent, news_context
from backend.news_context_store import Store

CREDENTIALS = Path('/data/news-agent-credentials.json')


def bootstrap():
    cipher = ai_config.cipher()
    if CREDENTIALS.exists():
        encrypted = json.loads(CREDENTIALS.read_text())
        key = cipher.decrypt(encrypted['mcp_key'].encode()).decode()
        if len(key) < 32:
            raise ValueError('Invalid existing service key')
    else:
        encrypted = {'api_key': None, 'mcp_key': cipher.encrypt(secrets.token_urlsafe(48).encode()).decode()}
        # Reuse only the same workspace's protected provider key; never print it.
        if ai_config.tables_exist():
            with management_store.connection() as db:
                state = ai_config.state(db)
                row = ai_config.version(db, state['desired_version'])
                values = ai_config.public(row)
                if values['config']['workspace'] == news_agent.Settings.workspace and row.get('encrypted_key'):
                    cipher.decrypt(row['encrypted_key'].encode())  # Validate the ciphertext before reusing it.
                    encrypted['api_key'] = row['encrypted_key']
        descriptor = os.open(CREDENTIALS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(encrypted, output)
    Store(Path('/data/news-agent.sqlite3'))
    print(json.dumps({'credentials_ready': True, 'api_key_configured': bool(encrypted['api_key']),
                      'mcp_key_configured': True, 'plaintext_keys_written': False, 'model_calls': 0}))


def scope(article_id):
    settings = news_agent.Settings.environment()
    cipher = ai_config.cipher()
    item, _, fingerprint, status = news_context.snapshot(article_id)
    if status != 'pending':
        raise ValueError('Article not permitted for scoped preflight')
    store = Store(Path(os.getenv('NEWS_AGENT_DB_PATH', '/data/news-agent.sqlite3')))
    now, expiry = time.time(), time.time() + 900
    conversation_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    owner = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO news_agent_conversations(id,owner,article_id,fingerprint,config_version,expires) VALUES(?,?,?,?,?,?)',
                   (conversation_id, owner, article_id, fingerprint, settings.version, expiry))
        db.execute('INSERT INTO news_agent_jobs(id,owner,conversation,request_id,question,kind,stage,created) VALUES(?,?,?,?,?,?,?,?)',
                   (job_id, owner, conversation_id, str(uuid.uuid4()), '', 'preflight', 'generating', now))
    token = cipher.encrypt(json.dumps({'job_id': job_id, 'article_id': article_id, 'fingerprint':fingerprint, 'expires':expiry}).encode()).decode()
    destination = Path('/data/news-mcp-preflight.json')
    encrypted = {'job_id':job_id,'article_id':article_id,'expires':expiry,
                 'context':cipher.encrypt(token.encode()).decode()}
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(encrypted, output)
    print(json.dumps({'job_id':job_id,'article_id':article_id,'expires_in_seconds':900,
                      'max_reads':3,'model_calls':0,'scope_file':str(destination)}))


def headers(temporary_file=False):
    # For operator-only TLS requests or console entry. Never use in ordinary public APIs.
    settings = news_agent.Settings.environment()
    cipher = ai_config.cipher()
    preflight = json.loads(Path('/data/news-mcp-preflight.json').read_text())
    if preflight['expires'] <= time.time():
        raise ValueError('Preflight expired')
    value = {'Authorization':'Bearer ' + settings.mcp_key,
             'X-News-Context':cipher.decrypt(preflight['context'].encode()).decode()}
    if temporary_file:
        target = Path('/data/news-mcp-headers.tmp.json')
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output)
        print(json.dumps({'temporary_header_file':str(target),'values_printed':False}))
    else:
        print(json.dumps(value))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['bootstrap','scope','headers','headers-file'])
    parser.add_argument('--article-id', type=int, default=362)
    args = parser.parse_args()
    try:
        if args.action == 'bootstrap': bootstrap()
        elif args.action == 'scope': scope(args.article_id)
        else: headers(args.action == 'headers-file')
    except Exception:
        raise SystemExit('Operator configuration failed; inspect protected server state without printing secrets.') from None


if __name__ == '__main__':
    main()
