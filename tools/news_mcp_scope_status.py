"""Operator-only scope timing/call metadata; no secret or original text output."""
import json
import sqlite3
import time
from pathlib import Path


def main():
    scope = json.loads(Path('/data/news-mcp-preflight.json').read_text())
    with sqlite3.connect('/data/news-agent.sqlite3') as db:
        db.row_factory = sqlite3.Row
        job = db.execute('SELECT stage,tool_calls,tool_read_version FROM news_agent_jobs WHERE id=?', (scope['job_id'],)).fetchone()
    print(json.dumps({'job_id':scope['job_id'],'article_id':scope['article_id'],
                      'seconds_remaining':int(scope['expires']-time.time()),
                      'stage':job['stage'],'tool_calls':job['tool_calls'],
                      'full_read_verified':bool(job['tool_read_version'])}))


if __name__ == '__main__': main()
