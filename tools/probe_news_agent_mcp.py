"""One opt-in paid server probe; dynamic MCP headers and shared budget evidence."""
import argparse
import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

from backend import ai_config, news_agent, news_limits
from backend.bailian import AIError, public_text
from backend.news_agent_client import NewsAgentClient
from backend.news_context_store import Store


async def run(args):
    settings = news_agent.Settings.environment()
    scope = json.loads(Path('/data/news-mcp-preflight.json').read_text())
    if scope['expires'] <= time.time() or not settings.key:
        raise AIError('configuration')
    cipher = ai_config.cipher()
    token = cipher.decrypt(scope['context'].encode()).decode()
    # Public generation must be off during this isolated operator acceptance call.
    if settings.enabled:
        raise AIError('configuration')
    budget = news_limits.budget()
    with budget.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='requests'").fetchone():
            raise AIError('storage')
        if db.execute("SELECT 1 FROM requests WHERE status='pending'").fetchone():
            raise AIError('capacity')
    budget.initialized = True  # Existing ledger only; do not interrupt other requests via initialize().
    store = Store(Path('/data/news-agent.sqlite3'))
    def evidence():
        with store.connection() as db:
            row = db.execute('SELECT tool_calls,tool_read_version FROM news_agent_jobs WHERE id=?', (scope['job_id'],)).fetchone()
        return {'tool_calls': row['tool_calls'], 'full_read_verified': bool(row['tool_read_version'])}
    report = {'service_id': args.service_id, 'job_id': scope['job_id'], 'article_id': scope['article_id'],
              'paid_calls': 0, 'before': evidence(), 'header_parameter': 'user_defined_params'}
    if args.call:
        question = f"请先调用 read_news(article_id={scope['article_id']}) 读取新闻原文，只用两句话说明新闻标题和报道的事件；附一个正文块编号引用。若工具拒绝，明确说无法读取，不要猜测。"
        ledger = budget.reserve_news(scope['job_id'], 'operator-mcp-probe', 'operator-mcp-probe', question)
        report['paid_calls'] = 1
        answer = None
        try:
            client = NewsAgentClient(settings.app_id, settings.key, settings.workspace, settings.region, timeout=120)
            answer = await client.ask(question, tool_context={args.service_id: {'X-News-Context': token}})
            text = public_text(answer.text, settings.key, 16000)
            for value in (token, settings.mcp_key, answer.session_id, settings.workspace):
                if value:
                    text = text.replace(value, '[已隐藏]')
            report.update(complete=True, answer=text, usage=answer.usage)
            budget.finish_news(ledger, answer)
        except BaseException as error:
            code = error.code if isinstance(error, AIError) else 'incomplete_answer'
            budget.finish_news(ledger, answer, code)
            report.update(complete=False, error=code)
        report['after'] = evidence()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'answer'}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--call', action='store_true')
    parser.add_argument('--service-id', required=True)
    parser.add_argument('--output', default='/data/news-agent-mcp-probe.json')
    args = parser.parse_args()
    if not __import__('re').fullmatch(r'[A-Za-z0-9_-]{1,100}', args.service_id):
        raise SystemExit('Invalid service ID')
    try:
        asyncio.run(run(args))
    except Exception:
        raise SystemExit('Probe preflight failed; no credentials printed. Check protected server state.') from None


if __name__ == '__main__':
    main()
