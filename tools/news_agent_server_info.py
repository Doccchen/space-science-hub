"""Server metadata only: no credentials, plaintext prompts or private settings."""
import hashlib
import json
import os
from pathlib import Path

from backend import ai_config, management_store

FILES = ('backend/app.py', 'backend/ai.py', 'backend/publisher_fetch.py', 'requirements.txt',
         'web/news-reader.js', 'web/news-ui.js')


def main():
    root = Path('/app')
    report = {'files': {name: hashlib.sha256((root / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                        for name in FILES if (root / name).is_file()},
              'provider_env_key_configured': bool(os.getenv('DASHSCOPE_API_KEY')),
              'master_key_file_present': Path(os.getenv('AI_MASTER_KEY_FILE','/run/secrets/site-management.key')).is_file()}
    try:
        report['ai_config_initialized'] = ai_config.tables_exist()
        if report['ai_config_initialized']:
            with management_store.connection() as db:
                state = ai_config.state(db)
                row = ai_config.version(db, state['desired_version'])
                values = ai_config.public(row)
                report['protected_provider_key_configured'] = values['key_configured']
                report['workspace_matches_news_app'] = values['config']['workspace'] == 'llm-ep9bqc9mnw50k8e0'
    except Exception:
        report['metadata_error'] = True
    print(json.dumps(report))


if __name__ == '__main__':
    main()
