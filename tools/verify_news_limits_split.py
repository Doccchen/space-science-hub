"""Read-only operator evidence for independent limits and ledger membership."""
import json
from contextlib import closing
import sqlite3

from backend import ai,ai_config,news_limits


def main():
    regular=ai_config.overview();news=news_limits.overview()
    with closing(sqlite3.connect(ai.Settings.environment().db.resolve().as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(news_limits.usage_path().resolve().as_uri()+'?mode=ro',uri=True)) as current:
        ordinary_news=old.execute("SELECT COUNT(*) FROM requests WHERE substr(id,1,5)='news-'").fetchone()[0]
        count,tokens=current.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(tokens,reservation)),0) FROM requests').fetchone()
    result={'independent_ledgers':True,'legacy_news_rows_remaining_in_general':ordinary_news,'news_ledger_requests':count,
        'news_ledger_tokens_accounted_all_days':tokens,'news_settings_status':news['status'],'news_settings':news['desired']['config'],
        'general_settings_status':regular['status'],'general_limits':{name:regular['desired']['config'][name] for name in news_limits.FIELDS},
        'news_usage':news['usage'],'model_calls':0}
    assert ordinary_news==0
    print(json.dumps(result))


if __name__=='__main__':main()
