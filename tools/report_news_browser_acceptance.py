"""Metadata and sanitized results for the isolated browser acceptance database."""
import json
import sqlite3
from pathlib import Path

import httpx
from backend import news_limits


def main():
    with sqlite3.connect('/data/news-agent-browser-acceptance.sqlite3') as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT id,conversation,question,stage,result,error,ledger_id FROM news_agent_jobs ORDER BY created').fetchall()
    report = {'scope':'ssh_loopback_real_browser','samples':[]}
    with sqlite3.connect(news_limits.usage_path()) as ledger, httpx.Client(trust_env=False,timeout=5) as stranger:
        for row in rows:
            usage = ledger.execute('SELECT status,tokens FROM requests WHERE id=?',(row['ledger_id'],)).fetchone()
            result = json.loads(row['result']) if row['result'] else None
            blocked = stranger.get('http://127.0.0.1:8769/api/news-agent/jobs/'+row['id']).status_code == 404
            report['samples'].append({'job_id':row['id'],'conversation_id':row['conversation'],'question':row['question'],
                'stage':row['stage'],'error':row['error'],'ledger_status':usage[0] if usage else None,
                'tokens':usage[1] if usage else None,'other_visitor_blocked':blocked,'result':result})
    report['total_tokens'] = sum(sample['tokens'] or 0 for sample in report['samples'])
    report['requests'] = len(rows)
    Path('/data/news-browser-acceptance-20261009.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    summary = {**report,'samples':[{key:value for key,value in sample.items() if key not in {'question','result'}} for sample in report['samples']]}
    print(json.dumps(summary))


if __name__ == '__main__': main()
